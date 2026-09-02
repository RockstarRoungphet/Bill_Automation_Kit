# -*- coding: utf-8 -*-
"""Unicode-safe editing for tk Entry/Text on Windows (IME / Lao layout)."""
from __future__ import annotations

import sys
import tkinter as tk
from typing import Any, Callable, Optional

_VK_A, _VK_C, _VK_V, _VK_X = 65, 67, 86, 88
_NAV_KEYS = frozenset(
    {
        "Left",
        "Right",
        "Up",
        "Down",
        "Home",
        "End",
        "Prior",
        "Next",
        "Tab",
        "Return",
        "BackSpace",
        "Delete",
        "Escape",
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Win_L",
        "Win_R",
        "Caps_Lock",
    }
)


def _ctrl(event: tk.Event) -> bool:
    return bool(event.state & 0x4)


def _read_clipboard(widget: tk.Misc) -> str:
    try:
        return str(widget.clipboard_get())
    except tk.TclError:
        return ""


def _mark_modified(widget: tk.Misc) -> None:
    if isinstance(widget, tk.Text):
        try:
            widget.edit_modified(True)
        except tk.TclError:
            pass


def _copy_text(widget: tk.Text) -> None:
    try:
        text = widget.get(tk.SEL_FIRST, tk.SEL_LAST)
    except tk.TclError:
        return
    if not text:
        return
    widget.clipboard_clear()
    widget.clipboard_append(text)


def _cut_text(widget: tk.Text) -> None:
    try:
        text = widget.get(tk.SEL_FIRST, tk.SEL_LAST)
    except tk.TclError:
        return
    if not text:
        return
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
    _mark_modified(widget)


def _paste_into_text(widget: tk.Text) -> str | None:
    clip = _read_clipboard(widget)
    if not clip:
        return None
    try:
        if widget.tag_ranges(tk.SEL):
            widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
    except tk.TclError:
        pass
    widget.insert(tk.INSERT, clip)
    _mark_modified(widget)
    return "break"


def _copy_entry(widget: tk.Entry) -> None:
    try:
        if not widget.selection_present():
            return
        text = widget.selection_get()
    except tk.TclError:
        return
    if not text:
        return
    widget.clipboard_clear()
    widget.clipboard_append(text)


def _cut_entry(widget: tk.Entry) -> None:
    try:
        if not widget.selection_present():
            return
        text = widget.selection_get()
    except tk.TclError:
        return
    if not text:
        return
    widget.clipboard_clear()
    widget.clipboard_append(text)
    widget.delete(tk.SEL_FIRST, tk.SEL_LAST)


def _paste_into_entry(widget: tk.Entry) -> str | None:
    clip = _read_clipboard(widget)
    if not clip:
        return None
    try:
        if widget.selection_present():
            widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
    except tk.TclError:
        pass
    widget.insert(tk.INSERT, clip)
    return "break"


def _select_all_text(widget: tk.Text) -> None:
    widget.tag_add(tk.SEL, "1.0", "end-1c")
    widget.mark_set(tk.INSERT, "1.0")
    widget.see(tk.INSERT)


def _select_all_entry(widget: tk.Entry) -> None:
    widget.select_range(0, tk.END)
    widget.icursor(tk.END)


def _win_char_from_keyevent(keycode: int) -> str:
    """Resolve Unicode from virtual-key when tk event.char is '?' (Lao layout)."""
    if not sys.platform.startswith("win") or keycode <= 0:
        return ""
    import ctypes

    user32 = ctypes.windll.user32
    state = (ctypes.c_byte * 256)()
    if not user32.GetKeyboardState(state):
        return ""
    layout = user32.GetKeyboardLayout(0)
    scan = user32.MapVirtualKeyExW(keycode, 0, layout)
    buf = (ctypes.c_wchar * 8)()
    n = user32.ToUnicodeEx(keycode, scan, state, buf, 8, 0, layout)
    if n == 0:
        return ""
    count = abs(n)
    return "".join(buf[i] for i in range(count) if buf[i])


def _resolve_typed_char(event: tk.Event) -> Optional[str]:
    ch = event.char or ""
    keysym = event.keysym
    vk = int(getattr(event, "keycode", 0) or 0)

    if keysym in _NAV_KEYS:
        return None

    if len(ch) == 1 and ord(ch) >= 0x80 and ch != "?":
        return ch

    if ch == "?" or keysym == "??":
        win_ch = _win_char_from_keyevent(vk)
        if win_ch:
            return win_ch
        if ch == "?":
            return None

    if len(ch) == 1 and ch.isprintable() and ord(ch) >= 32:
        if not (len(keysym) == 1 and keysym.isascii() and keysym.isprintable()):
            return ch
    return None


def _prepend_widget_bindtag(widget: tk.Misc) -> None:
    tags = list(widget.bindtags())
    name = str(widget)
    if not tags or tags[0] != name:
        widget.bindtags((name, *tags))


def _insert_text_char(widget: tk.Misc, text: str) -> str:
    if isinstance(widget, tk.Text):
        try:
            if widget.tag_ranges(tk.SEL):
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass
        widget.insert(tk.INSERT, text)
        _mark_modified(widget)
    elif isinstance(widget, tk.Entry):
        try:
            if widget.selection_present():
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass
        widget.insert(tk.INSERT, text)
    return "break"


def bind_unicode_editing(
    widget: tk.Misc,
    *,
    after_change: Optional[Callable[[], None]] = None,
) -> None:
    """Keycode-based shortcuts + manual Unicode insert (Lao/IME layouts)."""

    def _done() -> None:
        if after_change is not None:
            try:
                widget.after_idle(after_change)
            except tk.TclError:
                pass

    def _on_keypress(event: tk.Event) -> str | None:
        vk = int(getattr(event, "keycode", 0) or 0)
        ch = event.char or ""
        ctrl = _ctrl(event)

        if isinstance(widget, tk.Text):
            if ctrl and (ch == "\x01" or vk == _VK_A):
                _select_all_text(widget)
                return "break"
            if ctrl and (ch == "\x03" or vk == _VK_C):
                _copy_text(widget)
                return "break"
            if ctrl and (ch == "\x18" or vk == _VK_X):
                _cut_text(widget)
                _done()
                return "break"
            if ctrl and (ch == "\x16" or vk == _VK_V):
                result = _paste_into_text(widget)
                if result is not None:
                    _done()
                return result
        elif isinstance(widget, tk.Entry):
            if ctrl and (ch == "\x01" or vk == _VK_A):
                _select_all_entry(widget)
                return "break"
            if ctrl and (ch == "\x03" or vk == _VK_C):
                _copy_entry(widget)
                return "break"
            if ctrl and (ch == "\x18" or vk == _VK_X):
                _cut_entry(widget)
                _done()
                return "break"
            if ctrl and (ch == "\x16" or vk == _VK_V):
                result = _paste_into_entry(widget)
                if result is not None:
                    _done()
                return result

        if not ctrl and event.keysym not in _NAV_KEYS:
            resolved = _resolve_typed_char(event)
            if resolved:
                result = _insert_text_char(widget, resolved)
                _done()
                return result
            if (event.char or "") == "?" and event.keysym == "??":
                return "break"
        return None

    def _on_paste(_event: object = None) -> str | None:
        if isinstance(widget, tk.Text):
            result = _paste_into_text(widget)
        elif isinstance(widget, tk.Entry):
            result = _paste_into_entry(widget)
        else:
            return None
        if result is not None:
            _done()
        return result

    _prepend_widget_bindtag(widget)
    widget.bind("<KeyPress>", _on_keypress)
    widget.bind("<<Paste>>", _on_paste, add="+")


def bind_unicode_paste(widget: tk.Misc, *, after_paste: Any = None) -> None:
    """Backward-compatible alias."""
    bind_unicode_editing(widget, after_change=after_paste)
