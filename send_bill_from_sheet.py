#!/usr/bin/env python3
"""
ส่งบิลพัสดุจาก Google Sheet (หรือ CSV) ไป Messenger ตาม Order ID
- รองรับหลายเพจ (โหลด token จาก page_token.json array)
- จับคู่เพจจากชื่อเพจใน Column I ของ Sheet
- ใช้ Order→PSID จาก order_psid.json
- หลังส่งสำเร็จ อัปเดตวันที่ส่งใน Column R ของ Google Sheet

ใช้:
  python3 send_bill_from_sheet.py --sheet [--bills-dir bill_images] [--dry-run]
  python3 send_bill_from_sheet.py --csv <path_to_csv> [--bills-dir bill_images] [--dry-run]
  python3 send_bill_from_sheet.py --sheet --notify-delivered [--dry-run]
    (โหมด notify: คอลัมน์ A = 🏁ຮອດປາຍທາງແລ້ວ ຫຼື 💬ແຈ້ງຮອດແລ້ວ)
"""

import csv
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

# ข้อความลูกค้า + ลิงก์บิลตามขนส่ง — แหล่งเดียวกับ no_api_send_bill/scripts/bill_carrier_links.py
_SCRIPT_DIR_FOR_LINKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no_api_send_bill", "scripts")
if _SCRIPT_DIR_FOR_LINKS not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR_FOR_LINKS)
from bill_carrier_links import bill_tracking_customer_message  # noqa: E402

TOKEN_FILE = "page_token.json"
ORDER_PSID_FILE = "order_psid.json"
GRAPH_API_VERSION = "v25.0"
DEFAULT_BILLS_DIR = "bill_images"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHEET_CONFIG_PATH = os.path.join(SCRIPT_DIR, "no_api_send_bill", "config", "sheet_config.json")
DEFAULT_CREDENTIALS_PATH = os.path.join(SCRIPT_DIR, "no_api_send_bill", "config", "google_credentials.json")

# Column indices (0-based) matching the Google Sheet layout
STATUS_COL = 0       # A: สถานะ
ORDER_COL = 3        # D: Order ID
PAGE_NAME_COL = 8    # I: ชื่อเพจ
SEND_DATE_COL = 17   # R: วันที่ส่ง
TRACKING_COL = 25    # Z: Tracking ID
CARRIER_COL = 6      # G: ขนส่ง

SEND_DATE_COL_LETTER = "R"
REQUIRED_STATUS = "📦ລໍຈັດສົ່ງ"

REQUIRED_STATUS_DELIVERED = "🏁ຮອດປາຍທາງແລ້ວ"
# คอลัมน์ A = สถานะแจ้งถึงซ้ำ (หลังแจ้งครั้งแรกแล้วลูกค้ายังไม่รับ)
REQUIRED_STATUS_DELIVERED_FOLLOWUP = "💬ແຈ້ງຮອດແລ້ວ"
NOTIFY_DELIVERED_STATUSES = (REQUIRED_STATUS_DELIVERED, REQUIRED_STATUS_DELIVERED_FOLLOWUP)
NOTIFY_STOCK_OUT_STATUSES = ("🗑️ໝົດ", "⏳ລໍສິນຄ້າ")
NOTIFY_STOCK_AVAILABLE_STATUSES = ("📢ແຈ້ງສິນຄ້າໝົດແລ້ວ",)
NOTIFIED_DELIVERED_COL = 21       # V: แจ้งถึงแล้ว
NOTIFIED_DELIVERED_COL_LETTER = "V"
NOTIFY_DELIVERED_MESSAGE = "ຮອດແລ້ວເດີໄປຮັບເຄື່ອງແດ່ເຈົ້າ"
NOTIFY_STOCK_OUT_MESSAGE = "ເຄື່ອງເມິດແລ້ວເດີ ສາມາດຍົກເລີກ ຫຼື ຖ້າອີກ 1 ທິດເຄື່ອງມາຮອດເຮົາ ຫຼຸດລາຄາໃຫ້"
NOTIFY_STOCK_AVAILABLE_MESSAGE = "ມີເຄື່ອງແລ້ວເດີ ຖ້າຍັງຮັບແຈ້ງເດີ ເຮົາຈະລົດລາຄາໃຫ້ຕາມທີ່ແຈ້ງໄວ້"
NOTIFY_STOCK_OUT_RESULT = "📢ແຈ້ງສິນຄ້າໝົດແລ້ວ"
NOTIFY_STOCK_AVAILABLE_RESULT = "🔔ແຈ້ງມີສິນຄ້າແລ້ວ"

ORDER_HEADERS = ("Order", "order", "Order ID", "Order Id", "OrderID")
TRACKING_HEADERS = ("Tracking ID", "tracking_id", "Tracking Id", "เลขพัสดุ")
PAGE_NAME_HEADERS = ("ຊ່ອງທາງ", "ช่องทาง", "Channel", "channel", "Page", "page")
CARRIER_HEADERS = (
    "ຂົນສົ່ງ",
    "ขนส่ง",
    "Carrier",
    "carrier",
    "ຂນສົ່ງ",
    "Courier",
    "courier",
)


# ---------------------------------------------------------------------------
# Token / PSID helpers
# ---------------------------------------------------------------------------

def load_page_tokens() -> Dict[str, dict]:
    """โหลด page_token.json (array) → dict keyed by page_name (lowercase)
    แต่ละ value = {"page_id": ..., "access_token": ..., "page_name": ...}
    """
    mapping: Dict[str, dict] = {}
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    pages = raw if isinstance(raw, list) else [raw]
    for p in pages:
        if p.get("enabled") is False:
            continue
        name = p.get("page_name", "").strip()
        pid = str(p["page_id"])
        entry = {"page_id": pid, "access_token": p["access_token"], "page_name": name}
        mapping[name.lower()] = entry
        mapping[pid] = entry
    return mapping


def load_order_psid() -> Dict[str, dict]:
    """โหลด order_psid.json → dict {order_id: {"psid": ..., "page_id": ...}}
    รองรับ format เก่า (value เป็น string PSID) และ format ใหม่ (value เป็น dict)
    """
    if not os.path.exists(ORDER_PSID_FILE):
        return {}
    try:
        with open(ORDER_PSID_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        by_order_raw = data.get("by_order", {})
        result: Dict[str, dict] = {}
        for oid, val in by_order_raw.items():
            if isinstance(val, dict):
                result[oid] = val
            else:
                result[oid] = {"psid": str(val), "page_id": ""}
        return result
    except (json.JSONDecodeError, TypeError):
        return {}


def lookup_psid(by_order: Dict[str, dict], order_id_raw: str) -> Optional[dict]:
    """หา PSID+page_id จาก order_id (ลองทั้งมี/ไม่มี 0 นำหน้า)"""
    o = str(order_id_raw).strip() if order_id_raw else ""
    if not o:
        return None
    if o in by_order:
        return by_order[o]
    if o.startswith("0") and o[1:] in by_order:
        return by_order[o[1:]]
    if not o.startswith("0") and ("0" + o) in by_order:
        return by_order["0" + o]
    return None


# ---------------------------------------------------------------------------
# Google Sheet reading
# ---------------------------------------------------------------------------

def _find_col(headers: List[str], possible: tuple, default: int) -> int:
    for i, h in enumerate(headers):
        if h.strip() in possible:
            return i
    return default


def read_rows_from_sheet(
    sheet_id: str,
    sheet_names: List[str],
    credentials_path: str,
    row_map: Dict[Tuple[str, str], Tuple[str, int]],
) -> List[Tuple[str, str, str, str]]:
    """อ่าน Google Sheet → [(order_id, page_name, tracking_id, carrier), ...]
    พร้อมเก็บ row_map[(order_id, tracking_id)] = (sheet_name, row_num) สำหรับ write-back
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("❌ ต้องติดตั้ง: pip install gspread google-auth", file=sys.stderr)
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(sheet_id)

    all_rows: List[Tuple[str, str, str, str]] = []
    for sn in sheet_names:
        try:
            ws = workbook.worksheet(sn)
        except Exception as e:
            print(f"⚠️ ข้ามชีต '{sn}': {e}")
            continue
        data = ws.get_all_values()
        if not data:
            continue

        header = [str(c).strip() for c in data[0]]
        order_col = _find_col(header, ORDER_HEADERS, ORDER_COL)
        page_col = _find_col(header, PAGE_NAME_HEADERS, PAGE_NAME_COL)
        tracking_col = _find_col(header, TRACKING_HEADERS, TRACKING_COL)
        carrier_col = _find_col(header, CARRIER_HEADERS, CARRIER_COL)

        for idx, cells in enumerate(data[1:], start=2):
            cells = [str(x).strip() for x in cells]
            status = cells[STATUS_COL] if STATUS_COL < len(cells) else ""
            if status != REQUIRED_STATUS:
                continue
            oid = cells[order_col] if order_col < len(cells) else ""
            pname = cells[page_col] if page_col < len(cells) else ""
            tid = cells[tracking_col] if tracking_col < len(cells) else ""
            car = cells[carrier_col] if carrier_col < len(cells) else ""
            if not oid or not tid or len(tid) < 10:
                continue
            # ข้ามถ้า Column R มีวันที่แล้ว (ส่งไปแล้ว)
            send_date = cells[SEND_DATE_COL] if SEND_DATE_COL < len(cells) else ""
            if send_date.strip():
                continue
            all_rows.append((oid, pname, tid, car))
            row_map[(oid, tid)] = (sn, idx)

    return all_rows


def batch_update_send_dates(
    sheet_id: str,
    updates: List[Tuple[str, int, str]],
    credentials_path: str,
) -> bool:
    """อัปเดต Column R ใน Google Sheet หลังส่งสำเร็จ
    updates = [(sheet_name, row_num, date_str), ...]
    """
    if not updates:
        return True
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return False

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(sheet_id)

        from collections import defaultdict
        by_sheet: Dict[str, list] = defaultdict(list)
        for sn, row_num, date_str in updates:
            by_sheet[sn].append((row_num, date_str))

        for sn, cells in by_sheet.items():
            ws = workbook.worksheet(sn)
            batch = [{"range": f"{SEND_DATE_COL_LETTER}{r}", "values": [[d]]} for r, d in cells]
            if batch:
                ws.batch_update(batch)
                print(f"   📝 อัปเดต Column R ในชีต '{sn}': {len(batch)} แถว")
        return True
    except Exception as e:
        print(f"   ❌ อัปเดต Google Sheet ล้มเหลว: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Notify-delivered: read + write-back
# ---------------------------------------------------------------------------

def read_rows_for_notify(
    sheet_id: str,
    sheet_names: List[str],
    credentials_path: str,
    row_map: Dict[Tuple[str, str], Tuple[str, int]],
    required_statuses: Tuple[str, ...],
) -> List[Tuple[str, str, str, str]]:
    """Read rows where column A is one of required_statuses.
    Returns [(order_id, page_name, "", carrier), ...] (no tracking needed).
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("❌ ต้องติดตั้ง: pip install gspread google-auth", file=sys.stderr)
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(sheet_id)

    all_rows: List[Tuple[str, str, str, str]] = []
    for sn in sheet_names:
        try:
            ws = workbook.worksheet(sn)
        except Exception as e:
            print(f"⚠️ ข้ามชีต '{sn}': {e}")
            continue
        data = ws.get_all_values()
        if not data:
            continue

        header = [str(c).strip() for c in data[0]]
        order_col = _find_col(header, ORDER_HEADERS, ORDER_COL)
        page_col = _find_col(header, PAGE_NAME_HEADERS, PAGE_NAME_COL)
        carrier_col = _find_col(header, CARRIER_HEADERS, CARRIER_COL)

        for idx, cells in enumerate(data[1:], start=2):
            cells = [str(x).strip() for x in cells]
            status = cells[STATUS_COL] if STATUS_COL < len(cells) else ""
            if status not in required_statuses:
                continue
            oid = cells[order_col] if order_col < len(cells) else ""
            pname = cells[page_col] if page_col < len(cells) else ""
            car = cells[carrier_col] if carrier_col < len(cells) else ""
            if not oid or not pname:
                continue
            all_rows.append((oid, pname, "", car))
            row_map[(oid, "")] = (sn, idx)

    return all_rows


def batch_update_notified_delivered(
    sheet_id: str,
    updates: List[Tuple[str, int]],
    credentials_path: str,
    value: str = "💬ແຈ້ງຮອດແລ້ວ",
) -> bool:
    """Write notify result value to Column V for successfully notified orders.
    updates = [(sheet_name, row_num), ...]
    """
    if not updates:
        return True
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return False

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(sheet_id)

        from collections import defaultdict
        by_sheet: Dict[str, list] = defaultdict(list)
        for sn, row_num in updates:
            by_sheet[sn].append(row_num)

        for sn, row_nums in by_sheet.items():
            ws = workbook.worksheet(sn)
            batch = [{"range": f"{NOTIFIED_DELIVERED_COL_LETTER}{r}", "values": [[value]]} for r in row_nums]
            if batch:
                ws.batch_update(batch)
                print(f"   📝 อัปเดต Column V ในชีต '{sn}': {len(batch)} แถว")
        return True
    except Exception as e:
        print(f"   ❌ อัปเดต Google Sheet ล้มเหลว: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# CSV reading (backward compatible)
# ---------------------------------------------------------------------------

def read_rows_from_csv(path: str) -> List[Tuple[str, str, str, str]]:
    """อ่าน CSV → [(order_id, page_name, tracking_id, carrier), ...]"""
    rows: List[Tuple[str, str, str, str]] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header: Optional[List[str]] = None
        for row in reader:
            cells = [str(x).strip() for x in row]
            if not cells or all(not c for c in cells):
                continue
            header = cells
            break
        if not header:
            return rows

        order_col = _find_col(header, ORDER_HEADERS, ORDER_COL)
        page_col = _find_col(header, PAGE_NAME_HEADERS, PAGE_NAME_COL)
        tracking_col = _find_col(header, TRACKING_HEADERS, TRACKING_COL)
        carrier_col = _find_col(header, CARRIER_HEADERS, CARRIER_COL)

        for row in reader:
            cells = [str(x).strip() for x in row]
            status = cells[STATUS_COL] if STATUS_COL < len(cells) else ""
            if status != REQUIRED_STATUS:
                continue
            oid = cells[order_col] if order_col < len(cells) else ""
            pname = cells[page_col] if page_col < len(cells) else ""
            tid = cells[tracking_col] if tracking_col < len(cells) else ""
            car = cells[carrier_col] if carrier_col < len(cells) else ""
            if not oid or not tid or len(tid) < 10:
                continue
            rows.append((oid, pname, tid, car))
    return rows


# ---------------------------------------------------------------------------
# Graph API sending
# ---------------------------------------------------------------------------

def _graph_send(page_id: str, access_token: str, body: dict) -> dict:
    """POST to Graph messages endpoint; returns JSON response."""
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{page_id}/messages"
    r = requests.post(url, params={"access_token": access_token}, json=body)
    try:
        return r.json()
    except Exception:
        return {"error": {"message": f"non-JSON status={r.status_code}"}}


def _send_with_window_fallback(
    page_id: str,
    access_token: str,
    base_body: dict,
    *,
    use_message_tag: bool,
    log_label: str = "API",
) -> bool:
    """
    Send message preferring the 24h RESPONSE window.

    POST_PURCHASE_UPDATE (and related tags) were deprecated by Meta on 2026-04-27
    and now return error code 100 Invalid parameter. Use RESPONSE first; fall back to
    HUMAN_AGENT (7-day human-agent window) if the standard window is closed.
    """
    attempts: List[dict] = []
    # Always try RESPONSE first when caller wants out-of-session capability
    # (covers active 24h window after customer contact).
    attempts.append({"messaging_type": "RESPONSE"})
    if use_message_tag:
        attempts.append({"messaging_type": "MESSAGE_TAG", "tag": "HUMAN_AGENT"})

    last_err: Optional[dict] = None
    for i, extra in enumerate(attempts):
        body = dict(base_body)
        body.update(extra)
        res = _graph_send(page_id, access_token, body)
        if "error" not in res:
            return True
        last_err = res.get("error") if isinstance(res.get("error"), dict) else {"message": str(res.get("error"))}
        code = last_err.get("code")
        # Only fall through to HUMAN_AGENT when window is closed / tag issues
        if i + 1 < len(attempts) and code in (10, 100, 551, 1545041):
            continue
        break

    if last_err:
        print(f"   ❌ {log_label}: {last_err.get('message', last_err)}")
    return False


def send_message(
    page_id: str,
    access_token: str,
    recipient_id: str,
    text: str,
    use_message_tag: bool = False,
) -> bool:
    base = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    return _send_with_window_fallback(
        page_id, access_token, base, use_message_tag=use_message_tag, log_label="API"
    )


def find_bill_image(bills_dir: str, tracking_id: str) -> Optional[str]:
    if not bills_dir or not os.path.isdir(bills_dir):
        return None
    for ext in (".png", ".jpg", ".jpeg"):
        path = os.path.join(bills_dir, f"{tracking_id}{ext}")
        if os.path.isfile(path):
            return path
    return None


def upload_attachment(page_id: str, access_token: str, image_path: str) -> Optional[str]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{page_id}/message_attachments"
    msg = json.dumps({"attachment": {"type": "image", "payload": {"is_reusable": True}}})
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    try:
        with open(image_path, "rb") as f:
            r = requests.post(
                url,
                params={"access_token": access_token},
                data={"message": msg},
                files={"filedata": (os.path.basename(image_path), f, mime)},
            )
        res = r.json()
        if "attachment_id" in res:
            return res["attachment_id"]
        if "error" in res:
            print(f"   ❌ อัปโหลดรูป: {res['error'].get('message', res['error'])}")
        return None
    except Exception as e:
        print(f"   ❌ อัปโหลดรูป: {e}")
        return None


def send_image(
    page_id: str,
    access_token: str,
    recipient_id: str,
    attachment_id: str,
    use_message_tag: bool = False,
) -> bool:
    base = {
        "recipient": {"id": recipient_id},
        "message": {"attachment": {"type": "image", "payload": {"attachment_id": attachment_id}}},
    }
    return _send_with_window_fallback(
        page_id, access_token, base, use_message_tag=use_message_tag, log_label="ส่งรูป"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_sheet_config():
    """Load sheet config + credentials path; exit on error."""
    if not os.path.exists(SHEET_CONFIG_PATH):
        print(f"❌ ไม่พบ sheet config: {SHEET_CONFIG_PATH}")
        sys.exit(1)
    with open(SHEET_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    sheet_id = cfg["sheet_id"]
    sheet_names = cfg.get("sheet_names", ["ອໍເດີ່"])
    credentials_path = os.path.join(
        SCRIPT_DIR, "no_api_send_bill",
        cfg.get("credentials_path", "config/google_credentials.json"),
    )
    if not os.path.exists(credentials_path):
        credentials_path = DEFAULT_CREDENTIALS_PATH
    if not os.path.exists(credentials_path):
        print(f"❌ ไม่พบ Google credentials: {credentials_path}")
        sys.exit(1)
    return sheet_id, sheet_names, credentials_path


def main_notify_mode(mode: str, dry_run: bool = False):
    """Notify mode (delivered/stock_out/stock_available): read sheet -> send text -> update Column V."""
    if mode == "delivered":
        mode_title = "แจ้งถึงแล้ว (notify-delivered)"
        required_statuses = NOTIFY_DELIVERED_STATUSES
        notify_message = NOTIFY_DELIVERED_MESSAGE
        result_value = "💬ແຈ້ງຮອດແລ້ວ"
        empty_hint = "❌ ไม่พบแถวที่ต้องแจ้ง (สถานะคอลัมน์ A ไม่ตรง 🏁 ຫรือ 💬 ตามโหมดแจ้งถึง)"
    elif mode == "stock_out":
        mode_title = "แจ้งสินค้าหมด (notify-stock-out)"
        required_statuses = NOTIFY_STOCK_OUT_STATUSES
        notify_message = NOTIFY_STOCK_OUT_MESSAGE
        result_value = NOTIFY_STOCK_OUT_RESULT
        empty_hint = "❌ ไม่พบแถวที่ต้องแจ้ง (สถานะคอลัมน์ A ไม่ตรง 🗑️ ຫรือ ⏳)"
    elif mode == "stock_available":
        mode_title = "แจ้งมีสินค้า (notify-stock-available)"
        required_statuses = NOTIFY_STOCK_AVAILABLE_STATUSES
        notify_message = NOTIFY_STOCK_AVAILABLE_MESSAGE
        result_value = NOTIFY_STOCK_AVAILABLE_RESULT
        empty_hint = "❌ ไม่พบแถวที่ต้องแจ้ง (สถานะคอลัมน์ A ไม่ตรง 📢ແຈ້ງສິນຄ້າໝົດແລ້ວ)"
    else:
        print(f"❌ โหมดแจ้งไม่ถูกต้อง: {mode}")
        sys.exit(1)

    print("=" * 50)
    print(f"โหมด: {mode_title}")
    print("=" * 50)

    try:
        page_map = load_page_tokens()
    except Exception as e:
        print(f"❌ โหลด {TOKEN_FILE} ไม่ได้: {e}")
        sys.exit(1)

    by_order = load_order_psid()
    if not by_order:
        print("⚠️ ยังไม่มี Order→PSID ใน order_psid.json")

    sheet_id, sheet_names, credentials_path = _load_sheet_config()
    print(f"📖 อ่าน Google Sheet: {sheet_id}")
    print(f"   ชีต: {', '.join(sheet_names)}")
    print(f"   กรองสถานะคอลัมน์ A: {' หรือ '.join(required_statuses)}")

    row_map: Dict[Tuple[str, str], Tuple[str, int]] = {}
    rows = read_rows_for_notify(
        sheet_id,
        sheet_names,
        credentials_path,
        row_map,
        required_statuses=required_statuses,
    )

    if not rows:
        print(empty_hint)
        sys.exit(0)

    print(f"📊 พบ {len(rows)} รายการที่ต้องแจ้ง")
    if dry_run:
        print("[โหมด dry-run ไม่ส่งจริง]\n")

    sent = 0
    skipped_no_psid = 0
    skipped_api = 0
    skipped_no_page = 0
    notify_updates: List[Tuple[str, int]] = []

    for order_id, page_name, _, __ in rows:
        page_info = page_map.get(page_name.lower().strip())
        if not page_info:
            print(f"⚠️ ข้าม Order {order_id} — ไม่พบเพจ '{page_name}' ใน {TOKEN_FILE}")
            skipped_no_page += 1
            continue
        pid = page_info["page_id"]
        token = page_info["access_token"]

        psid_info = lookup_psid(by_order, order_id)
        psid = psid_info["psid"] if psid_info else None
        if not psid:
            print(f"⚠️ ข้าม Order {order_id} [{page_name}] — ไม่มี PSID")
            skipped_no_psid += 1
            continue

        if dry_run:
            print(f"  จะแจ้ง → Order {order_id} [{page_name}] (PSID {psid})")
            sent += 1
            if (order_id, "") in row_map:
                sn, rn = row_map[(order_id, "")]
                notify_updates.append((sn, rn))
            continue

        ok = send_message(pid, token, psid, notify_message, use_message_tag=True)
        if not ok:
            skipped_api += 1
            continue

        print(f"✅ แจ้งแล้ว Order {order_id} [{page_name}]")
        sent += 1
        if (order_id, "") in row_map:
            sn, rn = row_map[(order_id, "")]
            notify_updates.append((sn, rn))

    print(f"\n{'=' * 50}")
    print(f"แจ้งถึงแล้วสำเร็จ {sent} รายการ")
    if skipped_no_psid:
        print(f"ไม่มี PSID: {skipped_no_psid} รายการ")
    if skipped_api:
        print(f"ส่ง API ไม่สำเร็จ: {skipped_api} รายการ")
    if skipped_no_page:
        print(f"ไม่พบเพจใน token: {skipped_no_page} รายการ")

    if notify_updates and not dry_run:
        print(f"\n📝 อัปเดต Column V ใน Google Sheet ({len(notify_updates)} แถว)...")
        batch_update_notified_delivered(sheet_id, notify_updates, credentials_path, value=result_value)


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    dry_run = "--dry-run" in args
    notify_delivered = "--notify-delivered" in args
    notify_stock_out = "--notify-stock-out" in args
    notify_stock_available = "--notify-stock-available" in args
    args = [a for a in args if a not in ("--dry-run", "--notify-delivered", "--notify-stock-out", "--notify-stock-available")]

    notify_modes = [
        ("delivered", notify_delivered),
        ("stock_out", notify_stock_out),
        ("stock_available", notify_stock_available),
    ]
    selected_notify_modes = [name for name, enabled in notify_modes if enabled]
    if len(selected_notify_modes) > 1:
        print("❌ เลือกได้เพียงโหมดแจ้งเดียว: --notify-delivered หรือ --notify-stock-out หรือ --notify-stock-available")
        sys.exit(1)

    # --- Notify mode ---
    if selected_notify_modes:
        main_notify_mode(selected_notify_modes[0], dry_run)
        return

    bills_dir: Optional[str] = None
    if "--bills-dir" in args:
        i = args.index("--bills-dir")
        if i + 1 < len(args):
            bills_dir = args[i + 1]
        args = [args[j] for j in range(len(args)) if j != i and j != i + 1]
    if bills_dir is None:
        bills_dir = DEFAULT_BILLS_DIR if os.path.isdir(DEFAULT_BILLS_DIR) else None

    # --- Determine data source ---
    use_sheet = "--sheet" in args
    csv_path: Optional[str] = None
    if "--csv" in args:
        ci = args.index("--csv")
        if ci + 1 < len(args):
            csv_path = args[ci + 1]
    elif not use_sheet and len([a for a in args if not a.startswith("--")]) >= 1:
        csv_path = [a for a in args if not a.startswith("--")][0]

    if not use_sheet and not csv_path:
        print("ใช้:")
        print("  python3 send_bill_from_sheet.py --sheet [--bills-dir โฟลเดอร์] [--dry-run]")
        print("  python3 send_bill_from_sheet.py --csv <path_to_csv> [--bills-dir โฟลเดอร์] [--dry-run]")
        print("  python3 send_bill_from_sheet.py --sheet --notify-delivered [--dry-run]")
        print("  python3 send_bill_from_sheet.py --sheet --notify-stock-out [--dry-run]")
        print("  python3 send_bill_from_sheet.py --sheet --notify-stock-available [--dry-run]")
        sys.exit(1)

    # --- Load page tokens (multi-page) ---
    try:
        page_map = load_page_tokens()
    except Exception as e:
        print(f"❌ โหลด {TOKEN_FILE} ไม่ได้: {e}")
        sys.exit(1)

    # --- Load Order→PSID ---
    by_order = load_order_psid()
    if not by_order:
        print("⚠️ ยังไม่มี Order→PSID ใน order_psid.json")
        print("   ให้รัน webhook + ngrok แล้วส่งข้อความที่มี 'Order: XXX' จาก Business Inbox ก่อน")

    # --- Read rows ---
    row_map: Dict[Tuple[str, str], Tuple[str, int]] = {}
    sheet_id = ""
    credentials_path = ""

    if use_sheet:
        sheet_id, sheet_names, credentials_path = _load_sheet_config()
        print(f"📖 อ่าน Google Sheet: {sheet_id}")
        print(f"   ชีต: {', '.join(sheet_names)}")
        rows = read_rows_from_sheet(sheet_id, sheet_names, credentials_path, row_map)
    else:
        if not os.path.exists(csv_path):
            print(f"❌ ไม่พบไฟล์: {csv_path}")
            sys.exit(1)
        rows = read_rows_from_csv(csv_path)

    if not rows:
        print("❌ ไม่พบแถวที่ต้องส่ง (สถานะ 📦ລໍຈັດສົ່ງ + มี Tracking ID + ยังไม่ส่ง)")
        sys.exit(0)

    print(f"📊 พบ {len(rows)} รายการที่ต้องส่ง")
    if bills_dir:
        print(f"📁 โฟลเดอร์รูปบิล: {bills_dir}")
    if dry_run:
        print("[โหมด dry-run ไม่ส่งจริง]\n")

    # --- Process each order ---
    sent = 0
    skipped_no_psid = 0
    skipped_api = 0
    skipped_no_page = 0
    sheet_updates: List[Tuple[str, int, str]] = []
    # ใช้รูปแบบวันที่ที่รองรับทั้ง Linux/Windows (เลิกใช้ %-d/%-m เพราะ Windows ไม่รองรับ)
    today_str = datetime.now().strftime("%d/%m/%Y")

    for order_id, page_name, tracking_id, carrier in rows:
        page_info = page_map.get(page_name.lower().strip())
        if not page_info:
            print(f"⚠️ ข้าม Order {order_id} — ไม่พบเพจ '{page_name}' ใน {TOKEN_FILE}")
            skipped_no_page += 1
            continue
        pid = page_info["page_id"]
        token = page_info["access_token"]

        psid_info = lookup_psid(by_order, order_id)
        psid = psid_info["psid"] if psid_info else None
        if not psid:
            print(f"⚠️ ข้าม Order {order_id} tracking {tracking_id} [{page_name}] — ไม่มี PSID")
            skipped_no_psid += 1
            continue

        text = bill_tracking_customer_message(tracking_id, carrier)

        if dry_run:
            img_note = " + รูป" if bills_dir and find_bill_image(bills_dir, tracking_id) else ""
            print(f"  จะส่ง → Order {order_id} [{page_name}] (PSID {psid}): {tracking_id}{img_note}")
            sent += 1
            if (order_id, tracking_id) in row_map:
                sn, rn = row_map[(order_id, tracking_id)]
                sheet_updates.append((sn, rn, today_str))
            continue

        ok = send_message(pid, token, psid, text, use_message_tag=True)
        if not ok:
            skipped_api += 1
            continue

        img_path = find_bill_image(bills_dir, tracking_id) if bills_dir else None
        if img_path:
            att_id = upload_attachment(pid, token, img_path)
            if att_id:
                send_image(pid, token, psid, att_id, use_message_tag=True)

        print(f"✅ ส่งแล้ว Order {order_id} [{page_name}] tracking {tracking_id}" + (" + รูป" if img_path else ""))
        sent += 1

        if (order_id, tracking_id) in row_map:
            sn, rn = row_map[(order_id, tracking_id)]
            sheet_updates.append((sn, rn, today_str))

    print(f"\n{'='*50}")
    print(f"รวมส่งได้ {sent} รายการ")
    if skipped_no_psid:
        print(f"ไม่มี PSID: {skipped_no_psid} รายการ")
    if skipped_api:
        print(f"ส่ง API ไม่สำเร็จ: {skipped_api} รายการ")
    if skipped_no_page:
        print(f"ไม่พบเพจใน token: {skipped_no_page} รายการ")

    if sheet_updates and use_sheet and not dry_run:
        print(f"\n📝 อัปเดตวันที่ส่งใน Google Sheet ({len(sheet_updates)} แถว)...")
        batch_update_send_dates(sheet_id, sheet_updates, credentials_path)


if __name__ == "__main__":
    main()
