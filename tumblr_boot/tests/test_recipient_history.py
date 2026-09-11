"""Offline regression checks. Run: python -B -m unittest discover -s tumblr_boot/tests -v"""

import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.contact_history import ContactHistory, ContactHistoryError, normalize_recipient
from core import engine as engine_module
from core import messenger as messenger_module
from core import persistence as persistence_module


class ContactHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "history.sqlite3"
        self.history = ContactHistory(self.database)

    def test_equivalent_recipient_forms_share_one_claim(self):
        forms = [
            "Some-Blog", " @SOME-BLOG ", "https://some-blog.tumblr.com/post/123",
            "https://www.tumblr.com/some-blog?source=share",
            "https://www.tumblr.com/blog/view/some-blog/123",
            "some-blog.tumblr.com", "tumblr.com/@some-blog",
            "https://www.tumblr.com/%53ome-blog",
        ]
        for form in forms:
            self.assertEqual(normalize_recipient(form), "some-blog")
        self.assertTrue(self.history.claim_recipient(forms[0]))
        for form in forms[1:]:
            self.assertFalse(self.history.claim_recipient(form))
        self.assertFalse(self.history.claim_recipient("https://other.example/some-blog"))
        self.assertFalse(self.history.claim_recipient("https://www.tumblr.com/dashboard"))

    def test_pending_attempt_survives_restart_without_counting_as_sent(self):
        self.assertTrue(self.history.claim_recipient("recipient"))
        restarted = ContactHistory(self.database)
        self.assertFalse(restarted.claim_recipient("@Recipient"))
        self.assertEqual(restarted.load_contacted_users(), {"recipient"})
        self.assertEqual(restarted.load_sent_users(), set())

    def test_sent_status_is_durable(self):
        self.history.claim_recipient("recipient")
        self.history.mark_sent("recipient")
        restarted = ContactHistory(self.database)
        self.assertEqual(restarted.load_sent_users(), {"recipient"})
        self.assertFalse(restarted.claim_recipient("recipient"))

    def test_all_legacy_histories_merge_and_missing_text_does_not_remove_protection(self):
        paths = [self.root / f"legacy-{i}.txt" for i in range(3)]
        paths[0].write_text("CURRENT\n", encoding="utf-8-sig")
        paths[1].write_text("@Older\nhttps://current.tumblr.com\n", encoding="utf-8")
        paths[2].write_text("https://www.tumblr.com/oldest\n", encoding="utf-8")
        history = ContactHistory(self.database, paths)
        self.assertEqual(history.load_sent_users(), {"current", "older", "oldest"})
        for path in paths:
            path.unlink()
        self.assertEqual(history.load_sent_users(), {"current", "older", "oldest"})
        self.assertFalse(history.claim_recipient("oldest"))

    def test_legacy_updates_are_checked_before_a_claim(self):
        legacy = self.root / "legacy.txt"
        history = ContactHistory(self.database, [legacy])
        history.load_contacted_users()
        legacy.write_text("newly-sent\n", encoding="utf-8")
        self.assertFalse(history.claim_recipient("newly-sent"))

    def test_concurrent_instances_only_claim_once(self):
        def claim(_):
            return ContactHistory(self.database).claim_recipient("same-person")
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(claim, range(16))).count(True), 1)

    def test_unreadable_database_or_legacy_history_fails_closed(self):
        self.database.write_bytes(b"invalid sqlite database")
        with self.assertRaises(ContactHistoryError):
            self.history.claim_recipient("recipient")
        with self.assertRaises(ContactHistoryError):
            ContactHistory(self.root / "other.sqlite3", [self.root]).load_contacted_users()


class EngineDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.history = ContactHistory(root / "history.sqlite3")
        self.persistence = persistence_module.PersistenceManager.__new__(persistence_module.PersistenceManager)
        self.persistence.contact_history = self.history
        for name, filename in (
            ("SENT_USERS_FILE", "sent.txt"), ("TARGET_QUEUE_FILE", "queue.txt"),
            ("PROGRESS_FILE", "progress.json"),
        ):
            self.stack.enter_context(patch.object(persistence_module, name, str(root / filename)))
        self.stack.enter_context(patch.object(persistence_module, "logger"))
        self.stack.enter_context(patch.object(engine_module, "logger"))
        self.stack.enter_context(patch.object(engine_module, "persistence", self.persistence))
        self.factory = self.stack.enter_context(patch.object(engine_module, "BrowserFactory"))
        self.factory.create_browser.return_value = (Mock(), None, None)
        self.stack.enter_context(patch.object(engine_module, "login", return_value=True))
        self.stack.enter_context(patch.object(engine_module, "logout"))
        self.stack.enter_context(patch.object(engine_module, "time"))
        self.send = self.stack.enter_context(patch.object(engine_module, "send_message_to_user"))
        self.engine = engine_module.BotEngine(Mock())
        self.engine._sleep_with_checks = Mock(return_value=True)

    def process(self, email="first@example.test", target="Recipient"):
        self.engine._process_single_account(
            acc={"email": email, "password": "test"}, post_url="https://www.tumblr.com/example/123",
            tab_type="likes", target_queue=[target], sent_users=set(), progress={},
            messages=["test"], greetings=["hello"], max_per_account=30, session_cap=1,
            no_msg_limit=10, action_delay=0, line_delay=0, after_send_delay=0,
            after_success_delay=0, min_between=0, max_between=0, notes_max=1,
            follow_every=0, scrape_threshold=0, scrape_timeout=1, enable_fp_rotation=False,
        )

    def test_claim_is_saved_before_send_and_prevents_resend_after_account_change(self):
        def delivery(**kwargs):
            self.assertEqual(self.history.load_contacted_users(), {"recipient"})
            self.assertEqual(self.history.load_sent_users(), set())
            self.assertEqual(self.persistence.load_target_queue(), [])
            return True, False
        self.send.side_effect = delivery
        self.process()
        self.process(email="second@example.test", target="https://recipient.tumblr.com")
        self.send.assert_called_once()
        self.assertEqual(self.history.load_sent_users(), {"recipient"})

    def test_failed_or_uncertain_attempt_is_not_retried(self):
        for index, result in enumerate((False, "could_not_send", "no_message_button")):
            with self.subTest(result=result):
                self.send.reset_mock()
                self.send.return_value = (result, False)
                target = f"recipient-{index}"
                self.process(target=target)
                self.process(email="second@example.test", target=target)
                self.send.assert_called_once()
                self.assertNotIn(target, self.history.load_sent_users())

    def test_exception_after_delivery_does_not_release_recipient(self):
        self.send.side_effect = RuntimeError("disconnected after a possible delivery")
        self.process()
        self.persistence.contact_history = ContactHistory(self.history.database_path)
        self.process(email="second@example.test")
        self.send.assert_called_once()

    def test_failed_claim_aborts_before_sending(self):
        with patch.object(self.persistence, "claim_recipient", side_effect=ContactHistoryError("Disk full")):
            with self.assertRaises(ContactHistoryError):
                self.process()
        self.send.assert_not_called()

    def test_history_failure_is_shown_in_gui_before_browser_start(self):
        self.engine.settings_mgr.get_settings.return_value = {"post_url": "https://www.tumblr.com/example/123"}
        self.engine.settings_mgr.get_accounts.return_value = [{"email": "test@example.test", "password": "test"}]
        self.engine.settings_mgr.get_messages.return_value = ["test"]
        self.engine.settings_mgr.get_greetings.return_value = ["hello"]
        with patch.object(self.persistence, "load_sent_users", side_effect=ContactHistoryError("History unavailable")):
            self.engine._run_loop()
        self.factory.create_browser.assert_not_called()
        events = list(self.engine.gui_queue.queue)
        self.assertTrue(any(event["type"] == "error" for event in events))

    def test_queue_and_progress_reset_keep_recipient_protection(self):
        self.history.claim_recipient("already-attempted")
        self.history.mark_sent("already-sent")
        self.persistence.save_target_queue([
            "@Already-Sent", "https://already-attempted.tumblr.com", "New-Person", "@new-person",
        ])
        self.assertEqual(self.persistence.load_target_queue(), ["new-person"])
        self.persistence.reset_progress()
        self.persistence.clear_target_queue()
        with self.assertRaises(ContactHistoryError):
            self.persistence.clear_sent_users()
        self.assertFalse(self.history.claim_recipient("already-attempted"))
        self.assertFalse(self.history.claim_recipient("already-sent"))

    def test_text_export_failure_does_not_lose_sent_recipient(self):
        self.history.claim_recipient("recipient")
        with patch("builtins.open", side_effect=PermissionError("Text export is locked")):
            self.persistence.save_sent_user("recipient")
        self.assertEqual(self.history.load_sent_users(), {"recipient"})
        self.assertFalse(self.history.claim_recipient("recipient"))


class SingleSubmitTests(unittest.TestCase):
    def test_each_message_part_uses_one_submit_action(self):
        driver, textbox = Mock(), Mock()
        driver.page_source = ""
        with patch.object(messenger_module, "time"), patch.object(messenger_module, "dismiss_consent_screen_if_present"), patch.object(messenger_module, "WebDriverWait") as wait:
            wait.return_value.until.return_value = textbox
            result = messenger_module.send_message_to_user(driver, "recipient", ["test"], line_delay=0)
        self.assertEqual(result, (True, False))
        enter_calls = [call for call in textbox.send_keys.call_args_list if call.args == (messenger_module.Keys.ENTER,)]
        self.assertEqual(len(enter_calls), 1)
        self.assertFalse(any("Send" in str(call) for call in driver.find_element.call_args_list))


if __name__ == "__main__":
    unittest.main()
