"""Shared text-editing shortcuts and context menus for the application's inputs."""

import tkinter as tk
from tkinter import ttk


class ClipboardSupport:
    _KEYS = {"a": "SelectAll", "c": "Copy", "v": "Paste", "x": "Cut"}
    # Windows virtual key codes remain stable when the input language changes.
    _WINDOWS_KEYS = {65: "SelectAll", 67: "Copy", 86: "Paste", 88: "Cut"}
    _TEXT_WIDGETS = (tk.Text, tk.Entry, tk.Spinbox, ttk.Entry)

    def __init__(self, root):
        self.root = root
        self._windows = root.tk.call("tk", "windowingsystem") == "win32"
        self._tag = f"ClipboardSupport_{id(self)}"
        self._target = None
        self.menu = tk.Menu(
            root, tearoff=False, bg="#1e1e2e", fg="#cdd6f4",
            activebackground="#89b4fa", activeforeground="#11111b",
        )
        for label, shortcut, action in (
            ("Cut", "Ctrl+X", "Cut"), ("Copy", "Ctrl+C", "Copy"),
            ("Paste", "Ctrl+V", "Paste"), ("Select All", "Ctrl+A", "SelectAll"),
        ):
            self.menu.add_command(
                label=label, accelerator=shortcut,
                command=lambda action=action: self.invoke(self._target, action),
            )
        root.bind_class(self._tag, "<Control-KeyPress>", self._on_control_key)
        root.bind_class(self._tag, "<Button-3>", self._show_menu)
        self.install(root)

    def install(self, parent):
        """Attach before Tk's default bindings so a shortcut only runs once."""
        if isinstance(parent, self._TEXT_WIDGETS):
            if self._tag not in parent.bindtags():
                parent.bindtags((self._tag, *parent.bindtags()))
            # Preserve the selected text when focus moves to the context menu.
            parent.configure(exportselection=False)
        for child in parent.winfo_children():
            self.install(child)

    def _on_control_key(self, event):
        # Let AltGr and Ctrl+Alt combinations retain their normal behavior.
        if event.state & (0x0008 | 0x20000):
            return None
        action = self._WINDOWS_KEYS.get(event.keycode) if self._windows else None
        if action is None:
            action = self._KEYS.get(event.keysym.lower())
        if action is None:
            return None
        self.invoke(event.widget, action)
        return "break"

    @staticmethod
    def _editable(widget):
        return str(widget.cget("state")) not in ("disabled", "readonly")

    def invoke(self, widget, action):
        if widget is None or not widget.winfo_exists():
            return
        if action in ("Cut", "Paste") and not self._editable(widget):
            return
        # Keep Tk's Unicode clipboard, selection replacement and widget behavior.
        widget.event_generate(f"<<{action}>>")

    def _show_menu(self, event):
        widget = event.widget
        self._target = widget
        widget.focus_set()
        selected = bool(widget.tag_ranges("sel")) if isinstance(widget, tk.Text) else widget.selection_present()
        editable = self._editable(widget)
        try:
            has_clipboard_text = bool(widget.clipboard_get())
        except tk.TclError:
            has_clipboard_text = False
        for label, enabled in (
            ("Copy", selected), ("Cut", selected and editable),
            ("Paste", has_clipboard_text and editable), ("Select All", True),
        ):
            self.menu.entryconfigure(label, state="normal" if enabled else "disabled")
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"
