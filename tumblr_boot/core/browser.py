# -*- coding: utf-8 -*-
"""Launch Chrome through AutoHotkey, then attach Selenium to that session."""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from config.settings import SCREENSHOTS_DIR
from utils.logger import logger


DEBUG_HOST = "127.0.0.1"
LOGIN_URL = "https://www.tumblr.com/login"
PROFILE_PREFIX = "tumblr_bot_profile_"

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
    debug_host: str,
    debug_port: int,
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
    if chromeWindow != "" {{
        try {{
            targetPid := WinGetPID(chromeWindow)
            WinClose chromeWindow
            if !WinWaitClose(chromeWindow,, 5)
                ProcessClose targetPid
        }}
    }}
}}

OnExit CloseBotChrome

CheckForStop() {{
    global stopPath
    if FileExist(stopPath)
        ExitApp 0
}}

SetTimer CheckForStop, 250

FindNewChromeWindow(knownWindows, timeoutMs) {{
    deadline := A_TickCount + timeoutMs
    while A_TickCount < deadline {{
        for hwnd in WinGetList("ahk_exe chrome.exe") {{
            if !knownWindows.Has(hwnd)
                return hwnd
        }}
        Sleep 100
    }}
    return 0
}}

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
    . " --remote-debugging-address={debug_host}"
    . " --remote-debugging-port={debug_port}"
    . " --disable-background-mode --disable-background-timer-throttling"
    . " --disable-backgrounding-occluded-windows --disable-renderer-backgrounding"
    . " --no-first-run"
    . " --user-data-dir=" . Chr(34) . profileDir . Chr(34)
    . " " . Chr(34) . loginUrl . Chr(34)

knownChromeWindows := Map()
for hwnd in WinGetList("ahk_exe chrome.exe")
    knownChromeWindows[hwnd] := true

Run chromeCmd,,, &chromePid
chromeWindow := "ahk_pid " . chromePid
if !WinWait(chromeWindow,, 15) {{
    newChromeHwnd := FindNewChromeWindow(knownChromeWindows, 10000)
    if !newChromeHwnd
        ExitApp 2
    chromeWindow := "ahk_id " . newChromeHwnd
}}

Sleep 5000
WinActivate chromeWindow
if !WinWaitActive(chromeWindow,, 10)
    ExitApp 3
Sleep 500
FillAndSubmit()
try FileAppend "ready", signalPath
'''


def _allocate_debug_port() -> int:
    """Ask Windows for an unused localhost port for this Chrome instance."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((DEBUG_HOST, 0))
        return int(probe.getsockname()[1])


def _debugger_is_ready(address: str, timeout: float = 0.5) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{address}/json/version", timeout=timeout
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


def _wait_for_debugger(address: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _debugger_is_ready(address):
            return
        time.sleep(0.2)
    raise TimeoutError(f"Chrome did not open its debugging endpoint on {address}.")


def _wait_for_debugger_shutdown(address: Optional[str], timeout: float = 8.0) -> None:
    if not address:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _debugger_is_ready(address, timeout=0.2):
            return
        time.sleep(0.2)


def _remove_session_profile(profile_dir: Optional[str]) -> bool:
    """Delete only profiles created by this module inside the system temp directory."""
    if not profile_dir:
        return True
    profile = Path(profile_dir).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if profile.parent != temp_root or not profile.name.startswith(PROFILE_PREFIX):
        logger.error(f"[BROWSER] Refusing to delete an unrecognized profile path: {profile}")
        return False

    for attempt in range(6):
        try:
            if profile.exists():
                shutil.rmtree(profile)
            logger.info(f"[BROWSER] Session cookies and profile data removed: {profile}")
            return True
        except OSError as error:
            if attempt == 5:
                logger.warning(f"[BROWSER] Could not fully remove session profile {profile}: {error}")
                return False
            time.sleep(0.5)
    return False


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

    _launch_lock = threading.RLock()

    @classmethod
    @contextmanager
    def desktop_login_slot(cls):
        """Serialize the complete focus-sensitive login phase on RDP desktops."""
        with cls._launch_lock:
            yield

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
            ahk_executable = find_autohotkey_executable()
            chrome_executable = find_chrome_executable()
            profile_dir = tempfile.mkdtemp(prefix=PROFILE_PREFIX)
            debug_port = _allocate_debug_port()
            debug_address = f"{DEBUG_HOST}:{debug_port}"

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
                    profile_dir,
                    signal_path,
                    stop_path,
                    DEBUG_HOST,
                    debug_port,
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
                _wait_for_debugger(debug_address, timeout=15.0)

                options = webdriver.ChromeOptions()
                options.debugger_address = debug_address
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
                driver._tumblr_debug_address = debug_address
                logger.info(
                    f"[BROWSER] Selenium attached to the AutoHotkey Chrome session on {debug_address}."
                )
                return driver, profile_dir, used_profile
            except Exception:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                _stop_controller(controller, stop_path)
                _wait_for_debugger_shutdown(debug_address)
                _remove_session_profile(profile_dir)
                for temporary_path in (script_path, signal_path, stop_path):
                    try:
                        os.unlink(temporary_path)
                    except OSError:
                        pass
                raise

    @staticmethod
    def close_browser(driver: Optional[webdriver.Chrome], profile_dir: Optional[str] = None):
        controller = getattr(driver, "_tumblr_ahk_controller", None) if driver else None
        debug_address = getattr(driver, "_tumblr_debug_address", None) if driver else None
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
        _wait_for_debugger_shutdown(debug_address)

        for temporary_path in temporary_paths:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
        _remove_session_profile(profile_dir)
        time.sleep(1.0)

    @staticmethod
    def move_browser_to_background(driver: webdriver.Chrome, email: str = "") -> bool:
        """Minimize a logged-in Chrome instance while keeping it renderable.

        AutoHotkey needs the native window only until the login is verified.
        Minimizing that exact instance prevents it from covering the next RDP
        login window while Selenium continues through its debugging connection.
        """
        try:
            driver.minimize_window()
            suffix = f" for {email}" if email else ""
            logger.info(f"[BROWSER] Logged-in browser moved to background{suffix}.")
            return True
        except Exception as error:
            suffix = f" for {email}" if email else ""
            logger.warning(
                f"[BROWSER] Could not minimize the logged-in browser{suffix}: {error}"
            )
            return False

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
