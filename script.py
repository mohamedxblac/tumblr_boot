# -*- coding: utf-8 -*-
"""
Tumblr Outreach Script — PURE SELENIUM ENGINE (undetected-chromedriver)
========================================================================
Features & Fixes:
  1. Single Persistent Tab Navigation (Fixed 'invalid session id'):
     - Direct navigation (`driver.get(user_url)`) in the same main browser tab.
     - No window.open('') or driver.close(), preventing ChromeDriver session detachment.
  2. Top-to-Bottom Scoped Notes Scraping with Internal Container Scrolling:
     - Directly scrolls `div[data-testid='notes-root']` and clicks 'Show more notes'.
     - Filters out system badges (likes9, following48, etc.) and 'www'.
     - Strict top-to-bottom chronological ordering preserved.
  3. Automatic Consent Screen & Modal Popup Bypass (GDPR/Privacy/CMP overlays & iframes).
  4. Multi-line Shift+Enter message typing (no premature submission).
  5. Progress tracking (account_progress.json) & Deduplication (sent_users.txt).
  6. Clean teardown between accounts to prevent port conflicts.
"""

import os
import re
import sys
import json
import time
import random
import logging
from datetime import datetime

# ── Force UTF-8 stdout on Windows ────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Selenium & undetected-chromedriver ─────────────────────────────────────────
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


# =============================================================================
# CONFIGURATION
# =============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(BASE_DIR, exist_ok=True)

accounts = [
    {"email": "kazoulayacine012@gmail.com", "password": "Xcvb654need"},
]

MAX_SUCCESS_PER_ACCOUNT  = 30
SESSION_SUCCESS_CAP      = 15
NO_MESSAGE_LIMIT         = 10

LINE_DELAY               = 7.55
AFTER_SEND_DELAY         = 2.2
AFTER_SUCCESS_DELAY      = 2.2
MIN_BETWEEN_USERS        = 60
MAX_BETWEEN_USERS        = 130
SLEEP_BETWEEN_ROUNDS_HRS = 12

NOTES_MAX_USERS          = 3000
SCROLL_PAUSE             = 1.5
STAGNANT_LIMIT           = 8

sent_users_file   = os.path.join(BASE_DIR, "sent_users.txt")
log_file          = os.path.join(BASE_DIR, "account_logs.txt")
summary_file      = os.path.join(BASE_DIR, "account_summaries.txt")
progress_file     = os.path.join(BASE_DIR, "account_progress.json")
target_queue_file = os.path.join(BASE_DIR, "target_queue.txt")

base_messages = [
    """I never imagined I would have to ask for help like this. My name is Wedad, and I am from P.a.l.e.s.t.i.n.e. My family consists of 7 members. Our home was completely destroyed, and now we are living in a torn tent with nothing left. My family and I have not had any food for the past 32 hours. Watching my family suffer from hunger is heartbreaking, and every hour feels endless.

 My mother is sick, and my sister Mira is also sick. They both urgently need medicine and medical care, but we cannot afford it. I feel helpless watching them suffer while we have no food and no way to help them.

 If you are able to help, your d.o.n.a.t.i.o.n can provide food for my family and medicine for my mother and my sister Mira. If you cannot donate, please share our story with others. Your kindness and support could give my family hope during this heartbreaking time. Thank you for reading my story.""",

    """I never imagined I would have to ask for help like this. My name is Wedad, and I am from P.a.l.e.s.t.i.n.e. My family consists of 7 members. Our home was completely destroyed, and now we are living in a torn tent with nothing left. My family and I have not had any food for the past 32 hours. Watching my family suffer from hunger is heartbreaking, and every hour feels endless.

 My mother is sick, and my sister Mira is also sick. They both urgently need medicine and medical care, but we cannot afford it. I feel helpless watching them suffer while we have no food and no way to help them.

  If you are able to help, your d.o.n.a.t.i.o.n can provide food for my family and medicine for my mother and my sister Mira. If you cannot donate, please share our story with others. Your kindness and support could give my family hope during this heartbreaking time. Thank you for reading my story.""",

    """I never imagined I would have to ask for help like this. My name is Wedad, and I am from P.a.l.e.s.t.i.n.e. My family consists of 7 members. Our home was completely destroyed, and now we are living in a torn tent with nothing left. My family and I have not had any food for the past 32 hours. Watching my family suffer from hunger is heartbreaking, and every hour feels endless.

 My mother is sick, and my sister Mira is also sick. They both urgently need medicine and medical care, but we cannot afford it. I feel helpless watching them suffer while we have no food and no way to help them.

 If you are able to help, your d.o.n.a.t.i.o.n can provide food for my family and medicine for my mother and my sister Mira. If you cannot donate, please share our story with others. Your kindness and support could give my family hope during this heartbreaking time. Thank you for reading my story.""",
]

greetings = [
    "I hope this message finds you in peace",
    "I hope you're safe and surrounded by kindness",
    "I hope you're safe and doing okay today",
]


# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("TumblrSelenium")


def now_ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_event(email, total_ok, fails, note=""):
    extra = f" | {note}" if note else ""
    logger.info(f"{email} | Sent:{total_ok} | Failed:{fails}{extra}")


def log_summary(email, total_ok, fails, note=""):
    extra = f" | {note}" if note else ""
    logger.info(f"{email} | ===SUMMARY=== | Sent:{total_ok} | Failed:{fails}{extra}")
    try:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(f"{now_ts()} | {email} | Sent:{total_ok} | Failed:{fails}{extra}\n")
    except Exception:
        pass


# =============================================================================
# PROGRESS & QUEUE PERSISTENCE
# =============================================================================
def load_progress():
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: int(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def save_progress(progress):
    try:
        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Progress save failed: {e}")


# =============================================================================
# SENT USERS & TARGET QUEUE
# =============================================================================
if not os.path.exists(sent_users_file):
    open(sent_users_file, "w", encoding="utf-8").close()


def extract_username(url: str) -> str:
    url = (url or "").strip().replace("https://", "").replace("http://", "")
    if ".tumblr.com" in url:
        return url.split(".tumblr.com")[0].strip("/")
    if "tumblr.com/" in url:
        return url.split("tumblr.com/")[1].split("/")[0].strip("/")
    return url.strip("/").split("/")[0]


def load_sent_users():
    users = set()
    if os.path.exists(sent_users_file):
        with open(sent_users_file, "r", encoding="utf-8") as f:
            for line in f:
                u = extract_username(line.strip())
                if u:
                    users.add(u.lower())
    return users


def save_sent_user(username: str):
    username = username.lower().strip()
    if not username:
        return
    try:
        with open(sent_users_file, "a", encoding="utf-8") as f:
            f.write(username + "\n")
    except Exception as e:
        logger.error(f"Could not save sent user: {e}")


def load_target_queue():
    queue = []
    if os.path.exists(target_queue_file):
        try:
            with open(target_queue_file, "r", encoding="utf-8") as f:
                for line in f:
                    u = line.strip().lower()
                    if u and u not in queue:
                        queue.append(u)
        except Exception:
            pass
    return queue


def save_target_queue(queue):
    try:
        with open(target_queue_file, "w", encoding="utf-8") as f:
            for u in queue:
                f.write(f"{u}\n")
    except Exception as e:
        logger.error(f"Failed to save target queue: {e}")


# =============================================================================
# CONSENT SCREEN & POPUP BYPASS HANDLER
# =============================================================================
def dismiss_consent_screen_if_present(driver):
    """
    Detects and automatically dismisses Tumblr Consent / GDPR / Cookie walls,
    whether they appear as a full-page redirect, an overlay modal popup,
    a CMP iframe, or a floating banner.
    """
    try:
        curr_url = driver.current_url.lower()
        if "consent" in curr_url or "privacy" in curr_url:
            logger.info("[CONSENT] Detected full-page consent redirect, dismissing...")
            for sel in [
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'i agree')]",
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept all')]",
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
                "//button[@type='submit']",
            ]:
                try:
                    btn = driver.find_element(By.XPATH, sel)
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(2.0)
                        logger.info("[CONSENT] Clicked full-page consent submit button.")
                        return True
                except Exception:
                    continue

        popup_selectors = [
            "//div[@role='dialog']//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
            "//div[@role='dialog']//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
            "//div[@aria-modal='true']//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
            "//div[@aria-modal='true']//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'i agree')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept all')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'got it')]",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'allow all')]",
            "button[data-testid='consent-accept-all']",
            "button[data-testid='accept-all-btn']",
            "button.cmp-button_accept",
            "#cmpwelcomebtnyes",
            "#onetrust-accept-btn-handler",
            "button[id*='accept']",
            "button[id*='agree']",
            "button[class*='consent']",
            "[aria-label*='cookie'] button",
            "[aria-label*='consent'] button",
        ]

        for sel in popup_selectors:
            try:
                elements = (
                    driver.find_elements(By.XPATH, sel)
                    if sel.startswith("//")
                    else driver.find_elements(By.CSS_SELECTOR, sel)
                )
                for el in elements:
                    if el.is_displayed():
                        driver.execute_script("arguments[0].click();", el)
                        time.sleep(0.8)
                        logger.info(f"[CONSENT] Dismissed consent popup via selector: '{sel}'")
                        return True
            except Exception:
                continue

        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                inner_buttons = driver.find_elements(
                    By.XPATH,
                    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree') or "
                    "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept') or "
                    "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'got it') or "
                    "contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'allow')]"
                )
                for ib in inner_buttons:
                    if ib.is_displayed():
                        driver.execute_script("arguments[0].click();", ib)
                        time.sleep(1.0)
                        logger.info("[CONSENT] Dismissed popup button inside iframe.")
                        driver.switch_to.default_content()
                        return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()

    except Exception as e:
        logger.debug(f"[CONSENT] Exception in consent handler: {e}")
    return False


# =============================================================================
# SELENIUM DRIVER SETUP & ACTIONS
# =============================================================================
def create_driver():
    options = uc.ChromeOptions()
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    try:
        return uc.Chrome(options=options, version_main=152)
    except Exception:
        return uc.Chrome(options=options)


def human_type(element, text, min_d=0.03, max_d=0.08):
    element.click()
    time.sleep(0.25)
    element.send_keys(Keys.CONTROL + "a")
    time.sleep(0.1)
    element.send_keys(Keys.BACKSPACE)
    time.sleep(0.15)
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(min_d, max_d))
    time.sleep(0.3)


def uc_login(driver, email: str, password: str) -> bool:
    driver.get("https://www.tumblr.com/login")
    try:
        time.sleep(3)
        dismiss_consent_screen_if_present(driver)

        email_el = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.NAME, "email"))
        )
        human_type(email_el, email)

        pwd_el = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.NAME, "password"))
        )
        human_type(pwd_el, password)

        time.sleep(0.8)
        login_btn = None
        for sel in [
            "//button[@type='submit' and contains(.,'Log in')]",
            "//button[contains(.,'Log in')]",
            "//button[@type='submit']",
        ]:
            try:
                b = driver.find_element(By.XPATH, sel)
                if b.is_displayed():
                    login_btn = b
                    break
            except Exception:
                continue

        if login_btn:
            ActionChains(driver).move_to_element(login_btn).pause(0.3).click().perform()
        else:
            pwd_el.send_keys(Keys.ENTER)

        WebDriverWait(driver, 20).until(
            lambda d: "dashboard" in d.current_url
            or bool(d.find_elements(By.CSS_SELECTOR, "[data-testid='dashboard-feed'], nav"))
        )
        logger.info(f"[UC] Login OK: {email}")
        return True
    except Exception as e:
        logger.error(f"[UC] Login FAILED: {email} | {e}")
        return False


def uc_logout(driver):
    try:
        driver.get("https://www.tumblr.com/settings/account")
        time.sleep(2)
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Log out')]"))
        )
        btn.click()
        time.sleep(3)
        logger.info("[UC] Logged out successfully.")
    except Exception:
        logger.warning("[UC] Logout did not complete cleanly.")


def uc_follow(driver) -> bool:
    for sel in [
        "button[aria-label='Follow']",
        "button[aria-label='Follow @']",
        "button[data-testid='follow-button']",
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.5)
            return True
        except Exception:
            continue
    try:
        btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Follow')]"))
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(0.5)
        return True
    except Exception:
        return False


def type_message_safely(element, text: str):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            element.send_keys(line)
        if i < len(lines) - 1:
            element.send_keys(Keys.SHIFT, Keys.ENTER)
        time.sleep(0.05)


def send_message_to_user(driver, user_url: str, messages: list, do_follow: bool = False):
    """
    Navigates directly to the user's profile in the SAME active browser tab.
    100% immune to 'invalid session id' because it never closes or detaches tabs.
    """
    try:
        driver.get(user_url)
        time.sleep(4.5)

        dismiss_consent_screen_if_present(driver)

        followed = False
        if do_follow:
            followed = uc_follow(driver)

        try:
            driver.execute_script("window.scrollBy(0, 250);")
        except Exception:
            pass

        # Check for message button
        clicked = False
        for sel in [
            "a.tx-icon-button.message-button",
            "button[aria-label='Message']",
            "//button[contains(., 'Message')]",
            "//a[contains(@aria-label,'Message')]",
            "a[href*='/message/']",
        ]:
            try:
                btn = (driver.find_element(By.XPATH, sel)
                       if sel.startswith("//")
                       else driver.find_element(By.CSS_SELECTOR, sel))
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            return ("no_message_button", followed)

        input_box = None
        for sel in ["textarea", "div[contenteditable='true']", "[role='textbox']"]:
            try:
                input_box = WebDriverWait(driver, 6).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                if input_box:
                    break
            except Exception:
                continue

        if not input_box:
            return ("no_message_button", followed)

        for msg in messages:
            input_box.click()
            type_message_safely(input_box, msg)
            time.sleep(0.3)
            input_box.send_keys(Keys.ENTER)
            try:
                sb = driver.find_element(
                    By.XPATH, "//button[contains(@aria-label,'Send') or contains(.,'Send')]"
                )
                if sb.is_displayed():
                    driver.execute_script("arguments[0].click();", sb)
            except Exception:
                pass
            time.sleep(LINE_DELAY)

        time.sleep(AFTER_SEND_DELAY)

        if "Could not send" in driver.page_source:
            return ("could_not_send", followed)

        return (True, followed)

    except Exception as e:
        logger.warning(f"[SEND] Exception messaging {user_url}: {e}")
        return (False, False)


# =============================================================================
# NOTES SCRAPER (Strict Top-to-Bottom Scoped Pagination)
# =============================================================================
BLOG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_.]{1,62}$")
BAD_PREFIX_RE = re.compile(r"^(likes|following|followers|posts|drafts|queue|settings|inbox|tagged|explore|dashboard)\d*$")
RESERVED = {
    "dashboard","likes","reblogs","explore","communities","inbox","following","new","blog",
    "about","apps","policy","privacy","terms","help","support","legal","careers","press",
    "advertise","developers","themes","search","login","register","pricing","discover",
    "trending","activity","settings","notes","tagged","posts","ask","submit",
    "www","static","assets","api","help","corp","staff",
}


def is_valid_blog(slug: str) -> bool:
    s = (slug or "").lower().strip()
    if not s or s in RESERVED or s.startswith("#") or s == "www":
        return False
    if BAD_PREFIX_RE.fullmatch(s):
        return False
    return bool(BLOG_RE.fullmatch(s))


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    return url.replace("http://", "https://")


def extract_blog_from_href(href: str) -> str:
    href = normalize_url(href)
    lo = href.lower()
    bad = ("/tag/","/tags/","/search","/post/","/posts/","/reblog","/likes",
           "/inbox","/ask","/follow","/settings","/dashboard/blog/","/notes/",
           "/about","/privacy","/terms","/help","/apps","/following")
    if any(b in lo for b in bad):
        return ""
    if href.startswith("/"):
        parts = href.split("/")
        if len(parts) > 1 and is_valid_blog(parts[1]):
            return parts[1].lower()
    if "tumblr.com/" in href:
        try:
            seg = href.split("tumblr.com/")[1].split("/")[0].strip().lower()
            if is_valid_blog(seg):
                return seg
        except Exception:
            pass
    if ".tumblr.com" in href:
        try:
            sub = href.split("//")[-1].split(".tumblr.com")[0].strip().lower()
            if sub and sub != "www" and is_valid_blog(sub):
                return sub
        except Exception:
            pass
    return ""


def parse_post_info(url: str):
    m = re.search(r"tumblr\.com/([^/?#]+)/([0-9]{6,})", url)
    return (m.group(1), m.group(2)) if m else (None, None)


def open_notes_in_selenium(driver, want_tab: str) -> bool:
    """Opens the Notes view on the post article."""
    want = want_tab.lower()
    
    # 1. Try inline tabs on article
    tab_xpaths = (
        [
            "//article//button[contains(.,'likes') or contains(@aria-label,'Likes')]",
            "//button[@role='tab' and @title='Likes']",
            "//button[contains(@aria-label,'Likes')]",
        ] if want == "likes" else [
            "//article//button[contains(.,'reblog') or contains(@aria-label,'Reblogs')]",
            "//button[@role='tab' and @title='Reblogs']",
            "//button[contains(@aria-label,'Reblogs')]",
        ]
    )
    for xp in tab_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(1.0)
                logger.info("[SCRAPER] Clicked notes tab on article.")
                return True
        except Exception:
            continue

    # 2. Try footer notes button -> dialog
    for sel in [
        "//footer//button[contains(@aria-label,'Notes') or contains(@aria-label,'notes')]",
        "//button[contains(@aria-label,'Notes') or contains(@aria-label,'notes')]",
        "//a[contains(@aria-label,'Notes') or contains(@aria-label,'notes')]",
    ]:
        try:
            btn = driver.find_element(By.XPATH, sel)
            if btn.is_displayed():
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
                logger.info("[SCRAPER] Opened Notes Dialog.")
                return True
        except Exception:
            continue

    return False


def scrape_post_master_queue(
    driver,
    post_url: str,
    tab_type: str,
    owner_blog: str,
    already_sent: set,
    max_users: int = NOTES_MAX_USERS
) -> list:
    """
    Scrapes the target post strictly from the notes container in exact top-to-bottom order.
    Directly scrolls the notes-root container and clicks 'Show more notes'.
    """
    logger.info(f"[SCRAPER] Navigating to post: {post_url}")
    driver.get(post_url)
    time.sleep(3.5)
    dismiss_consent_screen_if_present(driver)

    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "article")))
    except Exception:
        pass

    open_notes_in_selenium(driver, tab_type)
    time.sleep(1.5)

    found = []
    seen = set()

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

    logger.info(f"[SCRAPER] Starting scoped top-to-bottom pagination (max target: {max_users} users)...")
    stagnant    = 0
    scroll_n    = 0
    start_time  = time.time()
    MAX_SECONDS = 150

    while len(found) < max_users and stagnant < STAGNANT_LIMIT:
        elapsed = time.time() - start_time
        if elapsed > MAX_SECONDS:
            logger.info(f"[SCRAPER] Reached time limit ({int(elapsed)}s), proceeding with {len(found)} users.")
            break

        scroll_n += 1
        before = len(found)

        # Scoped strictly to notes-root or post article
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
        logger.info(f"[SCRAPER] Scroll #{scroll_n} | Master Queue: {after} users (+{after - before} new)")

        if after >= max_users:
            break

        # ── Scroll internal container + page ────────────────────────────────
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

        # ── Click 'Show more notes' / 'Load more' if present ────────────────
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

        time.sleep(SCROLL_PAUSE)

        if after == before:
            stagnant += 1
        else:
            stagnant = 0

    total_time = int(time.time() - start_time)
    logger.info(f"[SCRAPER] Master list gathered: {len(found)} users in {total_time} seconds (top-to-bottom).")
    return found


# =============================================================================
# ACCOUNT RUNNER (Single-Tab Persistent Browser Session)
# =============================================================================
def run_for_account(
    acc: dict,
    post_url: str,
    tab_type: str,
    target_queue: list,
    sent_users: set,
    progress: dict,
):
    email    = acc["email"]
    password = acc["password"]

    total_ok = int(progress.get(email, 0))
    if total_ok >= MAX_SUCCESS_PER_ACCOUNT:
        logger.info(f"[SKIP] {email} already at lifetime target ({total_ok}/{MAX_SUCCESS_PER_ACCOUNT})")
        return

    session_ok    = 0
    fail_count    = 0
    no_msg_streak = 0
    account_note  = ""
    driver        = None

    try:
        log_event(email, total_ok, fail_count, note="--- SESSION START ---")

        # ── Step 1: Launch Browser & Login (ONCE per account) ────────────────
        driver = create_driver()
        if not uc_login(driver, email, password):
            account_note = "login_failed"
            log_event(email, total_ok, fail_count, note=account_note)
            log_summary(email, total_ok, fail_count, note=account_note)
            return

        # ── Step 2: Scrape Target Post if Master Queue is Low ────────────────
        owner_blog, _ = parse_post_info(post_url)
        uncontacted = [u for u in target_queue if u not in sent_users]

        if len(uncontacted) < 15:
            logger.info("[QUEUE] Master queue is low. Scraping target post for fresh users...")
            fresh_users = scrape_post_master_queue(
                driver=driver,
                post_url=post_url,
                tab_type=tab_type,
                owner_blog=owner_blog or "",
                already_sent=sent_users,
                max_users=NOTES_MAX_USERS,
            )
            for u in fresh_users:
                if u not in target_queue:
                    target_queue.append(u)
            save_target_queue(target_queue)
            uncontacted = [u for u in target_queue if u not in sent_users]

        if not uncontacted:
            account_note = "no_uncontacted_users_left"
            log_event(email, total_ok, fail_count, note=account_note)
            log_summary(email, total_ok, fail_count, note=account_note)
            uc_logout(driver)
            return

        logger.info(f"[{email}] Ready! Processing up to {SESSION_SUCCESS_CAP} users in this open browser session...")

        # ── Step 3: Send DMs in the SAME Single Browser Tab ──────────────────
        msg_i   = 0
        greet_i = 0
        users_seen = 0

        for username in uncontacted:
            if session_ok >= SESSION_SUCCESS_CAP:
                account_note = f"session_cap_{SESSION_SUCCESS_CAP}_reached"
                log_event(email, total_ok, fail_count, note=account_note)
                break
            if total_ok >= MAX_SUCCESS_PER_ACCOUNT:
                account_note = f"reached_max_{MAX_SUCCESS_PER_ACCOUNT}"
                log_event(email, total_ok, fail_count, note=account_note)
                break

            username = username.strip().lower()
            if not username or username in sent_users:
                continue

            user_url   = f"https://www.tumblr.com/{username}"
            users_seen += 1
            do_follow  = (users_seen % 4 == 0)

            message  = base_messages[msg_i % len(base_messages)]
            greeting = greetings[greet_i % len(greetings)]
            salute   = "hello" if (msg_i % 2 == 1) else "hi"
            parts    = [salute, f"{greeting}, {username}", message]
            msg_i   += 1
            greet_i += 1

            result, okf = send_message_to_user(driver, user_url, parts, do_follow=do_follow)

            if do_follow:
                log_event(email, total_ok, fail_count,
                          note=f"follow | user={username} | ok={okf}")

            if result == "could_not_send":
                account_note = "could_not_send"
                log_event(email, total_ok, fail_count, note=account_note)
                break

            if result == "no_message_button":
                fail_count    += 1
                no_msg_streak += 1
                log_event(email, total_ok, fail_count,
                          note=f"no_msg_button streak={no_msg_streak}/{NO_MESSAGE_LIMIT} user={username}")
                if no_msg_streak >= NO_MESSAGE_LIMIT:
                    account_note = "10x_no_msg_button_logout"
                    log_event(email, total_ok, fail_count, note=account_note)
                    break
                delay = random.uniform(MIN_BETWEEN_USERS, MAX_BETWEEN_USERS)
                logger.info(f"[WAIT] {int(delay)}s in open browser before next user...")
                time.sleep(delay)
                continue

            no_msg_streak = 0

            if result is True:
                save_sent_user(username)
                sent_users.add(username)
                total_ok   += 1
                session_ok += 1
                progress[email] = total_ok
                save_progress(progress)
                log_event(email, total_ok, fail_count,
                          note=f"sent_ok | user={username} | session={session_ok}/{SESSION_SUCCESS_CAP} | total={total_ok}/{MAX_SUCCESS_PER_ACCOUNT}")
                time.sleep(AFTER_SUCCESS_DELAY)
                delay = random.uniform(MIN_BETWEEN_USERS, MAX_BETWEEN_USERS)
                logger.info(f"[WAIT] {int(delay)}s in open browser before next user...")
                time.sleep(delay)
            else:
                fail_count += 1
                log_event(email, total_ok, fail_count,
                          note=f"send_failed | user={username}")
                delay = random.uniform(MIN_BETWEEN_USERS, MAX_BETWEEN_USERS)
                logger.info(f"[WAIT] {int(delay)}s in open browser before next user...")
                time.sleep(delay)

        # ── Step 4: Clean Logout & Close Session ─────────────────────────────
        log_summary(email, total_ok, fail_count, note=account_note)
        uc_logout(driver)

    except Exception as e:
        logger.exception(f"[ERROR] Session exception for {email}: {e}")
        log_summary(email, total_ok, fail_count, note=f"general_error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            # 3 second cooldown for ChromeDriver port cleanup
            time.sleep(3.0)


def main():
    post_url     = sys.argv[1] if len(sys.argv) > 1 else ""
    type_choice  = sys.argv[2] if len(sys.argv) > 2 else ""
    start_acc_s  = sys.argv[3] if len(sys.argv) > 3 else ""

    if not post_url:
        try:
            if sys.stdin and sys.stdin.isatty():
                post_url = input("Post URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            pass

    if not post_url:
        logger.error("No post URL provided. Exiting.")
        return

    if not type_choice:
        try:
            if sys.stdin and sys.stdin.isatty():
                type_choice = input("Type (1=Likes / 2=Reblogs) [default 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            pass
    if type_choice not in ("1", "2"):
        type_choice = "1"
    tab_type = "likes" if type_choice == "1" else "reblogs"

    start_acc = 0
    if start_acc_s:
        try:
            start_acc = max(0, int(start_acc_s) - 1)
        except ValueError:
            start_acc = 0
    elif sys.stdin and sys.stdin.isatty():
        try:
            v = input(f"Start from account # (1-{len(accounts)}) [default 1]: ").strip()
            if v:
                start_acc = max(0, int(v) - 1)
        except (EOFError, KeyboardInterrupt):
            pass

    sent_users   = load_sent_users()
    progress     = load_progress()
    target_queue = load_target_queue()

    while True:
        pending = [
            accounts[i]
            for i in range(start_acc, len(accounts))
            if int(progress.get(accounts[i]["email"], 0)) < MAX_SUCCESS_PER_ACCOUNT
        ]

        if not pending:
            if start_acc > 0:
                start_acc = 0
                continue
            logger.info("All accounts reached target. Done.")
            break

        logger.info(f"Round start — {len(pending)} accounts remaining")
        for acc in pending:
            run_for_account(acc, post_url, tab_type, target_queue, sent_users, progress)

        start_acc = 0

        still_pending = [
            a for a in accounts
            if int(progress.get(a["email"], 0)) < MAX_SUCCESS_PER_ACCOUNT
        ]
        if not still_pending:
            logger.info("All accounts reached target. Done.")
            break

        logger.info(f"Round complete. Sleeping {SLEEP_BETWEEN_ROUNDS_HRS}h before next round...")
        time.sleep(SLEEP_BETWEEN_ROUNDS_HRS * 3600)


if __name__ == "__main__":
    main()
