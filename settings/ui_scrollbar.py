# -*- coding: utf-8 -*-
"""Minimal scrollbars for Settings — native tk.Scrollbar like Launcher ScrolledText."""
from __future__ import annotations

import tkinter as tk


def create_vertical_scrollbar(
    parent: tk.Misc,
    *,
    command=None,
) -> tk.Scrollbar:
    """Single-piece native scrollbar (continuous thumb on Windows)."""
    return tk.Scrollbar(
        parent,
        orient=tk.VERTICAL,
        command=command,
        highlightthickness=0,
        bd=0,
    )
