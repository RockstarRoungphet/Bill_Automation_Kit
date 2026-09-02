# -*- coding: utf-8 -*-
"""Searchable page name picker with thin popup scrollbar."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable, List, Optional

from settings.thin_entry import create_thin_entry
from settings.ui_scrollbar import create_vertical_scrollbar

_WHITE = "#ffffff"
_TEXT = "#202124"
_HOVER = "#f1f3f4"
_BORDER_INPUT = "#e8eaed"
_POPUP_HEIGHT = 180
_MIN_WIDTH = 200
_MAX_WIDTH = 480
_SCROLLBAR_PAD = 20
_FONT = ("Segoe UI", 9)


class SearchablePagePicker(ttk.Frame):
    """Entry + filterable list popup for selecting a page name."""

    def __init__(
        self,
        parent: tk.Misc,
        textvariable: tk.StringVar,
        *,
        on_select: Optional[Callable[[], None]] = None,
        width: int = 32,
    ) -> None:
        super().__init__(parent)
        self._var = textvariable
        self._on_select = on_select
        self._char_width = width
        self._all_values: List[str] = []
        self._filtered: List[str] = []
        self._popup: Optional[tk.Toplevel] = None
        self._listbox: Optional[tk.Listbox] = None
        self._vsb: Optional[tk.Scrollbar] = None
        self._ignore_key = False
        self._searching = False
        self._popup_visible = False
        self._global_click_bound = False
        self._hover_index: Optional[int] = None
        self._font = tkfont.Font(font=_FONT)

        self._entry = create_thin_entry(self, textvariable=textvariable, width=width)
        self._entry.pack(side=tk.LEFT)

        self._entry.bind("<KeyRelease>", self._on_keyrelease)
        self._entry.bind("<Down>", self._on_down)
        self._entry.bind("<Up>", self._on_up)
        self._entry.bind("<Return>", self._on_return)
        self._entry.bind("<Escape>", lambda _e: self._hide_popup())
        self._entry.bind("<FocusIn>", self._on_focus_in)
        self._entry.bind("<FocusOut>", self._on_focus_out)

    def set_values(self, names: List[str]) -> None:
        self._all_values = list(names)
        self._searching = False
        self._refresh_filter(show=False)
        self._sync_entry_width()

    def focus_entry(self) -> None:
        self._entry.focus_set()

    def _sync_entry_width(self) -> None:
        names = self._all_values or [self._var.get().strip() or " "]
        self._apply_width(names)

    def _apply_width(self, names: List[str]) -> int:
        w = self._content_width_px(names)
        char_px = max(self._font.measure("0"), 1)
        chars = max(self._char_width, min(48, int(w / char_px) + 2))
        self._entry.configure(width=chars)
        self._entry.set_fixed_outer_size(w)
        self.update_idletasks()
        return w

    def _scrollbar_width_px(self) -> int:
        if self._vsb is not None:
            try:
                measured = self._vsb.winfo_width()
                if measured > 1:
                    return measured
            except tk.TclError:
                pass
        return _SCROLLBAR_PAD

    def _content_width_px(self, names: List[str]) -> int:
        if not names:
            return _MIN_WIDTH
        longest = max(self._font.measure(name) for name in names)
        return int(
            min(
                _MAX_WIDTH,
                max(_MIN_WIDTH, longest + self._scrollbar_width_px() + 16),
            )
        )

    def _on_focus_in(self, _event: object = None) -> None:
        if not self._all_values:
            return
        self._searching = False
        self._refresh_filter(show=True)

    def _on_focus_out(self, _event: object = None) -> None:
        self.after(150, self._after_focus_out)

    def _after_focus_out(self) -> None:
        try:
            focus = self.winfo_toplevel().focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if self._popup is not None and focus is not None:
            w = focus
            while w is not None:
                if w == self._popup:
                    return
                try:
                    w = w.master
                except (AttributeError, tk.TclError):
                    break
        self._hide_popup()
        typed = self._var.get().strip()
        if typed and typed in self._all_values and self._on_select:
            self._on_select()

    def _on_keyrelease(self, event: tk.Event) -> None:
        if self._ignore_key:
            return
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        self._searching = True
        self._refresh_filter(show=True)

    def _on_down(self, event: tk.Event) -> str:
        if self._popup is None or not self._popup.winfo_viewable():
            self._searching = False
            self._refresh_filter(show=True)
        if self._listbox is not None and self._filtered:
            cur = self._listbox.curselection()
            idx = (cur[0] + 1) if cur else 0
            idx = min(idx, len(self._filtered) - 1)
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(idx)
            self._listbox.activate(idx)
            self._listbox.see(idx)
            self._reset_item_backgrounds()
        return "break"

    def _on_up(self, event: tk.Event) -> str:
        if self._listbox is not None and self._filtered:
            cur = self._listbox.curselection()
            idx = (cur[0] - 1) if cur else 0
            idx = max(idx, 0)
            self._listbox.selection_clear(0, tk.END)
            self._listbox.selection_set(idx)
            self._listbox.activate(idx)
            self._listbox.see(idx)
            self._reset_item_backgrounds()
        return "break"

    def _on_return(self, event: tk.Event) -> str:
        if self._listbox is not None and self._listbox.curselection():
            self._apply_selection(self._listbox.curselection()[0])
        else:
            typed = self._var.get().strip()
            if typed in self._all_values:
                self._hide_popup()
                if self._on_select:
                    self._on_select()
        return "break"

    def _refresh_filter(self, *, show: bool) -> None:
        if self._searching:
            query = self._var.get().strip().lower()
            if query:
                self._filtered = [n for n in self._all_values if query in n.lower()]
            else:
                self._filtered = list(self._all_values)
        else:
            self._filtered = list(self._all_values)
        if show:
            self._show_popup()
        elif self._popup is not None and self._listbox is not None:
            self._fill_listbox()

    def _widget_contains(self, widget: tk.Misc, x_root: int, y_root: int) -> bool:
        try:
            x1 = widget.winfo_rootx()
            y1 = widget.winfo_rooty()
            x2 = x1 + widget.winfo_width()
            y2 = y1 + widget.winfo_height()
        except tk.TclError:
            return False
        return x1 <= x_root < x2 and y1 <= y_root < y2

    def _on_global_click(self, event: tk.Event) -> None:
        if not self._popup_visible or self._popup is None:
            return
        if not self._popup.winfo_viewable():
            return
        x, y = event.x_root, event.y_root
        if self._widget_contains(self._entry, x, y):
            return
        if self._widget_contains(self._popup, x, y):
            return
        self._hide_popup()

    def _bind_global_click(self) -> None:
        if self._global_click_bound:
            return
        self.winfo_toplevel().bind("<Button-1>", self._on_global_click, add="+")
        self._global_click_bound = True

    def _show_popup(self) -> None:
        if not self._filtered:
            self._hide_popup()
            return
        if self._popup is None:
            self._popup = tk.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._popup.configure(
                bg=_WHITE, highlightthickness=1, highlightbackground=_BORDER_INPUT
            )
            body = ttk.Frame(self._popup)
            body.pack(fill=tk.BOTH, expand=True)
            self._listbox = tk.Listbox(
                body,
                height=8,
                activestyle="none",
                highlightthickness=0,
                bd=0,
                font=_FONT,
                selectbackground=_HOVER,
                selectforeground=_TEXT,
                bg=_WHITE,
            )
            vsb = create_vertical_scrollbar(body, command=self._listbox.yview)
            self._vsb = vsb
            self._listbox.configure(yscrollcommand=vsb.set)
            self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            vsb.pack(side=tk.RIGHT, fill=tk.Y)
            self._listbox.bind("<ButtonRelease-1>", self._on_list_click)
            self._listbox.bind("<Return>", lambda _e: self._on_return(_e))
            self._listbox.bind("<Motion>", self._on_list_motion)
            self._listbox.bind("<Leave>", self._on_list_leave)
        self._fill_listbox()
        self.update_idletasks()
        w = self._apply_width(self._filtered)
        x = self._entry.winfo_rootx()
        y = self._entry.winfo_rooty() + self._entry.winfo_height()
        self._popup.geometry(f"{w}x{_POPUP_HEIGHT}+{x}+{y}")
        self._popup.deiconify()
        self._popup_visible = True
        self._bind_global_click()

    def _fill_listbox(self) -> None:
        if self._listbox is None:
            return
        self._hover_index = None
        self._listbox.delete(0, tk.END)
        for name in self._filtered:
            self._listbox.insert(tk.END, name)
        if self._filtered:
            self._listbox.selection_set(0)
            self._listbox.activate(0)

    def _reset_item_backgrounds(self) -> None:
        if self._listbox is None:
            return
        for i in range(self._listbox.size()):
            self._listbox.itemconfig(i, bg=_WHITE)
        self._hover_index = None

    def _on_list_motion(self, event: tk.Event) -> None:
        if self._listbox is None:
            return
        idx = self._listbox.nearest(event.y)
        if idx < 0 or idx >= self._listbox.size():
            return
        if idx == self._hover_index:
            return
        if self._hover_index is not None:
            prev = self._hover_index
            if 0 <= prev < self._listbox.size():
                self._listbox.itemconfig(prev, bg=_WHITE)
        self._hover_index = idx
        self._listbox.itemconfig(idx, bg=_HOVER)

    def _on_list_leave(self, _event: object = None) -> None:
        self._reset_item_backgrounds()

    def _on_list_click(self, _event: object = None) -> None:
        if self._listbox is None:
            return
        cur = self._listbox.curselection()
        if cur:
            self._apply_selection(cur[0])

    def _apply_selection(self, index: int) -> None:
        if index < 0 or index >= len(self._filtered):
            return
        name = self._filtered[index]
        self._ignore_key = True
        self._var.set(name)
        self._ignore_key = False
        self._searching = False
        self._hide_popup()
        if self._on_select:
            self._on_select()

    def _hide_popup(self) -> None:
        self._popup_visible = False
        self._hover_index = None
        if self._popup is not None:
            self._popup.withdraw()
