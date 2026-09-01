# -*- coding: utf-8 -*-
"""Thumbnail helpers: video frame extraction and open media for preview."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from PIL import Image


def load_video_thumbnail(path: str, size: int) -> Optional["Image.Image"]:
    """Extract first video frame and fit into size x size square."""
    from PIL import Image

    frame = _read_video_frame(path)
    if frame is None:
        return None
    try:
        if hasattr(frame, "thumbnail"):
            img = frame
        else:
            img = Image.fromarray(frame)
        return _fit_to_square(img, size)
    except Exception:
        return None


def _find_ffmpeg() -> Optional[str]:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _read_video_frame(path: str):
    """Read first video frame via ffmpeg subprocess (most reliable on Windows)."""
    if not path or not os.path.isfile(path):
        return None

    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        frame = _read_frame_ffmpeg(ffmpeg, path)
        if frame is not None:
            return frame

    try:
        import imageio.v3 as iio

        return iio.imread(path, index=0)
    except Exception:
        pass
    try:
        import imageio

        reader = imageio.get_reader(path, "ffmpeg")
        try:
            return reader.get_data(0)
        finally:
            reader.close()
    except Exception:
        return None


def _subprocess_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if flags:
        return {"creationflags": flags}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": info}


def _read_frame_ffmpeg(ffmpeg: str, path: str):
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "0.5",
                "-i",
                path,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                tmp_path,
            ],
            capture_output=True,
            timeout=120,
            **_subprocess_kwargs(),
        )
        if result.returncode != 0 or not os.path.isfile(tmp_path):
            return None
        from PIL import Image

        with Image.open(tmp_path) as im:
            return im.convert("RGB")
    except Exception:
        return None
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _fit_to_square(img: "Image.Image", size: int) -> "Image.Image":
    from PIL import Image

    thumb = img.copy()
    thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
    bg = Image.new("RGB", (size, size), "#f1f3f4")
    ox = (size - thumb.width) // 2
    oy = (size - thumb.height) // 2
    if thumb.mode == "RGBA":
        bg.paste(thumb, (ox, oy), thumb)
    else:
        bg.paste(thumb, (ox, oy))
    return bg


def add_play_overlay(img: "Image.Image") -> "Image.Image":
    """Draw a small play indicator on a video thumbnail."""
    from PIL import ImageDraw

    out = img.convert("RGBA")
    draw = ImageDraw.Draw(out)
    cx, cy = out.width // 2, out.height // 2
    r = 16
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(32, 33, 36, 160),
    )
    tri = [
        (cx - 5, cy - 8),
        (cx - 5, cy + 8),
        (cx + 9, cy),
    ]
    draw.polygon(tri, fill=(255, 255, 255, 230))
    return out.convert("RGB")


def open_media_file(path: str) -> None:
    """Open image/video with the system default application."""
    if not path or not os.path.isfile(path):
        return
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass
