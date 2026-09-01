# -*- coding: utf-8 -*-
"""Thumbnail grid for per-page welcome/price/promo media in Settings."""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple
import queue

from settings.config_io import ConfigIO
from settings.media_thumb_util import (
    add_play_overlay,
    load_video_thumbnail,
    open_media_file,
)

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

THUMB_SIZE = 96
TILE_PAD = 6
TILE_W = TILE_H = THUMB_SIZE
ADD_BORDER = "#9aa0a6"
DROP_HIGHLIGHT = "#1a73e8"
DRAG_THRESHOLD = 5


class MediaThumbnailPanel(ttk.Frame):
    """Thumbnail strip with add tile, drag-reorder, preview, and per-item delete."""

    def __init__(
        self,
        parent: tk.Misc,
        kind: str,
        io: ConfigIO,
        get_page_name: Callable[[], str],
        tip_text: str = "",
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.io = io
        self.get_page_name = get_page_name
        self._photo_refs: Dict[str, object] = {}
        self._rows: List[Dict[str, str]] = []
        self._tile_frames: List[tk.Frame] = []
        self._cols = 4
        self._layout_job: str | None = None
        self._drag_from_idx: Optional[int] = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._dragging = False
        self._highlight_frame: Optional[tk.Frame] = None
        self._thumb_gen = 0
        self._video_queue: queue.Queue[
            Tuple[int, tk.Label, Optional[object], str]
        ] = queue.Queue()
        self.after(50, self._poll_video_queue)

        if tip_text:
            tip = ttk.Label(self, text=tip_text, wraplength=680, font=("Segoe UI", 8))
            tip.pack(anchor=tk.W, padx=2, pady=(0, 2))

        self._grid = ttk.Frame(self)
        self._grid.pack(fill=tk.X, padx=2, pady=(0, 4))
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event) -> None:
        if event.widget is not self:
            return
        cols = max(1, (event.width - 16) // (TILE_W + TILE_PAD))
        if cols == self._cols:
            return
        self._cols = cols
        if self._layout_job:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after_idle(self.refresh)

    def refresh(self) -> None:
        self._layout_job = None
        self._thumb_gen += 1
        self._clear_drag_state()
        self._photo_refs.clear()
        self._tile_frames.clear()
        for child in self._grid.winfo_children():
            child.destroy()

        page = (self.get_page_name() or "").strip()
        self._rows = []
        if page:
            try:
                self._rows = self.io.list_page_media(self.kind, page)
            except ValueError:
                self._rows = []

        cols = self._cols
        if cols < 1:
            cols = max(1, (self.winfo_width() or 600) // (TILE_W + TILE_PAD))
        if cols < 1:
            cols = 4

        row = col = 0
        for idx, item in enumerate(self._rows):
            self._make_tile(item, idx, row, col)
            col += 1
            if col >= cols:
                col = 0
                row += 1

        self._make_add_tile(row, col)

    def _make_tile(self, item: Dict[str, str], idx: int, row: int, col: int) -> None:
        name = item.get("name") or ""
        path = item.get("path") or ""
        mkind = item.get("kind") or "image"

        tile = tk.Frame(
            self._grid,
            width=TILE_W,
            height=TILE_H,
            bg="#ffffff",
            highlightthickness=0,
        )
        tile.grid(row=row, column=col, padx=TILE_PAD // 2, pady=TILE_PAD // 2)
        tile.grid_propagate(False)
        self._tile_frames.append(tile)

        thumb_lbl = tk.Label(tile, bg="#f1f3f4", relief=tk.FLAT, cursor="hand2")
        thumb_lbl.place(x=0, y=0, width=THUMB_SIZE, height=THUMB_SIZE)
        self._set_thumbnail(thumb_lbl, path, mkind, name)

        trash = tk.Label(
            tile,
            text="🗑",
            bg="#ffffff",
            fg="#5f6368",
            font=("Segoe UI Emoji", 10),
            cursor="hand2",
        )
        trash.place(relx=1.0, rely=0.0, anchor=tk.NE, x=-2, y=2)
        trash.bind("<Button-1>", lambda _e: self._delete_one(name))

        self._bind_tile_drag(tile, thumb_lbl, idx, path)

    def _bind_tile_drag(
        self, tile: tk.Frame, thumb_lbl: tk.Label, idx: int, path: str
    ) -> None:
        def on_press(event: tk.Event) -> None:
            self._drag_from_idx = idx
            self._drag_start_x = event.x_root
            self._drag_start_y = event.y_root
            self._dragging = False

        def on_motion(event: tk.Event) -> None:
            if self._drag_from_idx != idx:
                return
            if not self._dragging:
                dx = abs(event.x_root - self._drag_start_x)
                dy = abs(event.y_root - self._drag_start_y)
                if dx > DRAG_THRESHOLD or dy > DRAG_THRESHOLD:
                    self._dragging = True
                    self.config(cursor="fleur")
            if self._dragging:
                drop_idx = self._index_at(event.x_root, event.y_root)
                self._set_drop_highlight(drop_idx)

        def on_release(event: tk.Event) -> None:
            if self._drag_from_idx != idx:
                return
            if self._dragging:
                drop_idx = self._index_at(event.x_root, event.y_root)
                if drop_idx is not None and drop_idx != idx:
                    self._apply_reorder(idx, drop_idx)
            else:
                open_media_file(path)
            self._clear_drag_state()

        for widget in (tile, thumb_lbl):
            widget.bind("<Button-1>", on_press)
            widget.bind("<B1-Motion>", on_motion)
            widget.bind("<ButtonRelease-1>", on_release)

    def _index_at(self, x_root: int, y_root: int) -> Optional[int]:
        for i, frame in enumerate(self._tile_frames):
            if not frame.winfo_exists():
                continue
            wx = frame.winfo_rootx()
            wy = frame.winfo_rooty()
            ww = frame.winfo_width()
            wh = frame.winfo_height()
            if wx <= x_root <= wx + ww and wy <= y_root <= wy + wh:
                return i
        return None

    def _set_drop_highlight(self, idx: Optional[int]) -> None:
        if self._highlight_frame and self._highlight_frame.winfo_exists():
            self._highlight_frame.configure(highlightthickness=0)
        self._highlight_frame = None
        if idx is not None and 0 <= idx < len(self._tile_frames):
            frame = self._tile_frames[idx]
            frame.configure(highlightthickness=2, highlightbackground=DROP_HIGHLIGHT)
            self._highlight_frame = frame

    def _clear_drag_state(self) -> None:
        self._drag_from_idx = None
        self._dragging = False
        self.config(cursor="")
        self._set_drop_highlight(None)

    def _apply_reorder(self, from_idx: int, to_idx: int) -> None:
        page = (self.get_page_name() or "").strip()
        if not page or from_idx == to_idx:
            return
        names = [row["name"] for row in self._rows]
        if from_idx < 0 or from_idx >= len(names) or to_idx < 0 or to_idx >= len(names):
            return
        name = names.pop(from_idx)
        names.insert(to_idx, name)
        try:
            self.io.reorder_page_media(self.kind, page, names)
            self.refresh()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.winfo_toplevel())

    def _make_add_tile(self, row: int, col: int) -> None:
        canvas = tk.Canvas(
            self._grid,
            width=THUMB_SIZE,
            height=THUMB_SIZE,
            bg="#ffffff",
            highlightthickness=0,
            cursor="hand2",
        )
        canvas.grid(row=row, column=col, padx=TILE_PAD // 2, pady=TILE_PAD // 2)
        self._draw_add_icon(canvas)
        canvas.bind("<Button-1>", lambda _e: self._add_files())
        canvas.bind("<Configure>", lambda e, c=canvas: self._draw_add_icon(c))

    def _draw_add_icon(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        w = max(THUMB_SIZE, canvas.winfo_width() or TILE_W)
        h = max(THUMB_SIZE, canvas.winfo_height() or TILE_H)
        pad = 8
        canvas.create_rectangle(
            pad,
            pad,
            w - pad,
            h - pad,
            outline=ADD_BORDER,
            dash=(6, 4),
            width=2,
        )
        cx, cy = w // 2, h // 2 - 8
        canvas.create_text(cx, cy, text="📷", font=("Segoe UI Emoji", 22))
        canvas.create_text(cx, cy + 28, text="+", font=("Segoe UI", 16, "bold"), fill="#5f6368")

    def _set_thumbnail(
        self, label: tk.Label, path: str, mkind: str, name: str
    ) -> None:
        if Image is None or ImageTk is None or not path:
            label.configure(
                text="▶" if mkind == "video" else "🖼",
                font=("Segoe UI", 28),
                width=THUMB_SIZE,
                height=THUMB_SIZE,
            )
            return

        img = None
        if mkind == "image":
            try:
                raw = Image.open(path)
                img = self._fit_image(raw)
            except Exception:
                img = None
        elif mkind == "video":
            label.configure(
                text="…",
                font=("Segoe UI", 20),
                fg="#5f6368",
                width=THUMB_SIZE,
                height=THUMB_SIZE,
                image="",
            )
            self._load_video_thumb_async(label, path, name)
            return

        if img is not None:
            self._apply_thumb_image(label, img, name)
            return

        label.configure(
            text="▶" if mkind == "video" else "🖼",
            font=("Segoe UI", 28),
            width=THUMB_SIZE,
            height=THUMB_SIZE,
        )

    def _apply_thumb_image(
        self, label: tk.Label, img: "Image.Image", name: str
    ) -> None:
        if ImageTk is None or not label.winfo_exists():
            return
        photo = ImageTk.PhotoImage(img)
        self._photo_refs[name] = photo
        label.configure(image=photo, width=THUMB_SIZE, height=THUMB_SIZE, text="")

    def _load_video_thumb_async(
        self, label: tk.Label, path: str, name: str
    ) -> None:
        gen = self._thumb_gen

        def work() -> None:
            frame = load_video_thumbnail(path, THUMB_SIZE)
            img = add_play_overlay(frame) if frame is not None else None
            self._video_queue.put((gen, label, img, name))

        threading.Thread(target=work, daemon=True).start()

    def _poll_video_queue(self) -> None:
        while True:
            try:
                gen, label, img, name = self._video_queue.get_nowait()
            except queue.Empty:
                break
            if gen != self._thumb_gen or not label.winfo_exists():
                continue
            if img is not None:
                self._apply_thumb_image(label, img, name)
            else:
                label.configure(
                    text="▶",
                    font=("Segoe UI", 28),
                    width=THUMB_SIZE,
                    height=THUMB_SIZE,
                    image="",
                )
        self.after(50, self._poll_video_queue)

    def _fit_image(self, img: "Image.Image") -> "Image.Image":
        thumb = img.copy()
        thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        bg = Image.new("RGB", (THUMB_SIZE, THUMB_SIZE), "#f1f3f4")
        ox = (THUMB_SIZE - thumb.width) // 2
        oy = (THUMB_SIZE - thumb.height) // 2
        if thumb.mode == "RGBA":
            bg.paste(thumb, (ox, oy), thumb)
        else:
            bg.paste(thumb, (ox, oy))
        return bg

    def _add_files(self) -> None:
        page = (self.get_page_name() or "").strip()
        if not page:
            messagebox.showwarning(
                "ยังไม่มีเพจ",
                "เลือกเพจก่อน แล้วค่อยเพิ่มไฟล์",
                parent=self.winfo_toplevel(),
            )
            return
        paths = filedialog.askopenfilenames(
            parent=self.winfo_toplevel(),
            title="เลือกรูปหรือวิดีโอ",
            filetypes=[
                ("สื่อ", "*.jpg *.jpeg *.png *.gif *.webp *.mp4 *.mov *.m4v *.webm"),
                ("รูป", "*.jpg *.jpeg *.png *.gif *.webp"),
                ("วิดีโอ", "*.mp4 *.mov *.m4v *.webm"),
                ("All", "*.*"),
            ],
        )
        if not paths:
            return
        try:
            added = self.io.add_page_media(self.kind, page, [Path(p) for p in paths])
            self.refresh()
            messagebox.showinfo(
                "เพิ่มแล้ว",
                f"คัดลอก {len(added)} ไฟล์เข้าโฟลเดอร์เพจแล้ว",
                parent=self.winfo_toplevel(),
            )
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.winfo_toplevel())

    def _delete_one(self, name: str) -> None:
        page = (self.get_page_name() or "").strip()
        if not page:
            return
        if not messagebox.askyesno(
            "ลบไฟล์",
            f"ลบไฟล์นี้ออกจากโฟลเดอร์เพจ?\n{name}",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            self.io.delete_page_media(self.kind, page, [name])
            self.refresh()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", str(e), parent=self.winfo_toplevel())
