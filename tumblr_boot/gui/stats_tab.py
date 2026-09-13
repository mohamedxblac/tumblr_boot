# -*- coding: utf-8 -*-
"""
gui/stats_tab.py — Analytics & Database Management Tab
======================================================
Visual dashboard showing:
- Total outreach metrics (Total Sent, In Queue, Active Accounts)
- Per-account performance and progress breakdown
- Data maintenance tools with permanent recipient protection
"""

import tkinter as tk
from tkinter import ttk, messagebox

from config.settings import SettingsManager
from core.persistence import persistence
from core.contact_history import ContactHistoryError


class StatsTab(ttk.Frame):
    """Tab displaying overall bot statistics and database maintenance utilities."""

    def __init__(self, parent, settings_mgr: SettingsManager):
        super().__init__(parent, padding=16)
        self.settings_mgr = settings_mgr

        self._build_ui()
        self.refresh_stats()

    def _build_ui(self):
        # ── Header ──
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(
            header,
            text="Performance Analytics & Maintenance",
            font=("Segoe UI", 14, "bold")
        ).pack(side="left")

        # ── Metric KPI Cards ──
        cards_frame = ttk.Frame(self)
        cards_frame.pack(fill="x", pady=(0, 14))

        self.card_sent = self._create_kpi_card(cards_frame, "Total Users Reached", "0", "#a6e3a1")
        self.card_queue = self._create_kpi_card(cards_frame, "In Target Queue", "0", "#89b4fa")
        self.card_accs = self._create_kpi_card(cards_frame, "Configured Accounts", "0", "#f9e2af")

        login_cards = ttk.Frame(self)
        login_cards.pack(fill="x", pady=(0, 14))
        self.card_login_success = self._create_kpi_card(
            login_cards, "Login Success — Current Run", "0", "#a6e3a1"
        )
        self.card_login_failed = self._create_kpi_card(
            login_cards, "Login Failed — Current Run", "0", "#f38ba8"
        )
        self.card_login_processed = self._create_kpi_card(
            login_cards, "Accounts Checked — Current Run", "0 / 0", "#89dceb"
        )

        # ── Per-Account Progress Table ──
        table_frame = ttk.LabelFrame(self, text="Account Performance Breakdown", padding=8)
        table_frame.pack(fill="both", expand=True, pady=(0, 10))

        cols = ("email", "sent", "quota", "percent", "status")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")

        self.tree.heading("email", text="Email Address")
        self.tree.heading("sent", text="Sent Count")
        self.tree.heading("quota", text="Target Quota")
        self.tree.heading("percent", text="Completion %")
        self.tree.heading("status", text="Current Status")

        self.tree.column("email", width=280, anchor="w")
        self.tree.column("sent", width=90, anchor="center")
        self.tree.column("quota", width=90, anchor="center")
        self.tree.column("percent", width=100, anchor="center")
        self.tree.column("status", width=140, anchor="center")

        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # ── Maintenance Action Buttons ──
        action_frame = ttk.LabelFrame(self, text="Data Maintenance & Cache Tools", padding=8)
        action_frame.pack(fill="x")

        ttk.Button(action_frame, text="Refresh Stats", command=self.refresh_stats).pack(side="left", padx=4)
        ttk.Button(action_frame, text="Reset Progress Counters", command=self.on_reset_progress).pack(side="left", padx=4)
        ttk.Button(action_frame, text="Clear Target Queue", command=self.on_clear_queue).pack(side="left", padx=4)
        self.history_note = ttk.Label(self, text="Recipient history is retained to prevent repeat messages.")
        self.history_note.pack(fill="x", pady=(8, 0))

    def _create_kpi_card(self, parent, title: str, initial_val: str, color: str):
        card = ttk.Frame(parent, padding=12)
        card.pack(side="left", fill="both", expand=True, padx=4)

        ttk.Label(card, text=title, font=("Segoe UI", 9)).pack(anchor="center")
        val_label = ttk.Label(card, text=initial_val, font=("Segoe UI", 20, "bold"), foreground=color)
        val_label.pack(anchor="center", pady=(4, 0))
        return val_label

    def refresh_stats(self):
        """Updates KPI counters and table data."""
        try:
            sent_users = persistence.load_sent_users()
            contacted_users = persistence.load_contacted_users()
            queue = persistence.load_target_queue()
        except ContactHistoryError as error:
            self.card_sent.configure(text="Unavailable")
            self.card_queue.configure(text="Unavailable")
            self.history_note.configure(text=str(error), foreground="#f38ba8")
            return
        self.history_note.configure(
            text=f"Protected recipients: {len(contacted_users)} | Unconfirmed attempts: {len(contacted_users - sent_users)}. History is retained to prevent repeats.",
            foreground="#cdd6f4",
        )
        accounts = self.settings_mgr.get_accounts()
        progress = persistence.load_progress()
        max_quota = int(self.settings_mgr.get_settings().get("max_success_per_account", 30))

        # Update KPIs
        self.card_sent.configure(text=str(len(sent_users)))
        self.card_queue.configure(text=str(len(queue)))
        self.card_accs.configure(text=str(len(accounts)))

        # Update Table
        for item in self.tree.get_children():
            self.tree.delete(item)

        for acc in accounts:
            email = acc["email"]
            sent = progress.get(email, 0)
            pct = f"{(sent / max_quota) * 100:.1f}%" if max_quota > 0 else "0%"
            status = "Target Finished" if sent >= max_quota else "Active"
            self.tree.insert("", "end", values=(email, sent, max_quota, pct, status))

    def update_login_stats(self, success: int, failed: int, processed: int, total: int):
        """Update volatile login counters for the current Start/Stop run."""
        self.card_login_success.configure(text=str(success))
        self.card_login_failed.configure(text=str(failed))
        self.card_login_processed.configure(text=f"{processed} / {total}")

    def on_reset_progress(self):
        if messagebox.askyesno("Confirm Reset", "Reset all account progress counters to zero?"):
            persistence.reset_progress()
            self.refresh_stats()
            messagebox.showinfo("Reset", "All progress counters have been reset.")

    def on_clear_queue(self):
        if messagebox.askyesno("Confirm Clear", "Clear the entire target queue file?"):
            persistence.clear_target_queue()
            self.refresh_stats()
            messagebox.showinfo("Cleared", "Target queue cleared.")
