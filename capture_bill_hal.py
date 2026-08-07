#!/usr/bin/env python3
"""
HAL bill capture (PNG only).

- Uses only username/password for auto-login.
- Captures only PNG image (no token, no API, no JSON output).
- Loads the outbound list once, opens each bill in a modal, clips, closes — then paginates
  if needed (avoids reloading the list for every tracking ID).
"""

import json
import asyncio
import os
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Set

# Timing (ms) — list loads once; per-bill uses modal open/close only
WAIT_AFTER_LIST_LOAD_MS = 2200
WAIT_AFTER_EYE_CLICK_MS = 1200
WAIT_AFTER_CLOSE_MODAL_MS = 500
WAIT_AFTER_PAGE_TURN_MS = 1500
MAX_PAGINATION_STEPS = 500
DEFAULT_PARALLEL_PAGES = 10

try:
    from playwright.async_api import async_playwright
except Exception:
    async_playwright = None

from capture_playwright_nav import (
    goto_hal_list_page,
    goto_hal_login_page,
    wait_hal_list_ready,
)


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BILLS_DIR = "bill_images"
ENV_FILE = ".env"
SHEET_CONFIG_PATH = SCRIPT_DIR / "no_api_send_bill_manual" / "config" / "sheet_config.json"
TRACKING_HEADERS = ("Tracking ID", "tracking_id", "Tracking Id", "เลขพัสดุ")
FILTER_COL_A_VALUE = "📦ລໍຈັດສົ່ງ"
COL_A_INDEX = 0
# คอลัมน์ G ใน Excel = index 6 (carrier)
COL_G_INDEX = 6
SHEET_CARRIER_HAL = "ຮຸ່ງອາລຸນ"
COL_Z_INDEX = 25

HAL_OUTBOUND_LIST_URL = "https://www.halexpress.la/parcel/outbound"
HAL_LOGIN_URL = "https://www.halexpress.la/login"
HAL_BROWSER_PROFILE_DIR = SCRIPT_DIR / "hal_browser_profile"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _find_col(headers: List[str], names: Tuple[str, ...], default: int) -> int:
    for i, h in enumerate(headers):
        if str(h).strip() in names:
            return i
    return default


def _looks_like_tracking_id(value: str) -> bool:
    value = (value or "").strip()
    if not value or value in TRACKING_HEADERS:
        return False
    return len(value) >= 10


def read_tracking_ids_from_sheet() -> List[str]:
    if not SHEET_CONFIG_PATH.exists():
        return []
    try:
        cfg = json.loads(SHEET_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

    sheet_id = cfg.get("sheet_id") or cfg.get("sheet_ID")
    sheet_names = cfg.get("sheet_names") or [cfg.get("sheet_name", "Sheet1")]
    cred_path = cfg.get("credentials_path")
    if cred_path and not os.path.isabs(cred_path):
        cred_path = str((SHEET_CONFIG_PATH.parent.parent / cred_path).resolve())
    if not sheet_id or not cred_path or not os.path.exists(cred_path):
        return []

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except Exception:
        return []

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(sheet_id)

    ids: List[str] = []
    for sheet_name in sheet_names:
        try:
            ws = workbook.worksheet(sheet_name)
            all_rows = ws.get_all_values()
        except Exception:
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
            if carrier != SHEET_CARRIER_HAL:
                continue
            tid = cells[track_col] if track_col < len(cells) else ""
            if _looks_like_tracking_id(tid):
                ids.append(tid)
    return list(dict.fromkeys(ids))


async def _try_auto_login_async(page) -> bool:
    user = os.getenv("HAL_USER", "").strip()
    password = os.getenv("HAL_PASSWORD", "").strip()
    if not user or not password:
        return False
    try:
        login_url = os.getenv("HAL_LOGIN_URL", HAL_LOGIN_URL).strip() or HAL_LOGIN_URL
        await goto_hal_login_page(page, login_url)
        await page.wait_for_timeout(1000)

        user_loc = page.locator(
            "input[type=text], input[type=email], input[type=tel], input[name*=user], input[name*=email], input[name*=phone], input[name*=username]"
        )
        pass_loc = page.locator("input[type=password], input[name*=password]")
        if await user_loc.count() == 0 or await pass_loc.count() == 0:
            return False
        await user_loc.first.fill(user)
        await pass_loc.first.fill(password)

        submit_loc = page.locator(
            "button[type=submit], input[type=submit], "
            "button:has-text('Login'), button:has-text('Sign in'), button:has-text('เข้าสู่ระบบ'), button:has-text('ล็อกอิน'), button:has-text('ເຂົ້າລະບົບ'), "
            "a:has-text('Login'), a:has-text('เข้าสู่ระบบ'), a:has-text('ເຂົ້າລະບົບ')"
        )
        if await submit_loc.count() > 0:
            await submit_loc.first.click(timeout=10000)
        else:
            await pass_loc.first.press("Enter")
        await page.wait_for_timeout(2000)
        return True
    except Exception:
        return False


async def _click_view_button_in_row_async(row) -> bool:
    # Avoid WhatsApp links and prefer eye/view controls in same row.
    try:
        return bool(
            await row.evaluate(
                """(rowEl) => {
                    const isWhatsApp = (node) => {
                        if (!node) return false;
                        let el = node;
                        for (let i = 0; i < 8 && el; i++) {
                            const href = el.getAttribute && el.getAttribute('href');
                            if (href && /whatsapp|wa\\.me|api\\.whatsapp/i.test(href)) return true;
                            el = el.parentElement;
                        }
                        return false;
                    };
                    const controls = Array.from(rowEl.querySelectorAll('button, a, [role="button"]'))
                        .filter((n) => !isWhatsApp(n));

                    const eye = controls.find((c) => {
                        const cls = (c.className || '').toString();
                        const html = (c.innerHTML || '').toLowerCase();
                        if (/eye|anticon-eye|icon-eye/i.test(cls)) return true;
                        if (c.querySelector && c.querySelector('i[class*="eye"], span[class*="eye"], .anticon-eye, [class*="anticon-eye"]')) return true;
                        return html.includes('eye');
                    });
                    if (eye) {
                        eye.click();
                        return true;
                    }

                    const tds = rowEl.querySelectorAll('td');
                    if (tds.length) {
                        const inLast = Array.from(tds[tds.length - 1].querySelectorAll('button, a, [role="button"]'))
                            .filter((n) => !isWhatsApp(n));
                        if (inLast.length) {
                            inLast[inLast.length - 1].click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )
        )
    except Exception:
        return False


async def _close_modal_async(page) -> None:
    """Close Ant Design modal/drawer after capture (Escape + common close selectors)."""
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    await page.wait_for_timeout(200)
    close_selectors = (
        ".ant-modal-close",
        ".ant-drawer-close",
        "button[aria-label='Close']",
        ".ant-modal-header .ant-modal-close",
        "[class*='Drawer'] button[class*='close']",
    )
    for sel in close_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=3000)
                break
        except Exception:
            continue
    await page.wait_for_timeout(WAIT_AFTER_CLOSE_MODAL_MS)


async def _ensure_list_page_async(page, list_url: str) -> None:
    """Load outbound list once (login if table empty)."""
    await goto_hal_list_page(page, list_url)
    await page.wait_for_timeout(WAIT_AFTER_LIST_LOAD_MS)

    if await page.get_by_text("No Name").count() > 0 or await page.locator("td").count() == 0:
        await _try_auto_login_async(page)
        await goto_hal_list_page(page, list_url)
        await page.wait_for_timeout(WAIT_AFTER_LIST_LOAD_MS)


async def _click_eye_for_row_async(page, tracking_id: str) -> bool:
    """On already-loaded list: find row, click eye. No page.goto."""
    rows = page.locator("tr", has_text=tracking_id)
    if await rows.count() == 0:
        return False
    row = rows.first

    if not await _click_view_button_in_row_async(row):
        return False

    await page.wait_for_timeout(WAIT_AFTER_EYE_CLICK_MS)
    # Defensive: if WhatsApp tab opens by mistake, close and fail.
    for p in list(page.context.pages):
        u = (p.url or "").lower()
        if "whatsapp" in u or "wa.me" in u:
            try:
                await p.close()
            except Exception:
                pass
            return False
    return True


async def _click_next_page_async(page) -> bool:
    """Click enabled pagination next; return True if a click was performed."""
    try:
        nxt = page.locator("li.ant-pagination-next:not(.ant-pagination-disabled)").first
        if await nxt.count() > 0 and await nxt.is_visible():
            await nxt.click(timeout=8000)
            await wait_hal_list_ready(page)
            return True
    except Exception:
        pass
    try:
        btn = page.locator(
            ".ant-pagination-next:not(.ant-pagination-disabled) button, .ant-pagination-next:not(.ant-pagination-disabled) a"
        ).first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click(timeout=8000)
            await wait_hal_list_ready(page)
            return True
    except Exception:
        pass
    return False


async def _scan_tracking_ids_on_page_async(page) -> List[str]:
    """Return all tracking-like ids visible on the current list page."""
    try:
        ids = await page.evaluate(
            """() => {
                const table = document.querySelector('table');
                const rows = table ? Array.from(table.querySelectorAll('tbody tr')) : Array.from(document.querySelectorAll('tr'));
                const text = rows.map(r => r.innerText || '').join('\\n');
                const out = new Set();
                const reXGI = /\\bXGI\\d{9,}\\b/g;
                const reNum = /\\b\\d{10,}\\b/g;
                let m;
                while ((m = reXGI.exec(text)) !== null) out.add(m[0]);
                while ((m = reNum.exec(text)) !== null) out.add(m[0]);
                return Array.from(out);
            }"""
        )
    except Exception:
        return []

    # Final filter in Python to match our validation rules.
    uniq: List[str] = []
    seen: Set[str] = set()
    for x in ids or []:
        s = str(x).strip()
        if not _looks_like_tracking_id(s):
            continue
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


async def _build_id_page_map_async(
    page,
    wanted_ids: Set[str],
    list_url: str,
) -> Dict[str, int]:
    """
    Pass 1: paginate sequentially and build a map {tracking_id -> list_page_number}.
    Scans only the currently-visible table rows (no per-id searching).
    """
    id_to_page: Dict[str, int] = {}

    await _ensure_list_page_async(page, list_url)

    page_num = 1
    transitions = 0
    while True:
        ids_on_page = await _scan_tracking_ids_on_page_async(page)
        for tid in ids_on_page:
            if tid in wanted_ids and tid not in id_to_page:
                id_to_page[tid] = page_num

        if len(id_to_page) >= len(wanted_ids):
            break
        if transitions >= MAX_PAGINATION_STEPS:
            break

        if not await _click_next_page_async(page):
            break

        await page.wait_for_timeout(WAIT_AFTER_PAGE_TURN_MS)
        page_num += 1
        transitions += 1

    return id_to_page


async def _navigate_to_list_page_async(page, list_url: str, target_page_num: int) -> bool:
    """Navigate the given Playwright page to list page `target_page_num` (1-indexed)."""
    if target_page_num <= 1:
        await _ensure_list_page_async(page, list_url)
        return True

    await _ensure_list_page_async(page, list_url)

    page_num = 1
    transitions = 0
    while page_num < target_page_num and transitions <= MAX_PAGINATION_STEPS:
        if not await _click_next_page_async(page):
            return False
        await page.wait_for_timeout(WAIT_AFTER_PAGE_TURN_MS)
        page_num += 1
        transitions += 1

    return page_num == target_page_num


async def _capture_page_batch_async(
    page,
    tracking_ids_for_this_page: List[str],
    bills_dir: Path,
) -> Tuple[int, List[Tuple[str, str]]]:
    """
    Capture a batch of tracking IDs from an already-loaded list page:
    eye -> clip -> close modal (sequential per page).
    """
    ok = 0
    failed: List[Tuple[str, str]] = []
    for tid in tracking_ids_for_this_page:
        out_path = bills_dir / f"{tid}.png"
        success, reason = await _capture_one_modal_on_current_page_async(page, tid, out_path)
        if success:
            ok += 1
        else:
            failed.append((tid, reason))
    return ok, failed


async def _clip_bill_panel_async(page, tracking_id: str, out_path: Path) -> bool:
    rect = await page.evaluate(
        """(tid) => {
            const hasKeyword = (txt) => {
                const t = (txt || "").toLowerCase();
                return t.includes("cod") || t.includes("kg") || t.includes("barcode") || t.includes("ກີບ") || t.includes("ນ້ຳ") || t.includes("ນ້ໍາ");
            };
            const all = Array.from(document.querySelectorAll("*"));
            const markers = all.filter(el => (el.textContent || "").includes(tid));
            if (!markers.length) return null;

            let best = null;
            for (const marker of markers) {
                let p = marker;
                for (let depth = 0; depth < 12 && p; depth += 1) {
                    const r = p.getBoundingClientRect();
                    const txt = (p.textContent || "").trim();
                    const width = r.width || 0;
                    const height = r.height || 0;
                    const area = width * height;
                    const isCardLike = width >= 280 && width <= 620 && height >= 350 && height <= 1600;
                    if (isCardLike && area > 0 && hasKeyword(txt)) {
                        if (!best || area < best.area) best = { x: r.x, y: r.y, width, height, area };
                    }
                    p = p.parentElement;
                }
            }
            if (!best) return null;
            return {
                x: Math.max(0, Math.floor(best.x - 8)),
                y: Math.max(0, Math.floor(best.y - 8)),
                width: Math.ceil(best.width + 16),
                height: Math.ceil(best.height + 16)
            };
        }""",
        tracking_id,
    )
    if not rect:
        return False
    if rect["width"] < 120 or rect["height"] < 200:
        return False
    await page.screenshot(path=str(out_path), clip=rect)
    return True


async def _capture_one_modal_on_current_page_async(
    page, tracking_id: str, out_path: Path
) -> Tuple[bool, str]:
    """Open modal for one row on current list view, clip bill, close modal."""
    if not await _click_eye_for_row_async(page, tracking_id):
        return False, "row_not_visible_or_eye_failed"

    if not await _clip_bill_panel_async(page, tracking_id, out_path):
        try:
            await page.screenshot(path=str(out_path), full_page=True)
        except Exception:
            pass
        await _close_modal_async(page)
        return False, "ui_changed_or_clip_failed"

    await _close_modal_async(page)
    return True, "png_saved"


async def capture_many_png_async_parallel(
    tracking_ids: List[str],
    bills_dir: Path,
    show_browser: bool,
    parallel_pages: int,
) -> Tuple[int, List[Tuple[str, str]]]:
    if async_playwright is None:
        return 0, [(tid, "playwright not installed") for tid in tracking_ids]

    list_url = os.getenv("HAL_OUTBOUND_LIST_URL", HAL_OUTBOUND_LIST_URL).strip() or HAL_OUTBOUND_LIST_URL
    profile_dir = Path(os.getenv("HAL_USER_DATA_DIR", str(HAL_BROWSER_PROFILE_DIR)))
    profile_dir.mkdir(parents=True, exist_ok=True)

    parallel_pages = max(1, min(int(parallel_pages), DEFAULT_PARALLEL_PAGES))
    total = len(tracking_ids)

    bills_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    failed: List[Tuple[str, str]] = []

    remaining: List[str] = []
    for tid in tracking_ids:
        png_path = bills_dir / f"{tid}.png"
        if png_path.is_file():
            ok += 1
        else:
            remaining.append(tid)

    if not remaining:
        progress = f"ถ่ายได้ {ok}/{total} รายการ"
        if sys.stdout.isatty():
            print("\r" + progress, end="", flush=True)
            print()
        else:
            print(progress, flush=True)
        return ok, failed

    remaining_set: Set[str] = set(remaining)
    try:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=not show_browser,
                viewport={"width": 1600, "height": 900},
            )

            # Pass 1: scan list pages sequentially (single page)
            scan_page = await context.new_page()
            try:
                id_to_page = await _build_id_page_map_async(scan_page, remaining_set, list_url)
            finally:
                try:
                    await scan_page.close()
                except Exception:
                    pass

            # Unmapped ids -> fail
            page_to_ids: Dict[int, List[str]] = {}
            for tid in remaining:
                pid = id_to_page.get(tid)
                if pid is None:
                    failed.append((tid, "tracking_not_found_on_list"))
                else:
                    page_to_ids.setdefault(pid, []).append(tid)
            # Progress (success count only). UI will replace the last progress line.
            def _emit_progress():
                progress = f"ถ่ายได้ {ok}/{total} รายการ"
                if sys.stdout.isatty():
                    print("\r" + progress, end="", flush=True)
                else:
                    print(progress, flush=True)

            _emit_progress()

            page_nums = sorted(page_to_ids.keys())

            # Pass 2: parallel capture. When many bills share the same list page, use one
            # browser page per bill (up to parallel_pages at a time) so captures run like
            # Anousith waves instead of one sequential modal chain on a single tab.

            async def _worker_capture_one_tid_on_page(
                page_num: int,
                tid: str,
            ) -> Tuple[int, List[Tuple[str, str]]]:
                page = await context.new_page()
                try:
                    nav_ok = await _navigate_to_list_page_async(page, list_url, page_num)
                    if not nav_ok:
                        return 0, [(tid, "tracking_not_found_on_list")]
                    return await _capture_page_batch_async(page, [tid], bills_dir)
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass

            for pn in page_nums:
                assigned_ids = page_to_ids[pn]
                for offset in range(0, len(assigned_ids), parallel_pages):
                    batch = assigned_ids[offset : offset + parallel_pages]
                    tasks = [_worker_capture_one_tid_on_page(pn, tid) for tid in batch]
                    wave_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for i, tid in enumerate(batch):
                        res = wave_results[i]
                        if isinstance(res, Exception):
                            failed.append((tid, str(res)))
                        else:
                            o, f = res
                            ok += o
                            failed.extend(f)
                        _emit_progress()

            await context.close()
    except Exception as e:
        err = str(e)
        for tid in remaining:
            failed.append((tid, err))
    # Final progress line (make sure we end with a newline in terminal).
    progress = f"ถ่ายได้ {ok}/{total} รายการ"
    if sys.stdout.isatty():
        print("\r" + progress, end="", flush=True)
        print()
    else:
        print(progress, flush=True)
    return ok, failed


def parse_args(argv: List[str]) -> Tuple[List[str], Path, bool, int]:
    args = [a.strip() for a in argv if a.strip()]
    bills_dir = Path(DEFAULT_BILLS_DIR)
    show_browser = False
    parallel_pages = DEFAULT_PARALLEL_PAGES
    tracking_ids: List[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--tracking" and i + 1 < len(args):
            tracking_ids.append(args[i + 1].strip())
            i += 2
            continue
        if a == "--bills-dir" and i + 1 < len(args):
            bills_dir = Path(args[i + 1].strip())
            i += 2
            continue
        if a == "--show-browser":
            show_browser = True
            i += 1
            continue
        if a == "--parallel-pages" and i + 1 < len(args):
            try:
                parallel_pages = int(args[i + 1].strip())
            except Exception:
                parallel_pages = DEFAULT_PARALLEL_PAGES
            i += 2
            continue
        i += 1

    if not tracking_ids:
        tracking_ids = read_tracking_ids_from_sheet()
    tracking_ids = [x for x in tracking_ids if _looks_like_tracking_id(x)]
    parallel_pages = max(1, min(int(parallel_pages), DEFAULT_PARALLEL_PAGES))
    return list(dict.fromkeys(tracking_ids)), bills_dir, show_browser, parallel_pages


def main() -> None:
    _load_dotenv(SCRIPT_DIR / ENV_FILE)
    tracking_ids, bills_dir, show_browser, parallel_pages = parse_args(sys.argv[1:])
    if not tracking_ids:
        print("ไม่มี ID")
        sys.exit(1)

    bills_dir.mkdir(parents=True, exist_ok=True)
    print(f"HAL PNG capture (map-then-capture parallel): processing {len(tracking_ids)} bills → {bills_dir}")
    print(f"  parallel-pages: {parallel_pages} (max {DEFAULT_PARALLEL_PAGES})")
    ok, failed = asyncio.run(
        capture_many_png_async_parallel(
            tracking_ids,
            bills_dir,
            show_browser=show_browser,
            parallel_pages=parallel_pages,
        )
    )

    print(f"\nDone: {ok}/{len(tracking_ids)} success")
    if failed:
        print("Failed:")
        for tid, reason in failed:
            print(f" - {tid}: {reason}")


if __name__ == "__main__":
    main()
