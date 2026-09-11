# -*- coding: utf-8 -*-
"""
gui/messages_tab.py — Message & Greeting Templates Editor
==========================================================
Visual template manager with:
- Multi-message text editor
- Rotational greetings editor
- Real-time live preview of how DM messages appear to recipients
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import List

from config.settings import SettingsManager, DEFAULT_MESSAGES, DEFAULT_GREETINGS
from core.messenger import compose_message_parts


class MessagesTab(ttk.Frame):
    """Tab for managing message variations and greetings with real-time preview."""

    def __init__(self, parent, settings_mgr: SettingsManager):
        super().__init__(parent, padding=16)
        self.settings_mgr = settings_mgr

        self.greeting_vars: List[tk.StringVar] = []
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        # Header
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(
            header,
            text="✉ Message & Greeting Templates",
            font=("Segoe UI", 14, "bold")
        ).pack(side="left")

        # Two-column layout: Left = Editor, Right = Live Preview
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left_frame = ttk.Frame(paned, padding=6)
        right_frame = ttk.Frame(paned, padding=6)
        paned.add(left_frame, weight=3)
        paned.add(right_frame, weight=2)

        # ── 1. Base Message Editor (Left) ──
        msg_frame = ttk.LabelFrame(left_frame, text="📝 Main Message Body", padding=8)
        msg_frame.pack(fill="both", expand=True, pady=(0, 8))

        ttk.Label(
            msg_frame,
            text="Separate multiple message variations with '---' on a new line.",
            font=("Segoe UI", 9, "italic")
        ).pack(anchor="w", pady=(0, 4))

        self.msg_text = tk.Text(msg_frame, wrap="word", height=14, font=("Segoe UI", 10))
        msg_scroll = ttk.Scrollbar(msg_frame, orient="vertical", command=self.msg_text.yview)
        self.msg_text.configure(yscrollcommand=msg_scroll.set)

        self.msg_text.pack(side="left", fill="both", expand=True)
        msg_scroll.pack(side="right", fill="y")
        self.msg_text.bind("<KeyRelease>", lambda e: self.update_preview())

        # ── 2. Greetings Editor (Left) ──
        greet_frame = ttk.LabelFrame(left_frame, text="👋 Greetings (Rotated per user)", padding=8)
        greet_frame.pack(fill="x", pady=(0, 8))

        self.greeting_vars = []
        for i in range(3):
            row = ttk.Frame(greet_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"Greeting #{i + 1}:", width=14).pack(side="left")
            var = tk.StringVar()
            entry = ttk.Entry(row, textvariable=var)
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<KeyRelease>", lambda e: self.update_preview())
            self.greeting_vars.append(var)

        # ── 3. Action Buttons (Left) ──
        btn_bar = ttk.Frame(left_frame)
        btn_bar.pack(fill="x", pady=4)
        ttk.Button(btn_bar, text="💾 Save Changes", command=self.save_data).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="🔄 Reset Defaults", command=self.reset_defaults).pack(side="left", padx=4)

        # ── 4. Live Message Preview (Right) ──
        prev_frame = ttk.LabelFrame(right_frame, text="👁 Live Recipient Preview (@sample_user)", padding=10)
        prev_frame.pack(fill="both", expand=True)

        self.preview_text = tk.Text(
            prev_frame,
            wrap="word",
            state="disabled",
            bg="#1e1e2e",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            font=("Segoe UI", 10),
            padx=10,
            pady=10,
            borderwidth=0
        )
        self.preview_text.pack(fill="both", expand=True)

    def load_data(self):
        messages = self.settings_mgr.get_messages()
        greetings = self.settings_mgr.get_greetings()

        self.msg_text.delete("1.0", "end")
        self.msg_text.insert("1.0", "\n---\n".join(messages))

        for i, var in enumerate(self.greeting_vars):
            if i < len(greetings):
                var.set(greetings[i])
            else:
                var.set("")

        self.update_preview()

    def update_preview(self):
        """Updates the live preview on the right side."""
        raw_text = self.msg_text.get("1.0", "end").strip()
        messages = [m.strip() for m in raw_text.split("---") if m.strip()]
        base_msg = messages[0] if messages else "No message text provided."

        greetings = [v.get().strip() for v in self.greeting_vars if v.get().strip()]
        greeting = greetings[0] if greetings else "I hope this message finds you in peace"

        parts = compose_message_parts(username="sample_user", base_message=base_msg, greeting=greeting, index=0)

        preview_content = (
            f"📨 [Line 1 — Salutation]:\n{parts[0]}\n\n"
            f"🤝 [Line 2 — Personalized Greeting]:\n{parts[1]}\n\n"
            f"📖 [Line 3 — Message Body]:\n{parts[2]}"
        )

        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", preview_content)
        self.preview_text.configure(state="disabled")

    def save_data(self):
        raw_text = self.msg_text.get("1.0", "end").strip()
        messages = [m.strip() for m in raw_text.split("---") if m.strip()]

        if not messages:
            messagebox.showwarning("Empty Message", "Please enter at least one message body.")
            return

        greetings = [v.get().strip() for v in self.greeting_vars if v.get().strip()]
        if not greetings:
            messagebox.showwarning("Empty Greetings", "Please enter at least one greeting.")
            return

        self.settings_mgr.update_messages(messages)
        self.settings_mgr.update_greetings(greetings)
        messagebox.showinfo("Saved", "Messages and greetings saved successfully!")
        self.update_preview()

    def reset_defaults(self):
        if messagebox.askyesno("Reset", "Reset messages and greetings to original defaults?"):
            self.settings_mgr.update_messages(DEFAULT_MESSAGES)
            self.settings_mgr.update_greetings(DEFAULT_GREETINGS)
            self.load_data()
            messagebox.showinfo("Reset", "Restored default messages and greetings.")
