# -*- coding: utf-8 -*-
"""
core/auth.py — Authentication & Consent Bypass Handler
======================================================
Handles Tumblr account login, logout, and automatic dismissal of GDPR / Cookie
consent walls, modals, and CMP iframes with retry logic and error diagnostics.
"""

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


def human_type(element, text: str, min_d: float = 0.03, max_d: float = 0.08):
    """Types text character by character with realistic randomized typing delay."""
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


def dismiss_consent_screen_if_present(driver) -> bool:
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

        # Check iframes for consent buttons
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


def login(driver, email: str, password: str, max_retries: int = 2) -> bool:
    """
    Performs full Tumblr authentication sequence with human typing,
    consent handling, and verification.
    """
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[AUTH] Attempting login for {email} (attempt {attempt}/{max_retries})...")
            driver.get("https://www.tumblr.com/login")
            time.sleep(3)
            dismiss_consent_screen_if_present(driver)

            # Wait for email input
            email_el = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.NAME, "email"))
            )
            human_type(email_el, email)

            # Wait for password input
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

            # Wait for successful dashboard load
            WebDriverWait(driver, 20).until(
                lambda d: "dashboard" in d.current_url
                or bool(d.find_elements(By.CSS_SELECTOR, "[data-testid='dashboard-feed'], nav"))
            )
            logger.info(f"[AUTH] Login SUCCESSFUL: {email}")
            return True

        except Exception as e:
            logger.warning(f"[AUTH] Login attempt {attempt} failed for {email}: {e}")
            dismiss_consent_screen_if_present(driver)
            if attempt < max_retries:
                time.sleep(4.0)

    # All attempts failed - take diagnostic screenshot
    BrowserFactory.capture_screenshot(driver, prefix=f"login_fail_{email.split('@')[0]}")
    logger.error(f"[AUTH] All login attempts failed for {email}")
    return False


def logout(driver):
    """Logs out cleanly by navigating to account settings."""
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
