#!/usr/bin/env python3
"""
บันทึก session (cookies/localStorage) หลังล็อกอิน app.anousith.express
รันครั้งเดียว: เปิดเบราว์เซอร์ → ล็อกอิน (ด้วยมือ หรืออัตโนมัติถ้ากำหนด user/pass) → บันทึกเป็น auth.json
จากนั้นใช้: capture_bill_screenshot.py --private --storage-state auth.json

เรื่อง session หมดอายุ:
  เว็บขนส่งมักให้ล็อกอินใหม่ทุก 2–3 วัน หรือ 1 สัปดาห์ (แล้วแต่เว็บ)
  auth.json คือ snapshot ของ session ตอนบันทึก — เมื่อเว็บให้ login ใหม่ session ใน auth.json ก็หมดอายุ
  จึงต้องรัน save_auth_state.py อีกครั้งเมื่อถ่ายบิลแล้วเจอหน้า login หรือบิลไม่โหลด

ล็อกอินอัตโนมัติ (ถ้าเว็บใช้ฟอร์ม user + password):
  ใส่ user/pass ในไฟล์ .env (ในโฟลเดอร์โปรเจกต์) หรือใน environment แล้วรันด้วย --auto
  ไฟล์ .env อยู่ใน .gitignore จะไม่ถูก commit — ดู STEPS.md หัวข้อ "จะใส่ user/password ไว้ที่ไหน"

ใช้:
  .venv/bin/python3 save_auth_state.py
  .venv/bin/python3 save_auth_state.py --output my_auth.json
  .venv/bin/python3 save_auth_state.py --auto   # อ่าน user/pass จาก .env หรือจาก environment
"""

import argparse
import os
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("❌ ต้องติดตั้ง Playwright ก่อน: ใช้ .venv ที่มี playwright")
    sys.exit(1)

LOGIN_URL = "https://app.anousith.express/nextday/item_bill/bill_item?search="
DEFAULT_OUTPUT = "auth.json"
AUTO_LOGIN_WAIT_SEC = 5
ENV_FILE = ".env"


def load_dotenv(path: str = None) -> None:
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


def try_auto_login(page) -> bool:
    """ถ้ามีฟอร์มล็อกอิน (ช่อง user + password) ให้กรอกจาก env แล้วกดส่ง คืน True ถ้าทำสำเร็จ"""
    user = os.environ.get("ANOUSITH_USER", "").strip()
    password = os.environ.get("ANOUSITH_PASSWORD", "").strip()
    if not user or not password:
        return False
    try:
        # ช่อง user/เบอร์โทร: text/email/tel หรือ name=username/email/phone
        user_loc = page.locator(
            "input[type=text], input[type=email], input[type=tel], input[name=username], input[name=email], input[name=user], input[name=phone]"
        )
        if user_loc.count() == 0:
            return False
        user_loc.first.fill(user)
        # ช่องรหัสผ่าน
        pass_loc = page.locator("input[type=password]")
        if pass_loc.count() == 0:
            return False
        pass_loc.first.fill(password)
        # ปุ่มส่ง: submit หรือข้อความ ເຂົ້າສູ່ລະບົບ (ลาว)/เข้าสู่ระบบ/ล็อกอิน/Login
        submit_loc = page.locator(
            "button[type=submit], input[type=submit], "
            "button:has-text('ເຂົ້າສູ່ລະບົບ'), button:has-text('เข้าสู่ระบบ'), button:has-text('ล็อกอิน'), button:has-text('Login'), button:has-text('Sign in'), "
            "a:has-text('ເຂົ້າສູ່ລະບົບ'), a:has-text('เข้าสู่ระบบ'), a:has-text('ล็อกอิน'), a:has-text('Login')"
        )
        if submit_loc.count() == 0:
            return False
        submit_loc.first.click()
        page.wait_for_timeout(2000)
        return True
    except Exception:
        return False


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description="บันทึก session หลังล็อกอิน Anousith")
    p.add_argument("--output", "-o", default=DEFAULT_OUTPUT, help=f"ไฟล์ output (ค่าเริ่มต้น: {DEFAULT_OUTPUT})")
    p.add_argument("--auto", action="store_true", help="ลองล็อกอินอัตโนมัติจาก .env หรือ ANOUSITH_USER/ANOUSITH_PASSWORD")
    args = p.parse_args()
    out_path = args.output

    if args.auto:
        if not os.environ.get("ANOUSITH_USER") or not os.environ.get("ANOUSITH_PASSWORD"):
            print("❌ ใช้ --auto ต้องตั้ง ANOUSITH_USER และ ANOUSITH_PASSWORD")
            print("   วิธีที่ 1: สร้างไฟล์ .env ในโฟลเดอร์โปรเจกต์ แล้วเขียน 2 บรรทัด:")
            print("     ANOUSITH_USER=เบอร์หรืออีเมล")
            print("     ANOUSITH_PASSWORD=รหัสผ่าน")
            print("   วิธีที่ 2: ใส่ในคำสั่ง ANOUSITH_USER=xxx ANOUSITH_PASSWORD=yyy ... save_auth_state.py --auto")
            sys.exit(1)
        print("จะเปิดเบราว์เซอร์ แล้วลองล็อกอินอัตโนมัติจาก user/password ใน env")
    else:
        print("จะเปิดเบราว์เซอร์ (ไม่ headless) ให้คุณล็อกอินที่ app.anousith.express")
        print("หลังล็อกอินเสร็จ ให้กลับมาที่เทอร์มินัลแล้วกด Enter เพื่อบันทึก session")
    input("กด Enter เพื่อเริ่ม... ")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 430, "height": 932})
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

        if args.auto:
            print("กำลังลองล็อกอินอัตโนมัติ...")
            if try_auto_login(page):
                print("ส่งฟอร์มล็อกอินแล้ว — รอโหลดหน้า")
                page.wait_for_timeout(int(AUTO_LOGIN_WAIT_SEC * 1000))
            else:
                print("⚠️ ไม่พบฟอร์มล็อกอินหรือ selector ไม่ตรง — กรุณาล็อกอินด้วยมือในเบราว์เซอร์")
                input("ล็อกอินเสร็จแล้ว? กด Enter เพื่อบันทึก session... ")
        else:
            print("\n✅ เปิดหน้าแล้ว — ล็อกอินในเบราว์เซอร์ให้เสร็จ แล้วกลับมาที่นี่")
            input("ล็อกอินเสร็จแล้ว? กด Enter เพื่อบันทึก session... ")

        context.storage_state(path=out_path)
        print(f"✅ บันทึก session ลง {os.path.abspath(out_path)} แล้ว")
        browser.close()

    print("\nต่อไปใช้คำสั่ง:")
    print(f"  .venv/bin/python3 capture_bill_screenshot.py --private --storage-state {out_path} <path_to_csv>")
    print("หรือ")
    print(f"  .venv/bin/python3 capture_bill_screenshot.py --private --storage-state {out_path} --tracking <tracking_id>")


if __name__ == "__main__":
    main()
