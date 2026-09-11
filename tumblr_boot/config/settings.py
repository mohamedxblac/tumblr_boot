# -*- coding: utf-8 -*-
"""
config/settings.py — Central Configuration & Default Settings
=============================================================
All tunable parameters with their defaults.
The GUI reads/writes these values at runtime.
"""

import os
import json

# ─── Base Directories ────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "error_screenshots"), exist_ok=True)

# ─── Data File Paths ─────────────────────────────────────────────────────────
SENT_USERS_FILE   = os.path.join(DATA_DIR, "sent_users.txt")
LOG_FILE          = os.path.join(DATA_DIR, "account_logs.txt")
SUMMARY_FILE      = os.path.join(DATA_DIR, "account_summaries.txt")
PROGRESS_FILE     = os.path.join(DATA_DIR, "account_progress.json")
TARGET_QUEUE_FILE = os.path.join(DATA_DIR, "target_queue.txt")
SCREENSHOTS_DIR   = os.path.join(DATA_DIR, "error_screenshots")
SETTINGS_FILE     = os.path.join(DATA_DIR, "bot_settings.json")
ACCOUNTS_FILE     = os.path.join(DATA_DIR, "accounts.json")
MESSAGES_FILE     = os.path.join(DATA_DIR, "messages.json")

# ─── Default Settings ────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    # ── Account Limits ──
    "max_success_per_account":  30,    # الحد الأقصى الكلي للرسائل لكل حساب
    "session_success_cap":      15,    # الحد الأقصى للجلسة الواحدة
    "no_message_limit":         10,    # عدد الفشل المتتالي قبل الانتقال

    # ── Timing & Delays (seconds) ──
    "line_delay":               7.55,  # التأخير بين أجزاء الرسالة الواحدة
    "after_send_delay":         2.2,   # التأخير بعد إرسال الرسالة
    "after_success_delay":      2.2,   # التأخير بعد النجاح
    "min_between_users":        60,    # أقل فاصل بين المستخدمين (ثوانٍ)
    "max_between_users":        130,   # أقصى فاصل بين المستخدمين (ثوانٍ)
    "sleep_between_rounds_hrs": 12,    # ساعات النوم بين الجولات

    # ── Scraper Settings ──
    "notes_max_users":          3000,  # الحد الأقصى لعدد المستخدمين المسحوبين
    "scroll_pause":             1.5,   # التأخير بين التمريرات
    "stagnant_limit":           8,     # عدد التمريرات بدون نتائج جديدة قبل التوقف
    "scrape_threshold":         15,    # الحد الأدنى للطابور قبل إعادة السحب
    "scrape_timeout_sec":       150,   # الحد الزمني للسحب (ثوانٍ)

    # ── Behavior ──
    "follow_every_n":           4,     # متابعة كل كام مستخدم
    "tab_type":                 "likes",  # نوع التفاعل: "likes" أو "reblogs"
    "post_url":                 "",    # رابط المنشور المستهدف
    "start_account_index":      0,     # رقم الحساب للبدء منه (0-indexed)

    # ── Stealth & Protection ──
    "enable_fingerprint_rotation": True,  # تفعيل تدوير بصمة المتصفح
    "enable_auto_retry":           True,  # تفعيل إعادة المحاولة التلقائية
    "max_retries":                 3,     # أقصى عدد محاولات إعادة المحاولة
    "retry_delay_sec":             5,     # التأخير بين المحاولات (ثوانٍ)
}

# ─── Default Messages ────────────────────────────────────────────────────────
DEFAULT_MESSAGES = [
    (
        "I never imagined I would have to ask for help like this. "
        "My name is Wedad, and I am from P.a.l.e.s.t.i.n.e. "
        "My family consists of 7 members. Our home was completely destroyed, "
        "and now we are living in a torn tent with nothing left. "
        "My family and I have not had any food for the past 32 hours. "
        "Watching my family suffer from hunger is heartbreaking, "
        "and every hour feels endless.\n\n"
        "My mother is sick, and my sister Mira is also sick. "
        "They both urgently need medicine and medical care, "
        "but we cannot afford it. I feel helpless watching them suffer "
        "while we have no food and no way to help them.\n\n"
        "If you are able to help, your d.o.n.a.t.i.o.n can provide food "
        "for my family and medicine for my mother and my sister Mira. "
        "If you cannot donate, please share our story with others. "
        "Your kindness and support could give my family hope during this "
        "heartbreaking time. Thank you for reading my story."
    ),
]

DEFAULT_GREETINGS = [
    "I hope this message finds you in peace",
    "I hope you're safe and surrounded by kindness",
    "I hope you're safe and doing okay today",
]


# ─── Settings Manager ────────────────────────────────────────────────────────
class SettingsManager:
    """Loads, saves, and provides access to all bot settings."""

    def __init__(self):
        self._settings = dict(DEFAULT_SETTINGS)
        self._accounts = []
        self._messages = list(DEFAULT_MESSAGES)
        self._greetings = list(DEFAULT_GREETINGS)
        self.load_all()

    # ── Settings ──────────────────────────────────────────────────────────
    def get(self, key, default=None):
        return self._settings.get(key, default)

    def set(self, key, value):
        self._settings[key] = value
        self._save_settings()

    def get_settings(self) -> dict:
        return dict(self._settings)

    def get_all_settings(self) -> dict:
        return dict(self._settings)

    def update_settings(self, new_settings: dict):
        self._settings.update(new_settings)
        self._save_settings()

    # ── Accounts ──────────────────────────────────────────────────────────
    def get_accounts(self) -> list:
        return list(self._accounts)

    def update_accounts(self, accounts: list):
        self._accounts = list(accounts)
        self._save_accounts()

    @property
    def accounts(self):
        return self._accounts

    @accounts.setter
    def accounts(self, value):
        self._accounts = list(value)
        self._save_accounts()

    def add_account(self, email: str, password: str):
        self._accounts.append({"email": email, "password": password})
        self._save_accounts()

    def remove_account(self, index: int):
        if 0 <= index < len(self._accounts):
            self._accounts.pop(index)
            self._save_accounts()

    # ── Messages & Greetings ──────────────────────────────────────────────
    def get_messages(self) -> list:
        return list(self._messages)

    def update_messages(self, messages: list):
        self._messages = list(messages)
        self._save_messages()

    @property
    def messages(self):
        return self._messages

    @messages.setter
    def messages(self, value):
        self._messages = list(value)
        self._save_messages()

    def get_greetings(self) -> list:
        return list(self._greetings)

    def update_greetings(self, greetings: list):
        self._greetings = list(greetings)
        self._save_messages()

    @property
    def greetings(self):
        return self._greetings

    @greetings.setter
    def greetings(self, value):
        self._greetings = list(value)
        self._save_messages()

    # ── Persistence ───────────────────────────────────────────────────────
    def load_all(self):
        """Load settings, accounts, and messages from disk."""
        self._load_settings()
        self._load_accounts()
        self._load_messages()

    def save_all(self):
        """Save settings, accounts, and messages to disk."""
        self._save_settings()
        self._save_accounts()
        self._save_messages()

    def _load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                if isinstance(stored, dict):
                    self._settings.update(stored)
            except Exception:
                pass

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_accounts(self):
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._accounts = data
            except Exception:
                pass

    def _save_accounts(self):
        try:
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._accounts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_messages(self):
        if os.path.exists(MESSAGES_FILE):
            try:
                with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if "messages" in data and isinstance(data["messages"], list):
                        self._messages = data["messages"]
                    if "greetings" in data and isinstance(data["greetings"], list):
                        self._greetings = data["greetings"]
            except Exception:
                pass

    def _save_messages(self):
        try:
            with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"messages": self._messages, "greetings": self._greetings},
                    f, ensure_ascii=False, indent=2,
                )
        except Exception:
            pass
