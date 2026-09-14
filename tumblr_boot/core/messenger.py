# -*- coding: utf-8 -*-
import random
import threading
import time
from typing import List, Tuple, Union

from core.compat import By, Keys, WebDriverWait, EC

from core.auth import dismiss_consent_screen_if_present
from core.browser import BrowserFactory
from utils.logger import logger


class NonRepeatingTemplateRotator:
    """Thread-safe shuffle bag shared by every active account.

    Every distinct template is used once before the bag is refilled.  The first
    item of a new bag is also kept different from the last item of the previous
    bag, so parallel browser sessions cannot restart at template number one.
    """

    def __init__(self, templates: List[str]):
        self._templates = []
        seen = set()
        for template in templates:
            cleaned = str(template).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                self._templates.append(cleaned)
        if not self._templates:
            raise ValueError("At least one non-empty template is required.")

        self._lock = threading.Lock()
        self._bag = []
        self._last_index = None
        self._sequence = 0

    def __len__(self) -> int:
        return len(self._templates)

    def next_template(self) -> Tuple[str, int]:
        with self._lock:
            if not self._bag:
                self._bag = list(range(len(self._templates)))
                random.shuffle(self._bag)
                if (
                    len(self._bag) > 1
                    and self._last_index is not None
                    and self._bag[0] == self._last_index
                ):
                    swap_at = next(
                        i for i, index in enumerate(self._bag)
                        if index != self._last_index
                    )
                    self._bag[0], self._bag[swap_at] = self._bag[swap_at], self._bag[0]

            index = self._bag.pop(0)
            sequence = self._sequence
            self._sequence += 1
            self._last_index = index
            return self._templates[index], sequence


# متابعة حساب المستخدم المستهدف إذا كان زر المتابعة متاحاً
def follow_user(driver, action_delay: float = 0.15) -> bool:
    try:
        btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((
            By.CSS_SELECTOR,
            "button[aria-label='Follow'], button[aria-label='Follow @'], "
            "button[data-testid='follow-button']",
        )))
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(action_delay)
        return True
    except Exception:
        pass

    try:
        btn = WebDriverWait(driver, 1.5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Follow')]"))
        )
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(action_delay)
        return True
    except Exception:
        return False


# كتابة فقرات الرسالة حرفاً بحرف وبسرعات متغيرة، دون لصق النص دفعة واحدة
def type_message_safely(
    element,
    text: str,
    action_delay: float = 0.15,
    typing_min_delay: float = 0.01,
    typing_max_delay: float = 0.03,
):
    typing_min_delay = max(0.0, float(typing_min_delay))
    typing_max_delay = max(typing_min_delay, float(typing_max_delay))
    lines = text.split("\n")
    for i, line in enumerate(lines):
        chunk = []
        chunk_delay = 0.0
        for character in line:
            chunk.append(character)
            chunk_delay += random.uniform(typing_min_delay, typing_max_delay)
            if character in ".,!?;:":
                chunk_delay += random.uniform(0.01, 0.04)
            if len(chunk) >= 8 or character in ".,!?;:":
                element.send_keys("".join(chunk))
                if chunk_delay:
                    time.sleep(chunk_delay)
                chunk = []
                chunk_delay = 0.0
        if chunk:
            element.send_keys("".join(chunk))
            if chunk_delay:
                time.sleep(chunk_delay)
        if i < len(lines) - 1:
            element.send_keys(Keys.SHIFT, Keys.ENTER)
            time.sleep(max(action_delay, random.uniform(0.05, 0.12)))


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
    action_delay: float = 0.15,
    line_delay: float = 0.65,
    after_send_delay: float = 0.35,
    typing_min_delay: float = 0.01,
    typing_max_delay: float = 0.03,
) -> Tuple[Union[bool, str], bool]:
    user_url = f"https://www.tumblr.com/{username}"
    try:
        navigation_error = None
        for attempt in range(2):
            try:
                driver.get(user_url)
                navigation_error = None
                break
            except Exception as error:
                navigation_error = error
                logger.warning(
                    f"[SEND] Navigation attempt {attempt + 1}/2 failed for "
                    f"{username}: {error}"
                )
                time.sleep(0.4)
        if navigation_error is not None:
            raise navigation_error
        dismiss_consent_screen_if_present(driver)

        followed = False
        if do_follow:
            followed = follow_user(driver, action_delay=action_delay)

        try:
            driver.execute_script("window.scrollBy(0, 250);")
        except Exception:
            pass

        button_selectors = [
            "a.tx-icon-button.message-button",
            "button[aria-label='Message']",
            "//button[contains(., 'Message')]",
            "//a[contains(@aria-label,'Message')]",
            "a[href*='/message/']",
        ]

        def find_message_button(current_driver):
            for selector in button_selectors:
                try:
                    button = (
                        current_driver.find_element(By.XPATH, selector)
                        if selector.startswith("//")
                        else current_driver.find_element(By.CSS_SELECTOR, selector)
                    )
                    if button.is_displayed() and button.is_enabled():
                        return button
                except Exception:
                    continue
            return False

        try:
            btn = WebDriverWait(driver, 4).until(find_message_button)
            driver.execute_script("arguments[0].click();", btn)
            clicked = True
        except Exception:
            clicked = False

        if not clicked:
            return ("no_message_button", followed)

        try:
            input_box = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    "textarea, div[contenteditable='true'], [role='textbox']",
                ))
            )
        except Exception:
            return ("no_message_button", followed)

        for msg in messages:
            input_box.click()
            type_message_safely(
                input_box,
                msg,
                action_delay=action_delay,
                typing_min_delay=typing_min_delay,
                typing_max_delay=typing_max_delay,
            )
            # A short thinking pause prevents even a very short salutation from
            # being submitted immediately after its final keystroke.
            time.sleep(max(action_delay, random.uniform(0.08, 0.18)))
            input_box.send_keys(Keys.ENTER)
            # Use one submit action. Clicking Send again can submit twice when
            # the input has not yet cleared after Enter.

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
