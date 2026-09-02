# -*- coding: utf-8 -*-
"""Thin-bordered tk.Entry matching Settings text fields."""
from __future__ import annotations

import tkinter as tk
from typing import Any, Optional

from settings.unicode_input import bind_unicode_editing

_WHITE = "#ffffff"
_TEXT = "#202124"
_BORDER_INPUT = "#e8eaed"
_FONT = ("Segoe UI", 9)
_HEIGHT_PX = 25
_PAD_X = 1
_PAD_Y = 3  # total outer height ~= 25px (matches ttk buttons)
_ENTRY_OPTS = frozenset(
    {
        "width",
        "show",
        "textvariable",
        "state",
        "font",
        "fg",
        "bg",
        "insertbackground",
        "exportselection",
        "justify",
    }
)


class ThinEntry(tk.Frame):
    """Entry with thin outer border and comfortable vertical padding."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        textvariable: Optional[tk.StringVar] = None,
        width: int = 20,
        show: Optional[str] = None,
    ) -> None:
        super().__init__(
            parent,
            highlightthickness=1,
            highlightbackground=_BORDER_INPUT,
            highlightcolor=_BORDER_INPUT,
            bg=_WHITE,
        )
        entry_kw: dict[str, Any] = {
            "relief": tk.FLAT,
            "bd": 0,
            "highlightthickness": 0,
            "bg": _WHITE,
            "fg": _TEXT,
            "insertbackground": _TEXT,
            "font": _FONT,
            "width": width,
        }
        if textvariable is not None:
            entry_kw["textvariable"] = textvariable
        if show is not None:
            entry_kw["show"] = show
        self.entry = tk.Entry(self, **entry_kw)
        self.entry.pack(fill=tk.X, expand=True, padx=_PAD_X, pady=_PAD_Y)

        def _keep_border(_event: object = None) -> None:
            self.configure(
                highlightbackground=_BORDER_INPUT,
                highlightcolor=_BORDER_INPUT,
            )

        self.entry.bind("<FocusIn>", _keep_border, add="+")
        self.entry.bind("<FocusOut>", _keep_border, add="+")
        self.bind("<Button-1>", lambda _e: self.entry.focus_set(), add="+")
        bind_unicode_editing(self.entry)

    def configure(self, cnf: Any = None, **kw: Any) -> Any:
        if isinstance(cnf, str):
            if cnf in _ENTRY_OPTS:
                return self.entry.configure(cnf, **kw)
            return super().configure(cnf, **kw)
        opts = dict(cnf or {})
        opts.update(kw)
        entry_kw = {k: v for k, v in opts.items() if k in _ENTRY_OPTS}
        frame_kw = {k: v for k, v in opts.items() if k not in _ENTRY_OPTS}
        result: Any = None
        if entry_kw:
            result = self.entry.configure(**entry_kw)
        if frame_kw:
            result = super().configure(**frame_kw)
        return result

    config = configure

    def cget(self, key: str) -> Any:
        if key in _ENTRY_OPTS:
            return self.entry.cget(key)
        return super().cget(key)

    __getitem__ = cget

    def bind(self, sequence: str | None = None, func: Any = None, add: Any = None) -> str:
        return self.entry.bind(sequence, func, add=add)

    def focus_set(self) -> None:
        self.entry.focus_set()

    def set_fixed_outer_size(self, width_px: int, height_px: int = _HEIGHT_PX) -> None:
        """Lock outer frame size (used by page picker to match popup width)."""
        super().configure(width=width_px, height=height_px)
        self.pack_propagate(False)


def create_thin_entry(
    parent: tk.Misc,
    *,
    textvariable: Optional[tk.StringVar] = None,
    width: int = 20,
    show: Optional[str] = None,
) -> ThinEntry:
    return ThinEntry(
        parent, textvariable=textvariable, width=width, show=show
    )
