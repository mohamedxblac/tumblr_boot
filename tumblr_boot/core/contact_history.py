"""Durable, account-independent protection against repeated recipient attempts."""

import os
import sqlite3
from contextlib import contextmanager

from utils.helpers import extract_username, is_valid_blog


class ContactHistoryError(RuntimeError):
    """Sending must stop when the recipient history cannot be read or saved."""


def normalize_recipient(value: str) -> str:
    username = extract_username(value)
    return username if is_valid_blog(username) else ""


class ContactHistory:
    def __init__(self, database_path: str, legacy_paths=()):
        self.database_path = os.fspath(database_path)
        self.legacy_paths = tuple(dict.fromkeys(os.fspath(path) for path in legacy_paths))

    @contextmanager
    def _connect(self):
        connection = None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.database_path)), exist_ok=True)
            connection = sqlite3.connect(self.database_path, timeout=10, isolation_level="IMMEDIATE")
            connection.execute("PRAGMA synchronous = FULL")
            with connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS recipients (
                        username TEXT PRIMARY KEY,
                        status TEXT NOT NULL CHECK (status IN ('attempted', 'sent')),
                        attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        sent_at TEXT
                    )
                """)
                # Merge all known text histories, even when the current one exists.
                # Rechecking before a claim also notices legacy application writes.
                for path in self.legacy_paths:
                    try:
                        with open(path, encoding="utf-8-sig") as stream:
                            usernames = {normalize_recipient(line) for line in stream}
                    except FileNotFoundError:
                        continue
                    connection.executemany("""
                        INSERT INTO recipients (username, status, sent_at)
                        VALUES (?, 'sent', CURRENT_TIMESTAMP)
                        ON CONFLICT(username) DO UPDATE SET
                            status = 'sent', sent_at = COALESCE(sent_at, excluded.sent_at)
                    """, [(username,) for username in usernames if username])
                yield connection
        except (OSError, UnicodeError, sqlite3.Error) as error:
            raise ContactHistoryError(
                "Recipient history could not be read or saved. Sending stopped to prevent duplicate messages."
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def load_sent_users(self) -> set[str]:
        with self._connect() as connection:
            return {row[0] for row in connection.execute("SELECT username FROM recipients WHERE status = 'sent'")}

    def load_contacted_users(self) -> set[str]:
        with self._connect() as connection:
            return {row[0] for row in connection.execute("SELECT username FROM recipients")}

    def claim_recipient(self, value: str) -> bool:
        """Commit before sending; the unique key protects concurrent app instances.

        Attempts stay blocked after a failure or crash because delivery may already
        have happened. This deliberately prefers a missed send over a duplicate.
        """
        username = normalize_recipient(value)
        if not username:
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO recipients (username, status) VALUES (?, 'attempted')",
                (username,),
            )
            claimed = cursor.rowcount == 1
        return claimed

    def mark_sent(self, value: str):
        username = normalize_recipient(value)
        if not username:
            raise ContactHistoryError("Cannot record an invalid recipient. Sending stopped.")
        with self._connect() as connection:
            connection.execute("""
                INSERT INTO recipients (username, status, sent_at)
                VALUES (?, 'sent', CURRENT_TIMESTAMP)
                ON CONFLICT(username) DO UPDATE SET status = 'sent', sent_at = CURRENT_TIMESTAMP
            """, (username,))
