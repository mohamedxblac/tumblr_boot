# -*- coding: utf-8 -*-
"""Two-phase control of normal Firefox Multi-Account Container tabs.

Credentials are entered through Firefox's native accessibility UI before a
WebDriver BiDi session exists. Each submitted login is trusted, then Python
connects to exactly the requested number of container tabs.
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
    clear_container_sessions_offline,
    find_default_profile,
    restore_tumblr_cookies,
    snapshot_tumblr_cookies,
)
from utils.logger import logger


_helper_process_lock = threading.RLock()
_active_helper_processes: set[subprocess.Popen] = set()
_helper_abort_event = threading.Event()


def _run_tracked_helper(command: list[str], timeout: float) -> int:
    """Run a native helper that the Stop button can interrupt immediately."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    with _helper_process_lock:
        if _helper_abort_event.is_set():
            try:
                process.terminate()
                process.wait(timeout=0.6)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            raise BidiError("Native browser helper was cancelled by the user.")
        _active_helper_processes.add(process)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except Exception:
            pass
        raise
    finally:
        with _helper_process_lock:
            _active_helper_processes.discard(process)


def _terminate_active_helpers() -> None:
    with _helper_process_lock:
        processes = list(_active_helper_processes)
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            process.terminate()
            process.wait(timeout=0.6)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def force_close_all_firefox() -> None:
    """Force-close every Firefox process and therefore every visible tab."""
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["taskkill.exe", "/F", "/T", "/IM", "firefox.exe"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as error:
        logger.debug(f"[BROWSER] Firefox force-close returned: {error}")


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


def _build_native_login_script(
    accounts: list[dict],
    uia_path: str,
    status_path: str,
    max_successes: Optional[int] = None,
) -> str:
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
    target_slots = max(1, min(MAX_CONTAINER_SLOTS, int(max_successes or len(accounts))))
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
TargetSlots := {target_slots}

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

    Successful := 0
    OpenSlot := 0
    InitialTabClosed := false
    StatusText := "OK`n"

    for Index, Account in Accounts {{
        if Successful >= TargetSlots
            break
        CurrentSlot := Successful + 1
        if !ActivateFirefox()
            throw Error("Firefox lost focus before container " CurrentSlot ".")
        if OpenSlot != CurrentSlot {{
            SendEvent("{{Ctrl down}}{{Shift down}}{{" CurrentSlot "}}{{Shift up}}{{Ctrl up}}")
            Sleep(2600)
            OpenSlot := CurrentSlot
        }}
        if !InitialTabClosed {{
            ; Remove Firefox's initial ordinary tab. The remaining container
            ; tabs then have stable positions 1..N for native message actions.
            SendEvent("^1")
            Sleep(500)
            SendEvent("^w")
            Sleep(1200)
            InitialTabClosed := true
        }}
        NavigateExact(LoginUrl)
        Sleep(4200)

        CurrentUrl := ReadAddressBar()
        ; A container can retain an older session. Never type new credentials
        ; until that session has been explicitly signed out.
        if !RegExMatch(CurrentUrl, "i)^https://(www\\.)?tumblr\\.com/login(?:[/?#]|$)") {{
            ; Tumblr can redirect an existing session to Dashboard, Explore,
            ; Trending, or another authenticated page. Any such redirect means
            ; the container must be logged out before credentials are entered.
            if !LogoutCurrentAccount() {{
                StatusText .= "FAILED|" Index "|logout_failed`n"
                ; Do not keep typing /login for more candidates into a
                ; container whose previous session could not be cleared.
                break
            }}
        }}

        Fields := WaitForTumblrFields(18)
        if !Fields {{
            StatusText .= "FAILED|" Index "|fields_not_found`n"
            continue
        }}
        if !ActivateFirefox()
            throw Error("Firefox was minimized or lost focus before email entry.")
        Fields.Email.SetFocus()
        Sleep(180)
        SendEvent("^a")
        SendText(Account.Email)
        Sleep(180)

        Fields := WaitForTumblrFields(5)
        if !Fields {{
            StatusText .= "FAILED|" Index "|form_changed`n"
            continue
        }}
        if !ActivateFirefox()
            throw Error("Firefox was minimized or lost focus before password entry.")
        Fields.Password.SetFocus()
        Sleep(180)
        SendEvent("^a")
        SendText(Account.Password)
        Sleep(180)
        if !ActivateFirefox()
            throw Error("Firefox was minimized or lost focus before login submission.")
        Fields.Submit.Click()
        ; Trust the submitted credentials. Do not inspect the redirect or
        ; classify the login as successful/failed; continue immediately.
        ; Keep the tab alive briefly so the submitted request can finish, but
        ; do not navigate it or read its result. Markers are added only when
        ; the saved container sessions are reopened for Python control.
        Sleep(3000)
        StatusText .= "SUCCESS|" Index "|" CurrentSlot "`n"
        Successful += 1
        OpenSlot := 0
    }}

    ; Do not leave a failed replacement attempt as an extra open tab.
    if OpenSlot {{
        if ActivateFirefox() {{
            SendEvent("^w")
            Sleep(800)
        }}
    }}

    FileAppend(StatusText, StatusFile, "UTF-8")
    ExitApp(0)
}}
catch as Err {{
    try FileAppend(Err.Message, StatusFile, "UTF-8")
    ExitApp(1)
}}

ActivateFirefox() {{
    global FirefoxHwnd, LoginUrl
    if !FirefoxHwnd || !WinExist("ahk_id " FirefoxHwnd)
        FirefoxHwnd := WinExist("ahk_exe firefox.exe")
    if !FirefoxHwnd
        return false
    try WinRestore("ahk_id " FirefoxHwnd)
    WinActivate("ahk_id " FirefoxHwnd)
    return !!WinWaitActive("ahk_id " FirefoxHwnd,, 6)
}}

LogoutCurrentAccount() {{
    global FirefoxHwnd, LoginUrl
    NavigateExact("https://www.tumblr.com/dashboard")
    Sleep(3500)
    if !ActivateFirefox()
        return false
    try {{
        FirefoxElement := UIA.ElementFromHandle(FirefoxHwnd)
        LogoutButton := FirefoxElement.ElementExist({{Name: "Log out", cs: false}})
        if !LogoutButton
            LogoutButton := FirefoxElement.ElementExist({{Name: "Logout", cs: false}})
        if !LogoutButton
            LogoutButton := FirefoxElement.ElementExist({{Name: "تسجيل الخروج", cs: false}})
        if !LogoutButton || LogoutButton.IsOffscreen {{
            AccountButton := FirefoxElement.ElementExist({{Name: "Account", cs: false}})
            if !AccountButton
                AccountButton := FirefoxElement.ElementExist({{Name: "Accounts", cs: false}})
            if !AccountButton
                AccountButton := FirefoxElement.ElementExist({{Name: "حساب", cs: false}})
            if !AccountButton
                AccountButton := FirefoxElement.ElementExist({{Name: "الحساب", cs: false}})
            if !AccountButton
                AccountButton := FirefoxElement.ElementExist({{Name: "حسابات", cs: false}})
            if !AccountButton
                return false
            AccountButton.Click()
            Sleep(900)

            FirefoxElement := UIA.ElementFromHandle(FirefoxHwnd)
            LogoutButton := FirefoxElement.ElementExist({{Name: "Log out", cs: false}})
            if !LogoutButton
                LogoutButton := FirefoxElement.ElementExist({{Name: "Logout", cs: false}})
            if !LogoutButton
                LogoutButton := FirefoxElement.ElementExist({{Name: "تسجيل الخروج", cs: false}})
        }}
        if !LogoutButton
            return false
        LogoutButton.Click()
        Sleep(900)

        ; Confirm the modal shown by Tumblr after choosing Log out.
        FirefoxElement := UIA.ElementFromHandle(FirefoxHwnd)
        ConfirmButton := FirefoxElement.ElementExist({{Type: "Button", Name: "OK", cs: false}})
        if !ConfirmButton
            ConfirmButton := FirefoxElement.ElementExist({{Type: "Button", Name: "Ok", cs: false}})
        if !ConfirmButton
            ConfirmButton := FirefoxElement.ElementExist({{Type: "Button", Name: "موافق", cs: false}})
        if !ConfirmButton
            return false
        ConfirmButton.Click()
        Sleep(2200)

        CurrentUrl := ReadAddressBar()
        if RegExMatch(CurrentUrl, "i)^https://(www\\.)?tumblr\\.com/login(?:[/?#]|$)")
            return true

        ; Some layouts do not navigate after OK. Open Login only once as a
        ; final verification; an uncleared session would redirect away again.
        NavigateExact(LoginUrl)
        Sleep(2800)
        return RegExMatch(ReadAddressBar(), "i)^https://(www\\.)?tumblr\\.com/login(?:[/?#]|$)")
    }}
    catch {{
        return false
    }}
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


def _run_native_logins(
    accounts: list[dict],
    ahk_executable: str,
    uia_path: str,
    max_successes: Optional[int] = None,
) -> tuple[dict[int, int], set[int]]:
    """Return successful account-index/slot mappings and attempted failures."""
    script_fd, script_path = tempfile.mkstemp(prefix="tumblr_native_login_", suffix=".ahk")
    status_fd, status_path = tempfile.mkstemp(prefix="tumblr_native_login_", suffix=".status")
    os.close(script_fd)
    os.close(status_fd)
    try:
        os.unlink(status_path)
        script = _build_native_login_script(
            accounts,
            uia_path,
            status_path,
            max_successes=max_successes,
        )
        Path(script_path).write_text(script, encoding="utf-8-sig")
        returncode = _run_tracked_helper(
            [ahk_executable, script_path],
            timeout=max(90, 55 * len(accounts)),
        )
        detail = ""
        if os.path.isfile(status_path):
            detail = Path(status_path).read_text(encoding="utf-8-sig", errors="replace").strip()
        lines = [line.strip() for line in detail.splitlines() if line.strip()]
        if returncode != 0 or not lines or lines[0] != "OK":
            raise BidiError(detail or f"Native Firefox login stopped (exit code {returncode}).")
        successes: dict[int, int] = {}
        failures: set[int] = set()
        for line in lines[1:]:
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            try:
                account_index = int(parts[1]) - 1
            except ValueError:
                continue
            if parts[0] == "SUCCESS":
                try:
                    successes[account_index] = int(parts[2])
                except ValueError:
                    continue
            elif parts[0] == "FAILED":
                failures.add(account_index)
        return successes, failures
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
        returncode = _run_tracked_helper([ahk_executable, script_path], timeout=timeout)
        detail = Path(status_path).read_text(
            encoding="utf-8-sig", errors="replace"
        ).strip() if os.path.isfile(status_path) else ""
        if returncode != 0 or detail != "OK":
            raise BidiError(detail or f"AutoHotkey stopped (exit code {returncode}).")
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


def _clear_container_sessions_before_login(
    slot_count: int,
    firefox_executable: str,
    profile_dir: str,
    ahk_executable: str,
) -> None:
    """Clear requested containers without desktop input or visible tabs."""
    del firefox_executable, ahk_executable
    context_ids, deleted_by_context, storage_count = clear_container_sessions_offline(
        profile_dir,
        slot_count,
    )
    for slot, context_id in enumerate(context_ids, start=1):
        logger.info(
            f"[BROWSER] Container slot {slot} (userContextId={context_id}) "
            f"was cleared directly: {deleted_by_context[context_id]} cookie(s)."
        )
    logger.info(
        f"[BROWSER] Offline container cleanup finished for all {slot_count} slot(s); "
        f"removed {storage_count} container storage folder(s)."
    )


class BrowserFactory:
    """Prepare native logins, then expose their tabs through one BiDi session."""

    _launch_lock = threading.RLock()
    _shutdown_lock = threading.RLock()
    _abort_event = threading.Event()
    _prepared_drivers: dict[str, BidiDriver] = {}

    @classmethod
    def reset_abort(cls) -> None:
        """Allow a fresh Start after a previous stop request."""
        cls._abort_event.clear()
        _helper_abort_event.clear()
        manager.reset_abort()

    @classmethod
    def _raise_if_aborted(cls) -> None:
        if cls._abort_event.is_set():
            raise BidiError("Browser preparation was cancelled by the user.")

    @classmethod
    def abort_all(cls) -> None:
        """Immediately cancel helpers, detach BiDi, and close every Firefox tab."""
        with cls._shutdown_lock:
            cls._abort_event.set()
            _helper_abort_event.set()
            _terminate_active_helpers()
            force_close_all_firefox()
            manager.abort()
            cls._prepared_drivers.clear()

    @classmethod
    @contextmanager
    def desktop_login_slot(cls):
        # Compatibility for existing callers; batch preparation is serialized.
        yield

    @classmethod
    def prepare_accounts(
        cls,
        accounts: list[dict],
        max_successes: Optional[int] = None,
        clear_sessions: bool = True,
    ) -> tuple[list[dict], list[dict]]:
        """Prepare only the requested number of successful container sessions.

        Submitted credentials are trusted without checking Tumblr's redirect,
        and no extra tabs are opened after the requested count is reached.
        """
        if not accounts:
            return [], []
        requested = max(1, min(MAX_CONTAINER_SLOTS, int(max_successes or len(accounts))))
        normalized = [str(account.get("email", "")).strip().lower() for account in accounts]
        if any(not email for email in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Every account in a Firefox batch must have a unique email address.")
        if any(account.get("password") is None for account in accounts):
            raise ValueError("Every Firefox account requires a password.")

        with cls._launch_lock:
            cls._raise_if_aborted()
            cls.finish_batch()
            firefox = find_firefox_executable()
            autohotkey = find_autohotkey_executable()
            profile_dir = find_default_profile()
            manager.ensure_plain_firefox_running(firefox, profile_dir)
            cls._raise_if_aborted()
            if clear_sessions:
                logger.info(
                    f"[BROWSER] Clearing previous sessions from "
                    f"{requested} container slot(s) once at startup."
                )
                # Do not use foreground window activation here. RDP can drop
                # those UI events when minimized/disconnected, leaving only
                # the first container cleaned.
                force_close_all_firefox()
                manager.wait_until_firefox_stops()
                cls._raise_if_aborted()
                _clear_container_sessions_before_login(
                    requested,
                    firefox,
                    profile_dir,
                    autohotkey,
                )
                cls._raise_if_aborted()
                manager.ensure_plain_firefox_running(firefox, profile_dir)
            else:
                logger.info(
                    "[BROWSER] Skipping container cleanup; it already ran for this Start."
                )
            logger.info(
                f"[BROWSER] Starting AutoHotkey-only login for {len(accounts)} account(s). "
                "Firefox has no remote-control option."
            )
            try:
                login_result = _run_native_logins(
                    accounts,
                    autohotkey,
                    find_uia_library(),
                    requested,
                )
                cls._raise_if_aborted()
                # Backward-compatible fallback for mocked/legacy callers.
                if login_result is None:
                    successful_slots = {
                        index: index + 1
                        for index in range(min(requested, len(accounts)))
                    }
                    failed_indexes = set()
                else:
                    successful_slots, failed_indexes = login_result

                prepared_accounts = [
                    accounts[index]
                    for index, _slot in sorted(
                        successful_slots.items(), key=lambda item: item[1]
                    )
                ]
                failed_accounts = [
                    accounts[index]
                    for index in sorted(failed_indexes)
                    if 0 <= index < len(accounts)
                ]
                if not prepared_accounts:
                    logger.warning("[BROWSER] No candidate account completed native login.")
                    _close_firefox_after_login(autohotkey)
                    manager.wait_until_firefox_stops()
                    return [], failed_accounts

                cookie_snapshot = snapshot_tumblr_cookies(profile_dir)
                logger.info(
                    f"[BROWSER] Captured {len(cookie_snapshot[1])} Tumblr container "
                    "cookies before closing the normal browser."
                )
                _close_firefox_after_login(autohotkey)
                manager.wait_until_firefox_stops()
                cls._raise_if_aborted()
                restored = restore_tumblr_cookies(profile_dir, cookie_snapshot)
                logger.info(
                    f"[BROWSER] Restored {restored} Tumblr cookies to the same "
                    "Firefox profile after the clean shutdown."
                )
                manager.ensure_firefox_running(firefox, profile_dir)
                cls._raise_if_aborted()
                _reopen_logged_container_tabs(len(prepared_accounts), autohotkey)
                cls._raise_if_aborted()
                logger.info(
                    "[BROWSER] Reopened the saved container sessions; attaching "
                    "Python after login without submitting credentials again."
                )
                manager.connect_session()
                contexts = manager.map_marked_container_tabs(
                    list(range(1, len(prepared_accounts) + 1))
                )
                cls._raise_if_aborted()
                with cls._shutdown_lock:
                    cls._raise_if_aborted()
                    cls._prepared_drivers = {
                        str(account.get("email", "")).strip().lower(): BidiDriver(
                            manager, contexts[slot], slot
                        )
                        for slot, account in enumerate(prepared_accounts, start=1)
                    }
                return prepared_accounts, failed_accounts
            except Exception:
                cls._prepared_drivers.clear()
                if cls._abort_event.is_set():
                    force_close_all_firefox()
                    manager.abort()
                    raise
                manager.disconnect_session()
                try:
                    _close_firefox_after_login(autohotkey)
                    manager.wait_until_firefox_stops()
                except Exception as cleanup_error:
                    logger.warning(
                        f"[BROWSER] Could not fully reset Firefox after an error: "
                        f"{cleanup_error}"
                    )
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
        cls._raise_if_aborted()
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
            if cls._abort_event.is_set():
                manager.abort()
                return
            for driver in leftovers:
                try:
                    driver.quit()
                except Exception:
                    pass
            manager.disconnect_session()

    @staticmethod
    def close_browser(driver: Optional[BidiDriver], profile_dir: Optional[str] = None):
        del profile_dir
        if driver and not BrowserFactory._abort_event.is_set():
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
