"""Tests for portable Firefox profile discovery and cookie preservation."""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.firefox_profile import (
    find_default_profile,
    restore_tumblr_cookies,
    snapshot_tumblr_cookies,
)


class FirefoxProfileTests(unittest.TestCase):
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
