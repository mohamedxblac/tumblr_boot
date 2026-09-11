# -*- coding: utf-8 -*-
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

STEALTH_INJECTION_JS = """
(function() {
    const fp = window.__BOT_FP__ || {};

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

    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445 && fp.webgl_vendor) return fp.webgl_vendor;
        if (parameter === 37446 && fp.webgl_renderer) return fp.webgl_renderer;
        return getParameter.apply(this, arguments);
    };

    if (window.WebGL2RenderingContext) {
        const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445 && fp.webgl_vendor) return fp.webgl_vendor;
            if (parameter === 37446 && fp.webgl_renderer) return fp.webgl_renderer;
            return getParameter2.apply(this, arguments);
        };
    }

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

    Object.defineProperty(navigator, 'webdriver', { get: () => false, configurable: true });
})();
"""


# فئة تشغيل المتصفح الخفي وتدوير البصمة الرقمية وعزل بيانات كل جلسة
class BrowserFactory:
    @staticmethod
    def create_browser(
        fingerprint: Optional[dict] = None,
        headless: bool = False
    ) -> Tuple[uc.Chrome, str, dict]:
        if fingerprint is None:
            fingerprint = generate_stealth_fingerprint()

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
            driver = uc.Chrome(options=options)
        except Exception as ex_main:
            logger.warning(f"[BROWSER] Standard initialization failed ({ex_main}), attempting fallback...")
            try:
                driver = uc.Chrome(options=options, version_main=None)
            except Exception as ex_fallback:
                logger.error(f"[BROWSER] Failed to initialize Chrome driver: {ex_fallback}")
                if os.path.exists(profile_dir):
                    try:
                        shutil.rmtree(profile_dir, ignore_errors=True)
                    except Exception:
                        pass
                raise ex_fallback

        driver.set_page_load_timeout(60)
        driver.implicitly_wait(6)

        try:
            setup_script = f"window.__BOT_FP__ = {fingerprint};\n" + STEALTH_INJECTION_JS
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": setup_script})
        except Exception as e:
            logger.warning(f"[BROWSER] Could not inject stealth script via CDP: {e}")

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

    # إغلاق المتصفح وحذف المجلد المؤقت لتنظيف أثر الجلسة
    @staticmethod
    def close_browser(driver: Optional[uc.Chrome], profile_dir: Optional[str] = None):
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.debug(f"[BROWSER] Error during driver.quit: {e}")

        time.sleep(1.0)

        if profile_dir and os.path.exists(profile_dir):
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass

    # التقاط لقطة شاشة وحفظها عند حدوث خطأ للتشخيص
    @staticmethod
    def capture_screenshot(driver: Optional[uc.Chrome], prefix: str = "error") -> Optional[str]:
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
