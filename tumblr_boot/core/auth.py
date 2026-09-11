# -*- coding: utf-8 -*-
import time
import random
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
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


# كتابة النص حرفاً بحرف مع تأخير زمني عشوائي لمحاكاة الكتابة البشرية
def human_type(element, text: str, min_d: float = 0.03, max_d: float = 0.08):
    try:
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
    except Exception as e:
        logger.debug(f"[HUMAN_TYPE] Fallback typing due to: {e}")
        element.send_keys(text)


def _type_and_verify(element, value: str) -> None:
    """Enter a value and verify that the DOM received it without logging it."""
    human_type(element, value)
    if element.get_attribute("value") == value:
        return

    element.click()
    element.send_keys(Keys.CONTROL + "a")
    element.send_keys(value)
    if element.get_attribute("value") != value:
        raise RuntimeError("The login form did not retain the entered field value")


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


# تسجيل الدخول إلى حساب تمبلر والتحقق من فتح لوحة التحكم بنجاح
def login(driver, email: str, password: str, max_retries: int = 2) -> bool:
    for attempt in range(1, max_retries + 1):
        started_at = time.monotonic()
        try:
            logger.info(f"[AUTH] Attempting login for {email} (attempt {attempt}/{max_retries})...")
            driver.get("https://www.tumblr.com/login")
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
            )
            dismiss_consent_screen_if_present(driver)

            email_el = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.NAME, "email"))
            )
            _type_and_verify(email_el, email)

            pwd_el = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.NAME, "password"))
            )
            _type_and_verify(pwd_el, password)

            login_btn = None
            for sel in [
                "./ancestor::form[1]//button[@type='submit']",
                "//button[@type='submit' and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'),'log in')]",
            ]:
                try:
                    b = pwd_el.find_element(By.XPATH, sel) if sel.startswith(".") else driver.find_element(By.XPATH, sel)
                    if b.is_displayed():
                        login_btn = b
                        break
                except Exception:
                    continue

            if login_btn:
                ActionChains(driver).move_to_element(login_btn).pause(0.3).click().perform()
            else:
                pwd_el.send_keys(Keys.ENTER)

            outcome = WebDriverWait(driver, 20).until(_login_page_outcome)
            elapsed = time.monotonic() - started_at
            if outcome == "success":
                logger.info(f"[AUTH] Login SUCCESSFUL: {email} ({elapsed:.1f}s)")
                return True

            if outcome == "credentials_rejected":
                logger.error(
                    f"[AUTH] Tumblr rejected the submitted credentials for {email} "
                    f"after the form values were verified ({elapsed:.1f}s)."
                )
                break

            if outcome == "challenge":
                logger.error(f"[AUTH] Tumblr presented a human-verification challenge for {email}.")
                break

        except Exception as e:
            elapsed = time.monotonic() - started_at
            logger.warning(
                f"[AUTH] Login attempt {attempt} failed for {email} after {elapsed:.1f}s: "
                f"{type(e).__name__}: {e}"
            )
            dismiss_consent_screen_if_present(driver)
            if attempt < max_retries:
                time.sleep(1.5)

    BrowserFactory.capture_screenshot(driver, prefix=f"login_fail_{email.split('@')[0]}")
    logger.error(f"[AUTH] All login attempts failed for {email}")
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
