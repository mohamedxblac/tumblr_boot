# -*- coding: utf-8 -*-
"""
utils/logger.py — Advanced Thread-Safe Logging System
=====================================================
Handles logging to file, console, and sends structured log records to a GUI
message queue for real-time display in the live runner tab.
"""

import os
import sys
import logging
import queue
from datetime import datetime
from typing import Optional, Callable

from config.settings import LOG_FILE, SUMMARY_FILE
from utils.helpers import now_ts


class GuiLogHandler(logging.Handler):
    """Logging handler that delivers formatted log records into a thread-safe queue for the GUI."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            level = record.levelname.upper()
            self.log_queue.put({
                "type": "log",
                "level": level,
                "timestamp": now_ts(),
                "message": msg,
            })
        except Exception:
            self.handleError(record)


class BotLogger:
    """Central Logger wrapper providing helper methods for event and summary tracking."""

    def __init__(self, name: str = "TumblrBot"):
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        self._gui_handler: Optional[GuiLogHandler] = None
        self._setup_handlers()

    def _setup_handlers(self):
        # Clear existing handlers
        self.logger.handlers.clear()

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        # File Handler (append mode)
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Stream Handler (stdout)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        self.logger.addHandler(stream_handler)

    def attach_gui_queue(self, q: queue.Queue):
        """Attaches a queue for live GUI streaming."""
        if self._gui_handler:
            self.logger.removeHandler(self._gui_handler)
        self._gui_handler = GuiLogHandler(q)
        formatter = logging.Formatter("[%(levelname)s] %(message)s")
        self._gui_handler.setFormatter(formatter)
        self.logger.addHandler(self._gui_handler)

    def info(self, msg: str):
        self.logger.info(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def success(self, msg: str):
        # We log success as INFO with a special prefix for the GUI
        self.logger.info(f"✔ {msg}")

    def log_event(self, email: str, total_ok: int, fails: int, note: str = ""):
        extra = f" | {note}" if note else ""
        self.logger.info(f"{email} | Sent:{total_ok} | Failed:{fails}{extra}")

    def log_summary(self, email: str, total_ok: int, fails: int, note: str = ""):
        extra = f" | {note}" if note else ""
        summary_line = f"{now_ts()} | {email} | Sent:{total_ok} | Failed:{fails}{extra}"
        self.logger.info(f"{email} | ===SUMMARY=== | Sent:{total_ok} | Failed:{fails}{extra}")
        try:
            with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
                f.write(summary_line + "\n")
        except Exception as e:
            self.logger.error(f"Failed to write summary: {e}")


# Global logger instance
logger = BotLogger()
