# -*- coding: utf-8 -*-
"""Place child windows under an anchor, left-aligned to a parent frame."""
from __future__ import annotations

from typing import Optional, Tuple

import tkinter as tk


def under_xy(
    anchor: tk.Misc,
    *,
    parent: Optional[tk.Misc] = None,
    gap: int = 4,
    pad: int = 0,
    width_hint: int = 0,
    left_align_parent: bool = True,
) -> Tuple[int, int]:
    """Return screen (x, y): under anchor, left-aligned to parent when given.

    Standard: x = parent left (+ pad), y = just below the clicked button (anchor).
    """
    try:
        anchor.update_idletasks()
    except tk.TclError:
        pass

    try:
        x = int(anchor.winfo_rootx())
        y = int(anchor.winfo_rooty()) + int(anchor.winfo_height()) + int(gap)
    except tk.TclError:
        return (0, 0)

    if parent is None:
        return (x, y)

    try:
        parent.update_idletasks()
        left = int(parent.winfo_rootx())
        top = int(parent.winfo_rooty())
        right = left + int(parent.winfo_width())
        bottom = top + int(parent.winfo_height())
    except tk.TclError:
        return (x, y)

    if left_align_parent:
        x = left + int(pad)
    elif width_hint > 0:
        if width_hint >= (right - left) - 2 * pad:
            x = left + int(pad)
        else:
            x = max(left + int(pad), min(x, right - int(pad) - int(width_hint)))
    else:
        x = max(left + int(pad), min(x, right - int(pad)))

    # Keep under the button; tall children may extend below parent.
    y = max(y, top + int(pad))
    return (x, y)


def place_window_under(
    win: tk.Misc,
    anchor: tk.Misc,
    *,
    parent: Optional[tk.Misc] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    gap: int = 4,
    pad: int = 0,
    left_align_parent: bool = True,
) -> None:
    """Set win geometry under anchor, left-aligned to parent (default)."""
    try:
        win.update_idletasks()
    except tk.TclError:
        pass

    try:
        w = int(width) if width is not None else max(int(win.winfo_reqwidth()), int(win.winfo_width()))
        h = int(height) if height is not None else max(int(win.winfo_reqheight()), int(win.winfo_height()))
    except tk.TclError:
        w = int(width or 400)
        h = int(height or 300)

    clamp_parent = parent if parent is not None else None
    x, y = under_xy(
        anchor,
        parent=clamp_parent,
        gap=gap,
        pad=pad,
        width_hint=w,
        left_align_parent=left_align_parent if clamp_parent is not None else False,
    )

    if clamp_parent is not None:
        try:
            left = int(clamp_parent.winfo_rootx())
            right = left + int(clamp_parent.winfo_width())
            if left_align_parent:
                x = left + int(pad)
            elif w >= (right - left) - 2 * pad:
                x = left + int(pad)
            else:
                x = max(left + int(pad), min(x, right - int(pad) - w))
            # Do not pull y up to fit inside parent — that covers the toolbar.
            # Tall dialogs intentionally extend below the launcher.
        except tk.TclError:
            pass

    try:
        win.geometry(f"{w}x{h}+{x}+{y}")
    except tk.TclError:
        pass


def show_placed_toplevel(
    win: tk.Misc,
    anchor: tk.Misc,
    *,
    parent: Optional[tk.Misc] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    gap: int = 4,
    pad: int = 0,
) -> None:
    """Place a withdrawn toplevel then show it (avoids flash at 0,0)."""
    place_window_under(
        win,
        anchor,
        parent=parent,
        width=width,
        height=height,
        gap=gap,
        pad=pad,
        left_align_parent=True,
    )
    try:
        win.deiconify()
        win.lift()
        win.focus_force()
    except tk.TclError:
        pass
