#!/usr/bin/env python3
"""
บันทึก Facebook session (storage state) เพื่อไม่ต้องล็อกอินทุกครั้ง
ใช้ครั้งเดียวหลังจากล็อกอิน Facebook สำเร็จ

ใช้:
  python3 save_facebook_session.py [--output facebook_session.json]
"""

import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ ต้องติดตั้ง Playwright ก่อน: pip install playwright && playwright install chromium")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT = SCRIPT_DIR.parent / "facebook_session.json"


def main():
    args = sys.argv[1:]
    output_path = DEFAULT_OUTPUT
    
    if "--output" in args:
        i = args.index("--output")
        if i + 1 < len(args):
            output_path = Path(args[i + 1])
        args = [a for a in args if a != "--output" and args.index(a) != i + 1]
    
    print("🌐 กำลังเปิดเบราว์เซอร์...")
    print("   กรุณาล็อกอิน Facebook ในเบราว์เซอร์ที่เปิดขึ้นมา")
    print("   หลังจากล็อกอินเสร็จแล้ว กด Enter เพื่อบันทึก session...")
    print("")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
            ],
            ignore_default_args=["--enable-automation", "--enable-blink-features=IdleDetection"],
        )
        context = browser.new_context(
            locale="th-TH",
            timezone_id="Asia/Bangkok",
            color_scheme="light",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            try { delete Object.getPrototypeOf(navigator).webdriver; } catch {}
            if (!window.chrome) window.chrome = {};
            if (!window.chrome.runtime) window.chrome.runtime = { id: undefined };
        """)
        page = context.new_page()
        
        page.goto("https://business.facebook.com", wait_until="networkidle")
        
        # รอให้ผู้ใช้ล็อกอิน
        input("\n⏸️  กด Enter หลังจากล็อกอินเสร็จแล้ว...")
        
        # บันทึก storage state
        context.storage_state(path=str(output_path))
        
        print(f"\n✅ บันทึก session ลง: {output_path}")
        print("   ตอนนี้สามารถใช้ session นี้ได้โดยไม่ต้องล็อกอินอีก")
        print("   (session จะหมดอายุเมื่อ Facebook logout หรือหลังจากระยะเวลาหนึ่ง)")
        print("")
        print("💡 วิธีใช้:")
        print(f"   .venv/bin/python3 scripts/open_inbox_and_send.py --storage-state {output_path} ...")
        print("   หรือไม่ต้องระบุ --storage-state ถ้าใช้ชื่อไฟล์ facebook_session.json")
        
        browser.close()


if __name__ == "__main__":
    main()
