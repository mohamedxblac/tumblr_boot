# -*- coding: utf-8 -*-
"""
core/browser.py — Browser Factory with Advanced Stealth & Fingerprint Rotation
==============================================================================
Creates undetected Chrome instances with randomized, coherent fingerprints:
- Rotates User-Agent, Screen Resolution, Timezone, and Locale
- Injects WebGL Vendor/Renderer spoofing via CDP (Chrome DevTools Protocol)
- Injects Canvas Fingerprint perturbation noise to defeat canvas tracking
- Assigns a fresh, temporary user-data-dir for every account session to prevent cross-account linkability
- Automatically cleans up temporary profiles and handles error screenshots
"""

import os
import shutil
import tempfile
import time
from typing import Optional, Tuple
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

from config.settings import SCREENSHOTS_DIR
from config.fingerprints import generate_stealth_fingerprint
from utils.logger import logger
from utils.helpers import now_ts


# JavaScript injected into every page via CDP before any website scripts execute
STEALTH_INJECTION_JS = """
(function() {
    const fp = window.__BOT_FP__ || {};

    // 1. Spoof Navigator Properties
    if (fp.platform) {
        Object.defineProperty(navigator, 'platform', { get: () => fp.platform, configurable: true });
    }
    if (fp.hardware_concurrency) {
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => fp.hardware_concurrency, configurable: true });
    }
    if (fp.device_memory) {
        Object.defineProperty(navigator, 'deviceMemory', { get: () => fp.device_memory, configurable: true });
    }
    if (fp.languages) {
        Object.defineProperty(navigator, 'languages', { get: () => fp.languages, configurable: true });
    }

    // 2. Spoof WebGL Vendor and Renderer
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        // UNMASKED_VENDOR_WEBGL
        if (parameter === 37445 && fp.webgl_vendor) {
            return fp.webgl_vendor;
        }
        // UNMASKED_RENDERER_WEBGL
        if (parameter === 37446 && fp.webgl_renderer) {
            return fp.webgl_renderer;
        }
        return getParameter.apply(this, arguments);
    };

    if (window.WebGL2RenderingContext) {
        const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445 && fp.webgl_vendor) {
                return fp.webgl_vendor;
            }
            if (parameter === 37446 && fp.webgl_renderer) {
                return fp.webgl_renderer;
            }
            return getParameter2.apply(this, arguments);
        };
    }

    // 3. Canvas Fingerprint Noise (Subtle 1-bit pixel perturbation)
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        try {
            const ctx = this.getContext('2d');
            if (ctx && this.width > 0 && this.height > 0) {
                const imgData = ctx.getImageData(0, 0, Math.min(this.width, 16), Math.min(this.height, 16));
                for (let i = 0; i < imgData.data.length; i += 8) {
                    imgData.data[i] = (imgData.data[i] ^ 1);
                }
                ctx.putImageData(imgData, 0, 0);
            }
        } catch(e) {}
        return origToDataURL.apply(this, arguments);
    };

    // 4. Overwrite navigator.webdriver to false
    Object.defineProperty(navigator, 'webdriver', { get: () => false, configurable: true });
})();
"""


class BrowserFactory:
    """Manages browser instance creation, fingerprint injection, and lifetime."""

    @staticmethod
    def create_browser(
        fingerprint: Optional[dict] = None,
        headless: bool = False
    ) -> Tuple[uc.Chrome, str, dict]:
        """
        Creates an undetected Chrome instance with an isolated profile and active stealth.
        Returns: (driver, profile_dir, fingerprint_dict)
        """
        if fingerprint is None:
            fingerprint = generate_stealth_fingerprint()

        # Create isolated temporary user-data-dir
        profile_dir = tempfile.mkdtemp(prefix="tumblr_bot_profile_")

        options = uc.ChromeOptions()
        options.user_data_dir = profile_dir
        options.add_argument(f"--user-agent={fingerprint['user_agent']}")
        options.add_argument(f"--window-size={fingerprint['screen_width']},{fingerprint['screen_height']}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-service-autorun")
        options.add_argument("--password-store=basic")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument("--lang=en-US,en")

        if headless:
            options.add_argument("--headless=new")

        driver = None
        try:
            # Try matching local installed Chrome
            driver = uc.Chrome(options=options)
        except Exception as ex_main:
            logger.warning(f"[BROWSER] Standard initialization failed ({ex_main}), attempting fallback...")
            try:
                driver = uc.Chrome(options=options, version_main=None)
            except Exception as ex_fallback:
                logger.error(f"[BROWSER] Failed to initialize Chrome driver: {ex_fallback}")
                # Clean up profile dir if launch aborted
                if os.path.exists(profile_dir):
                    try:
                        shutil.rmtree(profile_dir, ignore_errors=True)
                    except Exception:
                        pass
                raise ex_fallback

        # Configure timeouts
        driver.set_page_load_timeout(60)
        driver.implicitly_wait(6)

        # Inject fingerprint data into DOM on every new document load
        try:
            setup_script = f"window.__BOT_FP__ = {fingerprint};\n" + STEALTH_INJECTION_JS
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": setup_script})
        except Exception as e:
            logger.warning(f"[BROWSER] Could not inject stealth script via CDP: {e}")

        # Override Timezone via CDP
        try:
            driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": fingerprint["timezone"]})
        except Exception as e:
            logger.debug(f"[BROWSER] Timezone CDP override skipped: {e}")

        logger.info(
            f"[BROWSER] Chrome launched | OS: {fingerprint['platform_type'].upper()} | "
            f"Res: {fingerprint['screen_width']}x{fingerprint['screen_height']} | "
            f"TZ: {fingerprint['timezone']}"
        )

        return driver, profile_dir, fingerprint

    @staticmethod
    def close_browser(driver: Optional[uc.Chrome], profile_dir: Optional[str] = None):
        """Safely quits the driver and cleans up the temporary profile folder."""
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.debug(f"[BROWSER] Error during driver.quit: {e}")

        # Small grace period for chrome processes to fully release file locks
        time.sleep(1.0)

        if profile_dir and os.path.exists(profile_dir):
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
                logger.debug(f"[BROWSER] Profile cleaned up: {profile_dir}")
            except Exception as e:
                logger.debug(f"[BROWSER] Could not remove temp profile dir ({e})")

    @staticmethod
    def capture_screenshot(driver: Optional[uc.Chrome], prefix: str = "error") -> Optional[str]:
        """Captures a screenshot of the current browser state for troubleshooting."""
        if not driver:
            return None
        try:
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{ts}.png"
            filepath = os.path.join(SCREENSHOTS_DIR, filename)
            driver.save_screenshot(filepath)
            logger.info(f"[SCREENSHOT] Saved state capture to: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"[SCREENSHOT] Failed to capture screenshot: {e}")
            return None
