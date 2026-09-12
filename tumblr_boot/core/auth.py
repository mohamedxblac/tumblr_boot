# -*- coding: utf-8 -*-
import time
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.browser import BrowserFactory
from utils.logger import logger


LOGIN_ERROR_MARKERS = (
    "your email or password were incorrect",
    "your email or password is incorrect",
    "incorrect email or password",
    "invalid email or password",
)

CHALLENGE_MARKERS = (
    "prove you're human",
    "verify you're human",
    "complete the captcha",
    "suspicious activity",
)


def _login_page_outcome(driver):
    """Return a terminal login state, or False while the page is still pending."""
    current_url = driver.current_url.lower()
    if "/dashboard" in current_url:
        return "success"

    page_text = driver.execute_script(
        "return (document.body && document.body.innerText || '').toLowerCase();"
    )
    if any(marker in page_text for marker in LOGIN_ERROR_MARKERS):
        return "credentials_rejected"
    if any(marker in page_text for marker in CHALLENGE_MARKERS):
        return "challenge"
    return False


# فحص وتخطي شاشات وإشعارات الموافقة وملفات تعريف الارتباط تلقائياً
def dismiss_consent_screen_if_present(driver) -> bool:
    try:
        curr_url = driver.current_url.lower()
        if "consent" in curr_url or "privacy" in curr_url:
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
                        driver.switch_to.default_content()
                        return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()

    except Exception as e:
        logger.debug(f"[CONSENT] Exception in consent handler: {e}")
    return False


# التحقق فقط من نتيجة تسجيل الدخول الذي نفذه AutoHotkey؛ لا تُكتب البيانات عبر Selenium.
def login(driver, email: str, password: Optional[str] = None, max_retries: int = 1) -> bool:
    del password, max_retries
    started_at = time.monotonic()
    try:
        outcome = WebDriverWait(driver, 30).until(_login_page_outcome)
        elapsed = time.monotonic() - started_at
        if outcome == "success":
            logger.info(f"[AUTH] Desktop login SUCCESSFUL: {email} ({elapsed:.1f}s)")
            return True
        if outcome == "credentials_rejected":
            logger.error(f"[AUTH] Tumblr rejected the desktop login credentials for {email}.")
        elif outcome == "challenge":
            logger.error(f"[AUTH] Tumblr presented a human-verification challenge for {email}.")
    except Exception as e:
        logger.warning(
            f"[AUTH] Could not confirm the AutoHotkey login for {email}: {type(e).__name__}: {e}"
        )

    BrowserFactory.capture_screenshot(driver, prefix=f"login_fail_{email.split('@')[0]}")
    logger.error(f"[AUTH] Desktop login failed for {email}")
    return False


# تسجيل الخروج من الحساب الحالي لإنهاء الجلسة بأمان
def logout(driver):
    try:
        driver.get("https://www.tumblr.com/settings/account")
        time.sleep(2)
        dismiss_consent_screen_if_present(driver)
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Log out')]"))
        )
        btn.click()
        time.sleep(3)
        logger.info("[AUTH] Logged out successfully.")
    except Exception as e:
        logger.warning(f"[AUTH] Logout did not complete cleanly ({e}).")
