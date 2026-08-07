#!/usr/bin/env python3
"""
ถ่ายภาพหน้าจอบิลจากเว็บ Anousith ตาม Tracking ID
- เปิด URL บิลแล้ว screenshot เก็บลงโฟลเดอร์ bill_images/ (ชื่อไฟล์ = tracking_id.png)
- ใช้ร่วมกับ send_bill_from_sheet.py (ส่งข้อความ + แนบรูป)
- ตอนอ่าน CSV จะกรองเฉพาะแถวที่คอลัมน์ A = "📦ລໍຈັດສົ່ງ" และคอลัมน์ Z มีข้อมูล

URL สองแบบ:
  - สาธารณะ (ค่าเริ่มต้น): ใครมีเลขบิลก็ค้นหาได้ — แสดงบิลเดียวต่อเลขบิล ไม่จำกัด 100 รายการ ไม่ต้องล็อกอิน (แนะนำ)
  - ส่วนตัว (--private): หน้า bill_item 100 บิลต่อหน้า — ใช้ URL เปิดหลายหน้า (bill_item, bill_item?page=2, ...) แล้วถ่ายเฉพาะการ์ดที่ตรงรายการเรา ต้องล็อกอิน

ใช้:
  python3 capture_bill_screenshot.py <path_to_csv>     # ถ่ายเฉพาะแถวที่ผ่านเงื่อนไข (URL สาธารณะ)
  python3 capture_bill_screenshot.py --tracking 8260294677122   # ถ่ายบิลเดียว
  python3 capture_bill_screenshot.py <path_to_csv> --private --user-data-dir /path/to/chrome/profile   # ใช้หน้าบิลส่วนตัว (ต้องล็อกอินใน Chrome profile นั้น)
  python3 capture_bill_screenshot.py <path_to_csv> --private --storage-state auth.json   # ใช้ cookies จาก auth.json (บันทึกจาก save_auth_state.py)
  python3 capture_bill_screenshot.py <path_to_csv> --private --storage-state auth.json --start-date 2026-01-01 --end-date 2026-02-02   # กำหนดช่วงวันที่ (YYYY-MM-DD)
"""

import asyncio
import csv
import json
import math
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional, Set, Tuple

# โหลด Playwright แบบ lazy (ถ้าไม่มีจะแจ้งให้ติดตั้ง)
try:
    from playwright.sync_api import sync_playwright
    from playwright.async_api import async_playwright
except ImportError:
    print("❌ ต้องติดตั้ง Playwright ก่อน: pip install playwright && playwright install chromium")
    sys.exit(1)

from capture_playwright_nav import goto_anousith_bill_page, goto_anousith_bill_page_sync

# URL สาธารณะ: ใครมีเลขบิลก็ค้นหาได้
ANOUSITH_BILL_URL = "https://app.anousith.express/landing/search_tracking/search_item?_bill_detail={tracking_id}"
# หน้าบิลส่วนตัว (ต้องล็อกอิน): ฐาน URL + pagination หน้า 1 = bill_item, หน้า 2+ = bill_item?page=N
BASE_BILL_ITEM_URL = "https://app.anousith.express/nextday/item_bill/bill_item"
ANOUSITH_BILL_ITEM_URL = BASE_BILL_ITEM_URL + "?search={tracking_id}"  # ใช้เมื่อถ่ายทีละบิล (เก่า)
BILLS_PER_PAGE = 100

TRACKING_HEADERS = ("Tracking ID", "tracking_id", "Tracking Id", "เลขพัสดุ")
DEFAULT_BILLS_DIR = "bill_images"
VIEWPORT = {"width": 430, "height": 932}
ENV_FILE = ".env"

STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  try { delete Object.getPrototypeOf(navigator).webdriver; } catch {}
  if (!window.chrome) window.chrome = {};
  if (!window.chrome.runtime) window.chrome.runtime = { id: undefined };
  Object.defineProperty(navigator, 'languages', { get: () => ['th-TH','th','lo','en-US','en'] });
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
  for (const k of ['__playwright','__pw_manual','__PW_inspect']) {
    try { delete window[k]; } catch {}
  }
})();
"""

STEALTH_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
]

# ใช้ config จากโปรเจกต์ no_api_send_bill_manual ร่วมกับ run_manual.py
PROJECT_DIR = Path(__file__).resolve().parent
MANUAL_DIR = PROJECT_DIR / "no_api_send_bill_manual"
CONFIG_DIR = MANUAL_DIR / "config"
SHEET_CONFIG_PATH = CONFIG_DIR / "sheet_config.json"
SHEET_STATUS_COL = 0
SHEET_REQUIRED_STATUS = "📦ລໍຈັດສົ່ງ"


def _load_dotenv(path: str = None) -> None:
    """โหลด KEY=VALUE จากไฟล์ .env ใส่ใน os.environ (ไม่เขียนทับค่าที่มีอยู่แล้ว)"""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ENV_FILE)
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value
    except Exception:
        pass

# กรองเฉพาะแถวที่คอลัมน์ A = ค่านี้ และคอลัมน์ Z มีข้อมูล ถึงจะถ่ายบิล
FILTER_COL_A_VALUE = "📦ລໍຈັດສົ່ງ"
COL_A_INDEX = 0
# คอลัมน์ G ใน Excel = index 6 (carrier: Anousith vs HAL)
COL_G_INDEX = 6
SHEET_CARRIER_ANOUSITH = "ອານຸສິດ"
COL_Z_INDEX = 25  # คอลัมน์ Z ใน Excel = index 25


def _looks_like_tracking_id(value: str) -> bool:
    """ตรวจว่าเป็นเลขติดตามพัสดุที่ใช้ได้ (ไม่ใช่วันที่หรือหัวคอลัมน์)"""
    if not value or value in TRACKING_HEADERS:
        return False
    if "/" in value and len(value) <= 12:  # หลีกเลี่ยงค่าแบบ 12/01/2026
        return False
    return len(value) >= 10


def _find_col(headers: List[str], names: Tuple[str, ...], default: int) -> int:
    """หาดัชนีคอลัมน์จาก header ที่ตรงกับ names อย่างใดอย่างหนึ่ง"""
    for i, h in enumerate(headers):
        if str(h).strip() in names:
            return i
    return default


def _read_tracking_ids_from_sheet() -> Tuple[List[str], int]:
    """อ่าน Tracking ID จาก Google Sheet (ใช้ config ร่วมกับ run_manual.py)

    - กรองเฉพาะแถวที่คอลัมน์ A = 📦ລໍຈັດສົ່ງ และคอลัมน์ G = Anousith (ອານຸສິດ) เท่านั้น — ไม่รวม HAL (ຮຸ່ງອາລຸນ)
    - ใช้คอลัมน์ที่ header ตรงกับ TRACKING_HEADERS เป็นแหล่ง tracking ID (หรือ fallback เป็นคอลัมน์ Z)
    คืนค่า: (รายการ tracking_id, จำนวนแถวที่มีสถานะ + carrier Anousith แต่ไม่มี tracking ID ที่ใช้ได้)
    """
    if not SHEET_CONFIG_PATH.is_file():
        print(f"❌ ບໍ່ພົບ config: {SHEET_CONFIG_PATH}")
        return [], 0
    try:
        with open(SHEET_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"❌ ອ່ານ config ບໍ່ໄດ້: {e}")
        return [], 0

    sheet_id = cfg.get("sheet_id") or cfg.get("sheet_ID")
    sheet_names = cfg.get("sheet_names") or [cfg.get("sheet_name", "Sheet1")]
    cred_path = cfg.get("credentials_path")
    if cred_path and not os.path.isabs(cred_path):
        cred_path = str(MANUAL_DIR / cred_path)
    if not sheet_id or not cred_path:
        print("❌ config/sheet_config.json ບໍ່ຄົບ: ຕ້ອງມີ sheet_id, sheet_names, credentials_path")
        return [], 0

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("❌ ຕ້ອງຕິດຕັ້ງ: pip install gspread google-auth")
        return [], 0
    if not os.path.exists(cred_path):
        print(f"❌ ບໍ່ພົບ credentials: {cred_path}")
        return [], 0

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(sheet_id)

    ids: List[str] = []
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
        track_col = _find_col(header, TRACKING_HEADERS, COL_Z_INDEX)
        for cells in all_rows[1:]:
            cells = [str(x).strip() for x in cells]
            need_len = max(COL_A_INDEX, COL_G_INDEX, track_col)
            if len(cells) <= need_len:
                continue
            if (cells[COL_A_INDEX] if COL_A_INDEX < len(cells) else "") != FILTER_COL_A_VALUE:
                continue
            carrier = cells[COL_G_INDEX] if COL_G_INDEX < len(cells) else ""
            if carrier != SHEET_CARRIER_ANOUSITH:
                continue
            z_val = cells[track_col] if track_col < len(cells) else ""
            if not z_val or not _looks_like_tracking_id(z_val):
                skipped_no_tracking += 1
                continue
            ids.append(z_val)

    ids = list(dict.fromkeys(ids))  # ลบซ้ำแต่รักษาลำดับ
    return ids, skipped_no_tracking


def _screenshot_public_page(page, out_path: str) -> None:
    """ถ่ายเฉพาะส่วนบิลหน้า search_item (สาธารณะ): ตั้งแต่ ຜົນການຄົ້ນຫາ ถึงก่อน ລາຍລະອຽດສະຖານະ"""
    result_header = page.get_by_text("ຜົນການຄົ້ນຫາ").first
    status_el = page.get_by_text("ລາຍລະອຽດສະຖານະ").first
    if result_header.count() > 0 and status_el.count() > 0:
        result_box = result_header.bounding_box()
        status_box = status_el.bounding_box()
        if result_box and status_box and status_box["y"] > result_box["y"]:
            vw = VIEWPORT["width"]
            top_y = max(0, result_box["y"] - 8)
            bottom_y = status_box["y"] - 10
            height = bottom_y - top_y
            if height > 50:
                page.screenshot(path=out_path, clip={"x": 0, "y": top_y, "width": vw, "height": height})
                return
    raise ValueError("ไม่พบตำแหน่งบิล")

def _screenshot_private_page(page, out_path: str) -> None:
    """ถ่ายเฉพาะการ์ดบิลหน้า bill_item (ส่วนตัว): จาก ເລກບິນ ถึงปุ่ม ແຊຣບິນ / ລວມທັງໝົດ"""
    top_el = page.get_by_text("ເລກບິນ").first
    if top_el.count() == 0:
        raise ValueError("ไม่พบເລກບິນ (อาจยังไม่ล็อกอิน)")
    top_box = top_el.bounding_box()
    if not top_box:
        raise ValueError("ไม่พบตำแหน่งເລກບິນ")
    vw = VIEWPORT["width"]
    top_y = max(0, top_box["y"] - 8)
    # หาจุดล่าง: ปุ่ม ແຊຣບິນ หรือ ລວມທັງໝົດ ครั้งถัดไป (บัตรถัดไป)
    share_btn = page.get_by_text("ແຊຣບິນ").first
    if share_btn.count() > 0:
        share_box = share_btn.bounding_box()
        if share_box and share_box["y"] > top_y:
            height = share_box["y"] + share_box["height"] - top_y + 10
            if height > 100:
                page.screenshot(path=out_path, clip={"x": 0, "y": top_y, "width": vw, "height": min(height, 2000)})
                return
    # fallback: หา ລວມທັງໝົດ แรกแล้ว clip ลงไปอีกนิด
    total_el = page.get_by_text("ລວມທັງໝົດ").first
    if total_el.count() > 0:
        total_box = total_el.bounding_box()
        if total_box:
            height = total_box["y"] + 80 - top_y
            if height > 100:
                page.screenshot(path=out_path, clip={"x": 0, "y": top_y, "width": vw, "height": min(height, 2000)})
                return
    page.screenshot(path=out_path, full_page=True)


def _bill_item_page_url(
    page_num: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """URL หน้าบิลส่วนตัว: หน้า 1 = bill_item, หน้า 2+ = bill_item?page=N
    ถ้าระบุ start_date และ end_date (YYYY-MM-DD) ใช้ bill_item?startDate=...&endDate=...&page=N"""
    if start_date and end_date:
        return f"{BASE_BILL_ITEM_URL}?startDate={start_date}&endDate={end_date}&page={page_num}"
    if page_num <= 1:
        return BASE_BILL_ITEM_URL
    return f"{BASE_BILL_ITEM_URL}?page={page_num}"


# --- โหมด private แบบ async: โหลดหลายหน้าพร้อมกัน + ถ่ายภาพเป็น wave ---

async def _get_tracking_ids_on_page(page) -> Set[str]:
    """ดึงรายการ tracking ID ที่ปรากฏในการ์ดบิลบนหน้านี้ (ใช้จัด wave ถ่ายภาพ) — ดึงข้อความทุกการ์ดครั้งเดียวแทนทีละอัน"""
    ids: Set[str] = set()
    try:
        texts = await page.locator("div").filter(has_text="ແຊຣບິນ").all_inner_texts()
    except Exception:
        return ids
    for text in texts:
        for part in text.split():
            part = part.strip()
            if part.isdigit() and len(part) >= 10:
                ids.add(part)
    return ids


async def _screenshot_one_card_async(page, tracking_id: str, out_path: str) -> bool:
    """เวอร์ชัน async ของการถ่ายการ์ดเดียวบนหน้า bill_item — ใช้ evaluate หาการ์ดที่เล็กที่สุดครั้งเดียวแทนวน bounding_box ทีละอัน"""
    marker = "ແຊຣບິນ"
    try:
        idx = await page.evaluate(
            """([tid, m]) => {
                const divs = Array.from(document.querySelectorAll("div")).filter(d =>
                    d.textContent && d.textContent.includes(tid) && d.textContent.includes(m)
                );
                let minArea = Infinity, bestIdx = -1;
                divs.forEach((d, i) => {
                    const r = d.getBoundingClientRect();
                    const area = r.width * r.height;
                    if (area > 0 && area < minArea) { minArea = area; bestIdx = i; }
                });
                return bestIdx;
            }""",
            [tracking_id, marker],
        )
    except Exception:
        return False
    if idx < 0:
        return False
    candidates = page.locator("div").filter(has_text=tracking_id).filter(has_text=marker)
    try:
        await candidates.nth(idx).screenshot(path=out_path)
        return True
    except Exception:
        return False


async def _goto_all_anousith_pages(pages: List, urls: List[str]) -> None:
    await asyncio.gather(
        *[goto_anousith_bill_page(pg, url) for pg, url in zip(pages, urls)]
    )


async def _try_auto_login_async(page, user: str, password: str) -> bool:
    """กรอก user/password แล้วกดปุ่มเข้าสู่ระบบบนหน้า login (async)"""
    user = (user or "").strip()
    password = (password or "").strip()
    if not user or not password:
        return False
    try:
        user_loc = page.locator(
            "input[type=text], input[type=email], input[type=tel], input[name=username], input[name=email], input[name=user], input[name=phone]"
        )
        if await user_loc.count() == 0:
            return False
        await user_loc.first.fill(user)
        pass_loc = page.locator("input[type=password]")
        if await pass_loc.count() == 0:
            return False
        await pass_loc.first.fill(password)
        submit_loc = page.locator(
            "button[type=submit], input[type=submit], "
            "button:has-text('ເຂົ້າສູ່ລະບົບ'), button:has-text('เข้าสู่ระบบ'), button:has-text('ล็อกอิน'), button:has-text('Login'), button:has-text('Sign in'), "
            "a:has-text('ເຂົ້າສູ່ລະບົບ'), a:has-text('เข้าสู่ระบบ'), a:has-text('ล็อกอิน'), a:has-text('Login')"
        )
        if await submit_loc.count() == 0:
            return False
        await submit_loc.first.click()
        await page.wait_for_timeout(2000)
        return True
    except Exception:
        return False


async def async_capture_private_paginated(
    user_data_dir: Optional[str],
    storage_state_path: Optional[str],
    tracking_ids: List[str],
    bills_dir: str,
    wait_sec: float = 3,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Tuple[int, Set[str]]:
    """โหลด P หน้าบิลพร้อมกัน (bill_item, bill_item?page=2, ... หรือมี startDate/endDate) แล้วถ่ายการ์ดที่ตรงรายการเราเป็น wave (เร็วขึ้น)"""
    os.makedirs(bills_dir, exist_ok=True)
    wanted: Set[str] = set(tracking_ids)
    num_pages = max(1, math.ceil(len(tracking_ids) / BILLS_PER_PAGE))
    t0 = time.perf_counter()

    async with async_playwright() as p:
        if user_data_dir:
            context = await p.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,
                viewport=VIEWPORT,
                args=STEALTH_CHROME_ARGS,
            )
            await context.add_init_script(STEALTH_INIT_SCRIPT)
            browser = None
        else:
            browser = await p.chromium.launch(headless=True, args=STEALTH_CHROME_ARGS)
            context = await browser.new_context(
                viewport=VIEWPORT,
                storage_state=storage_state_path,
            )
            await context.add_init_script(STEALTH_INIT_SCRIPT)
        t1 = time.perf_counter()

        try:
            # สร้าง P หน้าแล้วโหลด URL พร้อมกัน
            pages: List = list(await asyncio.gather(*[context.new_page() for _ in range(num_pages)]))
            urls = [_bill_item_page_url(p, start_date, end_date) for p in range(1, num_pages + 1)]
            t2 = time.perf_counter()

            await _goto_all_anousith_pages(pages, urls)
            t3 = time.perf_counter()

            await asyncio.gather(*[pg.wait_for_timeout(int(wait_sec * 1000)) for pg in pages])
            t4 = time.perf_counter()

            # ถ้าเจอหน้า login (session หมดอายุ) ล็อกอินอัตโนมัติจาก .env แล้วโหลดหน้าบิลใหม่
            pass_visible = (await pages[0].locator("input[type=password]").count()) > 0
            if pass_visible:
                user = os.environ.get("ANOUSITH_USER", "").strip()
                password = os.environ.get("ANOUSITH_PASSWORD", "").strip()
                if not user or not password:
                    print("\n⚠️ Session หมดอายุ — เจอหน้า login แต่ไม่มี user/password ใน .env")
                    print("   ใส่ ANOUSITH_USER และ ANOUSITH_PASSWORD ในไฟล์ .env แล้วรันใหม่")
                    sys.exit(1)
                print("\n🔄 เจอหน้า login — กำลังล็อกอินอัตโนมัติจาก .env...")
                if await _try_auto_login_async(pages[0], user, password):
                    await pages[0].wait_for_timeout(5000)
                    await _goto_all_anousith_pages(pages, urls)
                    await asyncio.gather(*[pg.wait_for_timeout(int(wait_sec * 1000)) for pg in pages])
                else:
                    print("⚠️ ล็อกอินอัตโนมัติไม่สำเร็จ — กรุณารัน save_auth_state.py แล้วล็อกอินด้วยมือ")
                    sys.exit(1)

            # ดูว่าแต่ละหน้ามี tracking ID อะไรบ้าง
            page_ids: List[Set[str]] = await asyncio.gather(
                *[_get_tracking_ids_on_page(pg) for pg in pages]
            )
            t5 = time.perf_counter()

            id_to_page: dict = {}
            for tid in wanted:
                for p_idx, p_ids in enumerate(page_ids):
                    if tid in p_ids:
                        id_to_page[tid] = p_idx
                        break

            # จัดกลุ่ม: แต่ละหน้ามีรายการ id อะไรบ้าง (เรียงตามที่เราต้องการ)
            page_assignments: List[List[str]] = [[] for _ in range(num_pages)]
            for tid in tracking_ids:
                if tid in id_to_page:
                    page_assignments[id_to_page[tid]].append(tid)
            t6 = time.perf_counter()

            # ถ่ายภาพเป็น wave: แต่ละ wave ถ่ายจากทุกหน้าที่มีรายการใน wave นั้น
            captured: Set[str] = set()
            total_bills = len(tracking_ids)
            max_len = max(len(a) for a in page_assignments) or 1
            for wave_idx in range(max_len):
                tasks = []
                for p_idx in range(num_pages):
                    if wave_idx < len(page_assignments[p_idx]):
                        tid = page_assignments[p_idx][wave_idx]
                        out_path = os.path.join(bills_dir, f"{tid}.png")
                        tasks.append(_screenshot_one_card_async(pages[p_idx], tid, out_path))
                if tasks:
                    results = await asyncio.gather(*tasks)
                    idx = 0
                    for p_idx in range(num_pages):
                        if wave_idx < len(page_assignments[p_idx]):
                            if results[idx]:
                                captured.add(page_assignments[p_idx][wave_idx])
                            idx += 1
                    progress = f"ถ่ายได้ {len(captured)}/{total_bills} รายการ"
                    # In a terminal, update one line with \r. In UI/pipe, print newline and let UI replace the last progress line.
                    if sys.stdout.isatty():
                        print("\r" + progress, end="", flush=True)
                    else:
                        print(progress, flush=True)
            if sys.stdout.isatty():
                print()
            t7 = time.perf_counter()

            for pg in pages:
                await pg.close()
            elapsed = time.perf_counter() - t0
            print("\n⏱ เวลาแต่ละจุด:")
            print(f"   เปิดเบราว์เซอร์/context: {t1 - t0:.1f} วินาที")
            print(f"   สร้าง {num_pages} หน้า: {t2 - t1:.1f} วินาที")
            print(f"   โหลด URL (goto): {t3 - t2:.1f} วินาที")
            print(f"   รอหลังโหลด ({wait_sec}s): {t4 - t3:.1f} วินาที")
            print(f"   ดึง tracking ID จากแต่ละหน้า: {t5 - t4:.1f} วินาที")
            print(f"   จัดกลุ่ม id → หน้า: {t6 - t5:.1f} วินาที")
            print(f"   ถ่ายภาพ (wave): {t7 - t6:.1f} วินาที")
            print(f"   รวม: {elapsed:.1f} วินาที")
            return len(captured), captured
        finally:
            await context.close()
            if browser:
                await browser.close()


def capture_one(
    playwright_or_context,
    tracking_id: str,
    bills_dir: str,
    use_private: bool = False,
    is_context: bool = False,
    wait_sec: float = 3,
) -> bool:
    """เปิดหน้าบิลแล้ว screenshot เฉพาะส่วนการ์ดบิล เก็บเป็น bills_dir/{tracking_id}.png"""
    url = (ANOUSITH_BILL_ITEM_URL if use_private else ANOUSITH_BILL_URL).format(tracking_id=tracking_id)
    os.makedirs(bills_dir, exist_ok=True)
    out_path = os.path.join(bills_dir, f"{tracking_id}.png")
    browser = None
    try:
        if is_context:
            page = playwright_or_context.new_page()
        else:
            browser = playwright_or_context.chromium.launch(headless=True, args=STEALTH_CHROME_ARGS)
            page = browser.new_page(viewport=VIEWPORT)
        goto_anousith_bill_page_sync(page, url)
        page.wait_for_timeout(int(wait_sec * 1000))

        try:
            if use_private:
                _screenshot_private_page(page, out_path)
            else:
                _screenshot_public_page(page, out_path)
        except Exception:
            page.screenshot(path=out_path, full_page=True)
        page.close()
        return True
    except Exception as e:
        print(f"   ❌ {tracking_id}: {e}")
        return False
    finally:
        if browser:
            browser.close()


def main():
    args = [a for a in sys.argv[1:] if a.strip()]
    bills_dir = DEFAULT_BILLS_DIR
    use_private = "--private" in args
    if use_private:
        args = [a for a in args if a != "--private"]
    user_data_dir = None
    storage_state_path = None
    if "--user-data-dir" in args:
        i = args.index("--user-data-dir")
        if i + 1 < len(args):
            user_data_dir = args[i + 1]
            args = [a for a in args if a != "--user-data-dir" and a != user_data_dir]
    if "--storage-state" in args:
        i = args.index("--storage-state")
        if i + 1 < len(args):
            storage_state_path = args[i + 1]
            args = [a for a in args if a != "--storage-state" and a != storage_state_path]
    if "--bills-dir" in args:
        i = args.index("--bills-dir")
        if i + 1 < len(args):
            bills_dir = args[i + 1]
        args = [a for a in args if a != "--bills-dir" and a != bills_dir]
    start_date_arg: Optional[str] = None
    end_date_arg: Optional[str] = None
    if "--start-date" in args:
        i = args.index("--start-date")
        if i + 1 < len(args):
            start_date_arg = args[i + 1]
            args = [a for a in args if a != "--start-date" and a != start_date_arg]
        else:
            args = [a for a in args if a != "--start-date"]
    if "--end-date" in args:
        i = args.index("--end-date")
        if i + 1 < len(args):
            end_date_arg = args[i + 1]
            args = [a for a in args if a != "--end-date" and a != end_date_arg]
        else:
            args = [a for a in args if a != "--end-date"]
    if "--tracking" in args:
        i = args.index("--tracking")
        if i + 1 < len(args):
            tracking_ids = [args[i + 1]]
        else:
            print("ใช้: python3 capture_bill_screenshot.py --tracking <tracking_id>")
            sys.exit(1)
        args = [a for a in args if a != "--tracking" and a != tracking_ids[0]]
    else:
        # อ่าน Tracking ID จาก Google Sheet ตาม config เดียวกับ run_manual.py
        tracking_ids, skipped_no_tracking = _read_tracking_ids_from_sheet()
        if not tracking_ids:
            print("❌ ບໍ່ພົບ Tracking ID ທີ່ສາມາດຖ່າຍບິນໄດ້ໃນ Google Sheet")
            sys.exit(1)
        if skipped_no_tracking > 0:
            print(f"ℹ️ ຂ້າມ {skipped_no_tracking} ແຖວທີ່ສະຖານະເທົ່າກັບ '{FILTER_COL_A_VALUE}' ແຕ່ບໍ່ມີ tracking ID ຫຼືຮູບແບບບໍ່ຖືກ")

    if use_private and not user_data_dir and not storage_state_path:
        print("⚠️  ใช้ --private ต้องระบุ --user-data-dir หรือ --storage-state เพื่อใช้ session ที่ล็อกอินแล้ว")
        print("   ตัวอย่าง: --user-data-dir /path/to/chrome/profile หรือ --storage-state auth.json")

    print(f"จะถ่ายภาพบิล {len(tracking_ids)} รายการ เก็บที่ {bills_dir}/" + (" (หน้าบิลส่วนตัว โหลดหลายหน้าพร้อมกัน + ถ่ายเป็น wave)" if use_private and (user_data_dir or storage_state_path) else " (หน้าสาธารณะ เบราว์เซอร์เดียว)" if not use_private else " (หน้าบิลส่วนตัว)"))
    ok = 0
    not_captured: List[str] = []
    if use_private and (user_data_dir or storage_state_path):
        # โหลด .env เพื่อใช้ล็อกอินอัตโนมัติเมื่อ session หมดอายุ
        _load_dotenv()
        # โหมด private: async โหลด P หน้าพร้อมกัน แล้วถ่ายการ์ดเป็น wave
        if user_data_dir and not os.path.isdir(user_data_dir):
            print(f"❌ โฟลเดอร์ไม่พบ: {user_data_dir}")
            sys.exit(1)
        if storage_state_path and not os.path.isfile(storage_state_path):
            print(f"❌ ไฟล์ไม่พบ: {storage_state_path}")
            sys.exit(1)
        # ช่วงวันที่: ถ้าไม่ระบุ --start-date/--end-date ใช้ วันที่ 1 ของเดือนก่อน ถึงวันนี้
        start_date: Optional[str] = start_date_arg
        end_date: Optional[str] = end_date_arg
        if not (start_date and end_date):
            today = date.today()
            end_date = today.isoformat()
            first_this_month = today.replace(day=1)
            last_prev = first_this_month - timedelta(days=1)
            start_date = last_prev.replace(day=1).isoformat()
        ok, captured_set = asyncio.run(async_capture_private_paginated(
            user_data_dir, storage_state_path, tracking_ids, bills_dir,
            start_date=start_date, end_date=end_date,
        ))
        not_captured = sorted(set(tracking_ids) - captured_set)
    else:
        # โหมด public: เปิดเบราว์เซอร์ครั้งเดียว แล้วเปิดหน้าใหม่ทีละบิล
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=STEALTH_CHROME_ARGS)
            context = browser.new_context(viewport=VIEWPORT)
            context.add_init_script(STEALTH_INIT_SCRIPT)
            try:
                for i, tid in enumerate(tracking_ids):
                    print(f"[{i+1}/{len(tracking_ids)}] {tid} ... ", end="", flush=True)
                    if capture_one(context, tid, bills_dir, use_private=False, is_context=True):
                        print("✅")
                        ok += 1
                    else:
                        print("ล้มเหลว")
                        not_captured.append(tid)
            finally:
                context.close()
                browser.close()
    print(f"\nรวมถ่ายได้ {ok}/{len(tracking_ids)} รายการ")
    if use_private and (user_data_dir or storage_state_path) and ok < len(tracking_ids):
        print("  (บิลที่เหลืออาจไม่อยู่ในหน้าที่เปิด หรือเลขบิลไม่ตรงกับในหน้า)")
    if not_captured:
        n = len(not_captured)
        print(f"\n📋 Tracking ID ที่ยังไม่ได้ถ่าย ({n} รายการ):")
        if n <= 30:
            for tid in not_captured:
                print(f"   {tid}")
        else:
            for tid in not_captured[:20]:
                print(f"   {tid}")
            print(f"   ... และอีก {n - 20} รายการ")


if __name__ == "__main__":
    main()
