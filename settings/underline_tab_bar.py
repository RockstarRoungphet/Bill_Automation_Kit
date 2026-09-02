# -*- coding: utf-8 -*-
"""Custom tab bar with hover fill and selected underline (Google Translate style)."""
from __future__ import annotations

import tkinter as tk
import tkinter.ttk as ttk
from typing import List

_WHITE = "#ffffff"
_TEXT = "#202124"
_HOVER = "#f1f3f4"
_UNDERLINE = "#5f6368"
_TAB_FONT = ("Segoe UI", 9)
_TAB_PADX = 14
_TAB_PADY = 6


class UnderlineTabBar(tk.Frame):
    """Horizontal tab strip: gray hover on inactive tabs, gray underline on selected."""

    def __init__(
        self,
        parent: tk.Misc,
        notebook: ttk.Notebook,
        labels: List[str],
    ) -> None:
        super().__init__(parent, bg=_WHITE, highlightthickness=0, bd=0)
        self._notebook = notebook
        self._labels: List[tk.Label] = []
        self._selected = 0
        self._hovering: int | None = None

        self._tabs_row = tk.Frame(self, bg=_WHITE, highlightthickness=0, bd=0)
        self._tabs_row.pack(fill=tk.X)

        for index, text in enumerate(labels):
            lbl = tk.Label(
                self._tabs_row,
                text=text,
                bg=_WHITE,
                fg=_TEXT,
                font=_TAB_FONT,
                padx=_TAB_PADX,
                pady=_TAB_PADY,
                cursor="hand2",
            )
            lbl.pack(side=tk.LEFT)
            lbl.bind("<Button-1>", lambda _e, i=index: self.select(i))
            lbl.bind("<Enter>", lambda _e, i=index: self._on_enter(i))
            lbl.bind("<Leave>", lambda _e, i=index: self._on_leave(i))
            self._labels.append(lbl)

        self._line = tk.Canvas(
            self,
            height=3,
            bg=_WHITE,
            highlightthickness=0,
            bd=0,
        )
        self._line.pack(fill=tk.X)

        self._tabs_row.bind("<Configure>", lambda _e: self._draw_underline())
        notebook.bind("<<NotebookTabChanged>>", self._sync_from_notebook, add="+")

        self.after_idle(self._sync_from_notebook)

    def select(self, index: int) -> None:
        if index < 0 or index >= len(self._labels):
            return
        self._notebook.select(index)
        self._set_selected(index)

    def _sync_from_notebook(self, _event: object | None = None) -> None:
        try:
            current = self._notebook.index(self._notebook.select())
        except tk.TclError:
            current = 0
        self._set_selected(int(current))

    def _set_selected(self, index: int) -> None:
        self._selected = index
        for i, lbl in enumerate(self._labels):
            lbl.configure(bg=_HOVER if self._hovering == i and i != index else _WHITE)
        self._draw_underline()

    def _draw_underline(self) -> None:
        if not self._labels:
            return
        lbl = self._labels[self._selected]
        self.update_idletasks()
        x1 = lbl.winfo_x()
        x2 = x1 + lbl.winfo_width()
        self._line.delete("underline")
        if x2 > x1:
            self._line.create_line(
                x1,
                1,
                x2,
                1,
                fill=_UNDERLINE,
                width=2,
                tags="underline",
            )

    def _on_enter(self, index: int) -> None:
        self._hovering = index
        if index != self._selected:
            self._labels[index].configure(bg=_HOVER)

    def _on_leave(self, index: int) -> None:
        self._hovering = None
        if index != self._selected:
            self._labels[index].configure(bg=_WHITE)
