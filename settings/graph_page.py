# -*- coding: utf-8 -*-
"""Fetch Facebook Page list / identity from Graph API (no App Secret)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

GRAPH_VERSION = "v18.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_TIMEOUT = 15


class GraphPageError(Exception):
    """User-facing Graph/API failure."""


def _http_get_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "BillAutomationKit/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        msg = _format_graph_error(body) or f"HTTP {e.code}"
        raise GraphPageError(msg) from e
    except urllib.error.URLError as e:
        raise GraphPageError(
            f"เชื่อมต่อ Graph API ไม่ได้ (เน็ต/ไฟร์วอลล์): {e.reason}"
        ) from e
    except TimeoutError as e:
        raise GraphPageError("หมดเวลาเชื่อมต่อ Graph API — ลองอีกครั้ง") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise GraphPageError("คำตอบจาก Graph API ไม่ใช่ JSON") from e
    if not isinstance(data, dict):
        raise GraphPageError("รูปแบบคำตอบจาก Graph API ไม่ถูกต้อง")
    if "error" in data:
        raise GraphPageError(_format_graph_error(raw) or "Graph API error")
    return data


def _format_graph_error(body: str) -> str:
    if not body:
        return ""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body[:200]
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return body[:200]
    message = str(err.get("message") or "").strip()
    code = err.get("code")
    sub = err.get("error_subcode")
    lower = message.lower()
    if code == 190 or "session has expired" in lower or "invalid oauth" in lower:
        return (
            "Token ไม่ถูกต้องหรือหมดอายุ — "
            "สร้าง Long-Lived User Token ใหม่แล้ววางอีกครั้ง"
        )
    if code == 10 or "permission" in lower:
        return (
            "Token ไม่มีสิทธิ์อ่านเพจ — "
            "ตรวจสิทธิ์ pages_show_list / pages_messaging บนแอป Meta"
        )
    extra = f" (code={code}"
    if sub is not None:
        extra += f", subcode={sub}"
    extra += ")"
    return (message or "Graph API error") + extra


def _normalize_page(item: Dict[str, Any]) -> Dict[str, str] | None:
    pid = str(item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    token = str(item.get("access_token") or "").strip()
    if not pid or not name:
        return None
    return {
        "page_id": pid,
        "page_name": name,
        "access_token": token,
    }


def _fetch_me_as_page(access_token: str) -> Dict[str, str] | None:
    """If token is a Page Access Token, /me returns that page (no access_token field)."""
    q = urllib.parse.urlencode(
        {"fields": "id,name", "access_token": access_token}
    )
    data = _http_get_json(f"{GRAPH_BASE}/me?{q}")
    pid = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    if not pid or not name:
        return None
    # Heuristic: user ids are numeric too; page tokens often still work as /me page.
    # Only accept as page fallback when caller got empty /me/accounts.
    return {
        "page_id": pid,
        "page_name": name,
        "access_token": access_token,
    }


def list_pages_from_user_token(
    user_token: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, str]]:
    """
    List pages for a (preferably Long-Lived) User Token via /me/accounts.

    Returns list of {page_id, page_name, access_token} (Page Access Tokens).
    Falls back to a single page from GET /me when accounts is empty but token
    looks like a Page Access Token.
    """
    token = (user_token or "").strip()
    if not token:
        raise GraphPageError("ยังไม่ได้วาง User Token")

    pages: List[Dict[str, str]] = []
    seen: set[str] = set()
    q = urllib.parse.urlencode(
        {
            "fields": "id,name,access_token",
            "limit": "100",
            "access_token": token,
        }
    )
    next_url: str | None = f"{GRAPH_BASE}/me/accounts?{q}"

    while next_url:
        data = _http_get_json(next_url, timeout=timeout)
        batch = data.get("data")
        if not isinstance(batch, list):
            batch = []
        for item in batch:
            if not isinstance(item, dict):
                continue
            row = _normalize_page(item)
            if not row:
                continue
            if not row["access_token"]:
                # Should not happen for /me/accounts; skip incomplete rows
                continue
            if row["page_id"] in seen:
                continue
            seen.add(row["page_id"])
            pages.append(row)

        paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
        nxt = paging.get("next") if isinstance(paging, dict) else None
        next_url = str(nxt) if nxt else None

    if pages:
        return pages

    # Fallback: pasted Page Access Token instead of User Token
    try:
        one = _fetch_me_as_page(token)
    except GraphPageError:
        raise GraphPageError(
            "ไม่พบเพจจาก Token นี้ — "
            "ใช้ Long-Lived User Token ที่มีสิทธิ์เพจ "
            "หรือ Page Access Token ที่ยังใช้ได้"
        )
    if one:
        return [one]
    raise GraphPageError(
        "ไม่พบเพจจาก Token นี้ — "
        "ตรวจว่าเป็น Long-Lived User Token และเชื่อมเพจกับแอปแล้ว"
    )


def fetch_page_by_id(
    user_token: str,
    page_id: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, str]:
    """
    Fetch one page by numeric Page ID using a User Token.

    For Business-owned pages that do not appear in /me/accounts.
    Returns {page_id, page_name, access_token}.
    """
    token = (user_token or "").strip()
    pid = (page_id or "").strip()
    if not token:
        raise GraphPageError("ยังไม่ได้วาง User Token")
    if not pid:
        raise GraphPageError("ยังไม่ได้ใส่ Page ID")
    if not pid.isdigit():
        raise GraphPageError("Page ID ต้องเป็นตัวเลขเท่านั้น")

    q = urllib.parse.urlencode(
        {
            "fields": "id,name,access_token",
            "access_token": token,
        }
    )
    data = _http_get_json(f"{GRAPH_BASE}/{pid}?{q}", timeout=timeout)
    row = _normalize_page(data)
    if not row:
        raise GraphPageError(
            "ได้คำตอบจาก Graph แต่ไม่มี id/name ของเพจ — ตรวจ Page ID อีกครั้ง"
        )
    if not row["access_token"]:
        raise GraphPageError(
            "ดึงเพจได้แต่ไม่มี Page Token — "
            "สร้าง User Token ใหม่แล้วติ๊กเพจนี้ตอนอนุญาต "
            "หรือเพิ่มสิทธิ์ pages_show_list / business_management"
        )
    return row
