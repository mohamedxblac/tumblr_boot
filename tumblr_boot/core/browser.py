# -*- coding: utf-8 -*-
"""Launch Chrome through AutoHotkey, then attach Selenium to that session."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from config.settings import BASE_DIR, SCREENSHOTS_DIR
from utils.logger import logger


DEBUG_HOST = "127.0.0.1"
DEBUG_PORT = 9222
DEBUG_ADDRESS = f"{DEBUG_HOST}:{DEBUG_PORT}"
LOGIN_URL = "https://www.tumblr.com/login"
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_debug_profile")

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
    Object.defineProperty(navigator, 'webdriver', { get: () => false, configurable: true });
})();
"""


def _first_existing_path(candidates) -> Optional[str]:
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def find_autohotkey_executable() -> str:
    """Find an AutoHotkey v2 executable without invoking a shell."""
    configured = os.environ.get("AUTOHOTKEY_EXE", "").strip()
    discovered = shutil.which("AutoHotkey64.exe") or shutil.which("AutoHotkey.exe")
    path = _first_existing_path(
        (
            configured,
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "AutoHotkey", "v2", "AutoHotkey64.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "AutoHotkey", "UX", "AutoHotkeyUX.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "AutoHotkey", "v2", "AutoHotkey64.exe"),
            discovered,
        )
    )
    if not path:
        raise RuntimeError(
            "AutoHotkey v2 was not found. Install AutoHotkey v2 or set AUTOHOTKEY_EXE "
            "to the full path of AutoHotkey64.exe."
        )
    return path


def find_chrome_executable() -> str:
    """Resolve the real Chrome executable used by the desktop login script."""
    configured = os.environ.get("CHROME_EXE", "").strip()
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    discovered = shutil.which("chrome.exe")
    try:
        uc_discovered = uc.find_chrome_executable()
    except Exception:
        uc_discovered = None
    path = _first_existing_path(
        (
            configured,
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe") if local_app_data else None,
            discovered,
            uc_discovered,
        )
    )
    if not path:
        raise RuntimeError(
            "Google Chrome was not found. Install Chrome or set CHROME_EXE to its full path."
        )
    return path


def _ahk_string(value: str) -> str:
    """Escape arbitrary text for an AutoHotkey v2 quoted string."""
    return (
        str(value)
        .replace("`", "``")
        .replace('"', '`"')
        .replace("\r", "`r")
        .replace("\n", "`n")
    )


def _build_login_script(
    email: str,
    password: str,
    chrome_path: str,
    profile_dir: str,
    signal_path: str,
    stop_path: str,
) -> str:
    """Build the tested keyboard-driven login flow; Selenium is not used here."""
    values = {
        "email": _ahk_string(email),
        "password": _ahk_string(password),
        "chrome": _ahk_string(chrome_path),
        "profile": _ahk_string(profile_dir),
        "signal": _ahk_string(signal_path),
        "stop": _ahk_string(stop_path),
    }
    return f'''#Requires AutoHotkey v2.0
#SingleInstance Force

email := "{values['email']}"
password := "{values['password']}"
loginUrl := "{LOGIN_URL}"
profileDir := "{values['profile']}"
chromePath := "{values['chrome']}"
signalPath := "{values['signal']}"
stopPath := "{values['stop']}"
chromePid := 0
chromeWindow := ""

CloseBotChrome(*) {{
    global chromeWindow
    if chromeWindow != ""
        try WinClose chromeWindow
}}

OnExit CloseBotChrome

CheckForStop() {{
    global stopPath
    if FileExist(stopPath)
        ExitApp 0
}}

SetTimer CheckForStop, 250

FillAndSubmit() {{
    global email, password
    Send "^a{{Backspace}}"
    Sleep 200
    SendText email
    Sleep 400
    Send "{{Tab}}"
    Sleep 300
    Send "^a{{Backspace}}"
    Sleep 200
    SendText password
    Sleep 400
    Send "{{Enter}}"
}}

chromeCmd := Chr(34) . chromePath . Chr(34)
    . " --remote-debugging-address={DEBUG_HOST}"
    . " --remote-debugging-port={DEBUG_PORT}"
    . " --user-data-dir=" . Chr(34) . profileDir . Chr(34)
    . " " . Chr(34) . loginUrl . Chr(34)

Run chromeCmd,,, &chromePid
chromeWindow := "ahk_pid " . chromePid
if !WinWait(chromeWindow,, 15) {{
    chromeWindow := "Tumblr ahk_exe chrome.exe"
    if !WinWait(chromeWindow,, 10)
        ExitApp 2
}}

Sleep 5000
WinActivate chromeWindow
if !WinWaitActive(chromeWindow,, 10)
    ExitApp 3
Sleep 500
FillAndSubmit()
try FileAppend "ready", signalPath

F2::
{{
    FillAndSubmit()
}}
'''


def _debugger_is_ready(timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{DEBUG_ADDRESS}/json/version", timeout=timeout
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("webSocketDebuggerUrl"))
    except Exception:
        return False


def _wait_for_file(path: str, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"AutoHotkey login controller stopped with exit code {return_code}.")
        time.sleep(0.1)
    raise TimeoutError("AutoHotkey did not finish the desktop login input in time.")


def _wait_for_debugger(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _debugger_is_ready():
            return
        time.sleep(0.2)
    raise TimeoutError(f"Chrome did not open its debugging endpoint on {DEBUG_ADDRESS}.")


def _stop_controller(controller: Optional[subprocess.Popen], stop_path: Optional[str]) -> None:
    """Ask AHK to exit normally so its OnExit handler can close Chrome."""
    if not controller or controller.poll() is not None:
        return
    try:
        if stop_path:
            Path(stop_path).write_text("stop", encoding="ascii")
        controller.wait(timeout=5)
    except Exception:
        try:
            controller.terminate()
            controller.wait(timeout=2)
        except Exception:
            try:
                controller.kill()
            except Exception:
                pass


class BrowserFactory:
    """Own the AHK controller and the Selenium attachment for one browser session."""

    _launch_lock = threading.Lock()

    @staticmethod
    def create_browser(
        fingerprint: Optional[dict] = None,
        headless: bool = False,
        *,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Tuple[webdriver.Chrome, str, dict]:
        if headless:
            raise RuntimeError("Desktop login requires a visible Chrome window.")
        if not email or password is None:
            raise ValueError("Desktop login requires an email and password.")

        native_profile = {
            "platform_type": "native-desktop",
            "screen_width": 0,
            "screen_height": 0,
            "timezone": "system",
        }

        with BrowserFactory._launch_lock:
            if _debugger_is_ready():
                raise RuntimeError(
                    f"Port {DEBUG_PORT} is already used by a Chrome debugging session. "
                    "Close that Chrome window, then press Start again."
                )

            ahk_executable = find_autohotkey_executable()
            chrome_executable = find_chrome_executable()
            os.makedirs(PROFILE_DIR, exist_ok=True)

            script_fd, script_path = tempfile.mkstemp(prefix="tumblr_desktop_login_", suffix=".ahk")
            os.close(script_fd)
            signal_fd, signal_path = tempfile.mkstemp(prefix="tumblr_desktop_login_", suffix=".ready")
            os.close(signal_fd)
            os.unlink(signal_path)
            stop_fd, stop_path = tempfile.mkstemp(prefix="tumblr_desktop_login_", suffix=".stop")
            os.close(stop_fd)
            os.unlink(stop_path)

            controller = None
            driver = None
            try:
                script_text = _build_login_script(
                    email,
                    password,
                    chrome_executable,
                    PROFILE_DIR,
                    signal_path,
                    stop_path,
                )
                Path(script_path).write_text(script_text, encoding="utf-8-sig")

                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                controller = subprocess.Popen(
                    [ahk_executable, script_path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
                logger.info(
                    f"[AUTH] Chrome opened by AutoHotkey for {email}; waiting for desktop input..."
                )
                _wait_for_file(signal_path, controller, timeout=25.0)
                _wait_for_debugger(timeout=15.0)

                options = webdriver.ChromeOptions()
                options.debugger_address = DEBUG_ADDRESS
                options.page_load_strategy = "eager"

                patcher = uc.Patcher()
                patcher.auto()
                service = Service(executable_path=patcher.executable_path)
                driver = webdriver.Chrome(service=service, options=options)
                driver.set_page_load_timeout(30)
                driver.implicitly_wait(0)

                # Login itself stays completely native. Optional fingerprint
                # rotation is installed only after attachment, for later pages.
                used_profile = fingerprint or native_profile
                if fingerprint:
                    try:
                        setup_script = (
                            f"window.__BOT_FP__ = {json.dumps(fingerprint)};\n"
                            + STEALTH_INJECTION_JS
                        )
                        driver.execute_cdp_cmd(
                            "Page.addScriptToEvaluateOnNewDocument",
                            {"source": setup_script},
                        )
                        if fingerprint.get("timezone"):
                            driver.execute_cdp_cmd(
                                "Emulation.setTimezoneOverride",
                                {"timezoneId": fingerprint["timezone"]},
                            )
                        if fingerprint.get("user_agent"):
                            driver.execute_cdp_cmd(
                                "Network.setUserAgentOverride",
                                {
                                    "userAgent": fingerprint["user_agent"],
                                    "acceptLanguage": "en-US,en",
                                    "platform": fingerprint.get("platform", "Win32"),
                                },
                            )
                    except Exception as e:
                        logger.warning(f"[BROWSER] Post-login fingerprint setup was skipped: {e}")

                driver._tumblr_ahk_controller = controller
                driver._tumblr_ahk_script = script_path
                driver._tumblr_ahk_signal = signal_path
                driver._tumblr_ahk_stop = stop_path
                logger.info(
                    f"[BROWSER] Selenium attached to the AutoHotkey Chrome session on {DEBUG_ADDRESS}."
                )
                return driver, PROFILE_DIR, used_profile
            except Exception:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                _stop_controller(controller, stop_path)
                for temporary_path in (script_path, signal_path, stop_path):
                    try:
                        os.unlink(temporary_path)
                    except OSError:
                        pass
                raise

    @staticmethod
    def close_browser(driver: Optional[webdriver.Chrome], profile_dir: Optional[str] = None):
        del profile_dir  # The fixed profile is intentionally retained between runs.
        controller = getattr(driver, "_tumblr_ahk_controller", None) if driver else None
        temporary_paths = (
            getattr(driver, "_tumblr_ahk_script", None) if driver else None,
            getattr(driver, "_tumblr_ahk_signal", None) if driver else None,
            getattr(driver, "_tumblr_ahk_stop", None) if driver else None,
        )
        stop_path = temporary_paths[2]

        if driver:
            try:
                driver.quit()
            except Exception as e:
                logger.debug(f"[BROWSER] Error during driver.quit: {e}")

        _stop_controller(controller, stop_path)

        for temporary_path in temporary_paths:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
        time.sleep(1.0)

    @staticmethod
    def capture_screenshot(driver: Optional[webdriver.Chrome], prefix: str = "error") -> Optional[str]:
        if not driver:
            return None
        try:
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(SCREENSHOTS_DIR, f"{prefix}_{ts}.png")
            driver.save_screenshot(filepath)
            logger.info(f"[SCREENSHOT] Saved state capture to: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"[SCREENSHOT] Failed to capture screenshot: {e}")
            return None
