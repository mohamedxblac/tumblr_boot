# -*- coding: utf-8 -*-
"""
gui/runner_tab.py — Live Execution & Real-Time Monitoring
=========================================================
Provides real-time controls (Start/Pause/Stop), countdown indicators, progress meters,
and a syntax-highlighted live log viewer streaming events directly from the engine.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
from typing import Optional, Callable

from core.engine import BotEngine
from config.settings import LOG_FILE


class RunnerTab(ttk.Frame):
    """Tab for controlling bot execution and observing live operation logs."""

    def __init__(self, parent, engine: BotEngine, on_timing_saved: Callable = None, on_pre_start: Callable = None):
        super().__init__(parent, padding=16)
        self.engine = engine
        self.on_timing_saved = on_timing_saved
        self.on_pre_start = on_pre_start
        self.timing_vars = {}
        self.parallel_var = tk.StringVar(value="1")

        self._build_ui()
        self.load_timing_values()

    def _build_ui(self):
        # ── 1. Top Control Bar ──
        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", pady=(0, 12))

        self.start_btn = ttk.Button(ctrl_frame, text="Start Bot", command=self.on_start)
        self.start_btn.pack(side="left", padx=(0, 6))

        self.pause_btn = ttk.Button(ctrl_frame, text="Pause", command=self.on_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=6)

        self.stop_btn = ttk.Button(ctrl_frame, text="Stop Bot", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)

        ttk.Label(ctrl_frame, text="Desktop login sessions:").pack(side="left", padx=(24, 5))
        self.parallel_spinbox = ttk.Spinbox(
            ctrl_frame,
            from_=1,
            to=1,
            increment=1,
            textvariable=self.parallel_var,
            width=5,
            style="Timing.TSpinbox",
        )
        self.parallel_spinbox.pack(side="left", padx=(0, 5))
        ttk.Label(
            ctrl_frame,
            text="(fixed at 1 for port 9222)",
            foreground="#6c7086",
        ).pack(side="left")

        timing_frame = ttk.LabelFrame(self, text="Quick Timing Controls (seconds)", padding=8)
        timing_frame.pack(fill="x", pady=(0, 10))

        timing_fields = (
            ("action_delay", "Between actions", 0.1),
            ("line_delay", "Between message parts", 0.5),
            ("min_between_users", "Users min", 1.0),
            ("max_between_users", "Users max", 1.0),
        )
        for key, label, increment in timing_fields:
            ttk.Label(timing_frame, text=f"{label}:").pack(side="left", padx=(4, 3))
            var = tk.StringVar()
            ttk.Spinbox(
                timing_frame,
                from_=0,
                to=3600,
                increment=increment,
                textvariable=var,
                width=7,
                style="Timing.TSpinbox",
            ).pack(side="left", padx=(0, 8))
            self.timing_vars[key] = var

        ttk.Button(
            timing_frame,
            text="Apply Timing",
            command=self.save_timing_values,
        ).pack(side="left", padx=6)
        ttk.Label(
            timing_frame,
            text="Applied on next Start",
            foreground="#6c7086",
        ).pack(side="left", padx=4)

        # ── 2. Live Dashboard Status Cards ──
        status_card = ttk.LabelFrame(self, text="Live Operation Dashboard", padding=10)
        status_card.pack(fill="x", pady=(0, 10))

        # Top row: State & Active Account
        row1 = ttk.Frame(status_card)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="State:", font=("Segoe UI", 9, "bold"), width=12).pack(side="left")
        self.state_label = ttk.Label(row1, text="Idle", foreground="#89b4fa", font=("Segoe UI", 9, "bold"))
        self.state_label.pack(side="left", padx=(0, 30))

        ttk.Label(row1, text="Active Account:", font=("Segoe UI", 9, "bold"), width=14).pack(side="left")
        self.account_label = ttk.Label(row1, text="None", font=("Segoe UI", 9))
        self.account_label.pack(side="left")

        # Second row: Current Action & Countdown
        row2 = ttk.Frame(status_card)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Current Action:", font=("Segoe UI", 9, "bold"), width=12).pack(side="left")
        self.action_label = ttk.Label(row2, text="Ready to start", font=("Segoe UI", 9))
        self.action_label.pack(side="left", padx=(0, 30))

        ttk.Label(row2, text="Wait Timer:", font=("Segoe UI", 9, "bold"), width=14).pack(side="left")
        self.timer_label = ttk.Label(row2, text="--", foreground="#f9e2af", font=("Segoe UI", 9, "bold"))
        self.timer_label.pack(side="left")

        # Third row: Progress Bars
        prog_frame = ttk.Frame(status_card)
        prog_frame.pack(fill="x", pady=(8, 2))

        ttk.Label(prog_frame, text="Session Progress:").pack(side="left", padx=(0, 8))
        self.progress_bar = ttk.Progressbar(prog_frame, mode="determinate")
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.prog_text = ttk.Label(prog_frame, text="0 / 0", width=12, anchor="e")
        self.prog_text.pack(side="left")

        # ── 3. Live Log Viewer ──
        log_card = ttk.LabelFrame(self, text="Live Activity Logs", padding=8)
        log_card.pack(fill="both", expand=True)

        self.log_text = ScrolledText(
            log_card,
            wrap="word",
            bg="#181825",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Consolas", 9),
            padx=8,
            pady=8,
            borderwidth=0
        )
        self.log_text.pack(fill="both", expand=True)

        # Configure color tags for rich log highlighting
        self.log_text.tag_config("INFO", foreground="#cdd6f4")
        self.log_text.tag_config("SUCCESS", foreground="#a6e3a1", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("WARNING", foreground="#f9e2af")
        self.log_text.tag_config("ERROR", foreground="#f38ba8", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("TIMESTAMP", foreground="#6c7086")

        # Bottom Log Controls
        log_btn_bar = ttk.Frame(log_card)
        log_btn_bar.pack(fill="x", pady=(6, 0))

        ttk.Button(log_btn_bar, text="Clear Log View", command=self.clear_logs).pack(side="left", padx=4)
        ttk.Button(log_btn_bar, text="Export Log File", command=self.export_logs).pack(side="left", padx=4)

    # ── Button Handlers ──
    def on_start(self):
        if callable(self.on_pre_start):
            try:
                self.on_pre_start()
            except Exception:
                pass
        try:
            parallel_accounts = int(self.parallel_var.get())
        except ValueError:
            messagebox.showerror("Invalid Parallel Count", "Parallel tabs/accounts must be a whole number.")
            return
        if parallel_accounts != 1:
            messagebox.showerror("Invalid Session Count", "Desktop login on port 9222 requires exactly one session.")
            return
        self.engine.settings_mgr.update_settings({"parallel_accounts": parallel_accounts})
        self.engine.start()

    def on_pause(self):
        if self.engine.is_paused:
            self.engine.resume()
            self.pause_btn.configure(text="Pause")
        else:
            self.engine.pause()
            self.pause_btn.configure(text="Resume")

    def on_stop(self):
        if messagebox.askyesno("Confirm Stop", "Are you sure you want to stop the bot?"):
            self.engine.stop()

    def load_timing_values(self):
        settings = self.engine.settings_mgr.get_settings()
        defaults = {
            "action_delay": 0.5,
            "line_delay": 7.55,
            "min_between_users": 60,
            "max_between_users": 130,
        }
        for key, var in self.timing_vars.items():
            var.set(str(settings.get(key, defaults[key])))
        self.parallel_var.set(str(settings.get("parallel_accounts", 1)))

    def save_timing_values(self):
        try:
            updates = {key: float(var.get()) for key, var in self.timing_vars.items()}
        except ValueError:
            messagebox.showerror("Invalid Timing", "All timing values must be valid numbers.")
            return

        if any(value < 0 for value in updates.values()):
            messagebox.showerror("Invalid Timing", "Timing values cannot be negative.")
            return
        if updates["min_between_users"] > updates["max_between_users"]:
            messagebox.showerror("Invalid Timing", "Users min cannot be greater than users max.")
            return

        self.engine.settings_mgr.update_settings(updates)
        if self.on_timing_saved:
            self.on_timing_saved()
        messagebox.showinfo(
            "Timing Saved",
            "Timing settings saved. They will be used the next time the bot starts.",
        )

    def update_engine_state(self, running: bool, paused: bool):
        """Called by the main app when the engine updates its operational state."""
        if running:
            self.start_btn.configure(state="disabled")
            self.pause_btn.configure(state="normal", text="Resume" if paused else "Pause")
            self.stop_btn.configure(state="normal")
            self.parallel_spinbox.configure(state="disabled")
            self.state_label.configure(
                text="Paused" if paused else "Running",
                foreground="#f9e2af" if paused else "#a6e3a1"
            )
        else:
            self.start_btn.configure(state="normal")
            self.pause_btn.configure(state="disabled", text="Pause")
            self.stop_btn.configure(state="disabled")
            self.parallel_spinbox.configure(state="normal")
            self.state_label.configure(text="Idle", foreground="#89b4fa")
            self.timer_label.configure(text="--")

    def update_status_info(self, status: str, detail: str):
        self.action_label.configure(text=f"{status} — {detail}")

    def update_account_active(self, email: str, index: int, total: int):
        self.account_label.configure(text=f"#{index}/{total} ({email})")

    def update_active_workers(self, accounts):
        if not accounts:
            self.account_label.configure(text="None")
            return
        if len(accounts) == 1:
            self.account_label.configure(text=accounts[0])
            return
        self.account_label.configure(
            text=f"{len(accounts)} parallel: " + ", ".join(accounts)
        )

    def update_progress(self, current: int, maximum: int):
        if maximum > 0:
            pct = (current / maximum) * 100
            self.progress_bar.configure(value=pct)
            self.prog_text.configure(text=f"{current} / {maximum}")

    def update_countdown(self, label: str, remaining: int, total: int):
        if remaining > 0:
            self.timer_label.configure(text=f"{label}: {remaining}s remaining")
        else:
            self.timer_label.configure(text="--")

    def append_log_line(self, timestamp: str, level: str, message: str):
        """Appends a new log message with proper color tags."""
        self.log_text.insert("end", f"[{timestamp}] ", "TIMESTAMP")

        level_upper = level.upper()
        if "✔" in message or "SENT_OK" in message.upper() or "SUCCESS" in level_upper:
            tag = "SUCCESS"
        elif "ERROR" in level_upper or "FAIL" in message.upper():
            tag = "ERROR"
        elif "WARNING" in level_upper or "WARN" in level_upper:
            tag = "WARNING"
        else:
            tag = "INFO"

        self.log_text.insert("end", f"{message.replace('✔', '').strip()}\n", tag)
        self.log_text.see("end")

    def clear_logs(self):
        self.log_text.delete("1.0", "end")

    def export_logs(self):
        if not os.path.exists(LOG_FILE):
            messagebox.showinfo("Empty", "No log file found to export.")
            return

        dest = filedialog.asksaveasfilename(
            title="Save Log File",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")]
        )
        if dest:
            try:
                import shutil
                shutil.copyfile(LOG_FILE, dest)
                messagebox.showinfo("Exported", f"Logs exported to {dest}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not export logs: {e}")
