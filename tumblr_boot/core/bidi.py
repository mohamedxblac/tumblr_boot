"""Synchronous Firefox WebDriver BiDi client for normal browser tabs.

This module talks directly to Firefox's loopback Remote Agent.  It doesn't use
Selenium, GeckoDriver, Marionette, a temporary browser profile, or a custom
browser extension.
"""

import atexit
import base64
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

from websockets.sync.client import connect

from utils.logger import logger


BIDI_HOST = "127.0.0.1"
BIDI_PORT = 9222
BIDI_ENDPOINT = f"ws://{BIDI_HOST}:{BIDI_PORT}/session"
LOGIN_URL = "https://www.tumblr.com/login"
MAX_CONTAINER_SLOTS = 9


class BidiError(RuntimeError):
    pass


def _port_is_open(timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((BIDI_HOST, BIDI_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _firefox_is_running() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq firefox.exe", "/NH"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "firefox.exe" in result.stdout.lower()
    except Exception:
        return False


def _local_value(value: Any) -> dict:
    if isinstance(value, BidiElement):
        return {"sharedId": value.shared_id}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, str):
        return {"type": "string", "value": value}
    if isinstance(value, (int, float)):
        return {"type": "number", "value": value}
    if isinstance(value, (list, tuple)):
        return {"type": "array", "value": [_local_value(item) for item in value]}
    if isinstance(value, dict):
        return {
            "type": "object",
            "value": [[str(key), _local_value(item)] for key, item in value.items()],
        }
    raise TypeError(f"Unsupported BiDi argument type: {type(value).__name__}")


def _remote_value(value: Optional[dict], driver: "BidiDriver") -> Any:
    if not value:
        return None
    value_type = value.get("type")
    if value_type in {"undefined", "null"}:
        return None
    if value_type in {"string", "boolean", "number", "bigint"}:
        return value.get("value")
    if value_type == "node":
        shared_id = value.get("sharedId")
        return BidiElement(driver, shared_id) if shared_id else None
    if value_type in {"array", "set"}:
        return [_remote_value(item, driver) for item in value.get("value") or []]
    if value_type in {"object", "map"}:
        converted = {}
        for key, item in value.get("value") or []:
            if isinstance(key, dict):
                key = _remote_value(key, driver)
            converted[str(key)] = _remote_value(item, driver)
        return converted
    return value.get("value")


class FirefoxBidiManager:
    """Own the single BiDi session shared by all container tabs."""

    def __init__(self):
        self._connection = None
        self._request_id = 0
        self._command_lock = threading.RLock()
        self._startup_lock = threading.RLock()
        self._slot_lock = threading.RLock()
        self._abort_event = threading.Event()
        self._free_slots = list(range(1, MAX_CONTAINER_SLOTS + 1))
        self._active_contexts = set()
        self._context_user_contexts = {}

    def ensure_firefox_running(
        self, firefox_executable: str, profile_dir: Optional[str] = None
    ) -> None:
        """Start normal Firefox with the local port, without creating a BiDi session."""
        with self._startup_lock:
            if self._abort_event.is_set():
                raise BidiError("Firefox startup was cancelled by the user.")
            if not _port_is_open():
                if _firefox_is_running():
                    raise BidiError(
                        "Firefox is already open without the local BiDi port. "
                        "Exit Firefox normally, then press Start in the bot again."
                    )
                logger.info("[BIDI] Starting the user's normal Firefox profile.")
                command = [firefox_executable]
                if profile_dir:
                    command.extend(["-profile", profile_dir])
                command.append(f"--remote-debugging-port={BIDI_PORT}")
                subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline and not _port_is_open():
                    if self._abort_event.is_set():
                        raise BidiError("Firefox startup was cancelled by the user.")
                    time.sleep(0.25)
                if not _port_is_open():
                    raise BidiError(
                        f"Firefox did not open the local BiDi port {BIDI_PORT}."
                    )

    def ensure_plain_firefox_running(
        self, firefox_executable: str, profile_dir: Optional[str] = None
    ) -> None:
        """Start Firefox normally, with no remote-control command-line option."""
        with self._startup_lock:
            if self._abort_event.is_set():
                raise BidiError("Firefox startup was cancelled by the user.")
            if _port_is_open():
                raise BidiError(
                    "Firefox is still running in remote-control mode. Exit Firefox "
                    "completely, then start the bot again."
                )
            if _firefox_is_running():
                logger.info("[BROWSER] Using the already-open normal Firefox window for native login.")
                return
            logger.info("[BROWSER] Starting Firefox normally for AutoHotkey-only login.")
            command = [firefox_executable]
            if profile_dir:
                command.extend(["-profile", profile_dir])
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not _firefox_is_running():
                if self._abort_event.is_set():
                    raise BidiError("Firefox startup was cancelled by the user.")
                time.sleep(0.25)
            if not _firefox_is_running():
                raise BidiError("Firefox did not start for the native login phase.")

    def wait_until_firefox_stops(self, timeout: float = 35) -> None:
        """Wait for a graceful profile-unlocking shutdown between the two phases."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._abort_event.is_set():
                return
            if not _firefox_is_running() and not _port_is_open():
                return
            time.sleep(0.35)
        raise BidiError(
            "Firefox did not close after native login. Close every Firefox window "
            "and press Start again."
        )

    def connect_session(self) -> None:
        """Create the automation session only after native desktop login finishes."""
        with self._startup_lock:
            if self._abort_event.is_set():
                raise BidiError("Firefox connection was cancelled by the user.")
            if self._connection is not None:
                return
            if not _port_is_open():
                raise BidiError("Firefox's local BiDi port is not available.")
            try:
                self._connection = connect(
                    BIDI_ENDPOINT,
                    open_timeout=10,
                    max_size=16 * 1024 * 1024,
                )
                result = self.command(
                    "session.new",
                    {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": False}}},
                )
                version = result.get("capabilities", {}).get("browserVersion", "")
                logger.info(f"[BIDI] Connected directly to Firefox {version}.")
            except Exception:
                self._close_connection()
                raise

    def ensure_started(self, firefox_executable: str) -> None:
        """Compatibility helper for tests and non-login diagnostic use."""
        self.ensure_firefox_running(firefox_executable)
        self.connect_session()

    def command(self, method: str, params: Optional[dict] = None, timeout: float = 40) -> dict:
        with self._command_lock:
            if self._abort_event.is_set():
                raise BidiError("Firefox action was cancelled by the user.")
            if self._connection is None:
                raise BidiError("Firefox BiDi is not connected.")
            self._request_id += 1
            request_id = self._request_id
            self._connection.send(json.dumps({
                "id": request_id,
                "method": method,
                "params": params or {},
            }))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self._abort_event.is_set():
                    raise BidiError("Firefox action was cancelled by the user.")
                remaining = max(0.1, deadline - time.monotonic())
                message = json.loads(self._connection.recv(timeout=remaining))
                if message.get("id") != request_id:
                    continue
                if message.get("type") == "error":
                    raise BidiError(
                        f"{method}: {message.get('error', 'unknown error')} - "
                        f"{message.get('message', '')}"
                    )
                return message.get("result", {})
            raise TimeoutError(f"Firefox BiDi command timed out: {method}")

    def contexts(self) -> list[dict]:
        return self.command("browsingContext.getTree", {"maxDepth": 0}).get("contexts", [])

    def map_marked_container_tabs(self, slots: list[int]) -> dict[int, str]:
        """Map marker URLs left by the native login phase to BiDi contexts."""
        pending = set(slots)
        mapped = {}
        user_contexts = set()
        deadline = time.monotonic() + 25
        while pending and time.monotonic() < deadline:
            for item in self.contexts():
                decoded_url = unquote(str(item.get("url", "")))
                for slot in list(pending):
                    if (
                        f"__tumblr_bot_slot={slot}" not in decoded_url
                        and f"tumblr-bot-slot-{slot}" not in decoded_url
                    ):
                        continue
                    context = item["context"]
                    user_context = item.get("userContext", "default")
                    if user_context == "default":
                        raise BidiError(
                            f"Shortcut Ctrl+Shift+{slot} opened a normal tab, not a "
                            "Multi-Account Container tab. Configure that shortcut in Firefox."
                        )
                    if user_context in user_contexts:
                        raise BidiError(
                            f"Shortcut Ctrl+Shift+{slot} reopened a container already used "
                            "by another account. Check the container shortcuts in Firefox."
                        )
                    mapped[slot] = context
                    user_contexts.add(user_context)
                    self._active_contexts.add(context)
                    self._context_user_contexts[context] = user_context
                    pending.remove(slot)
                    logger.info(
                        f"[BIDI] Mapped native login slot {slot} to context {context} "
                        f"(userContext={user_context})."
                    )
                    break
            if pending:
                time.sleep(0.35)
        if pending:
            missing = ", ".join(str(slot) for slot in sorted(pending))
            raise BidiError(
                f"Could not find the Firefox container tab marker for shortcut(s): {missing}."
            )
        return mapped

    def allocate_slot(self) -> int:
        with self._slot_lock:
            if not self._free_slots:
                raise BidiError(
                    "All nine Firefox Multi-Account Container shortcuts are in use. "
                    "Set Parallel Accounts to 9 or fewer."
                )
            return self._free_slots.pop(0)

    def release_slot(self, slot: int) -> None:
        with self._slot_lock:
            if slot not in self._free_slots:
                self._free_slots.append(slot)
                self._free_slots.sort()

    def open_container_tab(self, ahk_executable: str, slot: int) -> str:
        old_contexts = {item["context"] for item in self.contexts()}
        script = f'''#Requires AutoHotkey v2.0
#SingleInstance Force
SendMode("Event")
SetKeyDelay(45, 45)
firefoxHwnd := WinWait("ahk_exe firefox.exe",, 20)
if !firefoxHwnd
    ExitApp(2)
WinRestore("ahk_id " firefoxHwnd)
WinActivate("ahk_id " firefoxHwnd)
if !WinWaitActive("ahk_id " firefoxHwnd,, 8)
    ExitApp(3)
SendEvent("{{Ctrl down}}{{Shift down}}{{{slot}}}{{Shift up}}{{Ctrl up}}")
Sleep(1600)
SendEvent("^l")
Sleep(250)
SendEvent("^a")
SendText("{LOGIN_URL}")
SendEvent("{{Enter}}")
Sleep(1800)
ExitApp(0)
'''
        descriptor, script_path = tempfile.mkstemp(prefix="tumblr_bidi_container_", suffix=".ahk")
        os.close(descriptor)
        try:
            Path(script_path).write_text(script, encoding="utf-8-sig")
            result = subprocess.run(
                [ahk_executable, script_path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=35,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                raise BidiError(
                    f"AutoHotkey could not open Firefox container shortcut {slot} "
                    f"(exit code {result.returncode})."
                )
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            new_items = [
                item for item in self.contexts()
                if item["context"] not in old_contexts
            ]
            if new_items:
                item = new_items[-1]
                context = item["context"]
                user_context = item.get("userContext", "default")
                if user_context == "default":
                    try:
                        self.command("browsingContext.close", {
                            "context": context,
                            "promptUnload": False,
                        })
                    except Exception:
                        pass
                    raise BidiError(
                        f"Shortcut Ctrl+Shift+{slot} opened a normal tab, not a "
                        "Multi-Account Container tab. Configure that shortcut in Firefox."
                    )
                if user_context in self._context_user_contexts.values():
                    try:
                        self.command("browsingContext.close", {
                            "context": context,
                            "promptUnload": False,
                        })
                    except Exception:
                        pass
                    raise BidiError(
                        f"Shortcut Ctrl+Shift+{slot} reopened a container already used "
                        "by another active account. Check the container shortcuts in Firefox."
                    )
                self._active_contexts.add(context)
                self._context_user_contexts[context] = user_context
                logger.info(
                    f"[BIDI] Container shortcut {slot} opened in context {context} "
                    f"(userContext={user_context})."
                )
                return context
            time.sleep(0.3)
        raise BidiError(f"Firefox did not create a new tab for container shortcut {slot}.")

    def clear_tumblr_cookies(self, context: str) -> None:
        try:
            self.command("storage.deleteCookies", {
                "filter": {"domain": "tumblr.com"},
                "partition": {"type": "context", "context": context},
            })
            logger.info("[BIDI] Cleared old Tumblr cookies in the selected container.")
        except Exception as error:
            logger.warning(f"[BIDI] Could not clear old container cookies: {error}")

    def clear_container_cookies(self, context: str) -> None:
        """Delete every cookie in one Firefox Container storage partition."""
        self.command("storage.deleteCookies", {
            "partition": {"type": "context", "context": context},
        })
        logger.info("[BIDI] Cleared all cookies from the selected Firefox container.")

    def close_context(self, context: str) -> None:
        if context not in self._active_contexts:
            return
        try:
            self.command("browsingContext.close", {"context": context, "promptUnload": False})
        except Exception as error:
            logger.debug(f"[BIDI] Could not close tab {context}: {error}")
        finally:
            self._active_contexts.discard(context)
            self._context_user_contexts.pop(context, None)

    def disconnect_session(self) -> None:
        with self._startup_lock:
            if self._connection is not None:
                try:
                    self.command("session.end", {}, timeout=5)
                except Exception:
                    pass
            self._close_connection()
            self._active_contexts.clear()
            self._context_user_contexts.clear()
            self._free_slots = list(range(1, MAX_CONTAINER_SLOTS + 1))

    def reset_abort(self) -> None:
        self._abort_event.clear()

    def abort(self) -> None:
        """Break pending browser operations without waiting for their timeouts."""
        self._abort_event.set()
        self._close_connection()
        self._active_contexts.clear()
        self._context_user_contexts.clear()
        self._free_slots = list(range(1, MAX_CONTAINER_SLOTS + 1))

    def shutdown(self) -> None:
        self.disconnect_session()

    def _close_connection(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


class _SwitchTo:
    def __init__(self, driver: "BidiDriver"):
        self.driver = driver

    def window(self, context: str) -> None:
        self.driver.context = context

    def frame(self, _frame: "BidiElement") -> None:
        # Consent iframes are optional. Cross-origin frame control isn't needed
        # for the core Tumblr workflow; the caller already handles failure.
        raise BidiError("Frame switching is not available through this adapter.")

    def default_content(self) -> None:
        return None


class BidiDriver:
    def __init__(self, manager: FirefoxBidiManager, context: str, slot: int):
        self.manager = manager
        self.context = context
        self.slot = slot
        self.switch_to = _SwitchTo(self)
        self._closed = False

    def _call(self, function: str, arguments=None, ownership: str = "none") -> Any:
        result = self.manager.command("script.callFunction", {
            "functionDeclaration": function,
            "awaitPromise": True,
            "target": {"context": self.context},
            "arguments": [_local_value(item) for item in (arguments or [])],
            "resultOwnership": ownership,
            "serializationOptions": {"maxObjectDepth": 4},
        })
        if result.get("type") == "exception":
            details = result.get("exceptionDetails", {})
            raise BidiError(details.get("text", "JavaScript failed in the page"))
        return _remote_value(result.get("result"), self)

    @property
    def current_url(self) -> str:
        return str(self.execute_script("return location.href;") or "")

    @property
    def page_source(self) -> str:
        return str(self.execute_script("return document.documentElement.outerHTML;") or "")

    @property
    def current_window_handle(self) -> str:
        return self.context

    @property
    def window_handles(self) -> list[str]:
        return [item["context"] for item in self.manager.contexts()]

    def set_page_load_timeout(self, _seconds: float) -> None:
        return None

    def implicitly_wait(self, _seconds: float) -> None:
        return None

    def set_window_size(self, width: int, height: int) -> None:
        try:
            self.manager.command("browsingContext.setViewport", {
                "context": self.context,
                "viewport": {"width": int(width), "height": int(height)},
            })
        except Exception as error:
            logger.debug(f"[BIDI] Viewport override skipped: {error}")

    def get(self, url: str) -> None:
        self.manager.command("browsingContext.navigate", {
            "context": self.context,
            "url": str(url),
            "wait": "complete",
        }, timeout=60)

    def execute_script(self, script: str, *arguments) -> Any:
        function = (
            "function(...args) { return (function() {\n"
            + str(script)
            + "\n}).apply(null, args); }"
        )
        ownership = "root" if arguments or "querySelector" in script else "none"
        return self._call(function, list(arguments), ownership=ownership)

    def find_elements(self, by: str, selector: str) -> list["BidiElement"]:
        function = r"""
            (strategy, selector) => {
                if (strategy === 'xpath') {
                    const snapshot = document.evaluate(
                        selector, document, null,
                        XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null
                    );
                    const result = [];
                    for (let index = 0; index < snapshot.snapshotLength; index++) {
                        result.push(snapshot.snapshotItem(index));
                    }
                    return result;
                }
                if (strategy === 'tag name') {
                    return [...document.getElementsByTagName(selector)];
                }
                return [...document.querySelectorAll(selector)];
            }
        """
        result = self._call(function, [str(by), str(selector)], ownership="root") or []
        return [item for item in result if isinstance(item, BidiElement)]

    def find_element(self, by: str, selector: str) -> "BidiElement":
        elements = self.find_elements(by, selector)
        if not elements:
            raise LookupError(f"Element was not found ({by}): {selector}")
        return elements[0]

    def save_screenshot(self, path: str) -> bool:
        result = self.manager.command("browsingContext.captureScreenshot", {
            "context": self.context,
            "origin": "viewport",
        })
        Path(path).write_bytes(base64.b64decode(result["data"]))
        return True

    def close(self) -> None:
        self.quit()

    def quit(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.manager.close_context(self.context)
        self.manager.release_slot(self.slot)

    def _send_keys(self, values) -> None:
        shift = "\ue008"
        enter = "\ue007"
        actions = []
        shift_down = False
        for value in values:
            for character in str(value):
                if character == shift:
                    if not shift_down:
                        actions.append({"type": "keyDown", "value": shift})
                        shift_down = True
                    continue
                actions.append({"type": "keyDown", "value": character})
                actions.append({"type": "keyUp", "value": character})
        if shift_down:
            actions.append({"type": "keyUp", "value": shift})
        if not actions:
            return
        self.manager.command("input.performActions", {
            "context": self.context,
            "actions": [{"type": "key", "id": "keyboard", "actions": actions}],
        })


class BidiElement:
    def __init__(self, driver: BidiDriver, shared_id: str):
        self.driver = driver
        self.shared_id = shared_id

    def click(self) -> None:
        self.driver._call(
            "(element) => { element.scrollIntoView({block: 'center'}); "
            "element.focus(); element.click(); return true; }",
            [self],
        )

    def is_displayed(self) -> bool:
        return bool(self.driver._call(r"""
            (element) => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number(style.opacity || 1) !== 0
                    && rect.width > 0 && rect.height > 0;
            }
        """, [self]))

    def is_enabled(self) -> bool:
        return bool(self.driver._call(
            "(element) => !element.disabled && element.getAttribute('aria-disabled') !== 'true'",
            [self],
        ))

    def send_keys(self, *values) -> None:
        self.driver._call(
            "(element) => { element.scrollIntoView({block: 'center'}); element.focus(); return true; }",
            [self],
        )
        self.driver._send_keys(values)


manager = FirefoxBidiManager()
atexit.register(manager.shutdown)
