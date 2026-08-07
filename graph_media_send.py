#!/usr/bin/env python3
"""
Shared helpers for Facebook Messenger Graph API: discover per-page media files
in base_dir/<PageName>/ subfolders and upload/send image + video attachments
(one attachment per message — Messenger limitation).
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from typing import Iterable, List, Optional, Tuple

import requests

# Extensions treated as images / videos for discovery & upload
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def natural_sort_key(filename: str) -> List:
    """Sort key so that 2.jpg < 10.jpg (digit-aware)."""
    base = os.path.basename(filename)
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", base)]


def _list_subfolder_media(
    subfolder: str,
) -> Tuple[List[str], List[str]]:
    """Classify files in subfolder into images and videos; natural-sort each list."""
    images: List[str] = []
    videos: List[str] = []
    try:
        names = sorted(os.listdir(subfolder), key=natural_sort_key)
    except OSError:
        return [], []
    for name in names:
        path = os.path.join(subfolder, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            images.append(path)
        elif ext in VIDEO_EXTENSIONS:
            videos.append(path)
    return images, videos


def discover_page_media(base_dir: str, page_name: str) -> Tuple[List[str], List[str]]:
    """
    Return (image_paths, video_paths) from base_dir/page_name/ only.

    Files are natural-sorted; caller sends all images then all videos.
    Returns empty lists if the subfolder is missing or has no media files.
    """
    base_dir = os.path.normpath(base_dir)
    if not page_name or not os.path.isdir(base_dir):
        return [], []
    sub = os.path.join(base_dir, page_name)
    if not os.path.isdir(sub):
        return [], []
    return _list_subfolder_media(sub)


def guess_mime_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".gif":
        return "image/gif"
    if ext == ".webp":
        return "image/webp"
    if ext == ".mp4":
        return "video/mp4"
    if ext in (".mov", ".m4v"):
        return "video/quicktime"
    if ext == ".webm":
        return "video/webm"
    guessed, _ = mimetypes.guess_type(file_path)
    return guessed or "application/octet-stream"


def media_type_for_path(file_path: str) -> Optional[str]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def upload_message_attachment(
    page_id: str,
    page_access_token: str,
    file_path: str,
    graph_version: str = "v18.0",
) -> Optional[str]:
    """Upload a local file to Graph API message_attachments; return attachment_id or None."""
    if not page_access_token or not os.path.isfile(file_path):
        return None
    mtype = media_type_for_path(file_path)
    if not mtype:
        return None
    url = f"https://graph.facebook.com/{graph_version}/{page_id}/message_attachments"
    message_json = json.dumps({"attachment": {"type": mtype, "payload": {"is_reusable": True}}})
    mime = guess_mime_type(file_path)
    basename = os.path.basename(file_path)
    try:
        with open(file_path, "rb") as f:
            files = {"filedata": (basename, f, mime)}
            data = {"message": message_json}
            resp = requests.post(
                url,
                data=data,
                files=files,
                params={"access_token": page_access_token},
                timeout=120,
            )
        result = resp.json()
        aid = result.get("attachment_id")
        if aid:
            return str(aid)
        print(f"   ⚠️ อัปโหลดสื่อไม่สำเร็จ: {result}")
        return None
    except Exception as e:
        print(f"   ⚠️ อัปโหลดสื่อผิดพลาด: {e}")
        return None


def send_attachment_by_id(
    page_id: str,
    page_access_token: str,
    recipient_psid: str,
    attachment_id: str,
    media_type: str,
    graph_version: str = "v18.0",
) -> bool:
    """Send a previously uploaded attachment to a user."""
    url = f"https://graph.facebook.com/{graph_version}/{page_id}/messages"
    payload = {
        "recipient": {"id": recipient_psid},
        "message": {
            "attachment": {
                "type": media_type,
                "payload": {"attachment_id": attachment_id},
            }
        },
        "access_token": page_access_token,
    }
    try:
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        if "recipient_id" in result:
            return True
        print(f"   ❌ ส่ง attachment ไม่สำเร็จ: {result}")
        return False
    except Exception as e:
        print(f"   ❌ ส่ง attachment ผิดพลาด: {e}")
        return False


def send_text_message(
    page_id: str,
    page_access_token: str,
    recipient_psid: str,
    text: str,
    graph_version: str = "v18.0",
) -> bool:
    if not (text or "").strip():
        return True
    url = f"https://graph.facebook.com/{graph_version}/{page_id}/messages"
    payload = {
        "recipient": {"id": recipient_psid},
        "message": {"text": text},
        "access_token": page_access_token,
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        result = response.json()
        if "recipient_id" in result:
            return True
        print(f"   ❌ ส่งข้อความไม่สำเร็จ: {result}")
        return False
    except Exception as e:
        print(f"   ❌ ส่งข้อความผิดพลาด: {e}")
        return False


def send_media_sequence(
    page_id: str,
    page_access_token: str,
    recipient_psid: str,
    image_paths: Iterable[str],
    video_paths: Iterable[str],
    send_delay: float = 0.6,
    log_prefix: str = "",
) -> None:
    """Upload and send each image then each video; delay between sends."""
    imgs = list(image_paths)
    vids = list(video_paths)
    for path in imgs:
        mtype = media_type_for_path(path)
        if mtype != "image":
            continue
        aid = upload_message_attachment(page_id, page_access_token, path)
        if aid:
            if send_attachment_by_id(page_id, page_access_token, recipient_psid, aid, "image"):
                print(f"   ✅ {log_prefix}ส่งรูป: {os.path.basename(path)}")
        time.sleep(send_delay)
    for path in vids:
        mtype = media_type_for_path(path)
        if mtype != "video":
            continue
        aid = upload_message_attachment(page_id, page_access_token, path)
        if aid:
            if send_attachment_by_id(page_id, page_access_token, recipient_psid, aid, "video"):
                print(f"   ✅ {log_prefix}ส่งวิดีโอ: {os.path.basename(path)}")
        time.sleep(send_delay)
