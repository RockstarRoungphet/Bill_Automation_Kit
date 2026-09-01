#!/usr/bin/env python3
"""
Simple Webhook Server สำหรับรับข้อความจาก Facebook Messenger
ไม่ต้องใช้ Flask (ใช้ http.server แทน)
- ตอบ HTTP 200 ทันทีแล้วประมวลผลใน thread แยก (ลด timeout จาก Facebook)
- บันทึก last_message timestamp สำหรับระบบโปรโมชั่นอัตโนมัติ
- ตรวจจับเบอร์โทรจากลูกค้า (ถือว่ากำลังจะซื้อ)
- รองรับข้อความ welcome + หลายรูป/วิดีโอต่อเพจ (Graph API — page_reply_config + product_images/<เพจ>/)
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import sys
import time
import threading
import urllib.parse
import os
import re
from typing import Optional

import requests

from graph_media_send import (
    discover_page_media_ordered,
    send_media_paths_ordered,
    send_text_message,
)

# Verify Token
VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "my_verify_token_12345")

# Feature switches
ENABLE_MESSAGING = os.getenv("ENABLE_MESSAGING", "1").strip().lower() not in ("0", "false", "off", "no")
ENABLE_FEED = os.getenv("ENABLE_FEED", "0").strip().lower() in ("1", "true", "on", "yes")

BASE_URL = os.getenv("BASE_URL", "http://localhost:5000")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCT_IMAGES_DIR = os.path.join(SCRIPT_DIR, "product_images")
PRICE_IMAGES_DIR = os.path.join(SCRIPT_DIR, "price_images")
WELCOME_SEND_DELAY = float(os.getenv("WELCOME_SEND_DELAY", "0.6"))

ORDER_PSID_FILE = "order_psid.json"
LAST_MESSAGE_FILE = "last_message_by_psid.json"
PHONE_DETECTED_FILE = "phone_detected_psid.json"
PSID_NAME_CACHE_FILE = "psid_name_cache.json"

PHONE_REGEX = re.compile(r'(?<!\d)\d(?:[\s-]?\d){6,10}(?!\d)')

# ---------------------------------------------------------------------------
# Fuzzy price-keyword matching (Thai + Lao)
# ---------------------------------------------------------------------------
PRICE_FUZZY_THRESHOLD = float(os.getenv("PRICE_FUZZY_THRESHOLD", "0.55"))
PRICE_NEAR_THRESHOLD  = float(os.getenv("PRICE_NEAR_THRESHOLD",  "0.40"))

_LAO_TONE_MARKS  = "\u0EC8\u0EC9\u0ECA\u0ECB"   # ່ ້ ໊ ໋
_THAI_TONE_MARKS = "\u0E48\u0E49\u0E4A\u0E4B"    # ่ ้ ๊ ๋
_ALL_TONE_MARKS  = _LAO_TONE_MARKS + _THAI_TONE_MARKS
_TONE_RE = re.compile(f"[{_ALL_TONE_MARKS}]")
_SPACE_RE = re.compile(r"\s+")

PRICE_KEYWORDS_EXACT = [
    # ไทยปกติ
    "ราคา", "เท่าไหร่", "เท่าไร", "ขอราคา", "ราคาเท่าไร", "กี่บาท",
    # ลาวปกติ
    "ລາຄາ", "ທໍ່ໃດ", "ທໍ່ເດີ", "ເທົ່າເດີ",
    "ເທົ່າໃດ", "ເທົາໃດ", "ເທົາເດີ",
    "ຈັກກີບ", "ຈັກເງິນ", "ກີບ", "ກິບ",
    # ลาว tone variants (จาก kaojao.com + เพิ่ม)
    "ລາຄ່າ", "ລ່າຄ່າ", "ລ່າຄາ",
    # ลาวพิมพ์ผิดบ่อย (สลับสระ/พยัญชนะ)
    "ລາຄະ", "ລະຄາ", "ລາຄ້າ", "ລຄາ",
    "ເທົາເດິ", "ທໍ່ເດິ", "ທໍ່ໃດ້",
    # ไทยเขียนด้วยแป้นลาว / พิมพ์ผิดผสม
    "ลาคา", "ท่อใด", "ท่ใด", "เท่าใด", "ท่อเดี", "ท่เดี",
    # อังกฤษ
    "price", "how much",
]

PRICE_KEYWORDS_NORM = [
    # ไทย (หลังตัด tone)
    "ราคา", "เทาไหร", "เทาไร", "ขอราคา", "ราคาเทาไร", "กีบาท",
    # ไทย-ลาว ผสม
    "ลาคา", "ทอใด", "ทใด", "เทาใด", "ทอเดี", "ทเดี",
    # ลาว (หลังตัด tone)
    "ລາຄາ", "ລາຄະ", "ລະຄາ", "ລຄາ",
    "ທໍໃດ", "ທໍເດີ", "ເທົາເດີ", "ເທົາໃດ",
    "ເທົາເດິ", "ທໍເດິ",
    "ຈັກກີບ", "ຈັກເງິນ", "ກີບ", "ກິບ",
    # อังกฤษ
    "price", "how much",
]

def _normalize_text(s: str) -> str:
    """ลบ tone marks (ลาว+ไทย), ลดช่องว่าง, lowercase — ให้เปรียบเทียบได้ง่ายขึ้น"""
    s = _TONE_RE.sub("", s)
    s = _SPACE_RE.sub(" ", s).strip().lower()
    return s

def _char_ngrams(s: str, n: int = 2) -> set:
    """สร้าง character n-gram set (bigram default)"""
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i+n] for i in range(len(s) - n + 1)}

def _ngram_similarity(a: str, b: str) -> float:
    """Jaccard similarity ระหว่าง bigram sets ของ 2 สตริง"""
    if not a or not b:
        return 0.0
    sa, sb = _char_ngrams(a), _char_ngrams(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0

def _tokenize(text: str) -> list:
    """แยกข้อความเป็น token ย่อยๆ (รวมแบบ sliding window สำหรับคำที่ติดกัน)"""
    words = text.split()
    tokens = list(words)
    for w in words:
        if len(w) > 6:
            for size in range(3, min(len(w), 12) + 1):
                for start in range(len(w) - size + 1):
                    tokens.append(w[start:start+size])
    return tokens

def is_price_question(text: str) -> tuple:
    """
    ตรวจว่าข้อความเป็นคำถามราคาหรือไม่
    Returns: (matched: bool, best_keyword: str, best_score: float, method: str)
    """
    t = (text or "").strip()
    tl = t.lower()

    # --- Layer 1: Exact substring match (เดิม + คำลาว) ---
    for kw in PRICE_KEYWORDS_EXACT:
        if kw in t or kw in tl:
            return True, kw, 1.0, "exact"

    # --- Layer 2: Normalized substring match (ตัด tone marks แล้วเช็คอีกรอบ) ---
    tn = _normalize_text(t)
    for kw in PRICE_KEYWORDS_NORM:
        if kw in tn:
            return True, kw, 0.95, "normalized"

    # --- Layer 3: Fuzzy n-gram matching (เฉพาะคำที่ยาวพอ) ---
    tokens = _tokenize(tn)
    best_score = 0.0
    best_kw = ""
    for kw in PRICE_KEYWORDS_NORM:
        if len(kw) < 3:
            continue
        for tok in tokens:
            if len(tok) < 3:
                continue
            score = _ngram_similarity(tok, kw)
            if score > best_score:
                best_score = score
                best_kw = kw

    if best_score >= PRICE_FUZZY_THRESHOLD:
        return True, best_kw, best_score, "fuzzy"

    if best_score >= PRICE_NEAR_THRESHOLD:
        return False, best_kw, best_score, "near_miss"

    return False, best_kw, best_score, "no_match"

# ---------------------------------------------------------------------------
# Fuzzy order-intent matching (Thai + Lao)
# ---------------------------------------------------------------------------
# เป้าหมาย: ตรวจว่าข้อความของลูกค้าเป็น “คำสั่งซื้อ/เอาของ/ส่งมาให้”
# โดยกัน false-positive จากข้อความถามค่าส่ง/วิธีส่ง และกัน “เลขราคา” ที่หลุดมาใกล้คำว่าเอา

MAX_ORDER_QTY = int(os.getenv("MAX_ORDER_QTY", "20"))

# คำ/วลีที่บอกว่าเป็น “ถามค่าส่ง/วิธีส่ง” (ถ้ามีให้ถือว่าไม่ใช่คำสั่งซื้อ)
ORDER_EXCLUDE_SHIP_MARKERS = [
    # Lao
    "ຄ່າສົ່ງ",
    "ຂນສົ່ງ",
    "ຈັດສົ່ງ",
    "ສົ່ງແນວໃດ",
    "ສົ່ງຢັງໄດ",
    "ສົ່ງແບບ",
    "ສົ່ງຢັງໄດ",
    "ສົ່ງໄວ",
    "ວິທີສົ່ງ",
    "ຈັດສົ່ງແນວ",
    "ເລືອກຂນສົ່ງ",
    # Thai
    "ค่าส่ง",
    "ขนส่ง",
    "วิธีส่ง",
    "จัดส่ง",
    # Thai/Lao ที่มักตามด้วยคำถาม
    "ສົ່ງບໍ",
    "ສົ່ງແນວໃດ",
    # English
    "shipping",
]

# คำที่ชี้ว่าเป็น “ถามราคา” (ถ้ามีให้ถือว่าไม่ใช่คำสั่งซื้อ)
ORDER_EXCLUDE_PRICE_MARKERS = [
    "ราคา", "เท่าไหร่", "เท่าไร", "ขอราคา", "ราคาเท่าไร", "กี่บาท", "กี่เงิน",
    "ລາຄາ", "ລາຄ່າ", "ລ່າຄ່າ", "ລາຄະ", "ລະຄາ",
    "ເທົ່າໃດ", "ເທົາໃດ", "ເທົາເດີ", "ເທົາເດີ",
    "ຈັກກີບ", "ຈັກເງິນ", "ກີບ", "ກິບ",
    "how much", "price",
]

ORDER_SEND_PHRASES_EXACT = [
    # Lao (จากคีย์เวิร์ดที่คุณให้)
    "ສົ່ງແນ່",
    "ສົ່ງແດ່",
    "ສົ່ງໃຫ້ແນ່",
    "ສົ່ງໃຫ້ແດ່",
    # Thai
    "ส่งแน่",
    "ส่งแด่",
    "ส่งให้แน่",
    "ส่งให้แด่",
]

# Normalize marker/phrases once (ให้สอดคล้องกับ tn ที่เราทำใน is_order_intent)
ORDER_EXCLUDE_SHIP_MARKERS_NORM = [_normalize_text(m) for m in ORDER_EXCLUDE_SHIP_MARKERS]
ORDER_EXCLUDE_PRICE_MARKERS_NORM = [_normalize_text(m) for m in ORDER_EXCLUDE_PRICE_MARKERS]
ORDER_SEND_PHRASES_NORM = [_normalize_text(p) for p in ORDER_SEND_PHRASES_EXACT]

SANG_NORM = _normalize_text("ສັ່ງ")  # ສັ່ງ -> ສັງ
ORDER_CONTEXT_NORM = [_normalize_text(x) for x in ("ແດ່", "ແນ່", "ນຳ", "ເດີ", "ນຳເດີ", "ເດີ້")]

# Thai "สั่ง" (normalize แล้วจะตัด tone marks)
SANG_THAI_NORM = _normalize_text("สั่ง")  # สั่ง -> สัง
ORDER_THAI_CONTEXT_NORM = [_normalize_text(x) for x in ("แน่", "แด่", "เลย", "ซื้อ")]

# Keywords ลาวสำหรับ “สั่ง/เอา”
ORDER_KWS_EXACT = [
    "ສັ່ງແດ່",
    "ສັ່ງແນ່",
    "ສັ່ງນຳເດີ",
    "ສັ່ງເດີ",
    "ສັ່ງ",
    "ສົ່ງແນ່",
    "ສົ່ງແດ່",
    "ເອົາ",
    "ເອົາ1",
    "ເອົາ 1",
    "ສົ່ງແນ່",
    "ສົ່ງແດ່",
    # Thai short
    "เอา", "ส่ง",
    # Units/variants ที่เจอบ่อย
    "ຊຸດ", "ຊູດ", "ສຸດ", "ສູດ", "ອັນ", "ຫນວຍ",
]

# regex ตรวจ “เอา + จำนวน” (รองรับเอาแบบไม่มีเว้นวรรค เช่น ເອົາ1ຊຸດ)
TAKE_QTY_RE = re.compile(
    r"(?:ເອົາ|เอา)\s*([0-9]{1,6})(?:\s*(ຊຸດ|ຊູດ|ສຸດ|ສູດ|ອັນ|ຫນວຍ))?",
    re.IGNORECASE,
)


def is_order_intent(text: str) -> tuple:
    """
    ตรวจว่าข้อความเป็น intent “สั่งซื้อ/เอาของ/ส่งมาให้”
    Returns: (matched, best_keyword_or_reason, score, method)
    """
    t = (text or "").strip()
    if not t:
        return False, "", 0.0, "no_text"

    tn = _normalize_text(t)

    # Exclude explicit shipping-question / method questions
    if any(m in tn for m in ORDER_EXCLUDE_SHIP_MARKERS_NORM):
        return False, "excluded_ship_marker", 0.0, "exclude_ship"

    # Exclude price-question messages (กันลูกค้าถามราคา)
    if any(m in tn for m in ORDER_EXCLUDE_PRICE_MARKERS_NORM):
        return False, "excluded_price_marker", 0.0, "exclude_price"

    # 0) "รับ" / ຮັບ (ต้องมีบริบทพอ: มีจำนวนเล็กหรือมี unit การสั่ง)
    if any(m in tn for m in ("ຮັບ", "รับ")):
        if any(u in tn for u in ("ຊຸດ", "ຊູດ", "ສຸດ", "ສູດ", "ອັນ", "ຫນວຍ")) or re.search(r"\b[0-9]{1,2}\b", tn):
            return True, "receive_with_context", 0.8, "receive_word"

    # 1) Take quantity (เอา/ເອົາ + ตัวเลข)
    m_best = None
    for m in TAKE_QTY_RE.finditer(tn):
        qty = int(m.group(1))
        unit = m.group(2) or ""
        # ถ้าเป็นจำนวนมากผิดปกติ ให้ไม่ถือเป็นคำสั่งซื้อ ยกเว้นมีคำ unit ชัดเจน
        if qty <= MAX_ORDER_QTY or unit:
            m_best = (qty, unit)
            break
    if m_best:
        qty, unit = m_best
        return True, f"take_qty:{qty}{unit}", 0.95, "regex_take_qty"

    # 2) Send phrases: ส่งแน่/ส่งให้แด่/ສົ່ງແນ່/ສົ່ງໃຫ້ແດ່
    for p_norm, p_raw in zip(ORDER_SEND_PHRASES_NORM, ORDER_SEND_PHRASES_EXACT):
        if p_norm in tn:
            return True, p_raw, 1.0, "send_phrase"

    # 3) Order keywords: ສັ່ງ ... (มีบริบทแบบ “สั่งเลย/สั่งแน่/นຳເດີ”)
    if SANG_NORM in tn:
        if any(x in tn for x in ORDER_CONTEXT_NORM):
            return True, "sang_with_context", 0.9, "order_word"
        # กัน false-positive: ถ้าเป็นแค่คำว่า "ສັ່ງ" อย่างเดียว จะถือว่าไม่แน่ใจ
        # (ยกเว้นข้อความมีหน่วยการสั่ง เช่น ຊຸດ/ອັນ/ຫນວຍ หรือมีตัวเลขเล็ก)
        if any(u in tn for u in ("ຊຸດ", "ອັນ", "ຫນວຍ")) or re.search(r"\\b[0-9]{1,2}\\b", tn):
            return True, "sang_with_unit_or_qty", 0.75, "order_word_weak"

    # Thai order (เช่น สั่งแน่/สั่งแด่/สั่งซื้อ)
    if SANG_THAI_NORM in tn:
        if any(x in tn for x in ORDER_THAI_CONTEXT_NORM):
            return True, "sang_thai_with_context", 0.85, "order_word_thai"

    # 4) Fallback: คำว่า “ເອົາ” หรือ “เอา” ที่ตามด้วย unit ชัดเจน
    if "ເອົາ" in tn or "เอา" in tn:
        if any(u in tn for u in ("ຊຸດ", "ຊູດ", "ສຸດ", "ສູດ", "ອັນ", "ຫນວຍ")):
            return True, "take_with_unit", 0.7, "take_unit_only"

    return False, "", 0.0, "no_match"

# ข้อความตอบกลับอัตโนมัติ (Global fallback)
REPLY_COD = "ມີເກັບປາຍທາງເຈົ້າ"

REPLY_ORDER = "ຕ້ອງການສັ່ງຊື້ ພິມເບີໂທ, ບ່ອນສົ່ງ, ຫຼຸ້ນ ແລ້ວເຮົາຈະສົ່ງໃຫ້ເດີ"

REPLY_GENERIC = "ມີຫຍັງຖາມໂລດເດີ ດຽວເຮົາມາຕອບ"

COMMENT_PUBLIC_REPLY = "ສົ່ງລາຍລະອຽດໃຫ້ທາງຂໍ້ຄວາມແລ້ວເດີເຈົ້າ"

# ---------------------------------------------------------------------------
# โหลด Page Tokens
# ---------------------------------------------------------------------------
PAGE_TOKENS = {}
PAGE_NAMES = {}          # page_id -> page_name
PAGE_NAME_TO_ID = {}     # page_name -> page_id
PAGE_SUBSCRIBED_FIELDS = {}
try:
    with open("page_token.json", "r", encoding="utf-8") as f:
        raw = json.load(f)
    pages_list = raw if isinstance(raw, list) else [raw]
    for page in pages_list:
        if page.get("enabled") is False:
            pname_skip = page.get("page_name", page.get("page_id", "?"))
            print(f"⏭️  ข้ามเพจ (enabled=false): {pname_skip}")
            continue
        pid = str(page["page_id"])
        pname = page.get("page_name", pid)
        PAGE_TOKENS[pid] = page["access_token"]
        PAGE_NAMES[pid] = pname
        PAGE_NAME_TO_ID[pname] = pid
        if isinstance(page.get("subscribed_fields"), list):
            PAGE_SUBSCRIBED_FIELDS[pid] = [str(x) for x in page["subscribed_fields"] if x]
        print(f"✅ โหลด Page Token: {pname} ({pid})")
    print(f"📊 โหลดเพจทั้งหมด {len(PAGE_TOKENS)} เพจ")
except FileNotFoundError:
    print("⚠️ ไม่พบไฟล์ page_token.json")
except (KeyError, json.JSONDecodeError) as e:
    print(f"⚠️ อ่าน page_token.json ไม่สำเร็จ: {e}")

# ---------------------------------------------------------------------------
# Helper formatters (page / sender)
# ---------------------------------------------------------------------------

def fmt_page(page_id: str) -> str:
    pid = str(page_id or "")
    name = PAGE_NAMES.get(pid) or "UnknownPage"
    return f"{name} ({pid})" if pid else f"{name} (unknown_id)"


_psid_name_cache: dict = {}         # key: "page_id:psid" -> "First Last" or "" (cached-miss)
_psid_name_cache_legacy: dict = {}  # key: "psid" -> "First Last" or "" (from older versions)
try:
    if os.path.exists(PSID_NAME_CACHE_FILE):
        with open(PSID_NAME_CACHE_FILE, "r", encoding="utf-8") as f:
            _psid_name_cache = json.load(f) or {}
        if not isinstance(_psid_name_cache, dict):
            _psid_name_cache = {}
        # Split legacy vs new keys (new keys contain ":")
        legacy = {}
        new = {}
        for k, v in _psid_name_cache.items():
            if isinstance(k, str) and ":" in k:
                new[k] = v
            else:
                legacy[str(k)] = v
        _psid_name_cache = new
        _psid_name_cache_legacy = legacy
        print(f"📋 โหลด psid_name_cache: {len(_psid_name_cache)} รายการ")
except Exception:
    _psid_name_cache = {}
    _psid_name_cache_legacy = {}


def _sender_cache_key(page_id: str, sender_id: str) -> str:
    return f"{str(page_id or '')}:{str(sender_id or '')}"


def _save_psid_name_cache() -> None:
    """Persist both new+legacy cache keys to disk (backward compatible)."""
    try:
        data = {}
        data.update(_psid_name_cache_legacy)
        data.update(_psid_name_cache)
        with open(PSID_NAME_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _fetch_sender_name(page_id: str, sender_id: str) -> Optional[str]:
    """Best-effort: ดึงชื่อผู้ใช้จาก PSID (อาจ fail ได้ตามสิทธิ์/ข้อจำกัดของ Meta)"""
    token = PAGE_TOKENS.get(str(page_id or ""))
    sid = str(sender_id or "")
    if not token or not sid:
        return None
    try:
        url = f"https://graph.facebook.com/v18.0/{sid}"
        resp = requests.get(
            url,
            params={"fields": "first_name,last_name", "access_token": token},
            timeout=10,
        )
        data = resp.json() if resp.content else {}
        first = (data.get("first_name") or "").strip()
        last = (data.get("last_name") or "").strip()
        name = f"{first} {last}".strip()
        return name or None
    except Exception:
        return None


def fmt_sender(page_id: str, sender_id: str) -> str:
    """รูปแบบ: 'Name (PSID)' ถ้าดึงไม่ได้ → 'PSID'"""
    sid = str(sender_id or "")
    if not sid:
        return "unknown_sender"

    ck = _sender_cache_key(page_id, sid)
    cached = _psid_name_cache.get(ck)
    if cached is not None:
        return f"{cached} ({sid})" if cached else sid

    # Fallback to legacy cache (psid-only) and migrate in-memory to new key
    legacy = _psid_name_cache_legacy.get(sid)
    if legacy is not None:
        try:
            with _file_lock:
                _psid_name_cache[ck] = legacy
                _save_psid_name_cache()
        except Exception:
            pass
        return f"{legacy} ({sid})" if legacy else sid

    name = _fetch_sender_name(page_id, sid)
    try:
        with _file_lock:
            _psid_name_cache[ck] = name or ""
            _save_psid_name_cache()
    except Exception:
        pass
    return f"{name} ({sid})" if name else sid

# ---------------------------------------------------------------------------
# โหลด per-page welcome config
# ---------------------------------------------------------------------------
PAGE_WELCOME_CONFIG = {}   # page_id -> {"welcome_text":..., "price_reply":..., ...}
PAGE_REPLY_GLOBAL = {
    "promo_auto_send_disabled": False,
    "messenger_auto_replies_disabled": False,
    "generic_reply_disabled": False,
}
_TOP_LEVEL_KEYS = {
    "promo_send_after_hours",
    "promo_send_before_hours",
    "promo_auto_send_disabled",
    "messenger_auto_replies_disabled",
    "generic_reply_disabled",
}
try:
    with open("page_reply_config.json", "r", encoding="utf-8") as f:
        _raw_welcome = json.load(f)
    PAGE_REPLY_GLOBAL["promo_auto_send_disabled"] = bool(_raw_welcome.get("promo_auto_send_disabled"))
    PAGE_REPLY_GLOBAL["messenger_auto_replies_disabled"] = bool(
        _raw_welcome.get("messenger_auto_replies_disabled")
    )
    PAGE_REPLY_GLOBAL["generic_reply_disabled"] = bool(
        _raw_welcome.get("generic_reply_disabled")
    )
    for pname, cfg in _raw_welcome.items():
        if pname in _TOP_LEVEL_KEYS:
            continue
        pid = PAGE_NAME_TO_ID.get(pname)
        if pid:
            PAGE_WELCOME_CONFIG[pid] = cfg
            fields = [k for k in cfg if k not in ("welcome_text",)]
            print(f"📋 Page config สำหรับ {fmt_page(pid)} | extra fields: {fields or 'none'}")
        else:
            print(f"⚠️ page_reply_config: ไม่พบเพจ '{pname}' ใน page_token.json")
    print(f"📊 โหลด Page config {len(PAGE_WELCOME_CONFIG)} เพจ")
    if PAGE_REPLY_GLOBAL.get("messenger_auto_replies_disabled"):
        print("⏸️ page_reply_config: messenger_auto_replies_disabled=true → ไม่ส่ง welcome / ตอบราคา-คีย์เวิร์ดอัตโนมัติ")
    if PAGE_REPLY_GLOBAL.get("promo_auto_send_disabled"):
        print("⏸️ page_reply_config: promo_auto_send_disabled=true → สคริปต์ send_promo_within_24h จะไม่ส่งโปรโม")
    if PAGE_REPLY_GLOBAL.get("generic_reply_disabled"):
        print("⏸️ page_reply_config: generic_reply_disabled=true → ไม่ส่ง REPLY_GENERIC")
except FileNotFoundError:
    print("ℹ️ ไม่พบ page_reply_config.json — ใช้ค่า default ทุกเพจ")
except Exception as e:
    print(f"⚠️ อ่าน page_reply_config.json ไม่สำเร็จ: {e}")


def _generic_reply() -> str:
    if PAGE_REPLY_GLOBAL.get("generic_reply_disabled"):
        return ""
    return REPLY_GENERIC


# ---------------------------------------------------------------------------
# Seen senders (ลูกค้าที่เคยได้รับข้อความต้อนรับแล้ว)
# ---------------------------------------------------------------------------
SEEN_SENDERS_FILE = "seen_senders.json"
_seen_senders: dict = {}
try:
    if os.path.exists(SEEN_SENDERS_FILE):
        with open(SEEN_SENDERS_FILE, "r", encoding="utf-8") as f:
            _seen_senders = json.load(f)
        print(f"📋 โหลดรายชื่อลูกค้าที่เคยทัก: {len(_seen_senders)} คน")
except Exception:
    _seen_senders = {}

# ---------------------------------------------------------------------------
# Last message timestamps (สำหรับระบบโปรโมชั่นอัตโนมัติ)
# ---------------------------------------------------------------------------
_last_message: dict = {}
try:
    if os.path.exists(LAST_MESSAGE_FILE):
        with open(LAST_MESSAGE_FILE, "r", encoding="utf-8") as f:
            _last_message = json.load(f)
        print(f"📋 โหลด last_message: {len(_last_message)} รายการ")
except Exception:
    _last_message = {}

# ---------------------------------------------------------------------------
# Phone detected PSIDs (ลูกค้าที่ส่งเบอร์โทร = กำลังจะซื้อ)
# ---------------------------------------------------------------------------
_phone_detected: dict = {}
try:
    if os.path.exists(PHONE_DETECTED_FILE):
        with open(PHONE_DETECTED_FILE, "r", encoding="utf-8") as f:
            _phone_detected = json.load(f)
        print(f"📋 โหลด phone_detected: {len(_phone_detected)} รายการ")
except Exception:
    _phone_detected = {}

# ---------------------------------------------------------------------------
# Lock for file writes from multiple threads
# ---------------------------------------------------------------------------
_file_lock = threading.Lock()


def _mark_seen(page_id: str, sender_id: str) -> None:
    key = f"{page_id}:{sender_id}"
    _seen_senders[key] = int(time.time())
    try:
        with _file_lock:
            with open(SEEN_SENDERS_FILE, "w", encoding="utf-8") as f:
                json.dump(_seen_senders, f, ensure_ascii=False)
    except Exception:
        pass


def _is_seen(page_id: str, sender_id: str) -> bool:
    return f"{page_id}:{sender_id}" in _seen_senders


def _update_last_message(page_id: str, sender_id: str, timestamp_ms) -> None:
    key = f"{page_id}:{sender_id}"
    stored_ts = int(timestamp_ms) if timestamp_ms else int(time.time() * 1000)
    _last_message[key] = stored_ts
    try:
        with _file_lock:
            with open(LAST_MESSAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(_last_message, f, ensure_ascii=False)
    except Exception:
        pass


def _record_phone_detected(page_id: str, sender_id: str, timestamp_ms) -> None:
    key = f"{page_id}:{sender_id}"
    if key in _phone_detected:
        return
    _phone_detected[key] = int(timestamp_ms) if timestamp_ms else int(time.time() * 1000)
    try:
        with _file_lock:
            with open(PHONE_DETECTED_FILE, "w", encoding="utf-8") as f:
                json.dump(_phone_detected, f, ensure_ascii=False)
    except Exception:
        pass


def _subscribe_one_page(page_id: str, token: str):
    try:
        url = f"https://graph.facebook.com/v18.0/{page_id}/subscribed_apps"
        fields = PAGE_SUBSCRIBED_FIELDS.get(page_id)
        if not fields:
            fields = []
            if ENABLE_FEED:
                fields.append("feed")
            if ENABLE_MESSAGING:
                fields.extend(["messages", "messaging_postbacks", "message_echoes"])
        elif ENABLE_MESSAGING and "message_echoes" not in fields:
            fields = list(fields) + ["message_echoes"]
        subscribed_fields = ",".join(dict.fromkeys(fields))
        r = requests.post(
            url,
            data={"subscribed_fields": subscribed_fields, "access_token": token},
            timeout=10,
        )
        data = r.json()
        if data.get("success"):
            return True, page_id, subscribed_fields, None
        return False, page_id, subscribed_fields, data
    except Exception as e:
        return False, page_id, "", str(e)


def subscribe_pages_webhooks() -> None:
    """สมัครรับ webhook สำหรับแต่ละเพจ"""
    items = list(PAGE_TOKENS.items())
    if not items:
        return

    max_workers = min(10, max(1, len(items)))
    ok = 0
    fail = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_subscribe_one_page, page_id, token) for page_id, token in items]
        for fut in as_completed(futures):
            success, page_id, subscribed_fields, err = fut.result()
            if success:
                ok += 1
                print(f"✅ เพจ {fmt_page(page_id)} สมัคร webhook แล้ว: {subscribed_fields}")
            else:
                fail += 1
                print(f"⚠️ เพจ {fmt_page(page_id)} สมัคร webhook ไม่สำเร็จ: {err}")
    print(f"📌 สมัคร webhook เสร็จแล้ว: สำเร็จ {ok} | ไม่สำเร็จ {fail}")


# ---------------------------------------------------------------------------
# ฟังก์ชันที่เคยเป็น method ของ WebhookHandler — ย้ายมาเป็น module-level
# เพื่อให้ worker thread เรียกได้โดยไม่ต้องอ้าง self (ที่ผูกกับ HTTP connection)
# ---------------------------------------------------------------------------

def _extract_order_id(text: str) -> Optional[str]:
    if not text or "Order:" not in text and "Order：" not in text:
        return None
    m = re.search(r"Order\s*[：:]\s*(\S+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def generate_response(user_message: str, page_id: str = "") -> str:
    """สร้างข้อความตอบกลับตามคำที่ลูกค้าพิมพ์ (per-page → global fallback → generic คงที่)"""
    t = (user_message or "").strip()
    tl = t.lower()
    cfg = PAGE_WELCOME_CONFIG.get(page_id, {})

    if any(k in t for k in ("ปลายทาง", "เก็บปลายทาง", "เก็บปลายทางค่ะ", "cod")):
        return cfg.get("cod_reply", REPLY_COD)

    matched_order, reason, score, method = is_order_intent(t)
    if matched_order:
        print(f"   🛒 ตรวจพบคำสั่งซื้อ: reason='{reason}' score={score:.2f} method={method}")
        return cfg.get("order_reply", REPLY_ORDER)

    matched, best_kw, score, method = is_price_question(t)
    if matched:
        print(f"   💰 ตรวจพบคำถามราคา: keyword='{best_kw}' score={score:.2f} method={method}")
        price = cfg.get("price_reply")
        if price:
            return price
        return _generic_reply()

    if method == "near_miss":
        print(f"   🔍 [price_debug] near-miss: text='{t[:80]}' best='{best_kw}' score={score:.2f}")

    return _generic_reply()


def send_message(page_id: str, recipient_id: str, message_text: str,
                 image_url: Optional[str] = None, image_attachment_id: Optional[str] = None):
    """ส่งข้อความไปยังผู้ใช้"""
    page_token = PAGE_TOKENS.get(page_id)
    if not page_token:
        print(f"   ⚠️ ไม่พบ Page Token สำหรับเพจ {fmt_page(page_id)}")
        return

    url = f"https://graph.facebook.com/v18.0/{page_id}/messages"
    if message_text:
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message_text},
            "access_token": page_token
        }
        try:
            response = requests.post(url, json=payload)
            result = response.json()
            if "recipient_id" in result:
                print(f"   ✅ ส่งข้อความตอบกลับสำเร็จ!")
            else:
                print(f"   ❌ ไม่สามารถส่งข้อความได้: {result}")
        except Exception as e:
            print(f"   ❌ เกิดข้อผิดพลาด: {e}")

    if image_attachment_id:
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"attachment_id": image_attachment_id}
                }
            },
            "access_token": page_token
        }
        try:
            response = requests.post(url, json=payload)
            result = response.json()
            if "recipient_id" in result:
                print(f"   ✅ ส่งรูปสำเร็จ!")
            else:
                print(f"   ❌ ไม่สามารถส่งรูปได้: {result}")
        except Exception as e:
            print(f"   ❌ เกิดข้อผิดพลาดในการส่งรูป: {e}")
    elif image_url:
        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": image_url, "is_reusable": True}
                }
            },
            "access_token": page_token
        }
        try:
            response = requests.post(url, json=payload)
            result = response.json()
            if "recipient_id" in result:
                print(f"   ✅ ส่งรูปสำเร็จ!")
            else:
                print(f"   ❌ ไม่สามารถส่งรูปได้: {result}")
        except Exception as e:
            print(f"   ❌ เกิดข้อผิดพลาดในการส่งรูป: {e}")


def _messenger_auto_replies_disabled_for_page(page_id: str) -> bool:
    """ปิดข้อความอัตโนมัติจาก Messenger (welcome, ราคา, COD, ฯลฯ) — ระดับ root หรือต่อเพจใน page_reply_config.json"""
    if PAGE_REPLY_GLOBAL.get("messenger_auto_replies_disabled"):
        return True
    cfg = PAGE_WELCOME_CONFIG.get(page_id) or {}
    return bool(cfg.get("messenger_auto_replies_disabled"))


def _handle_feed_comment(page_id: str, comment_id: str, comment_message: str) -> None:
    """เมื่อมีคนคอมเมนต์บนโพสต์: ส่ง Private Reply + ตอบสาธารณะ"""
    page_token = PAGE_TOKENS.get(page_id)
    if not page_token:
        print(f"   ⚠️ [Comment] ไม่พบ Page Token สำหรับเพจ {fmt_page(page_id)}")
        return
    print(f"\n💬 รับคอมเมนต์บนโพสต์:")
    print(f"   Page: {fmt_page(page_id)} | Comment ID: {comment_id}")
    print(f"   ข้อความ: {comment_message[:80]}{'...' if len(comment_message) > 80 else ''}")
    url_private = f"https://graph.facebook.com/v24.0/{comment_id}/private_replies"
    if _messenger_auto_replies_disabled_for_page(page_id):
        print(f"   ⏸️ ข้าม Private Reply (messenger_auto_replies_disabled)")
    else:
        try:
            private_text = _get_welcome_text(page_id)
            resp = requests.post(url_private, data={"message": private_text, "access_token": page_token}, timeout=15)
            result = resp.json()
            if "id" in result or resp.status_code == 200:
                print(f"   ✅ ส่ง Private Reply ไป Messenger แล้ว (ดึงลูกค้าเข้าแชท)")
            else:
                print(f"   ❌ Private Reply ไม่สำเร็จ: {result}")
        except Exception as e:
            print(f"   ❌ Private Reply ผิดพลาด: {e}")
    url_public = f"https://graph.facebook.com/v24.0/{comment_id}/comments"
    try:
        resp = requests.post(url_public, data={"message": COMMENT_PUBLIC_REPLY, "access_token": page_token}, timeout=15)
        result = resp.json()
        if "id" in result or resp.status_code == 200:
            print(f"   ✅ ตอบคอมเมนต์แบบสาธารณะแล้ว")
        else:
            print(f"   ❌ ตอบสาธารณะไม่สำเร็จ: {result}")
    except Exception as e:
        print(f"   ❌ ตอบสาธารณะผิดพลาด: {e}")


def _get_welcome_text(page_id: str) -> str:
    """ดึงข้อความ welcome เฉพาะเพจ; ถ้าไม่มี key welcome_text → generic คงที่; ถ้า welcome_text เป็น \"\" โดยตั้งใจ → ไม่ส่งข้อความ (ส่งเฉพาะสื่อได้)"""
    cfg = PAGE_WELCOME_CONFIG.get(page_id)
    if cfg and "welcome_text" in cfg:
        wt = cfg["welcome_text"]
        if wt is not None:
            s = str(wt).strip()
            if s == "":
                return ""
            return str(wt)
    print(f"   ⚠️ ไม่มี welcome_text สำหรับเพจ {fmt_page(page_id)} → ใช้ข้อความ generic")
    return _generic_reply()


def send_welcome_bundle(page_id: str, recipient_id: str) -> None:
    """
    ส่งชุดต้อนรับ: ข้อความ (ถ้ามี) แล้วรูปแต่ละไฟล์ แล้ววิดีโอแต่ละไฟล์ (Messenger ส่งทีละ attachment)
    สื่อมาจาก product_images/<PageName>/ เท่านั้น
    """
    page_token = PAGE_TOKENS.get(page_id)
    if not page_token:
        print(f"   ⚠️ ไม่พบ Page Token สำหรับเพจ {fmt_page(page_id)}")
        return
    page_name = PAGE_NAMES.get(page_id) or ""
    if not page_name:
        print(f"   ⚠️ ไม่พบชื่อเพจสำหรับ page_id={page_id} — ข้ามการสแกนโฟลเดอร์สื่อ")

    if _messenger_auto_replies_disabled_for_page(page_id):
        print(f"   ⏸️ messenger_auto_replies_disabled — ข้าม welcome (ข้อความ+สื่อ)")
        return

    paths = discover_page_media_ordered(PRODUCT_IMAGES_DIR, page_name)

    response_text = _get_welcome_text(page_id)
    if response_text:
        send_text_message(page_id, page_token, recipient_id, response_text)
        time.sleep(WELCOME_SEND_DELAY)

    if paths:
        send_media_paths_ordered(
            page_id,
            page_token,
            recipient_id,
            paths,
            send_delay=WELCOME_SEND_DELAY,
            log_prefix="Welcome ",
        )
    elif not response_text:
        print(f"   ⚠️ ไม่มีข้อความต้อนรับและไม่มีสื่อ — ไม่ส่งอะไร")


def _get_price_reply_text(page_id: str) -> str:
    cfg = PAGE_WELCOME_CONFIG.get(page_id) or {}
    price = cfg.get("price_reply")
    if price is not None and str(price).strip():
        return str(price)
    return _generic_reply()


def send_price_reply_bundle(page_id: str, recipient_id: str, user_message: str) -> bool:
    """ตอบคำถามราคา: ข้อความ price_reply + สื่อจาก price_images/<เพจ>/"""
    matched, best_kw, score, method = is_price_question(user_message or "")
    if not matched:
        return False

    page_token = PAGE_TOKENS.get(page_id)
    if not page_token:
        print(f"   ⚠️ ไม่พบ Page Token สำหรับเพจ {fmt_page(page_id)}")
        return False

    print(f"   💰 ตรวจพบคำถามราคา: keyword='{best_kw}' score={score:.2f} method={method}")
    page_name = PAGE_NAMES.get(page_id) or ""
    response_text = _get_price_reply_text(page_id)
    if response_text:
        send_text_message(page_id, page_token, recipient_id, response_text)
        time.sleep(WELCOME_SEND_DELAY)

    paths = discover_page_media_ordered(PRICE_IMAGES_DIR, page_name)
    if paths:
        send_media_paths_ordered(
            page_id,
            page_token,
            recipient_id,
            paths,
            send_delay=WELCOME_SEND_DELAY,
            log_prefix="Price ",
        )
    elif not response_text:
        print(f"   ⚠️ ไม่มี price_reply และไม่มีสื่อ — ไม่ส่งอะไร")
    return True


def _handle_ad_postback_or_referral(event: dict) -> None:
    """Click-to-Messenger / ปุ่ม Get Started มักส่ง postback หรือ referral โดยไม่มี key message — เดิมถูกข้ามทั้งก้อน"""
    sender_id = event["sender"]["id"]
    recipient_id = event["recipient"]["id"]
    cur_page_id = str(recipient_id)
    event_timestamp = event.get("timestamp")
    if _is_seen(cur_page_id, sender_id):
        print(f"   ⏭️ postback/referral — ข้าม (PSID รับ welcome แล้ว)")
        return
    pb = event.get("postback") or {}
    ref = event.get("referral") or {}
    print(f"\n📨 รับ postback/referral (โฆษณา/ปุ่มเริ่มต้น — ไม่มี key message):")
    print(f"   Page: {fmt_page(cur_page_id)}")
    print(f"   Sender: {fmt_sender(cur_page_id, sender_id)}")
    if pb:
        print(f"   postback title={pb.get('title', '')!r} payload={str(pb.get('payload', ''))[:120]}")
    if ref:
        print(f"   referral source={ref.get('source')} type={ref.get('type')} ref={str(ref.get('ref', ''))[:80]}")
    _update_last_message(cur_page_id, sender_id, event_timestamp)
    _mark_seen(cur_page_id, sender_id)
    if _messenger_auto_replies_disabled_for_page(cur_page_id):
        print(f"   ⏸️ messenger_auto_replies_disabled — ข้าม welcome (postback/referral)")
        return
    print(f"   🆕 ลูกค้าใหม่ → ส่ง Welcome + สื่อ (Graph API)")
    send_welcome_bundle(cur_page_id, sender_id)


# ---------------------------------------------------------------------------
# Worker thread: ประมวลผล webhook body หลังจากตอบ 200 แล้ว
# ---------------------------------------------------------------------------

def _process_webhook_body(body: dict) -> None:
    """ประมวลผล webhook payload ใน background thread"""
    try:
        if body.get("object") != "page":
            return
        for entry in body.get("entry", []):
            page_id = entry.get("id", "")
            changes = entry.get("changes", [])
            messaging_events = entry.get("messaging", [])

            if changes:
                print(f"   Entry page={fmt_page(page_id)} | changes={len(changes)}")
            if messaging_events:
                print(f"   Entry page={fmt_page(page_id)} | messaging={len(messaging_events)} (ข้อความแชท)")
            if not changes and not messaging_events:
                print(f"   Entry page={fmt_page(page_id)} | keys={list(entry.keys())}")

            # --- Feed ---
            if ENABLE_FEED:
                for change in changes:
                    fld = change.get("field")
                    if fld != "feed":
                        print(f"   Change field={fld} (ข้าม)")
                        continue
                    value = change.get("value") or {}
                    item = value.get("item")
                    verb = value.get("verb")
                    print(f"   Feed change: item={item} verb={verb} | value keys={list(value.keys())}")
                    if item != "comment":
                        continue
                    if verb not in ("add", None):
                        continue
                    comment_id = value.get("comment_id")
                    comment_message = (value.get("message") or "").strip()
                    if comment_message == COMMENT_PUBLIC_REPLY:
                        print(f"   ⏭️ ข้าม: เป็นคำตอบของบอทเอง")
                        continue
                    from_info = value.get("from") or {}
                    commenter_id = str(from_info.get("id") or "")
                    if commenter_id == str(page_id):
                        print(f"   ⏭️ ข้าม: คอมเมนต์จากเพจเอง (กันลูป)")
                        continue
                    if (not page_id or str(page_id) == "0") and value.get("post_id"):
                        pid = str(value.get("post_id", "")).split("_")
                        if pid:
                            page_id = pid[0]
                    if comment_id and page_id and str(page_id) != "0":
                        _handle_feed_comment(str(page_id), comment_id, comment_message)
            elif changes:
                print("   ⏭️ ENABLE_FEED=0 → ข้ามการตอบคอมเมนต์/feed (เก็บโค้ดไว้ใช้ทีหลัง)")

            if not ENABLE_MESSAGING and messaging_events:
                print("   ⏭️ ENABLE_MESSAGING=0 → ข้ามการตอบข้อความ Messenger")

            # --- Messaging ---
            for event in (messaging_events if ENABLE_MESSAGING else []):
                if "message" not in event:
                    if "postback" in event or "referral" in event:
                        _handle_ad_postback_or_referral(event)
                    continue
                msg = event["message"]
                message_text = (msg.get("text") or "").strip()
                sender_id = event["sender"]["id"]
                recipient_id = event["recipient"]["id"]
                cur_page_id = str(recipient_id)
                event_timestamp = event.get("timestamp")

                # message_echo
                if msg.get("is_echo"):
                    customer_psid = recipient_id
                    echo_page_id = sender_id
                    order_id = _extract_order_id(message_text)
                    if order_id:
                        try:
                            with _file_lock:
                                by_order = {}
                                if os.path.exists(ORDER_PSID_FILE):
                                    with open(ORDER_PSID_FILE, "r", encoding="utf-8") as f:
                                        data = json.load(f)
                                        by_order = data.get("by_order", {})
                                by_order[str(order_id).strip()] = {
                                    "psid": customer_psid,
                                    "page_id": echo_page_id,
                                }
                                with open(ORDER_PSID_FILE, "w", encoding="utf-8") as f:
                                    json.dump({"by_order": by_order}, f, ensure_ascii=False, indent=2)
                            print(f"\n📨 [Echo] บันทึก Order {order_id} → PSID {customer_psid} (Page {fmt_page(echo_page_id)})")
                        except Exception as e:
                            print(f"   ❌ บันทึก Order→PSID ล้มเหลว: {e}")
                    continue

                # ลูกค้าทักครั้งแรกด้วยรูป/สติกเกอร์โดยไม่มีข้อความ — เดิม skip ทำให้ไม่ได้รับ welcome
                attachment_only_first = bool(msg.get("attachments")) and not message_text and not _is_seen(
                    cur_page_id, sender_id
                )
                if not message_text and not attachment_only_first:
                    continue

                print(f"\n📨 รับข้อความ:")
                print(f"   Page: {fmt_page(cur_page_id)}")
                print(f"   Sender: {fmt_sender(cur_page_id, sender_id)}")
                print(f"   ข้อความ: {message_text or '(ไม่มีข้อความ — อาจแนบรูป/สติกเกอร์เท่านั้น)'}")

                # บันทึก last message timestamp
                _update_last_message(cur_page_id, sender_id, event_timestamp)

                # ตรวจจับเบอร์โทร
                if PHONE_REGEX.search(message_text):
                    _record_phone_detected(cur_page_id, sender_id, event_timestamp)
                    print(f"   📞 ตรวจพบเบอร์โทร → บันทึก phone_detected")

                seen_before = _is_seen(cur_page_id, sender_id)
                auto_off = _messenger_auto_replies_disabled_for_page(cur_page_id)
                if not seen_before:
                    _mark_seen(cur_page_id, sender_id)
                    if auto_off:
                        print(f"   ⏸️ messenger_auto_replies_disabled — ข้าม welcome/สื่อ (ข้อความแรก)")
                    else:
                        print(f"   🆕 ลูกค้าใหม่ → ส่ง Welcome + สื่อ (Graph API)")
                        send_welcome_bundle(cur_page_id, sender_id)
                else:
                    if auto_off:
                        print(f"   ⏸️ messenger_auto_replies_disabled — ข้ามตอบราคา/คีย์เวิร์ดอัตโนมัติ")
                    elif send_price_reply_bundle(cur_page_id, sender_id, message_text):
                        pass
                    else:
                        response_text = generate_response(message_text, cur_page_id)
                        send_message(cur_page_id, sender_id, response_text)

    except Exception as e:
        print(f"❌ Error in worker thread: {e}")


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/webhook"):
            parsed_path = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_path.query)

            mode = query_params.get("hub.mode", [None])[0]
            token = query_params.get("hub.verify_token", [None])[0]
            challenge = query_params.get("hub.challenge", [None])[0]

            print(f"\n🔍 Webhook Verification Request:")
            print(f"   Path: {self.path}")
            print(f"   Mode: {mode}")
            print(f"   Token: {token}")
            print(f"   Expected Token: {VERIFY_TOKEN}")
            print(f"   Challenge: {challenge}")

            if mode == "subscribe" and token == VERIFY_TOKEN:
                print("✅ Webhook verified! Returning challenge...")
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.send_header("Content-Length", str(len(challenge.encode())))
                self.end_headers()
                self.wfile.write(challenge.encode())
                return
            else:
                print(f"❌ Verification failed!")
                print(f"   Mode match: {mode == 'subscribe'}")
                print(f"   Token match: {token == VERIFY_TOKEN}")
                self.send_response(403)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Forbidden")
                return

        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.rstrip("/") == "/robots.txt":
            robots = (
                "User-agent: *\n"
                "Disallow: /webhook\n"
                "User-agent: facebookexternalhit\n"
                "Allow: /image/\n"
                "User-agent: Facebot\n"
                "Allow: /image/\n"
            )
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(robots.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(robots.encode("utf-8"))
            except BrokenPipeError:
                pass
            return

        try:
            self.send_response(404)
            self.end_headers()
        except BrokenPipeError:
            pass

    def do_POST(self):
        if self.path == "/webhook":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)

            try:
                body = json.loads(post_data.decode("utf-8"))
                obj = body.get("object", "")
                entries = body.get("entry", [])
                print(f"\n🔔 Webhook POST received | object={obj} | entries={len(entries)}")
            except Exception as e:
                print(f"❌ Error parsing webhook body: {e}")
                self.send_response(400)
                self.end_headers()
                return

            # ตอบ 200 ทันที เพื่อไม่ให้ Facebook timeout
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())

            # ประมวลผลใน background thread
            threading.Thread(target=_process_webhook_body, args=(body,), daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


# ---------------------------------------------------------------------------
# Promo Scheduler — รัน send_promo_within_24h.py อัตโนมัติทุก 30 นาที
# ---------------------------------------------------------------------------
PROMO_INTERVAL_MINUTES = 30


def _promo_scheduler_loop():
    """Background daemon thread: รัน send_promo_within_24h.py ทุก PROMO_INTERVAL_MINUTES นาที"""
    promo_script = os.path.join(SCRIPT_DIR, "send_promo_within_24h.py")
    if not os.path.exists(promo_script):
        print(f"⚠️ [Promo] ไม่พบ send_promo_within_24h.py — ระบบโปรโมชั่นไม่ทำงาน", flush=True)
        return

    print(
        f"⏱️ [Promo] ระบบโปรโมชั่นเริ่มแล้ว — รันทันที จากนั้นทุก {PROMO_INTERVAL_MINUTES} นาที",
        flush=True,
    )

    while True:
        try:
            print(f"\n🔄 [Promo] กำลังรัน send_promo_within_24h.py...", flush=True)
            result = subprocess.run(
                [sys.executable, promo_script],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
            )
            if result.stdout:
                for line in result.stdout.splitlines():
                    print(f"  {line}", flush=True)
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip():
                        print(f"  ⚠️ [Promo:err] {line}", flush=True)
        except subprocess.TimeoutExpired:
            print("⚠️ [Promo] หมดเวลา (120 วินาที) — ข้ามรอบนี้", flush=True)
        except Exception as e:
            print(f"⚠️ [Promo] เกิดข้อผิดพลาด: {e}", flush=True)

        time.sleep(PROMO_INTERVAL_MINUTES * 60)


def run_server(port=5000):
    server_address = ("", port)
    httpd = HTTPServer(server_address, WebhookHandler)
    print("=" * 60)
    print("Facebook Messenger Webhook Server")
    print("=" * 60)
    print(f"\n✅ Webhook URL: http://localhost:{port}/webhook")
    print(f"✅ Verify Token: {VERIFY_TOKEN}")
    if PAGE_WELCOME_CONFIG:
        print(f"✅ Per-page welcome config: {len(PAGE_WELCOME_CONFIG)} เพจ")
    if PAGE_TOKENS:
        enabled = []
        if ENABLE_MESSAGING:
            enabled.append("messages/messaging_postbacks")
        if ENABLE_FEED:
            enabled.append("feed")
        print(f"\n📌 สมัครรับ webhook สำหรับเพจ... ({', '.join(enabled) if enabled else 'none'})")
        subscribe_pages_webhooks()
        print("   💡 ถ้าส่งแชทแล้วบอทไม่ตอบ: ใน App Dashboard → Webhooks → Page ต้องติ๊ก 'messages' ด้วย")
    print(f"\n🚀 Server กำลังทำงานที่ port {port}")
    print("=" * 60)

    # เริ่ม promo scheduler อัตโนมัติ (daemon thread — หยุดเมื่อ server หยุด)
    promo_thread = threading.Thread(target=_promo_scheduler_loop, daemon=True, name="PromoScheduler")
    promo_thread.start()
    # พิมพ์บน main thread เพื่อให้เห็นใน launcher (PIPE) แม้ thread ยังไม่ flush
    print(
        f"✅ [Promo] เปิดตารางโปรโมแล้ว — รันสคริปต์ทุก {PROMO_INTERVAL_MINUTES} นาที (ดูบรรทัด ⏱️/🔄 ด้านล่าง)",
        flush=True,
    )

    httpd.serve_forever()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    run_server(port)
