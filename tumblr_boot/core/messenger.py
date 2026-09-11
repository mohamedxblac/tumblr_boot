# -*- coding: utf-8 -*-
import time
from typing import List, Tuple, Union

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core.auth import dismiss_consent_screen_if_present
from core.browser import BrowserFactory
from utils.logger import logger


# متابعة حساب المستخدم المستهدف إذا كان زر المتابعة متاحاً
def follow_user(driver, action_delay: float = 0.5) -> bool:
    for sel in [
        "button[aria-label='Follow']",
        "button[aria-label='Follow @']",
        "button[data-testid='follow-button']",
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(action_delay)
            return True
        except Exception:
            continue

    try:
        btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Follow')]"))
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(action_delay)
        return True
    except Exception:
        return False


# كتابة فقرات الرسالة بأمان باستخدام Shift+Enter للفصل بين الأسطر دون إرسال مبكر
def type_message_safely(element, text: str, action_delay: float = 0.5):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            element.send_keys(line)
        if i < len(lines) - 1:
            element.send_keys(Keys.SHIFT, Keys.ENTER)
        if i < len(lines) - 1:
            time.sleep(action_delay)


# تجهيز أجزاء الرسالة الثلاثة: التحية البسيطة، التحية باسم المستخدم، ونص الرسالة
def compose_message_parts(
    username: str,
    base_message: str,
    greeting: str,
    index: int
) -> List[str]:
    salute = "hello" if (index % 2 == 1) else "hi"
    greeting_line = f"{greeting}, {username}"
    return [salute, greeting_line, base_message]


# الانتقال لحساب المستخدم في نفس التبويب وإرسال الرسائل واكتشاف أخطاء الحظر أو الإغلاق
def send_message_to_user(
    driver,
    username: str,
    messages: List[str],
    do_follow: bool = False,
    action_delay: float = 0.5,
    line_delay: float = 7.55,
    after_send_delay: float = 2.2,
) -> Tuple[Union[bool, str], bool]:
    user_url = f"https://www.tumblr.com/{username}"
    try:
        driver.get(user_url)
        time.sleep(4.5)
        dismiss_consent_screen_if_present(driver)

        followed = False
        if do_follow:
            followed = follow_user(driver, action_delay=action_delay)

        try:
            driver.execute_script("window.scrollBy(0, 250);")
        except Exception:
            pass

        clicked = False
        for sel in [
            "a.tx-icon-button.message-button",
            "button[aria-label='Message']",
            "//button[contains(., 'Message')]",
            "//a[contains(@aria-label,'Message')]",
            "a[href*='/message/']",
        ]:
            try:
                btn = (
                    driver.find_element(By.XPATH, sel)
                    if sel.startswith("//")
                    else driver.find_element(By.CSS_SELECTOR, sel)
                )
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
            type_message_safely(input_box, msg, action_delay=action_delay)
            time.sleep(action_delay)
            input_box.send_keys(Keys.ENTER)

            try:
                sb = driver.find_element(
                    By.XPATH, "//button[contains(@aria-label,'Send') or contains(.,'Send')]"
                )
                if sb.is_displayed():
                    driver.execute_script("arguments[0].click();", sb)
            except Exception:
                pass

            time.sleep(line_delay)

        time.sleep(after_send_delay)

        if "Could not send" in driver.page_source:
            BrowserFactory.capture_screenshot(driver, prefix=f"could_not_send_{username}")
            return ("could_not_send", followed)

        return (True, followed)

    except Exception as e:
        logger.warning(f"[SEND] Error messaging {username} ({user_url}): {e}")
        BrowserFactory.capture_screenshot(driver, prefix=f"send_err_{username}")
        return (False, False)
