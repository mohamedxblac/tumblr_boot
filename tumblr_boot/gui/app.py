# -*- coding: utf-8 -*-
"""
gui/app.py — Main Application Window & Dark Theme System
========================================================
Main application container featuring:
- Premium modern dark theme palette (Catppuccin Mocha inspired)
- Notebook multi-tab navigation
- Thread-safe non-blocking event loop communicating with BotEngine
- Graceful shutdown handling
"""

import os
import queue
import tkinter as tk
from tkinter import ttk, messagebox

from config.settings import SettingsManager
from core.engine import BotEngine
from utils.logger import logger
from gui.runner_tab import RunnerTab
from gui.settings_tab import SettingsTab
from gui.accounts_tab import AccountsTab
from gui.messages_tab import MessagesTab
from gui.stats_tab import StatsTab


class TumblrBotApp(tk.Tk):
    """Primary application window coordinating GUI tabs and the bot engine."""

    def __init__(self):
        super().__init__()

        self.title("Tumblr Outreach Bot v2.0 — Stealth Edition")
        self.geometry("1100x740")
        self.minsize(920, 620)

        # ── 1. Initialize State & Managers ──
        self.settings_mgr = SettingsManager()
        self.gui_queue = queue.Queue()

        # Connect logger to GUI queue
        logger.attach_gui_queue(self.gui_queue)

        # Initialize Bot Engine
        self.engine = BotEngine(settings_mgr=self.settings_mgr, gui_queue=self.gui_queue)

        # ── 2. Configure Modern Dark Styles ──
        self._apply_dark_theme()

        # ── 3. Build UI Layout ──
        self._build_tabs()
        self._build_statusbar()

        # ── 4. Start Event Loop Polling & Close Handler ──
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.after(100, self._poll_queue)

    def _apply_dark_theme(self):
        """Applies a coherent, modern dark palette across all ttk widgets."""
        self.configure(bg="#181825")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Color Palette
        bg_dark    = "#181825"
        bg_card    = "#1e1e2e"
        bg_input   = "#313244"
        fg_text    = "#cdd6f4"
        accent_blue= "#89b4fa"
        accent_cyan= "#89dceb"
        border_col = "#45475a"

        # General Widget Styles
        style.configure(".", background=bg_dark, foreground=fg_text, font=("Segoe UI", 9))
        style.configure("TFrame", background=bg_dark)
        style.configure("TLabelframe", background=bg_dark, foreground=accent_blue, relief="solid", borderwidth=1, bordercolor=border_col)
        style.configure("TLabelframe.Label", background=bg_dark, foreground=accent_blue, font=("Segoe UI", 10, "bold"))

        # Buttons
        style.configure(
            "TButton",
            background=bg_input,
            foreground=fg_text,
            relief="flat",
            padding=(10, 5),
            font=("Segoe UI", 9, "bold")
        )
        style.map(
            "TButton",
            background=[("active", accent_blue), ("disabled", "#252538")],
            foreground=[("active", "#11111b"), ("disabled", "#585b70")]
        )

        # Entry & Combobox
        style.configure("TEntry", fieldbackground=bg_input, foreground=fg_text, padding=4, relief="flat")
        style.configure("TCombobox", fieldbackground=bg_input, foreground=fg_text, padding=3)
        style.map("TCombobox", fieldbackground=[("readonly", bg_input)], foreground=[("readonly", fg_text)])

        # Explicit input colors also apply while focused, selected or disabled.
        for input_style in ("Timing.TSpinbox", "Timing.TEntry"):
            style.configure(
                input_style, fieldbackground="#ffffff", foreground="#000000",
                insertcolor="#000000", selectbackground="#cfe2ff",
                selectforeground="#000000", padding=4,
            )
            style.map(
                input_style,
                fieldbackground=[("disabled", "#ffffff"), ("!disabled", "#ffffff")],
                foreground=[("disabled", "#000000"), ("!disabled", "#000000")],
                selectforeground=[("!disabled", "#000000")],
            )

        # Notebook (Tabs)
        style.configure("TNotebook", background=bg_dark, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=bg_card,
            foreground=fg_text,
            padding=(16, 8),
            font=("Segoe UI", 9, "bold")
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", accent_blue), ("active", "#313244")],
            foreground=[("selected", "#11111b"), ("active", fg_text)]
        )

        # Treeview
        style.configure(
            "Treeview",
            background=bg_card,
            foreground=fg_text,
            fieldbackground=bg_card,
            borderwidth=0,
            rowheight=26,
            font=("Segoe UI", 9)
        )
        style.configure(
            "Treeview.Heading",
            background=bg_input,
            foreground=accent_cyan,
            font=("Segoe UI", 9, "bold"),
            relief="flat"
        )
        style.map("Treeview", background=[("selected", "#45475a")])

        # Progressbar
        style.configure("TProgressbar", troughcolor=bg_input, background=accent_blue, thickness=16)

        # Checkbutton
        style.configure("TCheckbutton", background=bg_dark, foreground=fg_text)
        style.map("TCheckbutton", background=[("active", bg_dark)])

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

        # Instantiate tabs
        self.tab_runner = RunnerTab(
            self.notebook,
            engine=self.engine,
            on_timing_saved=self._on_settings_saved,
        )
        self.tab_accounts = AccountsTab(self.notebook, settings_mgr=self.settings_mgr)
        self.tab_settings = SettingsTab(
            self.notebook,
            settings_mgr=self.settings_mgr,
            on_save_callback=self._on_settings_saved
        )
        self.tab_messages = MessagesTab(self.notebook, settings_mgr=self.settings_mgr)
        self.tab_stats = StatsTab(self.notebook, settings_mgr=self.settings_mgr)

        # Add tabs in preferred logical order
        self.notebook.add(self.tab_runner, text=" ▶ Runner & Live Log ")
        self.notebook.add(self.tab_accounts, text=" 👥 Accounts ")
        self.notebook.add(self.tab_settings, text=" ⚙ Settings ")
        self.notebook.add(self.tab_messages, text=" ✉ Messages ")
        self.notebook.add(self.tab_stats, text=" 📈 Stats & Data ")

    def _build_statusbar(self):
        self.status_bar = ttk.Frame(self, padding=(10, 4))
        self.status_bar.pack(fill="x", side="bottom")

        self.status_left = ttk.Label(self.status_bar, text="Status: Ready", font=("Segoe UI", 8))
        self.status_left.pack(side="left")

        self.status_right = ttk.Label(
            self.status_bar,
            text="Tumblr Bot v2.0 • Advanced Stealth • Isolated Profiles",
            font=("Segoe UI", 8),
            foreground="#6c7086"
        )
        self.status_right.pack(side="right")

    def _on_settings_saved(self):
        """Callback when settings are modified."""
        self.tab_runner.load_timing_values()
        self.tab_settings.load_values()
        self.tab_accounts.refresh_accounts()
        self.tab_stats.refresh_stats()

    def _poll_queue(self):
        """Continuously pulls updates from the BotEngine worker thread without freezing the UI."""
        try:
            while not self.gui_queue.empty():
                evt = self.gui_queue.get_nowait()
                evt_type = evt.get("type", "")

                if evt_type == "log":
                    self.tab_runner.append_log_line(
                        timestamp=evt.get("timestamp", ""),
                        level=evt.get("level", "INFO"),
                        message=evt.get("message", "")
                    )

                elif evt_type == "state_changed":
                    running = evt.get("running", False)
                    paused = evt.get("paused", False)
                    self.tab_runner.update_engine_state(running, paused)
                    state_str = "Running" if running else ("Paused" if paused else "Idle")
                    self.status_left.configure(text=f"Status: {state_str}")

                elif evt_type == "status_info":
                    status = evt.get("status", "")
                    detail = evt.get("detail", "")
                    self.tab_runner.update_status_info(status, detail)
                    self.status_left.configure(text=f"Status: {status}")

                elif evt_type == "account_active":
                    email = evt.get("email", "")
                    idx = evt.get("account_index", 1)
                    total = evt.get("total_accounts", 1)
                    self.tab_runner.update_account_active(email, idx, total)

                elif evt_type == "progress_update":
                    email = evt.get("email", "")
                    session_ok = evt.get("session_ok", 0)
                    session_cap = int(self.settings_mgr.get_settings().get("session_success_cap", 15))
                    self.tab_runner.update_progress(session_ok, session_cap)
                    self.tab_accounts.refresh_accounts()
                    self.tab_stats.refresh_stats()

                elif evt_type == "countdown":
                    label = evt.get("label", "")
                    rem = evt.get("remaining", 0)
                    tot = evt.get("total", 0)
                    self.tab_runner.update_countdown(label, rem, tot)

                elif evt_type == "error":
                    msg = evt.get("message", "An unexpected error occurred.")
                    messagebox.showerror("Bot Alert", msg)

        except Exception as e:
            pass
        finally:
            self.after(100, self._poll_queue)

    def on_closing(self):
        """Safely stops the engine before exiting."""
        if self.engine.is_running:
            if messagebox.askyesno(
                "Bot Running",
                "The bot is currently running. Stopping it now will finish the active action safely.\n\nExit anyway?"
            ):
                self.engine.stop()
                self.destroy()
        else:
            self.destroy()
