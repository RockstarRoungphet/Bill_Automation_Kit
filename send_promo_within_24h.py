#!/usr/bin/env python3
"""
ส่งข้อความโปรโมชั่นอัตโนมัติให้ลูกค้าที่ทักมาภายใน 24 ชม. แต่ยังไม่ซื้อ

ใช้ร่วมกับ messenger_webhook_server.py ที่บันทึก:
  - last_message_by_psid.json  (เวลาข้อความล่าสุดของลูกค้า)
  - phone_detected_psid.json   (ลูกค้าที่ส่งเบอร์โทร = กำลังจะซื้อ)
  - order_psid.json             (ลูกค้าที่มี Order ID = ซื้อแล้ว)

รันด้วย cron / Task Scheduler ทุก 30 นาที:
  Linux:   */30 * * * * cd /path/to/project && .venv/bin/python send_promo_within_24h.py
  Windows: Task Scheduler → .venv\\Scripts\\python.exe send_promo_within_24h.py
"""

import json
import os
import sys
import time
from datetime import datetime

import requests

from graph_media_send import discover_page_media_ordered, send_media_paths_ordered

LAST_MESSAGE_FILE = "last_message_by_psid.json"
ORDER_PSID_FILE = "order_psid.json"
PHONE_DETECTED_FILE = "phone_detected_psid.json"
PAGE_TOKEN_FILE = "page_token.json"
PAGE_CONFIG_FILE = "page_reply_config.json"
LAST_PROMO_SENT_FILE = "last_promo_sent.json"
PROMO_IMAGE_DIR = "promo_images"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

SEND_DELAY = float(os.getenv("PROMO_SEND_DELAY", "0.8"))

def load_json(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ อ่าน {path} ไม่ได้: {e}")
        return default if default is not None else {}


def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ เขียน {path} ไม่ได้: {e}")


def load_page_tokens():
    """โหลด page tokens และสร้าง mapping page_name -> page_id"""
    raw = load_json(PAGE_TOKEN_FILE, default=[])
    pages = raw if isinstance(raw, list) else [raw]
    tokens = {}       # page_id -> access_token
    name_to_id = {}   # page_name -> page_id
    for page in pages:
        if page.get("enabled") is False:
            continue
        pid = str(page.get("page_id", ""))
        pname = page.get("page_name", pid)
        tok = page.get("access_token", "")
        if pid and tok:
            tokens[pid] = tok
            name_to_id[pname] = pid
    return tokens, name_to_id


def build_bought_psids(order_psid_data: dict, phone_detected: dict, last_message: dict | None = None) -> set:
    """
    สร้าง set ของ "page_id:psid" ที่ถือว่าซื้อแล้ว

    รองรับ order_psid.json ทั้ง format เก่า/ใหม่:
    - by_order[order_id] = {"psid": "...", "page_id": "..."}  (dict)
    - by_order[order_id] = "PSID"                             (string; ไม่มี page_id → best-effort จาก last_message)
    """
    bought: set = set()
    psid_only: set = set()

    by_order = {}
    if isinstance(order_psid_data, dict):
        by_order = order_psid_data.get("by_order", {}) or {}

    for _order_id, info in by_order.items():
        if isinstance(info, dict):
            psid = str(info.get("psid", "")).strip()
            page_id = str(info.get("page_id", "")).strip()
            if psid and page_id:
                bought.add(f"{page_id}:{psid}")
            elif psid:
                psid_only.add(psid)
        elif isinstance(info, str):
            psid = info.strip()
            if psid:
                psid_only.add(psid)

    # phone_detected เก็บ key เป็น "page_id:psid" อยู่แล้ว
    if isinstance(phone_detected, dict):
        for key in phone_detected:
            bought.add(str(key))

    # กรณี order_psid เป็น string ไม่มี page_id → หา page_id จาก last_message
    if last_message and psid_only:
        for key in last_message.keys():
            if not isinstance(key, str) or ":" not in key:
                continue
            _pid, _psid = key.split(":", 1)
            if _psid in psid_only:
                bought.add(key)

    return bought


def send_promo_message(
    page_id: str,
    access_token: str,
    psid: str,
    text: str,
    media_paths: list | None = None,
) -> bool:
    """ส่งข้อความโปรโมชั่น แล้วส่งรูป/วิดีโอทีละไฟล์ตามลำดับ (Graph API — อยู่ใน 24 ชม.)"""
    media_paths = media_paths or []

    url = f"https://graph.facebook.com/v18.0/{page_id}/messages"
    payload_text = {
        "recipient": {"id": psid},
        "message": {"text": text},
        "access_token": access_token,
    }
    try:
        resp = requests.post(url, json=payload_text, timeout=15)
        result = resp.json()
        if "recipient_id" in result and "message_id" in result:
            ok_text = True
        else:
            error = result.get("error", {})
            code = error.get("code", 0)
            # 551 = outside 24h window, 10 = policy/auth/permission related in this flow
            if code in (551, 10):
                print(f"   ⚠️ ส่งไม่ได้ (code={code}): {error.get('message', '')[:80]}")
            else:
                print(f"   ❌ ส่งไม่สำเร็จ: {result}")
            ok_text = False

    except Exception as e:
        print(f"   ❌ เกิดข้อผิดพลาด: {e}")
        return False

    if not ok_text:
        return False

    if media_paths:
        time.sleep(SEND_DELAY)
        send_media_paths_ordered(
            page_id,
            access_token,
            psid,
            media_paths,
            send_delay=SEND_DELAY,
            log_prefix="Promo ",
        )

    return ok_text


def main():
    now_ms = int(time.time() * 1000)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"🔄 send_promo_within_24h.py — {now_str}")
    print(f"{'='*60}")

    # โหลดข้อมูลทั้งหมด
    last_message = load_json(LAST_MESSAGE_FILE)
    order_psid = load_json(ORDER_PSID_FILE)
    phone_detected = load_json(PHONE_DETECTED_FILE)
    last_promo_sent = load_json(LAST_PROMO_SENT_FILE)
    page_config = load_json(PAGE_CONFIG_FILE)
    tokens, name_to_id = load_page_tokens()

    if not tokens:
        print("❌ ไม่มี page tokens — ออก")
        return
    if not page_config:
        print("❌ ไม่มี page_reply_config.json — ออก")
        return
    if page_config.get("promo_auto_send_disabled"):
        print("⏸️ page_reply_config.json: promo_auto_send_disabled=true — ไม่ส่งโปรโมอัตโนมัติ (ออก)")
        return
    if not last_message:
        print("ℹ️ ไม่มี last_message_by_psid.json (ยังไม่มีข้อมูล) — ออก")
        return

    after_hours = page_config.get("promo_send_after_hours", 6)
    before_hours = page_config.get("promo_send_before_hours", 23)
    _top_level_keys = {
        "promo_send_after_hours",
        "promo_send_before_hours",
        "promo_auto_send_disabled",
        "messenger_auto_replies_disabled",
        "generic_reply_disabled",
    }

    pages_promo = {}
    for pname, cfg in page_config.items():
        if pname in _top_level_keys:
            continue
        if not isinstance(cfg, dict):
            continue
        if cfg.get("promo_auto_send_disabled"):
            continue
        if cfg.get("promo_text"):
            pages_promo[pname] = cfg["promo_text"]

    if not pages_promo:
        print("ℹ️ ไม่มีเพจที่มี promo_text ใน config — ออก")
        return

    after_ms = after_hours * 3600 * 1000
    before_ms = before_hours * 3600 * 1000
    promo_cooldown_ms = 24 * 3600 * 1000


    bought_set = build_bought_psids(order_psid, phone_detected, last_message=last_message)

    print(f"📊 last_message: {len(last_message)} รายการ | bought: {len(bought_set)} | last_promo: {len(last_promo_sent)}")
    print(f"⏰ ส่งโปรโมเมื่อ last_message อยู่ในช่วง {after_hours}-{before_hours} ชม. ที่ผ่านมา")
    print(f"📋 เพจที่มีโปรโม: {list(pages_promo.keys())}")

    total_sent = 0
    total_skipped = 0

    promo_dir_base = os.path.join(SCRIPT_DIR, PROMO_IMAGE_DIR)

    for page_name, promo_text in pages_promo.items():
        promo_paths = discover_page_media_ordered(promo_dir_base, page_name)

        if not promo_text:
            print(f"\n⚠️ ไม่มีข้อความโปรโมชั่นสำหรับ '{page_name}' — ข้าม")
            continue

        page_id = name_to_id.get(page_name)
        if not page_id:
            print(f"\n⚠️ ไม่พบ page_id สำหรับ '{page_name}' — ข้าม")
            continue
        access_token = tokens.get(page_id)
        if not access_token:
            print(f"\n⚠️ ไม่พบ token สำหรับ '{page_name}' (ID: {page_id}) — ข้าม")
            continue

        eligible = []
        for key, ts in last_message.items():
            if not key.startswith(f"{page_id}:"):
                continue
            try:
                ts_int = int(ts)
            except Exception:
                continue
            age_ms = now_ms - ts_int
            if age_ms < after_ms:
                continue
            if age_ms > before_ms:
                continue
            if key in bought_set:
                continue
            if key in last_promo_sent:
                try:
                    promo_age = now_ms - int(last_promo_sent[key])
                except Exception:
                    promo_age = None
                if promo_age is not None and promo_age < promo_cooldown_ms:
                    continue
            psid = key.split(":", 1)[1]
            eligible.append(psid)

        if not eligible:
            print(f"\n📋 {page_name}: ไม่มีลูกค้าที่ต้องส่งโปรโม")
            continue

        n_media = len(promo_paths)
        media_desc = f"สื่อ {n_media} ไฟล์" if n_media else "ไม่มีสื่อ"
        print(f"\n📋 {page_name}: ส่งโปรโมให้ {len(eligible)} คน ({media_desc})")
        sent = 0
        for psid in eligible:
            ok = send_promo_message(
                page_id,
                access_token,
                psid,
                promo_text,
                media_paths=promo_paths,
            )
            if ok:
                last_promo_sent[f"{page_id}:{psid}"] = now_ms
                sent += 1
                print(f"   ✅ {psid}")
            else:
                total_skipped += 1
            time.sleep(SEND_DELAY)
        total_sent += sent
        print(f"   → ส่งสำเร็จ {sent}/{len(eligible)}")

    save_json(LAST_PROMO_SENT_FILE, last_promo_sent)

    print(f"\n{'='*60}")
    print(f"✅ เสร็จสิ้น: ส่งสำเร็จ {total_sent} | ส่งไม่ได้ {total_skipped}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
