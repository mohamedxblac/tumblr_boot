# -*- coding: utf-8 -*-
"""
gui/settings_tab.py — Configuration & Parameter Controls
=========================================================
Visual editor for all bot parameters, timing delays, safety caps, and stealth toggles.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable

from config.settings import SettingsManager, DEFAULT_SETTINGS


class SettingsTab(ttk.Frame):
    """Tab for viewing and editing bot configuration settings."""

    def __init__(self, parent, settings_mgr: SettingsManager, on_save_callback: Callable = None):
        super().__init__(parent, padding=16)
        self.settings_mgr = settings_mgr
        self.on_save_callback = on_save_callback

        self.entries = {}
        self._build_ui()
        self.load_values()

    def _build_ui(self):
        # Header
        header_frame = ttk.Frame(self)
        header_frame.pack(fill="x", pady=(0, 12))
        ttk.Label(
            header_frame,
            text="Bot Configuration & Settings",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")

        # Scrollable Canvas container for all settings cards
        canvas = tk.Canvas(self, background="#181825", borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        content_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ── 1. Target Post & Interaction Type Card ──
        card1 = ttk.LabelFrame(scrollable_frame, text="Target Post & Mode", padding=12)
        card1.pack(fill="x", pady=6, padx=4)

        self._add_row(card1, "post_url", "Target Post URL:", "https://www.tumblr.com/username/123456789/post-slug", width=60)
        
        # Tab Type Combo
        row_tab = ttk.Frame(card1)
        row_tab.pack(fill="x", pady=4)
        ttk.Label(row_tab, text="Interaction Tab:", width=26, anchor="w").pack(side="left")
        self.tab_type_var = tk.StringVar(value="likes")
        combo = ttk.Combobox(
            row_tab,
            textvariable=self.tab_type_var,
            values=["likes", "reblogs"],
            state="readonly",
            width=18
        )
        combo.pack(side="left")
        self.entries["tab_type"] = self.tab_type_var

        # ── 2. Account Limits & Safety Caps ──
        card2 = ttk.LabelFrame(scrollable_frame, text="Account Limits & Safety Caps", padding=12)
        card2.pack(fill="x", pady=6, padx=4)

        self._add_row(card2, "max_success_per_account", "Max Success Per Account (Lifetime):", "30", is_int=True)
        self._add_row(card2, "session_success_cap", "Session Cap (Messages per login):", "15", is_int=True)
        self._add_row(card2, "no_message_limit", "Streak Limit (Closed DMs before skip):", "10", is_int=True)
        self._add_row(card2, "start_account_index", "Start From Account # (1-indexed):", "1", is_int=True)

        # ── 3. Timing & Human Jitter (Seconds) ──
        card3 = ttk.LabelFrame(scrollable_frame, text="Human Delays & Jitter (Seconds)", padding=12)
        card3.pack(fill="x", pady=6, padx=4)

        self._add_row(card3, "action_delay", "Delay Between UI Actions (sec):", "0.5", is_float=True)
        self._add_row(card3, "min_between_users", "Min Delay Between Users (sec):", "60", is_float=True)
        self._add_row(card3, "max_between_users", "Max Delay Between Users (sec):", "130", is_float=True)
        self._add_row(card3, "line_delay", "Line Delay (Between message parts):", "7.55", is_float=True)
        self._add_row(card3, "after_send_delay", "Delay After Send (sec):", "2.2", is_float=True)
        self._add_row(card3, "after_success_delay", "Delay After Success (sec):", "2.2", is_float=True)
        self._add_row(card3, "sleep_between_rounds_hrs", "Sleep Between Full Rounds (Hours):", "12", is_float=True)

        # ── 4. Scraper & Behavior ──
        card4 = ttk.LabelFrame(scrollable_frame, text="Scraper & Follow Settings", padding=12)
        card4.pack(fill="x", pady=6, padx=4)

        self._add_row(card4, "notes_max_users", "Max Users to Scrape from Post:", "3000", is_int=True)
        self._add_row(card4, "scrape_threshold", "Scrape Trigger (Min queue size):", "15", is_int=True)
        self._add_row(card4, "scrape_timeout_sec", "Scraper Timeout (Seconds):", "150", is_int=True)
        self._add_row(card4, "follow_every_n", "Follow Every N Users (0 = Disabled):", "4", is_int=True)

        # ── 5. Stealth & Fingerprint Rotation ──
        card5 = ttk.LabelFrame(scrollable_frame, text="Stealth & Anti-Detection", padding=12)
        card5.pack(fill="x", pady=6, padx=4)

        self.fp_rotation_var = tk.BooleanVar(value=True)
        cb1 = ttk.Checkbutton(
            card5,
            text="Enable Automatic Browser Fingerprint Rotation (User-Agent, WebGL, Canvas, Timezone)",
            variable=self.fp_rotation_var
        )
        cb1.pack(anchor="w", pady=4)
        self.entries["enable_fingerprint_rotation"] = self.fp_rotation_var

        # ── Bottom Action Buttons ──
        btn_frame = ttk.Frame(scrollable_frame)
        btn_frame.pack(fill="x", pady=16)

        save_btn = ttk.Button(btn_frame, text="Save Settings", command=self.save_values)
        save_btn.pack(side="left", padx=6)

        reset_btn = ttk.Button(btn_frame, text="Reset to Defaults", command=self.reset_defaults)
        reset_btn.pack(side="left", padx=6)

    def _add_row(self, parent, key: str, label_text: str, default_val: str, width: int = 24, is_int: bool = False, is_float: bool = False):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label_text, width=34, anchor="w").pack(side="left")
        var = tk.StringVar(value=str(default_val))
        entry = ttk.Entry(row, textvariable=var, width=width, style="Timing.TEntry" if is_float else "TEntry")
        entry.pack(side="left", fill="x", expand=(width > 30))
        self.entries[key] = var

    def load_values(self):
        """Loads settings from SettingsManager into UI widgets."""
        settings = self.settings_mgr.get_settings()
        for key, var in self.entries.items():
            if key in settings:
                val = settings[key]
                if key == "start_account_index":
                    # Display 1-indexed to user
                    var.set(str(int(val) + 1))
                elif isinstance(var, tk.BooleanVar):
                    var.set(bool(val))
                else:
                    var.set(str(val))

    def save_values(self):
        """Validates and commits settings to SettingsManager."""
        try:
            updates = {}
            for key, var in self.entries.items():
                val = var.get()
                if key in ("max_success_per_account", "session_success_cap", "no_message_limit", "notes_max_users", "scrape_threshold", "scrape_timeout_sec", "follow_every_n"):
                    updates[key] = int(val)
                elif key == "start_account_index":
                    updates[key] = max(0, int(val) - 1)
                elif key in ("action_delay", "min_between_users", "max_between_users", "line_delay", "after_send_delay", "after_success_delay", "sleep_between_rounds_hrs"):
                    updates[key] = float(val)
                elif key == "enable_fingerprint_rotation":
                    updates[key] = bool(val)
                else:
                    updates[key] = str(val).strip()

            if updates["min_between_users"] > updates["max_between_users"]:
                messagebox.showerror("Validation Error", "Min delay cannot be greater than Max delay.")
                return

            delay_keys = (
                "action_delay", "min_between_users", "max_between_users",
                "line_delay", "after_send_delay", "after_success_delay",
                "sleep_between_rounds_hrs",
            )
            if any(updates[key] < 0 for key in delay_keys):
                messagebox.showerror("Validation Error", "Delay values cannot be negative.")
                return

            self.settings_mgr.update_settings(updates)
            messagebox.showinfo("Saved", "Settings successfully saved!")
            if self.on_save_callback:
                self.on_save_callback()

        except ValueError as e:
            messagebox.showerror("Validation Error", f"Invalid number format: {e}")

    def reset_defaults(self):
        """Resets all fields to their defaults."""
        if messagebox.askyesno("Confirm Reset", "Reset all settings to default values?"):
            self.settings_mgr.update_settings(DEFAULT_SETTINGS)
            self.load_values()
            messagebox.showinfo("Reset", "Settings restored to defaults.")
