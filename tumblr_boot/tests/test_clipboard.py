"""Exercise real Tk bindings with an isolated clipboard, without network access."""

import sys
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.clipboard import ClipboardSupport
from gui.messages_tab import MessagesTab


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        # Use Tk's normal Copy/Paste handlers without changing the OS clipboard.
        self.root.tk.eval("""
            set ::test_clipboard {}
            rename clipboard original_clipboard
            proc clipboard {operation args} {
                if {$operation eq "clear"} {set ::test_clipboard {}; return}
                if {$operation eq "append"} {append ::test_clipboard [lindex $args end]; return}
                if {$operation eq "get"} {return $::test_clipboard}
                error "unsupported clipboard operation"
            }
            rename selection original_selection
            proc selection {operation args} {
                if {$operation eq "get" && [lsearch -exact $args CLIPBOARD] >= 0} {
                    return $::test_clipboard
                }
                original_selection $operation {*}$args
            }
        """)

    def clipboard(self, value=None):
        if value is not None:
            self.root.tk.call("set", "::test_clipboard", value)
        return self.root.tk.call("set", "::test_clipboard")

    @staticmethod
    def content(widget):
        return widget.get("1.0", "end-1c") if isinstance(widget, tk.Text) else widget.get()

    def test_arabic_layout_shortcuts_copy_cut_paste_and_replace_selection(self):
        for constructor in (ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Text):
            with self.subTest(widget=constructor.__name__):
                widget = constructor(self.root)
                widget.pack()
                support = ClipboardSupport(self.root)
                support._windows = True
                self.root.update_idletasks()
                widget.winfo_id()  # Realize classic widgets while the test window stays hidden.
                def shortcut(code, symbol):
                    result = support._on_control_key(SimpleNamespace(
                        widget=widget, keycode=code, keysym=symbol, state=4,
                    ))
                    self.assertEqual(result, "break")
                self.clipboard("مرحبا hello")
                shortcut(86, "Arabic_ra")
                self.assertEqual(self.content(widget), "مرحبا hello")
                shortcut(65, "Arabic_sheen")
                shortcut(67, "Arabic_hamzaonwaw")
                self.assertEqual(self.clipboard().rstrip("\n"), "مرحبا hello")
                self.clipboard("replacement")
                shortcut(86, "v")
                self.assertEqual(self.content(widget), "replacement")
                shortcut(65, "A")
                shortcut(88, "Arabic_hamza")
                self.assertEqual(self.content(widget), "")
                self.assertEqual(self.clipboard().rstrip("\n"), "replacement")
                widget.destroy()

    def test_readonly_fields_allow_copy_but_not_modification(self):
        for constructor, state in ((ttk.Entry, "readonly"), (tk.Text, "disabled")):
            with self.subTest(widget=constructor.__name__):
                widget = constructor(self.root)
                widget.pack()
                widget.insert("1.0" if isinstance(widget, tk.Text) else 0, "Read only")
                widget.configure(state=state)
                support = ClipboardSupport(self.root)
                self.root.update_idletasks()
                widget.winfo_id()
                support.invoke(widget, "SelectAll")
                support.invoke(widget, "Copy")
                self.assertEqual(self.clipboard().rstrip("\n"), "Read only")
                self.clipboard("replacement")
                support.invoke(widget, "Cut")
                support.invoke(widget, "Paste")
                self.assertEqual(self.content(widget), "Read only")
                widget.destroy()

    def test_context_menu_pastes_into_selected_field(self):
        widget = ttk.Entry(self.root)
        widget.insert(0, "old")
        widget.selection_range(0, "end")
        support = ClipboardSupport(self.root)
        self.root.update_idletasks()
        self.clipboard("new")
        with patch.object(support.menu, "tk_popup"), patch.object(support.menu, "grab_release"):
            result = support._show_menu(SimpleNamespace(widget=widget, x_root=0, y_root=0))
        self.assertEqual(result, "break")
        self.assertEqual(str(support.menu.entrycget("Paste", "state")), "normal")
        support.menu.invoke("Paste")
        self.assertEqual(widget.get(), "new")

    def test_other_shortcuts_and_altgr_are_not_intercepted(self):
        widget = ttk.Entry(self.root)
        support = ClipboardSupport(self.root)
        support._windows = True
        with patch.object(support, "invoke") as invoke:
            for code, keysym, state in ((90, "z", 4), (86, "v", 4 | 0x20000)):
                self.assertIsNone(support._on_control_key(SimpleNamespace(
                    widget=widget, keycode=code, keysym=keysym, state=state,
                )))
            invoke.assert_not_called()

    def test_preview_updates_after_paste_without_key_release(self):
        manager = Mock()
        manager.get_messages.return_value = ["Original message"]
        manager.get_greetings.return_value = ["Hello"]
        tab = MessagesTab(self.root, settings_mgr=manager)
        support = ClipboardSupport(self.root)
        self.root.update()
        self.clipboard("Pasted message\nSecond line")
        support.invoke(tab.msg_text, "SelectAll")
        support.invoke(tab.msg_text, "Paste")
        self.root.update()
        self.assertIn("Pasted message\nSecond line", tab.preview_text.get("1.0", "end"))
        greeting_field = next(
            child for child in self._descendants(tab)
            if isinstance(child, ttk.Entry)
        )
        self.clipboard("Welcome")
        support.invoke(greeting_field, "SelectAll")
        support.invoke(greeting_field, "Paste")
        self.root.update()
        self.assertIn("Welcome, sample_user", tab.preview_text.get("1.0", "end"))

    def _descendants(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._descendants(child)


if __name__ == "__main__":
    unittest.main()
