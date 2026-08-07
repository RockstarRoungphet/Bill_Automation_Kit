#!/usr/bin/env python3
"""
อ่าน CSV export จาก Google Sheet หรือเชื่อมต่อ Google Sheet โดยตรง
ดึงข้อมูล Order, ชื่อเพจ (Column I), Tracking ID (Column Z)
- คอลัมน์ A (index 0) = สถานะ (ต้องเป็น "📦ລໍຈັດສົ່ງ" เท่านั้น)
- คอลัมน์ D (index 3) = Order
- คอลัมน์ I (index 8) = ชื่อเพจ
- คอลัมน์ G (index 6) = ขนส่ง (ອານຸສິດ / ຮຸ່ງອາລຸນ)
- คอลัมน์ Z (index 25) = Tracking ID

ใช้:
  python3 read_sheet.py <path_to_csv>
  python3 read_sheet.py <path_to_csv> --output json
  python3 read_sheet.py --sheet <sheet_id> [--credentials <path>] [--sheet-name Sheet1]
"""

import csv
import json
import os
import sys
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Union

# คอลัมน์ที่ใช้: A=0, D=3, E=4, F=5, I=8, R=17, Z=25 (0-based index)
STATUS_COL_INDEX = 0
ORDER_COL_INDEX = 3
CUSTOMER_NAME_COL_INDEX = 4  # Column E
PHONE_COL_INDEX = 5  # Column F
PAGE_NAME_COL_INDEX = 8
SEND_DATE_COL_INDEX = 17  # Column R
SEND_DATE_COL_LETTER = "R"
TRACKING_COL_INDEX = 25
CARRIER_COL_INDEX = 6  # Column G: ขนส่ง

# สถานะที่ต้องเป็น (คอลัมน์ A)
REQUIRED_STATUS = "📦ລໍຈັດສົ່ງ"
REQUIRED_STATUS_DELIVERED = "🏁ຮອດປາຍທາງແລ້ວ"
# คอลัมน์ A = แจ้งถึงซ้ำ (เตือนลูกค้าอีกครั้ง)
REQUIRED_STATUS_DELIVERED_FOLLOWUP = "💬ແຈ້ງຮອດແລ້ວ"
NOTIFY_DELIVERED_STATUSES = (REQUIRED_STATUS_DELIVERED, REQUIRED_STATUS_DELIVERED_FOLLOWUP)
NOTIFY_STOCK_OUT_STATUSES = ("🗑️ໝົດ", "⏳ລໍສິນຄ້າ")
NOTIFY_STOCK_AVAILABLE_STATUSES = ("📢ແຈ້ງສິນຄ້າໝົດແລ້ວ",)

# คอลัมน์ V สำหรับบันทึก "ແຈ້ງຮອດແລ້ວ"
NOTIFIED_DELIVERED_COL_INDEX = 21
NOTIFIED_DELIVERED_COL_LETTER = "V"

# Header ที่อาจพบ
ORDER_HEADERS = ("Order", "order", "Order ID", "Order Id", "OrderID")
PAGE_NAME_HEADERS = ("ຊ່ອງທາງ", "ช่องทาง", "Channel", "channel", "Page", "page")
TRACKING_HEADERS = ("Tracking ID", "tracking_id", "Tracking Id", "เลขพัสดุ")
CARRIER_HEADERS = (
    "ຂົນສົ່ງ",
    "ขนส่ง",
    "Carrier",
    "carrier",
    "ຂນສົ່ງ",
    "Courier",
    "courier",
)


def find_column_index(headers: List[str], possible_names: Tuple[str, ...], default_index: int) -> int:
    """หาดัชนีคอลัมน์จาก header row"""
    for i, header in enumerate(headers):
        if header.strip() in possible_names:
            return i
    return default_index


def _parse_data_rows(
    header_row: List[str],
    data_rows: List[List[str]],
    required_status: Optional[Union[str, Tuple[str, ...]]] = None,
) -> List[Tuple[str, str, str, str]]:
    """
    ใช้ header กับแถวข้อมูล คืนรายการ (order_id, page_name, tracking_id หรือ "", carrier).
    - required_status=None หรือ REQUIRED_STATUS: กรองแถวที่สถานะตรง และ tracking_id ยาวอย่างน้อย 10 ตัวอักษร
    - required_status=REQUIRED_STATUS_DELIVERED: กรองแถวที่สถานะ = 🏁 เท่านั้น ไม่ตรวจสอบคอลัมน์ Z
    - required_status=tuple: กรองแถวที่สถานะอยู่ใน tuple และส่งแบบ text-only (ไม่ใช้ tracking)
    """
    if required_status is None:
        status_filter = REQUIRED_STATUS
        status_values = None
        is_text_only = False
    elif isinstance(required_status, tuple):
        status_filter = None
        status_values = required_status
        is_text_only = True
    else:
        status_filter = required_status
        status_values = None
        is_text_only = required_status == REQUIRED_STATUS_DELIVERED

    rows: List[Tuple[str, str, str, str]] = []
    order_col = find_column_index(header_row, ORDER_HEADERS, ORDER_COL_INDEX)
    page_name_col = find_column_index(header_row, PAGE_NAME_HEADERS, PAGE_NAME_COL_INDEX)
    tracking_col = find_column_index(header_row, TRACKING_HEADERS, TRACKING_COL_INDEX)
    carrier_col = find_column_index(header_row, CARRIER_HEADERS, CARRIER_COL_INDEX)
    max_col = max(STATUS_COL_INDEX, order_col, page_name_col, carrier_col, tracking_col)

    for cells in data_rows:
        cells = [str(x).strip() for x in cells]
        if len(cells) <= max_col:
            continue
        status = cells[STATUS_COL_INDEX] if STATUS_COL_INDEX < len(cells) else ""
        if status_values is not None:
            if status not in status_values:
                continue
        elif status != status_filter:
            continue
        order_id = cells[order_col] if order_col < len(cells) else ""
        page_name = cells[page_name_col] if page_name_col < len(cells) else ""
        if not order_id or not page_name:
            continue
        carrier = cells[carrier_col] if carrier_col < len(cells) else ""
        if is_text_only:
            rows.append((order_id, page_name, "", carrier))
            continue
        # WhatsApp rows: ไม่ต้องมี tracking_id (ใช้เบอร์โทรแทน)
        if page_name.strip().lower() == "whatsapp":
            tracking_id = cells[tracking_col] if tracking_col < len(cells) else ""
            rows.append((order_id, page_name, tracking_id, carrier))
            continue
        tracking_id = cells[tracking_col] if tracking_col < len(cells) else ""
        if not tracking_id or tracking_id in TRACKING_HEADERS:
            continue
        if len(tracking_id) < 10:
            continue
        rows.append((order_id, page_name, tracking_id, carrier))
    return rows


def read_rows_from_csv(csv_path: str) -> List[Tuple[str, str, str, str]]:
    """
    อ่าน CSV และคืนรายการ (order_id, page_name, tracking_id, carrier)
    กรองเฉพาะแถวที่:
    - คอลัมน์ A (สถานะ) = "📦ລໍຈັດສົ່ງ"
    - มี tracking_id และยาวอย่างน้อย 10 ตัวอักษร
    """
    rows: List[Tuple[str, str, str, str]] = []

    if not os.path.exists(csv_path):
        print(f"❌ ไม่พบไฟล์: {csv_path}", file=sys.stderr)
        return rows
    
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header_row: Optional[List[str]] = None
            
            # หา header row
            for row in reader:
                cells = [str(x).strip() for x in row]
                if not cells or all(not c for c in cells):
                    continue
                # ตรวจสอบว่าเป็น header row หรือไม่
                if any(h in cells for h in ORDER_HEADERS) or any(h in cells for h in TRACKING_HEADERS):
                    header_row = cells
                    break
                # ถ้าไม่เจอ header ให้ใช้แถวแรกเป็น header
                if header_row is None:
                    header_row = cells
                    break
            
            if not header_row:
                print("⚠️ ไม่พบ header row ใน CSV", file=sys.stderr)
                return rows

            data_rows = list(reader)
            rows = _parse_data_rows(header_row, data_rows)
    
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการอ่าน CSV: {e}", file=sys.stderr)
        return rows
    
    return rows


def read_rows_from_google_sheet(
    sheet_id: str,
    sheet_name: str = "Sheet1",
    credentials_path: Optional[str] = None,
    row_map: Optional[Dict[Tuple[str, str], Tuple[str, int]]] = None,
    required_status: Optional[Union[str, Tuple[str, ...]]] = None,
    customer_name_map: Optional[Dict[str, str]] = None,
    phone_map: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, str, str, str]]:
    """
    อ่าน Google Sheet โดยตรง (ต้องแชร์ Sheet ให้ Service Account แล้ว)
    คืนรายการ (order_id, page_name, tracking_id, carrier) หรือ (order_id, page_name, sheet_name, carrier) เมื่อโหมดแจ้งถึง

    - required_status=None: ใช้ REQUIRED_STATUS (ລໍຈັດສົ່ງ), row_map key = (order_id, tracking_id)
    - required_status=REQUIRED_STATUS_DELIVERED: ไม่ตรวจสอบคอลัมน์ Z, row_map key = (order_id, sheet_name)
    - required_status=tuple: โหมด text-only ที่กรองสถานะคอลัมน์ A ตามค่าใน tuple
    - customer_name_map: ถ้าส่งมา จะเติม order_id -> customer_name (คอลัมน์ E) สำหรับ fuzzy matching
    - phone_map: ถ้าส่งมา จะเติม order_id -> phone_number (คอลัมน์ F) สำหรับ WhatsApp
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("❌ ต้องติดตั้ง: pip install gspread google-auth", file=sys.stderr)
        return []

    if not credentials_path:
        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        # โฟลเดอร์ config อยู่ระดับเดียวกับโฟลเดอร์ scripts
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_path = os.path.join(script_dir, "..", "config", "google_credentials.json")
        credentials_path = os.path.normpath(default_path)
    if not os.path.exists(credentials_path):
        print(f"❌ ไม่พบไฟล์ credentials: {credentials_path}", file=sys.stderr)
        return []

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(sheet_id)
        worksheet = workbook.worksheet(sheet_name)
        all_rows = worksheet.get_all_values()
    except Exception as e:
        print(f"❌ ไม่สามารถอ่าน Google Sheet ได้: {e}", file=sys.stderr)
        return []

    if not all_rows:
        return []

    if required_status is None:
        status_filter = REQUIRED_STATUS
        status_values = None
        is_text_only = False
    elif isinstance(required_status, tuple):
        status_filter = None
        status_values = required_status
        is_text_only = True
    else:
        status_filter = required_status
        status_values = None
        is_text_only = required_status == REQUIRED_STATUS_DELIVERED

    header_row = [str(c).strip() for c in all_rows[0]]
    data_rows = all_rows[1:]
    rows = _parse_data_rows(header_row, data_rows, required_status=required_status)

    # ดึง phone_map สำหรับแถว WhatsApp (กรองเฉพาะสถานะที่ตรง)
    if phone_map is not None:
        order_col = find_column_index(header_row, ORDER_HEADERS, ORDER_COL_INDEX)
        page_col = find_column_index(header_row, PAGE_NAME_HEADERS, PAGE_NAME_COL_INDEX)
        for cells in data_rows:
            cells_str = [str(x).strip() for x in cells]
            if len(cells_str) <= max(order_col, page_col):
                continue
            st = cells_str[STATUS_COL_INDEX] if STATUS_COL_INDEX < len(cells_str) else ""
            if status_values is not None:
                if st not in status_values:
                    continue
            elif st != status_filter:
                continue
            pname = cells_str[page_col] if page_col < len(cells_str) else ""
            if pname.lower().strip() == "whatsapp":
                oid = cells_str[order_col] if order_col < len(cells_str) else ""
                phone = cells_str[PHONE_COL_INDEX] if PHONE_COL_INDEX < len(cells_str) else ""
                if oid and phone:
                    phone_map[oid] = phone

    if is_text_only:
        # โหมดແຈ້ງຮອດແລ້ວ: คืน (order_id, page_name, sheet_name, carrier), row_map (order_id, sheet_name) -> (sheet_name, row_num)
        rows_with_sheet = [(oid, pname, sheet_name, car) for oid, pname, _, car in rows]
        if row_map is not None or customer_name_map is not None:
            order_col = find_column_index(header_row, ORDER_HEADERS, ORDER_COL_INDEX)
            for idx, cells in enumerate(data_rows):
                cells_str = [str(x).strip() for x in cells]
                if len(cells_str) <= order_col:
                    continue
                st = cells_str[STATUS_COL_INDEX] if STATUS_COL_INDEX < len(cells_str) else ""
                if status_values is not None:
                    if st not in status_values:
                        continue
                elif st != status_filter:
                    continue
                oid = cells_str[order_col] if order_col < len(cells_str) else ""
                if oid:
                    if row_map is not None:
                        row_map[(oid, sheet_name)] = (sheet_name, idx + 2)
                    if customer_name_map is not None:
                        cname = cells_str[CUSTOMER_NAME_COL_INDEX] if CUSTOMER_NAME_COL_INDEX < len(cells_str) else ""
                        if cname:
                            customer_name_map[oid] = cname
        return rows_with_sheet

    if row_map is not None or customer_name_map is not None:
        order_col = find_column_index(header_row, ORDER_HEADERS, ORDER_COL_INDEX)
        tracking_col = find_column_index(header_row, TRACKING_HEADERS, TRACKING_COL_INDEX)
        for idx, cells in enumerate(data_rows):
            cells_str = [str(x).strip() for x in cells]
            if len(cells_str) <= max(order_col, tracking_col):
                continue
            st = cells_str[STATUS_COL_INDEX] if STATUS_COL_INDEX < len(cells_str) else ""
            if st != status_filter:
                continue
            oid = cells_str[order_col] if order_col < len(cells_str) else ""
            tid = cells_str[tracking_col] if tracking_col < len(cells_str) else ""
            if oid and tid:
                if row_map is not None:
                    row_map[(oid, tid)] = (sheet_name, idx + 2)
                if customer_name_map is not None and CUSTOMER_NAME_COL_INDEX < len(cells_str):
                    cname = cells_str[CUSTOMER_NAME_COL_INDEX].strip()
                    if cname:
                        customer_name_map[oid] = cname

    return rows


def _get_credentials_path(credentials_path: Optional[str] = None) -> Optional[str]:
    """Resolve credentials path from argument, env var, or default location."""
    if not credentials_path:
        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_path = os.path.join(script_dir, "..", "config", "google_credentials.json")
        credentials_path = os.path.normpath(default_path)
    return credentials_path


def batch_update_send_dates(
    sheet_id: str,
    updates: List[Tuple[str, int, str]],
    credentials_path: Optional[str] = None,
) -> bool:
    """Batch update Column R with send dates for successfully sent orders.
    updates: [(sheet_name, row_number, date_string), ...]
    """
    if not updates:
        return True
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("   pip install gspread google-auth", file=sys.stderr)
        return False

    credentials_path = _get_credentials_path(credentials_path)
    if not credentials_path or not os.path.exists(credentials_path):
        print(f"   ไม่พบ credentials: {credentials_path}", file=sys.stderr)
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
            batch = []
            for row_num, date_str in cells:
                cell_ref = f"{SEND_DATE_COL_LETTER}{row_num}"
                batch.append({"range": cell_ref, "values": [[date_str]]})
            if batch:
                ws.batch_update(batch)
                print(f"   อัปเดต Column R ในชีต '{sn}': {len(batch)} แถว")

        return True
    except Exception as e:
        print(f"   ไม่สามารถอัปเดต Google Sheet: {e}", file=sys.stderr)
        return False


def batch_update_notified_delivered(
    sheet_id: str,
    updates: List[Tuple[str, int]],
    credentials_path: Optional[str] = None,
    value: str = "💬ແຈ້ງຮອດແລ້ວ",
) -> bool:
    """Batch update Column V with a custom notify value for successfully processed orders.
    updates: [(sheet_name, row_number), ...]
    """
    if not updates:
        return True
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("   pip install gspread google-auth", file=sys.stderr)
        return False

    credentials_path = _get_credentials_path(credentials_path)
    if not credentials_path or not os.path.exists(credentials_path):
        print(f"   ไม่พบ credentials: {credentials_path}", file=sys.stderr)
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
            batch = []
            for row_num in row_nums:
                cell_ref = f"{NOTIFIED_DELIVERED_COL_LETTER}{row_num}"
                batch.append({"range": cell_ref, "values": [[value]]})
            if batch:
                ws.batch_update(batch)
                print(f"   อัปเดต Column V ในชีต '{sn}': {len(batch)} แถว")

        return True
    except Exception as e:
        print(f"   ไม่สามารถอัปเดต Google Sheet: {e}", file=sys.stderr)
        return False


def main():
    args = sys.argv[1:]
    output_format = "text"
    credentials_path = None
    sheet_name = "Sheet1"

    while "--output" in args:
        i = args.index("--output")
        if i + 1 < len(args):
            output_format = args[i + 1].lower()
        args = args[:i] + args[i + 2:]
    while "--credentials" in args:
        i = args.index("--credentials")
        if i + 1 < len(args):
            credentials_path = args[i + 1]
        args = args[:i] + args[i + 2:]
    while "--sheet-name" in args:
        i = args.index("--sheet-name")
        if i + 1 < len(args):
            sheet_name = args[i + 1]
        args = args[:i] + args[i + 2:]

    if "--sheet" in args:
        i = args.index("--sheet")
        if i + 1 >= len(args):
            print("ใช้: python3 read_sheet.py --sheet <sheet_id> [--credentials <path>] [--sheet-name Sheet1] [--output json|text]")
            sys.exit(1)
        sheet_id = args[i + 1]
        rows = read_rows_from_google_sheet(sheet_id, sheet_name=sheet_name, credentials_path=credentials_path)
    elif len(args) < 1:
        print("ใช้: python3 read_sheet.py <path_to_csv> [--output json|text]")
        print("     python3 read_sheet.py --sheet <sheet_id> [--credentials <path>] [--sheet-name Sheet1] [--output json|text]")
        sys.exit(1)
    else:
        csv_path = args[0]
        rows = read_rows_from_csv(csv_path)

    if output_format == "json":
        result = [
            {"order_id": o, "page_name": p, "tracking_id": t, "carrier": c}
            for o, p, t, c in rows
        ]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"พบ {len(rows)} แถวที่มีสถานะ '{REQUIRED_STATUS}' และ Tracking ID:")
        for order_id, page_name, tracking_id, carrier in rows:
            print(
                f"  Order: {order_id or '(ว่าง)'} | เพจ: {page_name or '(ว่าง)'} | "
                f"Tracking: {tracking_id} | Carrier: {carrier or '(ว่าง)'}"
            )


if __name__ == "__main__":
    main()
