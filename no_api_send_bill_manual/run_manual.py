#!/usr/bin/env python3
"""
ສົ່ງບິນແບບ Manual — ປອດໄພ 100% (ໃຊ້ຮ່ວມກັບ AutoHotkey)
- ດຶງຂໍ້ມູນຈາກ Google Sheet ແລ້ວແບ່ງຕາມເພຈ
- Copy ລິ້ງ/ເລກ Order/ຂໍ້ຄວາມ/ຮູບ ໄປ clipboard
- ເຈົ້າເປັນຄົນເປີດ Browser ແລະວາງ (Ctrl+V) ກົດສົ່ງເອງ
- ສັນຍານຈາກ AutoHotkey: Ctrl+Alt+Enter, Ctrl+Alt+D, Ctrl+Alt+N

ປຸ່ມລັດ (ຕັ້ງໃນ AHK):
- Ctrl+Alt+Enter = ເປີດໜ້າ / ເປີດເພຈໃໝ່
- Ctrl+Alt+D = ເລືອກແຊັດ / ວາງຂໍ້ຄວາມ / ກົດສົ່ງ (ແທນ Double-click)
- Ctrl+Alt+N = ບໍ່ພົບຜົນ (ແທນ Triple-click)
"""

import json
import os
import sys
import threading
import queue
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler

# Pre-import เพื่อให้ copy ข้อความครั้งแรกเร็ว (ไม่รอ import ตอนกดวาง)
try:
    import pyperclip
except ImportError:
    pyperclip = None

# โฟลเดอร์โปรเจกต์
PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_DIR / "config"
SIGNAL_PORT = 29582

# ข้อความลูกค้า + ลิงก์บิล — แหล่งเดียวกับ no_api_send_bill/scripts/bill_carrier_links.py
_BILL_SCRIPTS = str(PROJECT_DIR.parent / "no_api_send_bill" / "scripts")
if _BILL_SCRIPTS not in sys.path:
    sys.path.insert(0, _BILL_SCRIPTS)
from bill_carrier_links import bill_tracking_customer_message  # noqa: E402

# ค่าคงที่สำหรับ Google Sheet (ใช้ร่วมกันทั้งอ่านและอัปเดต — ลดความซ้ำ)
SHEET_STATUS_COL = 0
SHEET_ORDER_COL_DEFAULT = 3
SHEET_PHONE_COL_DEFAULT = 5  # Column F
SHEET_CARRIER_COL_DEFAULT = 6  # Column G
SHEET_PAGE_COL_DEFAULT = 8
SHEET_TRACKING_COL_DEFAULT = 25
SHEET_SENT_DATE_COL = 18  # R
SHEET_REQUIRED_STATUS = "📦ລໍສົ່ງບິນ"
SHEET_ORDER_HEADERS = ("Order", "order", "Order ID", "Order Id", "OrderID")
SHEET_PAGE_HEADERS = ("ຊ່ອງທາງ", "ช่องทาง", "Channel", "channel", "Page", "page")
SHEET_TRACKING_HEADERS = ("Tracking ID", "tracking_id", "Tracking Id", "เลขพัสดุ")
SHEET_CARRIER_HEADERS = (
    "ຂົນສົ່ງ",
    "ขนส่ง",
    "Carrier",
    "carrier",
    "ຂນສົ່ງ",
    "Courier",
    "courier",
)

WHATSAPP_COUNTRY_CODE = "856"


def _find_col(headers: List[str], names: tuple, default: int) -> int:
    """หาดัชนีคอลัมน์จาก header ที่ตรงกับ names อย่างใดอย่างหนึ่ง"""
    for i, h in enumerate(headers):
        if str(h).strip() in names:
            return i
    return default


def _is_whatsapp_page(page_name: str) -> bool:
    return page_name.strip().lower() == "whatsapp"


def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith(WHATSAPP_COUNTRY_CODE):
        return phone
    if phone.startswith("0"):
        phone = phone[1:]
    return WHATSAPP_COUNTRY_CODE + phone


def _build_whatsapp_url(phone: str, text: str = "") -> str:
    from urllib.parse import quote
    normalized = _normalize_phone(phone)
    url = f"https://web.whatsapp.com/send?phone={normalized}"
    if text:
        url += f"&text={quote(text)}"
    return url


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_page_id(page_name: str, mapping: dict) -> Optional[str]:
    return mapping.get(page_name.strip())


def get_business_page_names(mapping: dict) -> set:
    return set(mapping.get("__business_pages", []))


def build_inbox_url(page_name: str, page_id: str, business_page_names: set, mapping: dict) -> str:
    base_url = "https://business.facebook.com/latest/inbox/all/"
    selected_item_id = mapping.get("__initial_selected_item_id") or mapping.get("__initial_selected_item_ids", {}).get(page_name)
    if not selected_item_id:
        return f"{base_url}?asset_id={page_id}&selected_page_id={page_id}"
    thread_type = "FB_MESSAGE"
    if page_name in business_page_names:
        url = f"{base_url}?business_id={page_id}"
        url += f"&mailbox_id=&thread_type={thread_type}&selected_item_id={selected_item_id}"
    else:
        url = f"{base_url}?asset_id={page_id}&selected_page_id={page_id}"
        url += f"&mailbox_id=&selected_item_id={selected_item_id}&thread_type={thread_type}"
    return url


def get_sheet_workbook(sheet_id: str, credentials_path: str):
    """ເປີດ workbook ຄັ້ງດຽວ (ອ່ານ+ຂຽນ) ໃຊ້ຮ່ວມກັນທັງອ່ານແຖວແລະອັບເດດວັນທີສົ່ງ"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return None
    if not os.path.exists(credentials_path):
        return None
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)


def read_rows_from_workbook(
    workbook, sheet_names: List[str], phone_map: Optional[Dict[str, str]] = None
) -> Tuple[List[Tuple[str, str, str, str]], int]:
    """ດຶງແຖວທີ່ມີສະຖານະ 'ລໍສົ່ງບິນ' (+ WhatsApp rows with phone); ສົ່ງຄືນ (rows, ຈຳນວນແຖວທີ່ຂ້າມ)"""
    rows: List[Tuple[str, str, str, str]] = []
    skipped_no_tracking = 0
    for sheet_name in sheet_names:
        try:
            ws = workbook.worksheet(sheet_name)
            all_rows = ws.get_all_values()
        except Exception as e:
            print(f"ຂ້າມຊີດ '{sheet_name}': {e}")
            continue
        if not all_rows:
            continue
        header = [str(c).strip() for c in all_rows[0]]
        order_col = _find_col(header, SHEET_ORDER_HEADERS, SHEET_ORDER_COL_DEFAULT)
        page_col = _find_col(header, SHEET_PAGE_HEADERS, SHEET_PAGE_COL_DEFAULT)
        track_col = _find_col(header, SHEET_TRACKING_HEADERS, SHEET_TRACKING_COL_DEFAULT)
        carrier_col = _find_col(header, SHEET_CARRIER_HEADERS, SHEET_CARRIER_COL_DEFAULT)
        for cells in all_rows[1:]:
            cells = [str(x).strip() for x in cells]
            if len(cells) <= max(SHEET_STATUS_COL, order_col, page_col, carrier_col):
                continue
            if (cells[SHEET_STATUS_COL] if SHEET_STATUS_COL < len(cells) else "") != SHEET_REQUIRED_STATUS:
                continue
            order_id = cells[order_col] if order_col < len(cells) else ""
            page_name = cells[page_col] if page_col < len(cells) else ""
            tracking_id = cells[track_col] if track_col < len(cells) else ""
            carrier = cells[carrier_col] if carrier_col < len(cells) else ""

            if _is_whatsapp_page(page_name):
                phone = cells[SHEET_PHONE_COL_DEFAULT] if SHEET_PHONE_COL_DEFAULT < len(cells) else ""
                if phone and phone_map is not None:
                    phone_map[order_id] = phone
                rows.append((order_id, page_name, tracking_id, carrier))
                continue

            if not tracking_id or tracking_id in SHEET_TRACKING_HEADERS or len(tracking_id) < 10:
                skipped_no_tracking += 1
                continue
            rows.append((order_id, page_name, tracking_id, carrier))
    return rows, skipped_no_tracking


def update_sheet_sent_dates(
    workbook,
    sheet_names: List[str],
    done_orders: List[str],
) -> None:
    """ຂຽນວັນທີປະຈຸບັນ (D/M/YYYY) ລົງຄໍລໍາ R ໃນແຖວທີ່ Order ສົ່ງສຳເລັດ (ໃຊ້ workbook ທີ່ເປີດໄວ້ແລ້ວ)"""
    if not done_orders or workbook is None:
        return
    try:
        from datetime import date
    except ImportError:
        return
    today = date.today()
    date_str = f"{today.day}/{today.month}/{today.year}"
    done_set = set(done_orders)
    updated = 0
    for sheet_name in sheet_names:
        try:
            ws = workbook.worksheet(sheet_name)
            all_rows = ws.get_all_values()
        except Exception as e:
            print(f"   ຂ້າມຊີດ '{sheet_name}': {e}")
            continue
        if not all_rows:
            continue
        header = [str(c).strip() for c in all_rows[0]]
        order_col = _find_col(header, SHEET_ORDER_HEADERS, SHEET_ORDER_COL_DEFAULT)
        rows_to_update = []
        for row_idx, cells in enumerate(all_rows[1:], start=2):
            cells = [str(x).strip() for x in cells]
            status_ok = (
                SHEET_STATUS_COL < len(cells)
                and (cells[SHEET_STATUS_COL] or "").strip() == SHEET_REQUIRED_STATUS
            )
            if status_ok and order_col < len(cells) and cells[order_col] in done_set:
                rows_to_update.append(row_idx)
        if not rows_to_update:
            continue
        try:
            body = {
                "valueInputOption": "RAW",
                "data": [
                    {"range": f"'{sheet_name}'!R{row}", "values": [[date_str]]}
                    for row in rows_to_update
                ],
            }
            workbook.values_batch_update(body=body)
            fmt_body = {
                "requests": [
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": min(rows_to_update) - 1,
                                "endRowIndex": max(rows_to_update),
                                "startColumnIndex": SHEET_SENT_DATE_COL - 1,
                                "endColumnIndex": SHEET_SENT_DATE_COL,
                            },
                            "cell": {
                                "userEnteredFormat": {"horizontalAlignment": "RIGHT"}
                            },
                            "fields": "userEnteredFormat.horizontalAlignment",
                        }
                    }
                ]
            }
            workbook.batch_update(fmt_body)
            updated += len(rows_to_update)
        except Exception as e:
            print(f"   ອັບເດດຊີດ '{sheet_name}' ບໍ່ໄດ້: {e}")
    if updated:
        print(f"   ອັບເດດວັນທີສົ່ງໃນ Sheet (ຄໍລໍາ R): {date_str} — {updated} ແຖວ")


def find_bill_image(bills_dir: Path, tracking_id: str) -> Optional[Path]:
    if not bills_dir or not bills_dir.is_dir():
        return None
    for ext in (".png", ".jpg", ".jpeg"):
        p = bills_dir / f"{tracking_id}{ext}"
        if p.is_file():
            return p
    return None


def copy_text(text: str) -> bool:
    """Copy ข้อความลง clipboard — ใช้ pyperclip (โหลดไว้แล้วที่ต้นไฟล์ เพื่อความเร็ว)."""     
    try:
        if pyperclip is None:
            import pyperclip as _pc
            _pc.copy(text)
        else:
            pyperclip.copy(text)
        return True
    except Exception:
        return False


def _wsl_path_to_win(path: Path) -> str:
    """Convert path to Windows-accessible form (//wsl.localhost/Distro/...) สำหรับเรียกจาก WSL."""
    distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu").strip() or "Ubuntu"
    s = str(path.resolve()).replace("\\", "/")
    return "//wsl.localhost/" + distro + ("/" + s.lstrip("/") if not s.startswith("/") else s)


def copy_image_to_clipboard(image_path: Path) -> bool:
    """Copy image to clipboard. On Windows: win32. On WSL: เรียก copy_image.py ผ่าน PowerShell."""
    if not image_path or not image_path.is_file():
        return False
    try:
        import io
        import subprocess
        from PIL import Image
        # --- Windows: win32clipboard (DIB + PNG ถ้าได้) ---
        if sys.platform == "win32":
            try:
                import win32clipboard
                image = Image.open(image_path)
                output = io.BytesIO()
                image.convert("RGB").save(output, "BMP")
                dib_data = output.getvalue()[14:]
                output.close()
                # PNG: อ่านจากไฟล์ตรง (ไม่ต้อง encode กลับ) เร็วกว่า image.save("PNG")
                if image_path.suffix.lower() == ".png":
                    with open(image_path, "rb") as f:
                        png_data = f.read()
                else:
                    png_io = io.BytesIO()
                    image.save(png_io, "PNG")
                    png_data = png_io.getvalue()
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
                    try:
                        fmt = win32clipboard.RegisterClipboardFormat("PNG")
                        win32clipboard.SetClipboardData(fmt, png_data)
                    except Exception:
                        pass
                finally:
                    win32clipboard.CloseClipboard()
                return True
            except ImportError:
                pass
        # --- WSL: เรียก Windows Python ผ่าน PowerShell (ใช้ copy_image_win.py ในโปรเจกต์นี้) ---
        if sys.platform == "linux":
            script_path = PROJECT_DIR / "copy_image_win.py"
            if script_path.is_file():
                try:
                    script_win = _wsl_path_to_win(script_path)
                    image_win = _wsl_path_to_win(image_path)
                    r = subprocess.run(
                        [
                            "powershell.exe",
                            "-NoProfile",
                            "-Command",
                            f"python '{script_win}' '{image_win}'",
                        ],
                        capture_output=True,
                        timeout=15,
                    )
                    if r.returncode == 0:
                        return True
                except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
                    pass
        # --- Linux (ไม่ใช่ WSL) หรือ fallback: xclip ---
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", str(image_path)],
                check=True, capture_output=True
            )
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
    except Exception:
        pass
    return False


def notify_done(
    done_count: int,
    not_found_count: int,
    not_found_orders: List[str],
    no_tracking_count: int = 0,
):
    """copy ສະຫຼຸບຜົນໄວ້ໃນ clipboard ໃຫ້ວາງໄດ້ທັນທີ"""
    lines: List[str] = []
    lines.append("ສົ່ງຄົບທຸກ Order ແລ້ວ")
    lines.append(f"ສົ່ງສຳເລັດ: {done_count} | ບໍ່ພົບ: {not_found_count}")
    if no_tracking_count > 0:
        lines.append(f"ບໍ່ມີ tracking ID ໃນ Sheet (ບໍ່ນຳສົ່ງ): {no_tracking_count} ລາຍການ")
    if not_found_orders:
        lines.append("ລາຍການທີ່ບໍ່ພົບ:")
        for o in not_found_orders[:15]:
            lines.append(f"- {o}")
        if len(not_found_orders) > 15:
            lines.append(f"... ແລະອີກ {len(not_found_orders) - 15}")
    text = "\n".join(lines)
    try:
        copy_text(text)
    except Exception:
        # ຖ້າ copy clipboard ບໍ່ສຳເລັດ ບໍ່ຈຳເປັນຕ້ອງເຮັດຫຍັງເພີ່ມ
        pass


def run_http_server(signal_queue: queue.Queue, port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path == "/enter":
                signal_queue.put("enter")
            elif path == "/next":
                signal_queue.put("next")
            elif path == "/not_found":
                signal_queue.put("not_found")
            elif path == "/undo":
                signal_queue.put("undo")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sheet_config_path = CONFIG_DIR / "sheet_config.json"
    page_config_path = CONFIG_DIR / "page_name_to_id.json"
    if not sheet_config_path.exists():
        print(f"❌ ບໍ່ພົບ {sheet_config_path}")
        return
    if not page_config_path.exists():
        print(f"❌ ບໍ່ພົບ {page_config_path}")
        return
    sheet_cfg = load_json(sheet_config_path)
    page_mapping = load_json(page_config_path)
    sheet_id = sheet_cfg.get("sheet_id") or sheet_cfg.get("sheet_ID")
    sheet_names = sheet_cfg.get("sheet_names") or [sheet_cfg.get("sheet_name", "Sheet1")]
    cred_path = sheet_cfg.get("credentials_path")
    if cred_path and not os.path.isabs(cred_path):
        cred_path = str(PROJECT_DIR / cred_path)
    if not sheet_id:
        print("❌ ໃຫ້ໃສ່ sheet_id ໃນ config/sheet_config.json")
        return

    print("ກຳລັງດຶງຂໍ້ມູນຈາກ Google Sheet...")
    workbook = None
    if cred_path and os.path.exists(cred_path):
        workbook = get_sheet_workbook(sheet_id, cred_path)
    if workbook is None and cred_path:
        print("❌ ບໍ່ພົບ credentials ຫຼື ເປີດ Sheet ບໍ່ໄດ້ (ເບິ່ງ path ແລະ pip install gspread google-auth)")
        return
    skipped_no_tracking = 0
    phone_map: Dict[str, str] = {}
    if workbook is not None:
        rows, skipped_no_tracking = read_rows_from_workbook(workbook, sheet_names, phone_map=phone_map)
    else:
        rows = []
    if not rows:
        print("❌ ບໍ່ພົບຂໍ້ມູນໃນ Sheet")
        return
    grouped: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for order_id, page_name, tracking_id, carrier in rows:
        grouped[page_name].append((order_id, tracking_id, carrier))
    pages_order = list(grouped.keys())
    msg = f"ດຶງຂໍ້ມູນແລ້ວ: {len(rows)} ລາຍການ ຈາກ {len(pages_order)} ເພຈ"
    if skipped_no_tracking > 0:
        msg += f" (ຂ້າມ {skipped_no_tracking} ລາຍການທີ່ບໍ່ມີ tracking ID)"
    if phone_map:
        msg += f" (📱 {len(phone_map)} ລາຍການ WhatsApp)"
    print(msg)

    bills_dir = PROJECT_DIR.parent / "bills"

    business_pages = get_business_page_names(page_mapping)

    signal_queue: queue.Queue = queue.Queue()
    server_thread = threading.Thread(target=run_http_server, args=(signal_queue, SIGNAL_PORT), daemon=True)
    server_thread.start()
    print(f"\nລໍຖ້າສັນຍານຈາກ AutoHotkey ທີ່ http://127.0.0.1:{SIGNAL_PORT}")
    print("   Ctrl+V / ດັບເບິລຄລິກ / Enter = ຂັ້ນຕໍ່ໄປ | ທຣິເປິລຄລິກ = ບໍ່ພົບ | Ctrl+Z = ຍ້ອນກັບ 1 ຂັ້ນ\n")

    state = "READY"
    page_idx = 0
    order_idx_in_page = 0
    current_page_name = ""
    current_orders: List[Tuple[str, str, str]] = []
    not_found_orders: List[str] = []
    done_orders: List[str] = []
    history: List[dict] = []
    bill_image_cache: Dict[str, Optional[Path]] = {}

    def get_inbox_url(pname: str) -> str:
        pid = get_page_id(pname, page_mapping)
        if not pid:
            return ""
        return build_inbox_url(pname, pid, business_pages, page_mapping)

    def save_state():
        history.append({
            "state": state,
            "page_idx": page_idx,
            "order_idx_in_page": order_idx_in_page,
            "current_page_name": current_page_name,
            "current_orders": list(current_orders),
            "not_found_orders": list(not_found_orders),
            "done_orders": list(done_orders),
        })

    def restore_state() -> bool:
        nonlocal state, page_idx, order_idx_in_page, current_page_name, current_orders, not_found_orders, done_orders
        if not history:
            return False
        snap = history.pop()
        state = snap["state"]
        page_idx = snap["page_idx"]
        order_idx_in_page = snap["order_idx_in_page"]
        current_page_name = snap["current_page_name"]
        current_orders = snap["current_orders"]
        not_found_orders = snap["not_found_orders"]
        done_orders = snap["done_orders"]
        return True

    def apply_advance() -> bool:
        """ເອີ້ນ prepare_step ແລ້ວພິມຂໍ້ຄວາມ; ສົ່ງຄືນ True ຖ້າ DONE (ໃຫ້ break) ຫຼື False ຖ້າຍັງຕໍ່"""
        nonlocal state
        result = prepare_step()
        if result[0] == "DONE":
            return True
        print(result[1])
        if result[0] == "OPEN_PAGE":
            state = "OPEN_PAGE"
        return False

    def handle_not_found() -> bool:
        """ບັນທຶກ Order ປັດຈຸບັນວ່າບໍ່ພົບ ແລ້ວໄປຂັ້ນຕໍ່ໄປ; ສົ່ງຄືນ True ຖ້າ DONE"""
        nonlocal state, order_idx_in_page
        save_state()
        order_id = current_orders[order_idx_in_page][0]
        not_found_orders.append(order_id)
        print(f"   ບໍ່ພົບ: Order {order_id} — ຂ້າມ Order ນີ້ (ບໍ່ copy ຂໍ້ຄວາມ/ຮູບ)")
        order_idx_in_page += 1
        state = "WAIT_CHAT"
        return apply_advance()

    def prepare_step():
        """Copy ຂໍ້ມູນໄປ clipboard ຕາມ state ປັດຈຸບັນ ແລ້ວສົ່ງຄືນຂໍ້ຄວາມສະແດງ"""
        nonlocal state, page_idx, order_idx_in_page, current_page_name, current_orders
        is_wa = _is_whatsapp_page(current_page_name) if current_page_name else False
        if state == "OPEN_PAGE":
            if is_wa:
                # WhatsApp: ข้ามขั้น OPEN_PAGE → ไปหาแชทเลย
                state = "WAIT_CHAT"
                return prepare_step()
            url = get_inbox_url(current_page_name)
            if url:
                copy_text(url)
            return "OPEN_PAGE", f"ເພຈ: {current_page_name} — ວາງລິ້ງ (Ctrl+V) ແລ້ວໄປຂັ້ນຕໍ່ໄປ"
        if state == "READY":
            if page_idx >= len(pages_order):
                return "DONE", ""
            current_page_name = pages_order[page_idx]
            current_orders = grouped[current_page_name]
            order_idx_in_page = 0
            is_wa = _is_whatsapp_page(current_page_name)
            if is_wa:
                state = "WAIT_CHAT"
                return prepare_step()
            url = get_inbox_url(current_page_name)
            if not url:
                not_found_orders.append(f"ເພຈ {current_page_name} (ບໍ່ມີ page_id)")
                page_idx += 1
                return prepare_step()
            copy_text(url)
            return "OPEN_PAGE", f"ເພຈ: {current_page_name} — ວາງລິ້ງ (Ctrl+V) ແລ້ວໄປຂັ້ນຕໍ່ໄປ"
        if state == "WAIT_CHAT":
            if order_idx_in_page >= len(current_orders):
                page_idx += 1
                state = "READY"
                return prepare_step()
            order_id, tracking_id, carrier = current_orders[order_idx_in_page]
            if is_wa:
                phone = phone_map.get(order_id, "")
                if not phone:
                    print(f"   ❌ ບໍ່ພົບເບີໂທ WhatsApp: Order {order_id} — ຂ້າມ")
                    not_found_orders.append(order_id)
                    order_idx_in_page += 1
                    return prepare_step()
                wa_msg = bill_tracking_customer_message(tracking_id, carrier)
                wa_url = _build_whatsapp_url(phone, wa_msg)
                copy_text(wa_url)
                n = order_idx_in_page + 1
                total = len(current_orders)
                return "WAIT_CHAT", (
                    f"📱 Order {n}/{total}: {order_id} → WhatsApp {_normalize_phone(phone)} — "
                    f"ວາງລິ້ງ (Ctrl+V) ໃນ browser ເພື່ອເປີດແຊັດ, ສົ່ງຂໍ້ຄວາມ → ດັບເບິລຄລິກ | "
                    f"popup 'ไม่ได้ใช้ WhatsApp' → ກົດ ຕົກລົງ ແລ້ວ Ctrl+Alt+N (ບໍ່ພົບ)"
                )
            copy_text(order_id)
            n = order_idx_in_page + 1
            total = len(current_orders)
            return "WAIT_CHAT", f"Order {n}/{total}: {order_id} — ວາງ Order ID (Ctrl+V) ໃນຊ່ອງຄົ້ນຫາ, ເລືອກແຊັດ → ດັບເບິລຄລິກ | ບໍ່ພົບ → ທຣິເປິລຄລິກ"
        if state == "WAIT_MSG":
            order_id, tracking_id, carrier = current_orders[order_idx_in_page]
            if is_wa:
                # WhatsApp: ข้อความถูก pre-fill ใน URL แล้ว → ข้ามขั้น WAIT_MSG ไป WAIT_SEND
                state = "WAIT_SEND"
                return prepare_step()
            msg = bill_tracking_customer_message(tracking_id, carrier)
            copy_text(msg)
            return "WAIT_MSG", f"Order {order_id} — ວາງຂໍ້ຄວາມ (Ctrl+V) ໃນແຊັດ"
        if state == "WAIT_SEND":
            order_id, tracking_id, _carrier = current_orders[order_idx_in_page]
            if is_wa:
                # WhatsApp: copy รูปให้วาง (ถ้ามี) หรือข้ามเลย
                if not (tracking_id or "").strip():
                    print(f"   ບໍ່ມີ tracking_id (WhatsApp): Order {order_id} — ຂ້າມຮູບ")
                else:
                    if tracking_id not in bill_image_cache:
                        bill_image_cache[tracking_id] = find_bill_image(bills_dir, tracking_id)
                    image_path = bill_image_cache[tracking_id]
                    if image_path:
                        ok = copy_image_to_clipboard(image_path)
                        if not ok:
                            copy_text(str(image_path))
                            print(f"   copy ຮູບບໍ່ສຳເລັດ: Order {order_id} — ໃຊ້ path ໄປແນບຮູບ")
                    else:
                        copy_text("")
                        print(f"   ບໍ່ພົບຮູບບິນ: Order {order_id}, tracking_id {tracking_id}")
                return "WAIT_SEND", (
                    f"📱 Order {order_id} — ວາງຮູບ (Ctrl+V) ໃນ WhatsApp ກົດສົ່ງ ແລ້ວດັບເບິລຄລິກ | "
                    f"popup 'ไม่ได้ใช้ WhatsApp' → ກົດ ຕົກລົງ ແລ້ວ Ctrl+Alt+N"
                )
            if not (tracking_id or "").strip():
                print(f"   ບໍ່ມີ tracking_id: Order {order_id}")
                copy_text("")
            else:
                if tracking_id not in bill_image_cache:
                    bill_image_cache[tracking_id] = find_bill_image(bills_dir, tracking_id)
                image_path = bill_image_cache[tracking_id]
                if image_path:
                    ok = copy_image_to_clipboard(image_path)
                    if not ok:
                        copy_text(str(image_path))
                        print(f"   copy ຮູບບໍ່ສຳເລັດ: Order {order_id}, tracking_id {tracking_id} — ໃຊ້ path ທີ່ copy ໄປແນບຮູບໃນແຊັດໄດ້")
                else:
                    copy_text("")
                    print(f"   ບໍ່ພົບຮູບບິນ: Order {order_id}, tracking_id {tracking_id} (ໂຟນເດີ {bills_dir})")
            return "WAIT_SEND", f"Order {order_id} — ວາງຮູບ (Ctrl+V) ກົດສົ່ງ ແລ້ວດັບເບິລຄລິກ"

    def wait_signal() -> str:
        return signal_queue.get()

    result = prepare_step()
    if result[0] == "DONE":
        print("❌ ບໍ່ມີເພຈທີ່ເປີດໄດ້ (ກວດ config)")
        return
    _, msg = result
    print(msg)
    if result[0] == "OPEN_PAGE":
        state = "OPEN_PAGE"

    while True:
        sig = wait_signal()

        if sig == "undo":
            if restore_state():
                result = prepare_step()
                if result[0] == "DONE":
                    break
                print(f"⏪ ຍ້ອນກັບ → {result[1]}")
            else:
                print("⏪ ບໍ່ມີຂັ້ນໃຫ້ຍ້ອນກັບອີກ")
            continue

        if state in ("OPEN_PAGE", "READY") and (sig == "enter" or sig == "next"):
            save_state()
            state = "WAIT_CHAT"
            if apply_advance():
                break
            continue

        if state == "WAIT_CHAT":
            if sig == "next":
                save_state()
                state = "WAIT_MSG"
                result = prepare_step()
                print(result[1])
            elif sig == "not_found" and handle_not_found():
                break
            continue

        if state == "WAIT_MSG":
            if sig == "next":
                save_state()
                state = "WAIT_SEND"
                result = prepare_step()
                print(result[1])
            elif sig == "not_found" and handle_not_found():
                break
            continue

        if state == "WAIT_SEND":
            if sig == "next":
                save_state()
                order_id = current_orders[order_idx_in_page][0]
                done_orders.append(order_id)
                order_idx_in_page += 1
                state = "WAIT_CHAT"
                if apply_advance():
                    break
            elif sig == "not_found" and handle_not_found():
                break
            continue

    print()
    print(f"   ສົ່ງສຳເລັດ: {len(done_orders)} | ບໍ່ພົບ: {len(not_found_orders)}")
    if skipped_no_tracking > 0:
        print(f"   ບໍ່ມີ tracking ID ໃນ Sheet (ບໍ່ນຳສົ່ງ): {skipped_no_tracking} ລາຍການ")
    if not_found_orders:
        for o in not_found_orders[:15]:
            print(f"   - {o}")
        if len(not_found_orders) > 15:
            print(f"   ... ແລະອີກ {len(not_found_orders) - 15}")

    # Copy ສະຫຼຸບຜົນໄປ clipboard ທັນທີ (ບໍ່ລໍຖ້າອັບເດດ Sheet) ໃຫ້ຮູ້ວ່າສົ່ງຄົບແລ້ວ
    notify_done(len(done_orders), len(not_found_orders), not_found_orders, skipped_no_tracking)
    print("   Copy ສະຫຼຸບຜົນໄວ້ໃນ clipboard ແລ້ວ — ວາງ (Ctrl+V) ໄດ້ທັນທີ")

    if done_orders and workbook is not None:
        update_sheet_sent_dates(workbook, sheet_names, done_orders)


if __name__ == "__main__":
    main()
