# -*- coding: utf-8 -*-
"""
main.py — Tumblr Outreach Bot v2.0 (GUI Launcher)
=================================================
Entry point for the application. Initializes files, migrates legacy data if found,
and launches the graphical user interface.
"""

import os
import sys
import json
import shutil

# Ensure base directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import (
    DATA_DIR,
    ACCOUNTS_FILE,
    SETTINGS_FILE,
    SENT_USERS_FILE,
    TARGET_QUEUE_FILE,
    PROGRESS_FILE,
    DEFAULT_SETTINGS,
)
from gui.app import TumblrBotApp


def bootstrap_data():
    """Migrates any existing data files from root directory to data/ folder."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # 1. Migrate root files if they exist and data/ file is missing
    migrations = [
        ("sent_users.txt", SENT_USERS_FILE),
        ("target_queue.txt", TARGET_QUEUE_FILE),
        ("account_progress.json", PROGRESS_FILE),
    ]
    for src_name, dst_path in migrations:
        src_path = os.path.join(BASE_DIR, src_name)
        if os.path.exists(src_path) and not os.path.exists(dst_path):
            try:
                shutil.copyfile(src_path, dst_path)
            except Exception:
                pass

    # 2. Bootstrap accounts.json if not present
    if not os.path.exists(ACCOUNTS_FILE):
        default_accounts = [
            {"email": "kazoulayacine012@gmail.com", "password": "Xcvb654need"}
        ]
        try:
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(default_accounts, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # 3. Bootstrap bot_settings.json if not present
    if not os.path.exists(SETTINGS_FILE):
        settings = dict(DEFAULT_SETTINGS)
        settings["post_url"] = "https://www.tumblr.com/hazard-symbols-that-fuck-hard/827145486405337088/fuck-marry-kill-the-grinch-the-cat-in-the-hat?source=share"
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def main():
    """Main program entry point."""
    # Force UTF-8 encoding on Windows console
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    bootstrap_data()

    app = TumblrBotApp()
    app.mainloop()


if __name__ == "__main__":
    main()
