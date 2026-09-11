# -*- coding: utf-8 -*-
import re
import time
from typing import List, Set, Optional, Callable

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.auth import dismiss_consent_screen_if_present
from utils.helpers import extract_blog_from_href, is_valid_blog
from utils.logger import logger


# استخراج اسم الحساب ورقم المنشور من رابط البوست
def parse_post_info(url: str):
    m = re.search(r"tumblr\.com/([^/?#]+)/([0-9]{6,})", url)
    return (m.group(1), m.group(2)) if m else (None, None)


# فتح تبويب التفاعلات (الإعجابات أو إعادة التدوين) داخل صفحة المنشور
def open_notes_in_selenium(driver, want_tab: str = "likes") -> bool:
    want = want_tab.lower()
    dismiss_consent_screen_if_present(driver)

    tab_xpaths = (
        [
            "//article//button[contains(.,'likes') or contains(@aria-label,'Likes')]",
            "//button[@role='tab' and @title='Likes']",
            "//button[contains(@aria-label,'Likes')]",
            "//button[contains(.,'Likes')]",
        ] if want == "likes" else [
            "//article//button[contains(.,'reblog') or contains(@aria-label,'Reblogs')]",
            "//button[@role='tab' and @title='Reblogs']",
            "//button[contains(@aria-label,'Reblogs')]",
            "//button[contains(.,'Reblogs')]",
        ]
    )
    for xp in tab_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.0)
                logger.info(f"[SCRAPER] Clicked inline '{want}' tab on article.")
                return True
        except Exception:
            continue

    for sel in [
        "//footer//button[contains(@aria-label,'Notes') or contains(@aria-label,'notes')]",
        "//button[contains(@aria-label,'Notes') or contains(@aria-label,'notes')]",
        "//a[contains(@aria-label,'Notes') or contains(@aria-label,'notes')]",
    ]:
        try:
            btn = driver.find_element(By.XPATH, sel)
            if btn.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.2)
                tab_sel = (
                    "//button[@role='tab' and contains(., 'Like')]"
                    if want == "likes"
                    else "//button[@role='tab' and contains(., 'Reblog')]"
                )
                try:
                    tbtn = driver.find_element(By.XPATH, tab_sel)
                    driver.execute_script("arguments[0].click();", tbtn)
                    time.sleep(0.8)
                except Exception:
                    pass
                logger.info(f"[SCRAPER] Opened Notes Dialog for '{want}'.")
                return True
        except Exception:
            continue

    logger.warning("[SCRAPER] Could not find notes opener; scrolling default content.")
    return False


# جمع وسحب المتفاعلين مع المنشور بالترتيب من الأعلى للأسفل عبر التمرير
def scrape_post_master_queue(
    driver,
    post_url: str,
    tab_type: str = "likes",
    owner_blog: Optional[str] = None,
    already_sent: Optional[Set[str]] = None,
    max_users: int = 3000,
    scroll_pause: float = 1.5,
    stagnant_limit: int = 8,
    timeout_sec: int = 150,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> List[str]:
    if already_sent is None:
        already_sent = set()

    if not owner_blog:
        owner, _ = parse_post_info(post_url)
        owner_blog = owner

    logger.info(f"[SCRAPER] Navigating to target post: {post_url}")
    driver.get(post_url)
    time.sleep(3.5)
    dismiss_consent_screen_if_present(driver)

    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "article")))
    except Exception:
        pass

    open_notes_in_selenium(driver, tab_type)
    time.sleep(1.5)

    found: List[str] = []
    seen: Set[str] = set()

    def maybe_add(raw: str):
        b = (raw or "").lstrip("@").strip().lower()
        if not b or not is_valid_blog(b):
            return
        if owner_blog and b == owner_blog.lower():
            return
        if b in already_sent or b in seen:
            return
        seen.add(b)
        found.append(b)

    logger.info(f"[SCRAPER] Starting top-to-bottom notes collection (Target max: {max_users})...")
    stagnant = 0
    scroll_n = 0
    start_time = time.time()

    while len(found) < max_users and stagnant < stagnant_limit:
        if stop_check and stop_check():
            logger.info("[SCRAPER] Stopped by user request.")
            break

        elapsed = time.time() - start_time
        if elapsed > timeout_sec:
            logger.info(f"[SCRAPER] Reached time limit ({int(elapsed)}s), proceeding with {len(found)} users.")
            break

        scroll_n += 1
        before = len(found)

        raw_links = driver.execute_script("""
            const targetScope = document.querySelector("[data-testid='notes-root']") 
                             || document.querySelector("[role='dialog']") 
                             || document.querySelector("article");
            if (!targetScope) return [];
            const anchors = Array.from(targetScope.querySelectorAll("a[href]"));
            return anchors.map(a => ({
                href: a.href || '',
                text: (a.innerText || a.getAttribute('title') || '').trim()
            }));
        """)

        if raw_links:
            for item in raw_links:
                href = item.get("href", "")
                b = extract_blog_from_href(href)
                if not b:
                    t = item.get("text", "")
                    if t and " " not in t and not t.startswith("#"):
                        b = t
                maybe_add(b)
                if len(found) >= max_users:
                    break

        after = len(found)
        logger.info(f"[SCRAPER] Scroll #{scroll_n} | Found: {after} users (+{after - before} new)")

        if progress_callback:
            progress_callback(after, max_users)

        if after >= max_users:
            break

        driver.execute_script("""
            const root = document.querySelector("[data-testid='notes-root']");
            if (root) {
                let el = root;
                while (el) {
                    if (el.scrollHeight > el.clientHeight) {
                        el.scrollTop = el.scrollHeight;
                    }
                    el = el.parentElement;
                }
                root.scrollTop = root.scrollHeight;
                const scrollables = Array.from(root.querySelectorAll('*')).filter(e => e.scrollHeight > e.clientHeight);
                scrollables.forEach(s => s.scrollTop = s.scrollHeight);
            }
            window.scrollBy(0, 1000);
        """)

        try:
            more_btns = driver.find_elements(
                By.XPATH,
                "//button[contains(.,'Load more') or contains(.,'Show more') or contains(.,'More') or contains(.,'more')]"
                " | //a[contains(.,'Show more notes') or contains(.,'Load more')]"
            )
            for mb in more_btns[:2]:
                if mb.is_displayed():
                    driver.execute_script("arguments[0].click();", mb)
                    time.sleep(0.6)
                    break
        except Exception:
            pass

        time.sleep(scroll_pause)

        if after == before:
            stagnant += 1
        else:
            stagnant = 0

    total_time = int(time.time() - start_time)
    logger.info(f"[SCRAPER] Finished gathering {len(found)} users in {total_time}s.")
    return found
