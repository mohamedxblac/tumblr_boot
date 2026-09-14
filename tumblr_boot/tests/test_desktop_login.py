"""Regression tests for the normal-Firefox BiDi container workflow."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import auth, browser, engine
from core.bidi import BidiDriver


class DesktopLoginTests(unittest.TestCase):
    def test_container_key_is_stable_without_exposing_email(self):
        first = browser._container_key(" User@Example.test ")
        second = browser._container_key("user@example.test")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[a-f0-9]{16}$")
        self.assertNotIn("user", first)

    def tearDown(self):
        browser.BrowserFactory._prepared_drivers.clear()

    def test_factory_returns_only_a_prepared_native_login_tab(self):
        fake_driver = Mock(spec=BidiDriver)
        browser.BrowserFactory._prepared_drivers["user@example.test"] = fake_driver
        with patch.object(browser.manager, "ensure_started") as ensure_started:
            driver, profile, used = browser.BrowserFactory.create_browser(
                email="user@example.test", password="secret"
            )

        self.assertIs(driver, fake_driver)
        self.assertIsNone(profile)
        self.assertEqual(used["platform_type"], "normal-firefox-native-login-then-bidi")
        ensure_started.assert_not_called()
        fake_driver.get.assert_not_called()

    def test_native_script_uses_uia_and_marks_each_container(self):
        script = browser._build_native_login_script(
            [{"email": "user@example.test", "password": 's`e"cret'}],
            r"C:\Project\vendor\UIA-v2\Lib\UIA.ahk",
            r"C:\Temp\result.status",
        )
        self.assertIn("#Include C:\\Project\\vendor\\UIA-v2\\Lib\\UIA.ahk", script)
        self.assertIn('UIA.ElementFromHandle', script)
        self.assertIn('SendText(Account.Email)', script)
        self.assertIn('SendText(Account.Password)', script)
        self.assertIn('__tumblr_bot_slot=', script)
        self.assertIn('{Ctrl down}{Shift down}', script)
        self.assertNotIn('remote-debugging-port', script)
        self.assertNotIn('session.new', script)
        self.assertNotIn('webdriver', script.lower())

    @unittest.skipUnless(sys.platform == "win32", "AutoHotkey is Windows-only")
    def test_native_script_parses_in_autohotkey_v2(self):
        try:
            executable = browser.find_autohotkey_executable()
            uia_path = browser.find_uia_library()
        except RuntimeError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "syntax_check.ahk"
            script = browser._build_native_login_script(
                [{"email": "user@example.test", "password": "dummy-password"}],
                uia_path,
                str(Path(folder) / "status.txt"),
            )
            path.write_text(script, encoding="utf-8-sig")
            result = subprocess.run(
                [executable, "/ErrorStdOut", str(path), "--validate"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_prepare_connects_bidi_only_after_native_login(self):
        calls = []
        fake_driver = Mock(spec=BidiDriver)
        with (
            patch.object(browser.BrowserFactory, "finish_batch", side_effect=lambda: calls.append("finish")),
            patch.object(browser, "find_firefox_executable", return_value=r"C:\Firefox\firefox.exe"),
            patch.object(browser, "find_autohotkey_executable", return_value=r"C:\AHK\AutoHotkey64.exe"),
            patch.object(browser, "find_uia_library", return_value=r"C:\Project\UIA.ahk"),
            patch.object(browser, "find_default_profile", return_value=r"C:\Profile"),
            patch.object(browser.manager, "ensure_plain_firefox_running", side_effect=lambda *_: calls.append("plain")),
            patch.object(browser, "_run_native_logins", side_effect=lambda *_: calls.append("native")),
            patch.object(browser, "snapshot_tumblr_cookies", side_effect=lambda _: (['id'], [(1,)])),
            patch.object(browser, "_close_firefox_after_login", side_effect=lambda *_: calls.append("close")),
            patch.object(browser.manager, "wait_until_firefox_stops", side_effect=lambda: calls.append("stopped")),
            patch.object(browser, "restore_tumblr_cookies", side_effect=lambda *_: 1),
            patch.object(browser.manager, "ensure_firefox_running", side_effect=lambda *_: calls.append("remote")),
            patch.object(browser, "_reopen_logged_container_tabs", side_effect=lambda *_: calls.append("reopen")),
            patch.object(browser.manager, "connect_session", side_effect=lambda: calls.append("connect")),
            patch.object(browser.manager, "map_marked_container_tabs", return_value={1: "context-1"}),
            patch.object(browser, "BidiDriver", return_value=fake_driver),
        ):
            browser.BrowserFactory.prepare_accounts([
                {"email": "user@example.test", "password": "secret"}
            ])

        self.assertEqual(
            calls,
            ["finish", "plain", "native", "close", "stopped", "remote", "reopen", "connect"],
        )
        self.assertIs(browser.BrowserFactory._prepared_drivers["user@example.test"], fake_driver)

    def test_login_only_checks_bidi_result_and_never_submits_credentials(self):
        driver = Mock()
        wait = Mock()
        wait.until.return_value = "success"
        with patch.object(auth, "WebDriverWait", return_value=wait), patch.object(auth, "logger"):
            self.assertTrue(auth.login(driver, "user@example.test", "dummy-password"))
        driver.get.assert_not_called()
        driver.find_element.assert_not_called()
        driver.find_elements.assert_not_called()

    def test_login_stats_count_unique_accounts_and_track_failures(self):
        bot = engine.BotEngine(Mock())
        bot._reset_login_stats(400)
        bot._record_login_result("First@Example.test", success=True)
        bot._record_login_result("first@example.test", success=True)
        bot._record_login_result("failed@example.test", success=False)

        event = list(bot.gui_queue.queue)[-1]
        self.assertEqual(event["success"], 1)
        self.assertEqual(event["failed"], 1)
        self.assertEqual(event["processed"], 2)
        self.assertEqual(event["total"], 400)
        self.assertIn("failed@example.test", bot._session_login_failed_accounts)


if __name__ == "__main__":
    unittest.main()
