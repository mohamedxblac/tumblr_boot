# -*- coding: utf-8 -*-
"""Two-phase control of normal Firefox Multi-Account Container tabs.

Credentials are entered through Firefox's native accessibility UI before a
WebDriver BiDi session exists. Python connects only after every login in the
current batch has finished.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple

from config.settings import SCREENSHOTS_DIR
from core.bidi import BidiDriver, BidiError, MAX_CONTAINER_SLOTS, manager
from core.firefox_profile import (
    find_default_profile,
    restore_tumblr_cookies,
    snapshot_tumblr_cookies,
)
from utils.logger import logger


def _first_existing_path(candidates) -> Optional[str]:
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def find_autohotkey_executable() -> str:
    """Find bundled or installed AutoHotkey v2 without invoking a shell."""
    configured = os.environ.get("AUTOHOTKEY_EXE", "").strip()
    discovered = (
        shutil.which("AutoHotkey64.exe")
        or shutil.which("AutoHotkey32.exe")
        or shutil.which("AutoHotkey.exe")
    )
    path = _first_existing_path((
        configured,
        str(_bundle_root() / "tools" / "AutoHotkey64.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "AutoHotkey", "v2", "AutoHotkey64.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "AutoHotkey", "v2", "AutoHotkey32.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "AutoHotkey", "v2", "AutoHotkey32.exe"),
        discovered,
    ))
    if not path:
        raise RuntimeError(
            "AutoHotkey v2 was not found. Install AutoHotkey v2 or set "
            "AUTOHOTKEY_EXE to its full path."
        )
    return path


def find_uia_library() -> str:
    path = _first_existing_path((str(_bundle_root() / "vendor" / "UIA-v2" / "Lib" / "UIA.ahk"),))
    if not path:
        raise RuntimeError("The bundled UIA-v2 library was not found.")
    return path


def find_firefox_executable() -> str:
    """Resolve Firefox for the current Windows user."""
    configured = os.environ.get("FIREFOX_EXE", "").strip()
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    discovered = shutil.which("firefox.exe") or shutil.which("firefox")
    path = _first_existing_path((
        configured,
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Mozilla Firefox", "firefox.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Mozilla Firefox", "firefox.exe"),
        os.path.join(local_app_data, "Mozilla Firefox", "firefox.exe") if local_app_data else None,
        discovered,
    ))
    if not path:
        raise RuntimeError(
            "Mozilla Firefox was not found. Install Firefox or set FIREFOX_EXE "
            "to its full path."
        )
    return path


def _container_key(email: str) -> str:
    """Create a stable non-identifying key for logs and tests."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


def _ahk_string(value: str) -> str:
    """Quote untrusted text as an AutoHotkey v2 string literal."""
    cleaned = str(value).replace("`", "``").replace('"', '`"')
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    return f'"{cleaned}"'


def _build_native_login_script(accounts: list[dict], uia_path: str, status_path: str) -> str:
    account_rows = []
    for slot, account in enumerate(accounts, start=1):
        account_rows.append(
            "    {Shortcut: " + _ahk_string(str(slot))
            + ", Email: " + _ahk_string(account["email"])
            + ", Password: " + _ahk_string(account["password"]) + "}"
        )
    rows = ",\n".join(account_rows)
    include_path = str(uia_path).replace("`", "``")
    status = _ahk_string(status_path)
    return f'''#Requires AutoHotkey v2.0
#SingleInstance Force
#Include {include_path}

SendMode("Event")
SetKeyDelay(45, 45)
SetTitleMatchMode(2)
LoginUrl := "https://www.tumblr.com/login"
global FirefoxHwnd := 0
StatusFile := {status}
Accounts := [
{rows}
]

if A_Args.Length > 0 && A_Args[1] = "--validate"
    ExitApp(0)

try {{
    global FirefoxHwnd := WinWait("ahk_exe firefox.exe",, 25)
    if !FirefoxHwnd
        throw Error("Firefox did not appear within 25 seconds.")
    if !ActivateFirefox()
        throw Error("Firefox could not be activated. No credentials were typed.")
    ; On a fresh Firefox launch, wait for Multi-Account Containers to finish
    ; registering its keyboard commands before the first shortcut is sent.
    Sleep(6500)

    for Index, Account in Accounts {{
        if !ActivateFirefox()
            throw Error("Firefox lost focus before container " Account.Shortcut ".")
        SendEvent("{{Ctrl down}}{{Shift down}}{{" Account.Shortcut "}}{{Shift up}}{{Ctrl up}}")
        Sleep(2600)
        if Index = 1 {{
            ; Remove Firefox's initial ordinary tab. The remaining container
            ; tabs then have stable positions 1..N for native message actions.
            SendEvent("^1")
            Sleep(500)
            SendEvent("^w")
            Sleep(1200)
        }}
        NavigateExact(LoginUrl)
        Sleep(7500)

        CurrentUrl := ReadAddressBar()
        if !RegExMatch(CurrentUrl, "i)^https://(www\\.)?tumblr\\.com/(dashboard(?:[/?#]|$))") {{
            if !RegExMatch(CurrentUrl, "i)^https://(www\\.)?tumblr\\.com/login(?:[/?#]|$)")
                throw Error("Tumblr login did not open in container " Account.Shortcut
                    . ". Current address: " CurrentUrl)
            Fields := WaitForTumblrFields(22)
            if !Fields
                throw Error("Tumblr login fields were not found in container " Account.Shortcut ".")
            Fields.Email.SetFocus()
            Sleep(350)
            if !UIA.CompareElements(UIA.GetFocusedElement(), Fields.Email)
                throw Error("The email field did not receive focus for account " Index ".")
            SendEvent("^a")
            SendText(Account.Email)
            Sleep(500)

            Fields := WaitForTumblrFields(6)
            if !Fields
                throw Error("Tumblr changed the form before password entry for account " Index ".")
            Fields.Password.SetFocus()
            Sleep(350)
            if !UIA.CompareElements(UIA.GetFocusedElement(), Fields.Password)
                throw Error("The password field did not receive focus for account " Index ".")
            SendEvent("^a")
            SendText(Account.Password)
            Sleep(500)
            Fields.Submit.Click()
            Sleep(9500)
        }}

        MarkerUrl := "https://www.tumblr.com/dashboard?__tumblr_bot_slot=" Account.Shortcut
            . "#tumblr-bot-slot-" Account.Shortcut
        NavigateExact(MarkerUrl)
        Sleep(6000)
    }}

    for Index, Account in Accounts {{
        SendEvent("^" Index)
        Sleep(900)
        CurrentUrl := ReadAddressBar()
        if !RegExMatch(CurrentUrl, "i)^https://(www\\.)?tumblr\\.com/dashboard(?:[/?#]|$)")
            throw Error("Login was not confirmed for account " Index ". Current address: " CurrentUrl)
    }}
    FileAppend("OK", StatusFile, "UTF-8")
    ExitApp(0)
}}
catch as Err {{
    try FileAppend(Err.Message, StatusFile, "UTF-8")
    ExitApp(1)
}}

ActivateFirefox() {{
    global FirefoxHwnd
    if !FirefoxHwnd || !WinExist("ahk_id " FirefoxHwnd)
        FirefoxHwnd := WinExist("ahk_exe firefox.exe")
    if !FirefoxHwnd
        return false
    try WinRestore("ahk_id " FirefoxHwnd)
    WinActivate("ahk_id " FirefoxHwnd)
    return !!WinWaitActive("ahk_id " FirefoxHwnd,, 6)
}}

NavigateExact(Url) {{
    if !ActivateFirefox()
        throw Error("Firefox lost focus before navigation.")
    SendEvent("^l")
    Sleep(450)
    SendEvent("^a")
    SendText(Url)
    Sleep(350)
    SendEvent("{{Enter}}")
}}

ReadAddressBar() {{
    if !ActivateFirefox()
        return ""
    SavedClipboard := ClipboardAll()
    CurrentUrl := ""
    try {{
        A_Clipboard := ""
        SendEvent("^l")
        Sleep(400)
        SendEvent("^c")
        if ClipWait(2)
            CurrentUrl := A_Clipboard
    }}
    finally {{
        A_Clipboard := SavedClipboard
    }}
    SendEvent("{{Esc}}")
    Sleep(300)
    return CurrentUrl
}}

WaitForTumblrFields(TimeoutSeconds) {{
    global FirefoxHwnd
    Deadline := A_TickCount + (TimeoutSeconds * 1000)
    while A_TickCount < Deadline {{
        try {{
            FirefoxElement := UIA.ElementFromHandle(FirefoxHwnd)
            EmailField := FirefoxElement.ElementExist({{Type: "Edit", Name: "email", cs: false}})
            PasswordField := FirefoxElement.ElementExist({{Type: "Edit", Name: "password", cs: false}})
            SubmitButton := FirefoxElement.ElementExist({{Type: "Button", Name: "Log in", cs: false}})
            if EmailField && PasswordField && SubmitButton
                return {{Email: EmailField, Password: PasswordField, Submit: SubmitButton}}
        }}
        catch {{
        }}
        Sleep(400)
    }}
    return false
}}

^!Esc::ExitApp()
'''


def _run_native_logins(accounts: list[dict], ahk_executable: str, uia_path: str) -> None:
    script_fd, script_path = tempfile.mkstemp(prefix="tumblr_native_login_", suffix=".ahk")
    status_fd, status_path = tempfile.mkstemp(prefix="tumblr_native_login_", suffix=".status")
    os.close(script_fd)
    os.close(status_fd)
    try:
        os.unlink(status_path)
        script = _build_native_login_script(accounts, uia_path, status_path)
        Path(script_path).write_text(script, encoding="utf-8-sig")
        result = subprocess.run(
            [ahk_executable, script_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(90, 55 * len(accounts)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        detail = ""
        if os.path.isfile(status_path):
            detail = Path(status_path).read_text(encoding="utf-8-sig", errors="replace").strip()
        if result.returncode != 0 or detail != "OK":
            raise BidiError(detail or f"Native Firefox login stopped (exit code {result.returncode}).")
    except subprocess.TimeoutExpired as error:
        raise BidiError("Native Firefox login timed out before all accounts finished.") from error
    finally:
        for path in (script_path, status_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def _run_simple_ahk(script: str, ahk_executable: str, prefix: str, timeout: float) -> None:
    script_fd, script_path = tempfile.mkstemp(prefix=prefix, suffix=".ahk")
    status_fd, status_path = tempfile.mkstemp(prefix=prefix, suffix=".status")
    os.close(script_fd)
    os.close(status_fd)
    try:
        os.unlink(status_path)
        script = script.replace("__STATUS__", _ahk_string(status_path))
        Path(script_path).write_text(script, encoding="utf-8-sig")
        result = subprocess.run(
            [ahk_executable, script_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        detail = Path(status_path).read_text(
            encoding="utf-8-sig", errors="replace"
        ).strip() if os.path.isfile(status_path) else ""
        if result.returncode != 0 or detail != "OK":
            raise BidiError(detail or f"AutoHotkey stopped (exit code {result.returncode}).")
    finally:
        for path in (script_path, status_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def _close_firefox_after_login(ahk_executable: str) -> None:
    script = '''#Requires AutoHotkey v2.0
#SingleInstance Force
StatusFile := __STATUS__
hwnd := WinWait("ahk_exe firefox.exe",, 10)
if !hwnd
    ExitApp(2)
WinActivate("ahk_id " hwnd)
if !WinWaitActive("ahk_id " hwnd,, 5)
    ExitApp(3)
WinClose("ahk_id " hwnd)
if !WinWaitClose("ahk_id " hwnd,, 10) {
    WinActivate("ahk_id " hwnd)
    SendEvent("{Enter}")
    if !WinWaitClose("ahk_id " hwnd,, 12)
        ExitApp(4)
}
FileAppend("OK", StatusFile, "UTF-8")
ExitApp(0)
'''
    _run_simple_ahk(script, ahk_executable, "tumblr_close_after_login_", 35)


def _reopen_logged_container_tabs(slot_count: int, ahk_executable: str) -> None:
    slots = ", ".join(f'"{slot}"' for slot in range(1, slot_count + 1))
    script = f'''#Requires AutoHotkey v2.0
#SingleInstance Force
SendMode("Event")
SetKeyDelay(45, 45)
StatusFile := __STATUS__
Slots := [{slots}]
hwnd := WinWait("ahk_exe firefox.exe",, 25)
if !hwnd
    ExitApp(2)
WinActivate("ahk_id " hwnd)
if !WinWaitActive("ahk_id " hwnd,, 6)
    ExitApp(3)
Sleep(6500)
for Index, Slot in Slots {{
    SendEvent("{{Ctrl down}}{{Shift down}}{{" Slot "}}{{Shift up}}{{Ctrl up}}")
    Sleep(2600)
    if Index = 1 {{
        SendEvent("^1")
        Sleep(500)
        SendEvent("^w")
        Sleep(1200)
    }}
    MarkerUrl := "https://www.tumblr.com/dashboard?__tumblr_bot_slot=" Slot
        . "#tumblr-bot-slot-" Slot
    SendEvent("^l")
    Sleep(450)
    SendEvent("^a")
    SendText(MarkerUrl)
    SendEvent("{{Enter}}")
    Sleep(6000)
}}
FileAppend("OK", StatusFile, "UTF-8")
ExitApp(0)
'''
    _run_simple_ahk(
        script,
        ahk_executable,
        "tumblr_reopen_logged_containers_",
        max(70, 25 * slot_count),
    )


class BrowserFactory:
    """Prepare native logins, then expose their tabs through one BiDi session."""

    _launch_lock = threading.RLock()
    _prepared_drivers: dict[str, BidiDriver] = {}

    @classmethod
    @contextmanager
    def desktop_login_slot(cls):
        # Compatibility for existing callers; batch preparation is serialized.
        yield

    @classmethod
    def prepare_accounts(cls, accounts: list[dict]) -> None:
        if not accounts:
            return
        if len(accounts) > MAX_CONTAINER_SLOTS:
            raise ValueError(f"At most {MAX_CONTAINER_SLOTS} accounts can run in one batch.")
        normalized = [str(account.get("email", "")).strip().lower() for account in accounts]
        if any(not email for email in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Every account in a Firefox batch must have a unique email address.")
        if any(account.get("password") is None for account in accounts):
            raise ValueError("Every Firefox account requires a password.")

        with cls._launch_lock:
            cls.finish_batch()
            firefox = find_firefox_executable()
            autohotkey = find_autohotkey_executable()
            profile_dir = find_default_profile()
            manager.ensure_plain_firefox_running(firefox, profile_dir)
            logger.info(
                f"[BROWSER] Starting AutoHotkey-only login for {len(accounts)} account(s). "
                "Firefox has no remote-control option."
            )
            try:
                _run_native_logins(accounts, autohotkey, find_uia_library())
                cookie_snapshot = snapshot_tumblr_cookies(profile_dir)
                logger.info(
                    f"[BROWSER] Captured {len(cookie_snapshot[1])} Tumblr container "
                    "cookies before closing the normal browser."
                )
                _close_firefox_after_login(autohotkey)
                manager.wait_until_firefox_stops()
                restored = restore_tumblr_cookies(profile_dir, cookie_snapshot)
                logger.info(
                    f"[BROWSER] Restored {restored} Tumblr cookies to the same "
                    "Firefox profile after the clean shutdown."
                )
                manager.ensure_firefox_running(firefox, profile_dir)
                _reopen_logged_container_tabs(len(accounts), autohotkey)
                logger.info(
                    "[BROWSER] Reopened the saved container sessions; attaching "
                    "Python after login without submitting credentials again."
                )
                manager.connect_session()
                contexts = manager.map_marked_container_tabs(list(range(1, len(accounts) + 1)))
                cls._prepared_drivers = {
                    normalized[slot - 1]: BidiDriver(manager, contexts[slot], slot)
                    for slot in range(1, len(accounts) + 1)
                }
            except Exception:
                cls._prepared_drivers.clear()
                manager.disconnect_session()
                raise

    @classmethod
    def create_browser(
        cls,
        fingerprint: Optional[dict] = None,
        headless: bool = False,
        *,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Tuple[BidiDriver, None, dict]:
        del password
        if headless:
            raise RuntimeError("The normal Firefox container workflow must be visible.")
        key = str(email or "").strip().lower()
        with cls._launch_lock:
            driver = cls._prepared_drivers.pop(key, None)
        if driver is None:
            raise RuntimeError(
                "This account was not prepared by the native Firefox login phase. "
                "Stop the run and start it again."
            )
        if fingerprint:
            logger.info(
                "[BIDI] Fingerprint rotation is skipped because the bot uses "
                "the user's normal shared Firefox profile."
            )
        logger.info(
            f"[BROWSER] Python control attached after native login for "
            f"{email} ({_container_key(email or '')})."
        )
        native_profile = {
            "platform_type": "normal-firefox-native-login-then-bidi",
            "screen_width": 0,
            "screen_height": 0,
            "timezone": "system",
        }
        return driver, None, native_profile

    @classmethod
    def finish_batch(cls) -> None:
        with cls._launch_lock:
            leftovers = list(cls._prepared_drivers.values())
            cls._prepared_drivers.clear()
            for driver in leftovers:
                try:
                    driver.quit()
                except Exception:
                    pass
            manager.disconnect_session()

    @staticmethod
    def close_browser(driver: Optional[BidiDriver], profile_dir: Optional[str] = None):
        del profile_dir
        if driver:
            try:
                driver.quit()
            except Exception as error:
                logger.debug(f"[BROWSER] Error while closing container tab: {error}")
        time.sleep(0.3)

    @staticmethod
    def capture_screenshot(driver: Optional[BidiDriver], prefix: str = "error") -> Optional[str]:
        if not driver:
            return None
        try:
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(SCREENSHOTS_DIR, f"{prefix}_{timestamp}.png")
            driver.save_screenshot(filepath)
            logger.info(f"[SCREENSHOT] Saved state capture to: {filepath}")
            return filepath
        except Exception as error:
            logger.warning(f"[SCREENSHOT] Failed to capture screenshot: {error}")
            return None
