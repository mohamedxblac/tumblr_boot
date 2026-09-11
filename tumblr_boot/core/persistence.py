# -*- coding: utf-8 -*-
"""
core/persistence.py — State & Progress Persistence
===================================================
Manages persistent storage for:
- sent_users.txt (set of users who already received messages)
- target_queue.txt (ordered list of prospective users to message)
- account_progress.json (dictionary of email -> sent_count)
- account_summaries.txt (historical records of each session)

Implements atomic writes to prevent corruption on unexpected termination.
"""

import os
import json
import tempfile
from typing import Set, List, Dict

from config.settings import (
    SENT_USERS_FILE,
    TARGET_QUEUE_FILE,
    PROGRESS_FILE,
    SUMMARY_FILE,
)
from utils.helpers import extract_username
from utils.logger import logger


class PersistenceManager:
    """Handles thread-safe, crash-resistant file I/O for bot operations."""

    def __init__(self):
        self._ensure_files()

    def _ensure_files(self):
        for filepath in [SENT_USERS_FILE, TARGET_QUEUE_FILE]:
            if not os.path.exists(filepath):
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, "w", encoding="utf-8") as f:
                    pass

    @staticmethod
    def _atomic_write_text(filepath: str, lines: List[str]):
        """Writes lines to a temporary file and atomically replaces target file."""
        dirname = os.path.dirname(filepath)
        os.makedirs(dirname, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=dirname, text=True)
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(f"{line}\n")
            os.replace(temp_path, filepath)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    # ─── Sent Users ──────────────────────────────────────────────────────────
    def load_sent_users(self) -> Set[str]:
        """Loads all usernames that have already received messages into a set."""
        users = set()
        if os.path.exists(SENT_USERS_FILE):
            try:
                with open(SENT_USERS_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        u = extract_username(line.strip())
                        if u:
                            users.add(u.lower())
            except Exception as e:
                logger.error(f"Failed to load sent users: {e}")
        return users

    def save_sent_user(self, username: str):
        """Appends a new sent user to the sent_users.txt file."""
        u = extract_username(username).lower()
        if not u:
            return
        try:
            with open(SENT_USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{u}\n")
        except Exception as e:
            logger.error(f"Could not save sent user {u}: {e}")

    def clear_sent_users(self):
        """Clears all sent users (useful for testing or reset)."""
        try:
            with open(SENT_USERS_FILE, "w", encoding="utf-8") as f:
                pass
            logger.info("Sent users history cleared.")
        except Exception as e:
            logger.error(f"Failed to clear sent users: {e}")

    # ─── Target Queue ────────────────────────────────────────────────────────
    def load_target_queue(self) -> List[str]:
        """Loads the pending target users in order, preserving uniqueness."""
        queue = []
        seen = set()
        if os.path.exists(TARGET_QUEUE_FILE):
            try:
                with open(TARGET_QUEUE_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        u = line.strip().lower()
                        if u and u not in seen:
                            queue.append(u)
                            seen.add(u)
            except Exception as e:
                logger.error(f"Failed to load target queue: {e}")
        return queue

    def save_target_queue(self, queue: List[str]):
        """Persists the target queue to disk atomically."""
        try:
            # Deduplicate while preserving order
            unique_queue = []
            seen = set()
            for u in queue:
                u_clean = u.strip().lower()
                if u_clean and u_clean not in seen:
                    unique_queue.append(u_clean)
                    seen.add(u_clean)
            self._atomic_write_text(TARGET_QUEUE_FILE, unique_queue)
        except Exception as e:
            logger.error(f"Failed to save target queue: {e}")

    def clear_target_queue(self):
        """Clears the target queue."""
        try:
            with open(TARGET_QUEUE_FILE, "w", encoding="utf-8") as f:
                pass
            logger.info("Target queue cleared.")
        except Exception as e:
            logger.error(f"Failed to clear target queue: {e}")

    # ─── Account Progress ────────────────────────────────────────────────────
    def load_progress(self) -> Dict[str, int]:
        """Loads total sent counts per account."""
        if os.path.exists(PROGRESS_FILE):
            try:
                with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {k: int(v) for k, v in data.items()} if isinstance(data, dict) else {}
            except Exception as e:
                logger.warning(f"Could not read progress file ({e}), starting fresh.")
        return {}

    def save_progress(self, progress: Dict[str, int]):
        """Saves account progress dictionary to json atomically."""
        dirname = os.path.dirname(PROGRESS_FILE)
        os.makedirs(dirname, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=dirname, text=True)
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, PROGRESS_FILE)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logger.error(f"Progress save failed: {e}")

    def reset_progress(self):
        """Resets account progress counts to zero."""
        self.save_progress({})


# Global singleton instance
persistence = PersistenceManager()
