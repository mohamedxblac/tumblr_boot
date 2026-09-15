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

from config.settings import (
    DEFAULT_GREETINGS,
    DEFAULT_MESSAGES,
    MESSAGE_SLOT_COUNT,
    SettingsManager,
)
from core.messenger import compose_message_parts


class MessagesTab(ttk.Frame):
    """Tab for managing message variations and greetings with real-time preview."""

    def __init__(self, parent, settings_mgr: SettingsManager):
        super().__init__(parent, padding=16)
        self.settings_mgr = settings_mgr

        self.greeting_vars: List[tk.StringVar] = []
        self.message_texts: List[tk.Text] = []
        self.preview_message_var = tk.IntVar(value=1)
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        # Header
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(
            header,
            text="Message & Greeting Templates",
            font=("Segoe UI", 14, "bold")
        ).pack(side="left")

        # Two-column layout: Left = Editor, Right = Live Preview
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left_frame = ttk.Frame(paned, padding=6)
        right_frame = ttk.Frame(paned, padding=6)
        paned.add(left_frame, weight=3)
        paned.add(right_frame, weight=2)

        # ── 1. Fifteen separate message variations (Left) ──
        msg_frame = ttk.LabelFrame(
            left_frame,
            text=f"Message Variations ({MESSAGE_SLOT_COUNT} slots)",
            padding=8,
        )
        msg_frame.pack(fill="both", expand=True, pady=(0, 8))

        ttk.Label(
            msg_frame,
            text="Fill at least two different messages. They are shuffled and never repeated consecutively.",
            font=("Segoe UI", 9, "italic")
        ).pack(anchor="w", pady=(0, 4))

        msg_canvas = tk.Canvas(
            msg_frame,
            background="#181825",
            borderwidth=0,
            highlightthickness=0,
            height=330,
        )
        msg_scroll = ttk.Scrollbar(msg_frame, orient="vertical", command=msg_canvas.yview)
        msg_list = ttk.Frame(msg_canvas)
        msg_window = msg_canvas.create_window((0, 0), window=msg_list, anchor="nw")
        msg_list.bind(
            "<Configure>",
            lambda _event: msg_canvas.configure(scrollregion=msg_canvas.bbox("all")),
        )
        msg_canvas.bind(
            "<Configure>",
            lambda event: msg_canvas.itemconfigure(msg_window, width=event.width),
        )
        msg_canvas.configure(yscrollcommand=msg_scroll.set)
        msg_canvas.pack(side="left", fill="both", expand=True)
        msg_scroll.pack(side="right", fill="y")

        def _on_mousewheel(event):
            msg_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        msg_canvas.bind("<Enter>", lambda _: msg_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        msg_canvas.bind("<Leave>", lambda _: msg_canvas.unbind_all("<MouseWheel>"))

        for index in range(MESSAGE_SLOT_COUNT):
            row = ttk.Frame(msg_list)
            row.pack(fill="x", pady=(2, 7), padx=(0, 6))
            ttk.Label(
                row,
                text=f"Message #{index + 1}",
                width=12,
                anchor="nw",
            ).pack(side="left", padx=(0, 6), pady=4)
            field = tk.Text(
                row,
                wrap="word",
                height=4,
                font=("Segoe UI", 10),
                bg="#313244",
                fg="#cdd6f4",
                insertbackground="#cdd6f4",
                selectbackground="#585b70",
                borderwidth=0,
                padx=7,
                pady=5,
            )
            field.pack(side="left", fill="x", expand=True)
            field.bind("<<Modified>>", self._on_message_modified)
            self.message_texts.append(field)

        # Compatibility alias for integrations that previously targeted the
        # single message editor. It now points at variation number one.
        self.msg_text = self.message_texts[0]

        # ── 2. Greetings Editor (Left) ──
        greet_frame = ttk.LabelFrame(left_frame, text="Greetings (Rotated per user)", padding=8)
        greet_frame.pack(fill="x", pady=(0, 8))

        self.greeting_vars = []
        for i in range(3):
            row = ttk.Frame(greet_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"Greeting #{i + 1}:", width=14).pack(side="left")
            var = tk.StringVar()
            entry = ttk.Entry(row, textvariable=var)
            entry.pack(side="left", fill="x", expand=True)
            var.trace_add("write", lambda *_: self.update_preview())
            self.greeting_vars.append(var)

        # ── 3. Action Buttons (Left) ──
        btn_bar = ttk.Frame(left_frame)
        btn_bar.pack(fill="x", pady=4)
        ttk.Button(btn_bar, text="Save Changes", command=self.save_data).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="Reset Defaults", command=self.reset_defaults).pack(side="left", padx=4)
        self.message_count_label = ttk.Label(btn_bar, text="0 / 15 filled", foreground="#6c7086")
        self.message_count_label.pack(side="right", padx=6)

        # ── 4. Live Message Preview (Right) ──
        preview_picker = ttk.Frame(right_frame)
        preview_picker.pack(fill="x", pady=(0, 6))
        ttk.Label(preview_picker, text="Preview variation:").pack(side="left")
        preview_spin = ttk.Spinbox(
            preview_picker,
            from_=1,
            to=MESSAGE_SLOT_COUNT,
            textvariable=self.preview_message_var,
            width=5,
            state="readonly",
            command=self.update_preview,
            style="Timing.TSpinbox",
        )
        preview_spin.pack(side="left", padx=6)
        self.preview_message_var.trace_add("write", lambda *_: self.update_preview())

        prev_frame = ttk.LabelFrame(right_frame, text="Live Recipient Preview (@sample_user)", padding=10)
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

        for index, field in enumerate(self.message_texts):
            field.delete("1.0", "end")
            if index < len(messages):
                val = messages[index]
                if val:
                    field.insert("1.0", val)
            field.edit_modified(False)

        for i, var in enumerate(self.greeting_vars):
            if i < len(greetings):
                var.set(greetings[i])
            else:
                var.set("")

        self.update_preview()

    def _on_message_modified(self, event=None):
        field = event.widget if event is not None else None
        if field is None or field.edit_modified():
            if field is not None:
                field.edit_modified(False)
            self.update_preview()

    def _messages_by_slot(self) -> List[str]:
        return [field.get("1.0", "end").strip() for field in self.message_texts]

    def update_preview(self):
        """Updates the live preview on the right side."""
        messages_by_slot = self._messages_by_slot()
        filled_messages = [message for message in messages_by_slot if message]
        self.message_count_label.configure(
            text=f"{len(filled_messages)} / {MESSAGE_SLOT_COUNT} filled"
        )
        try:
            preview_index = max(
                0,
                min(MESSAGE_SLOT_COUNT - 1, int(self.preview_message_var.get()) - 1),
            )
        except (tk.TclError, ValueError):
            preview_index = 0
        base_msg = messages_by_slot[preview_index]
        if not base_msg:
            base_msg = filled_messages[0] if filled_messages else "No message text provided."

        greetings = [v.get().strip() for v in self.greeting_vars if v.get().strip()]
        greeting = greetings[0] if greetings else "I hope this message finds you in peace"

        parts = compose_message_parts(username="sample_user", base_message=base_msg, greeting=greeting, index=0)

        preview_content = (
            f"[Line 1 — Personalized Greeting]:\n{parts[0]}\n\n"
            f"[Line 2 — Message Body]:\n{parts[1]}"
        )

        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", preview_content)
        self.preview_text.configure(state="disabled")

    def save_data(self, silent: bool = False) -> bool:
        """Saves all 15 message slots and greetings to disk.

        Preserves slot positions and saves even if only 1 variation is entered
        (with a clear warning that the bot engine requires at least 2 distinct
        variations to run safely without trigger spam filters).
        """
        raw_slots = self._messages_by_slot()
        filled_messages = [message for message in raw_slots if message]
        distinct_messages = list(dict.fromkeys(filled_messages))

        if not filled_messages:
            if not silent:
                messagebox.showwarning(
                    "Empty Messages",
                    "Please enter at least one message body before saving.",
                )
            return False

        greetings = [v.get().strip() for v in self.greeting_vars if v.get().strip()]
        if not greetings:
            if not silent:
                messagebox.showwarning("Empty Greetings", "Please enter at least one greeting.")
            return False

        saved_ok = self.settings_mgr.update_messages_and_greetings(raw_slots, greetings)

        if not saved_ok:
            if not silent:
                messagebox.showerror(
                    "Save Failed",
                    "Messages could NOT be written to disk.\n"
                    "Check file permissions for the data/ folder.",
                )
            return False

        if not silent:
            if len(distinct_messages) < 2:
                messagebox.showwarning(
                    "Saved (Warning)",
                    f"Saved {len(filled_messages)} message(s) and {len(greetings)} greeting(s) successfully.\n\n"
                    "⚠️ Note: The Bot requires at least 2 DIFFERENT message variations before it can start sending.",
                )
            else:
                messagebox.showinfo(
                    "Saved Successfully",
                    f"{len(filled_messages)} message(s) ({len(distinct_messages)} distinct) and "
                    f"{len(greetings)} greeting(s) saved successfully!",
                )

        self.update_preview()
        return True

    def reset_defaults(self):
        if messagebox.askyesno("Reset", "Reset messages and greetings to original defaults?"):
            self.settings_mgr.update_messages_and_greetings(DEFAULT_MESSAGES, DEFAULT_GREETINGS)
            self.load_data()
            messagebox.showinfo("Reset", "Restored default messages and greetings.")
