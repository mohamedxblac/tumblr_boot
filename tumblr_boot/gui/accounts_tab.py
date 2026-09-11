# -*- coding: utf-8 -*-
"""
gui/accounts_tab.py — Tumblr Accounts Management Tab
====================================================
Treeview-based account manager supporting:
- Adding, editing, and deleting accounts
- Password masking with reveal toggle
- Bulk import from TXT / CSV (email:pass or email,pass)
- Real-time progress and quota tracking per account
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import List, Dict

from config.settings import SettingsManager
from core.persistence import persistence


class AccountsTab(ttk.Frame):
    """Tab for managing Tumblr bot credentials."""

    def __init__(self, parent, settings_mgr: SettingsManager):
        super().__init__(parent, padding=16)
        self.settings_mgr = settings_mgr
        self.show_passwords = False

        self._build_ui()
        self.refresh_accounts()

    def _build_ui(self):
        # ── Header ──
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(
            header,
            text="👥 Accounts Management",
            font=("Segoe UI", 14, "bold")
        ).pack(side="left")

        # ── Add Account Form ──
        add_frame = ttk.LabelFrame(self, text="➕ Add New Account", padding=10)
        add_frame.pack(fill="x", pady=(0, 12))

        ttk.Label(add_frame, text="Email:").pack(side="left", padx=(0, 4))
        self.email_var = tk.StringVar()
        email_entry = ttk.Entry(add_frame, textvariable=self.email_var, width=28)
        email_entry.pack(side="left", padx=(0, 10))

        ttk.Label(add_frame, text="Password:").pack(side="left", padx=(0, 4))
        self.pwd_var = tk.StringVar()
        pwd_entry = ttk.Entry(add_frame, textvariable=self.pwd_var, width=20, show="*")
        pwd_entry.pack(side="left", padx=(0, 10))

        add_btn = ttk.Button(add_frame, text="Add Account", command=self.add_account)
        add_btn.pack(side="left")

        # ── Treeview Table ──
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True)

        columns = ("index", "email", "password", "sent", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")

        self.tree.heading("index", text="#")
        self.tree.heading("email", text="Email Address")
        self.tree.heading("password", text="Password")
        self.tree.heading("sent", text="Sent Total")
        self.tree.heading("status", text="Quota Status")

        self.tree.column("index", width=50, anchor="center")
        self.tree.column("email", width=280, anchor="w")
        self.tree.column("password", width=160, anchor="center")
        self.tree.column("sent", width=100, anchor="center")
        self.tree.column("status", width=140, anchor="center")

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # ── Bottom Action Controls ──
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill="x", pady=(10, 0))

        ttk.Button(btn_bar, text="🗑 Delete Selected", command=self.delete_selected).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="👁 Toggle Passwords", command=self.toggle_passwords).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="📂 Import from File", command=self.import_accounts).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="💾 Export to TXT", command=self.export_accounts).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="🔄 Refresh", command=self.refresh_accounts).pack(side="left", padx=4)

    def refresh_accounts(self):
        """Reloads accounts and current sent counts into Treeview."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        accounts = self.settings_mgr.get_accounts()
        progress = persistence.load_progress()
        max_quota = int(self.settings_mgr.get_settings().get("max_success_per_account", 30))

        for idx, acc in enumerate(accounts, start=1):
            email = acc.get("email", "")
            pwd = acc.get("password", "")
            masked_pwd = pwd if self.show_passwords else "••••••••"
            sent_count = progress.get(email, 0)

            if sent_count >= max_quota:
                status = "✔ Target Reached"
            elif sent_count > 0:
                status = f"In Progress ({sent_count}/{max_quota})"
            else:
                status = "Ready"

            self.tree.insert("", "end", iid=str(idx - 1), values=(
                idx, email, masked_pwd, f"{sent_count}/{max_quota}", status
            ))

    def add_account(self):
        email = self.email_var.get().strip()
        pwd = self.pwd_var.get().strip()

        if not email or not pwd:
            messagebox.showwarning("Missing Fields", "Please enter both email and password.")
            return

        if "@" not in email:
            messagebox.showwarning("Invalid Email", "Please enter a valid email address.")
            return

        accounts = self.settings_mgr.get_accounts()
        if any(a["email"].lower() == email.lower() for a in accounts):
            messagebox.showwarning("Duplicate", "This account email already exists in the list.")
            return

        accounts.append({"email": email, "password": pwd})
        self.settings_mgr.update_accounts(accounts)
        self.email_var.set("")
        self.pwd_var.set("")
        self.refresh_accounts()

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Selection Required", "Please select one or more accounts to delete.")
            return

        if messagebox.askyesno("Confirm Delete", f"Delete {len(selected)} selected account(s)?"):
            indices = set(int(i) for i in selected)
            accounts = self.settings_mgr.get_accounts()
            new_accounts = [acc for i, acc in enumerate(accounts) if i not in indices]
            self.settings_mgr.update_accounts(new_accounts)
            self.refresh_accounts()

    def toggle_passwords(self):
        self.show_passwords = not self.show_passwords
        self.refresh_accounts()

    def import_accounts(self):
        file_path = filedialog.askopenfilename(
            title="Select Accounts File",
            filetypes=[("Text / CSV files", "*.txt *.csv"), ("All files", "*.*")]
        )
        if not file_path:
            return

        try:
            added = 0
            accounts = self.settings_mgr.get_accounts()
            existing_emails = {a["email"].lower() for a in accounts}

            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Support email:pass or email,pass or email;pass
                    delim = ":" if ":" in line else ("," if "," in line else (";" if ";" in line else None))
                    if not delim:
                        continue

                    parts = line.split(delim, 1)
                    email = parts[0].strip()
                    pwd = parts[1].strip()

                    if email and pwd and "@" in email and email.lower() not in existing_emails:
                        accounts.append({"email": email, "password": pwd})
                        existing_emails.add(email.lower())
                        added += 1

            self.settings_mgr.update_accounts(accounts)
            self.refresh_accounts()
            messagebox.showinfo("Import Complete", f"Successfully imported {added} new account(s).")
        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not read file: {e}")

    def export_accounts(self):
        accounts = self.settings_mgr.get_accounts()
        if not accounts:
            messagebox.showinfo("Empty", "No accounts to export.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Export Accounts",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt")]
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                for acc in accounts:
                    f.write(f"{acc['email']}:{acc['password']}\n")
            messagebox.showinfo("Export Successful", f"Exported {len(accounts)} accounts.")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export accounts: {e}")
