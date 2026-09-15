"""Tests for portable Firefox profile discovery and cookie preservation."""

import os
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.firefox_profile import (
    clear_container_sessions_offline,
    find_default_profile,
    restore_tumblr_cookies,
    snapshot_tumblr_cookies,
)


class FirefoxProfileTests(unittest.TestCase):
    def test_offline_cleanup_clears_every_requested_container(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            (profile / "containers.json").write_text(
                json.dumps({
                    "identities": [
                        {"userContextId": 1, "public": True},
                        {"userContextId": 2, "public": True},
                        {"userContextId": 3, "public": True},
                        {"userContextId": 4, "public": True},
                    ]
                }),
                encoding="utf-8",
            )
            database = profile / "cookies.sqlite"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "CREATE TABLE moz_cookies ("
                    "id INTEGER PRIMARY KEY, originAttributes TEXT, host TEXT)"
                )
                connection.executemany(
                    "INSERT INTO moz_cookies VALUES (?, ?, ?)",
                    [
                        (1, "^userContextId=1", ".tumblr.com"),
                        (2, "^userContextId=2", ".example.com"),
                        (3, "^userContextId=3&partitionKey=test", ".tumblr.com"),
                        (4, "^userContextId=4", ".tumblr.com"),
                        (5, "", ".tumblr.com"),
                    ],
                )
                connection.commit()
            finally:
                connection.close()
            storage = profile / "storage" / "default"
            for context_id in (1, 2, 3, 4):
                (storage / f"https+++www.tumblr.com^userContextId={context_id}").mkdir(
                    parents=True
                )

            context_ids, deleted, deleted_storage = clear_container_sessions_offline(
                str(profile), 3
            )

            self.assertEqual(context_ids, [1, 2, 3])
            self.assertEqual(deleted, {1: 1, 2: 1, 3: 1})
            self.assertEqual(deleted_storage, 3)
            connection = sqlite3.connect(database)
            try:
                remaining = connection.execute(
                    "SELECT id FROM moz_cookies ORDER BY id"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(remaining, [(4,), (5,)])
            self.assertTrue(
                (storage / "https+++www.tumblr.com^userContextId=4").is_dir()
            )

    def test_discovers_current_users_profile_without_a_hardcoded_username(self):
        with tempfile.TemporaryDirectory() as folder:
            appdata = Path(folder)
            root = appdata / "Mozilla" / "Firefox"
            profile = root / "Profiles" / "portable.default-release"
            profile.mkdir(parents=True)
            (profile / "prefs.js").write_text("", encoding="utf-8")
            (root / "installs.ini").write_text(
                "[InstallABC]\nDefault=Profiles/portable.default-release\nLocked=1\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"APPDATA": str(appdata)}):
                self.assertEqual(find_default_profile(), str(profile.resolve()))

    def test_restores_only_snapshotted_tumblr_container_cookies(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "cookies.sqlite"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "CREATE TABLE moz_cookies ("
                    "id INTEGER PRIMARY KEY, originAttributes TEXT, name TEXT, "
                    "value TEXT, host TEXT)"
                )
                connection.executemany(
                    "INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?)",
                    [
                        (1, "^userContextId=1", "auth", "one", ".tumblr.com"),
                        (2, "^userContextId=2", "auth", "two", "www.tumblr.com"),
                        (3, "", "other", "keep", ".example.com"),
                    ],
                )
                connection.commit()
            finally:
                connection.close()
            snapshot = snapshot_tumblr_cookies(folder)
            connection = sqlite3.connect(database)
            try:
                connection.execute("DELETE FROM moz_cookies WHERE host LIKE '%tumblr.com'")
                connection.commit()
            finally:
                connection.close()
            self.assertEqual(restore_tumblr_cookies(folder, snapshot), 2)
            connection = sqlite3.connect(database)
            try:
                rows = connection.execute(
                    "SELECT originAttributes, value FROM moz_cookies "
                    "WHERE host LIKE '%tumblr.com' ORDER BY id"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(rows, [("^userContextId=1", "one"), ("^userContextId=2", "two")])


if __name__ == "__main__":
    unittest.main()
