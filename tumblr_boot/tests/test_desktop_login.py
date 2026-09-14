"""Regression tests for the AutoHotkey login and Selenium attachment boundary."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import auth, browser, engine


class DesktopLoginTests(unittest.TestCase):
    def test_generated_script_uses_keyboard_login_and_remote_debugging(self):
        script = browser._build_login_script(
            "user@example.test",
            'p`a"ss',
            r"C:\Chrome\chrome.exe",
            r"C:\Bot\chrome_debug_profile",
            r"C:\Temp\ready.flag",
            r"C:\Temp\stop.flag",
            "127.0.0.1",
            9345,
        )
        self.assertIn("--remote-debugging-port=9345", script)
        self.assertIn("--user-data-dir=", script)
        self.assertIn("--disable-background-timer-throttling", script)
        self.assertIn("--disable-backgrounding-occluded-windows", script)
        self.assertIn("--disable-renderer-backgrounding", script)
        self.assertIn('Send "^a{Backspace}"', script)
        self.assertIn('SendText email', script)
        self.assertIn('SendText password', script)
        self.assertIn('Send "{Enter}"', script)
        self.assertNotIn("F2::", script)
        self.assertIn('password := "p``a`"ss"', script)

    @unittest.skipUnless(sys.platform == "win32", "AutoHotkey is Windows-only")
    def test_generated_script_parses_in_installed_autohotkey_v2(self):
        try:
            executable = browser.find_autohotkey_executable()
        except RuntimeError as exc:
            self.skipTest(str(exc))

        script = browser._build_login_script(
            "user@example.test",
            "dummy-password",
            r"C:\Chrome\chrome.exe",
            r"C:\Bot\chrome_debug_profile",
            r"C:\Temp\ready.flag",
            r"C:\Temp\stop.flag",
            "127.0.0.1",
            9345,
        )
        script = script.replace("#SingleInstance Force\n", "#SingleInstance Force\nExitApp 0\n", 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "syntax_check.ahk"
            path.write_text(script, encoding="utf-8-sig")
            result = subprocess.run(
                [executable, str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_selenium_only_checks_result_and_never_submits_credentials(self):
        driver = Mock()
        wait = Mock()
        wait.until.return_value = "success"
        with patch.object(auth, "WebDriverWait", return_value=wait), patch.object(auth, "logger"):
            self.assertTrue(auth.login(driver, "user@example.test", "dummy-password"))
        driver.get.assert_not_called()
        driver.find_element.assert_not_called()
        driver.find_elements.assert_not_called()

    def test_temporary_session_profile_is_completely_removed(self):
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root) / f"{browser.PROFILE_PREFIX}example"
            profile.mkdir()
            (profile / "Cookies").write_text("old-session", encoding="utf-8")
            with patch.object(browser.tempfile, "gettempdir", return_value=root):
                self.assertTrue(browser._remove_session_profile(str(profile)))
            self.assertFalse(profile.exists())

    def test_logged_in_browser_is_minimized_for_next_rdp_login(self):
        driver = Mock()
        with patch.object(browser, "logger"):
            self.assertTrue(
                browser.BrowserFactory.move_browser_to_background(
                    driver, "user@example.test"
                )
            )
        driver.minimize_window.assert_called_once_with()

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
