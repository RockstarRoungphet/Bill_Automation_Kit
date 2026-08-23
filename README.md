# Bill Automation Kit

โปรเจค**แจกแยก**สำหรับการส่งบิล / แจ้งเตือนผ่าน Facebook Messenger, WhatsApp (Playwright), และ Google Sheet

ชุดนี้**ไม่มี** token, password, โปรไฟล์ Chrome, Sheet ID หรือข้อความต้อนรับของใครคนใดคนหนึ่ง  
ผู้ใช้แต่ละคนต้องใส่บัญชีของตัวเองผ่าน **Settings UI**

โปรเจค production ของผู้พัฒนา (`Automation_Work`) แยกต่างหาก — ไม่ผูกกับโฟลเดอร์นี้

## ความต้องการระบบ

- Windows 10/11
- Python 3.10+
- บัญชี Facebook Page + (ถ้าใช้ Token) Meta Developer App + **Long-Lived User Token** (ดึง Page Token หลายเพจใน Settings)
- Google Sheet + Service Account JSON
- (ถ้าใช้ Webhook) ngrok

## ติดตั้งครั้งแรก (แนะนำ — ดับเบิลคลิกอย่างเดียว)

1. Clone หรือ unzip โฟลเดอร์ `Bill_Automation_Kit`
2. ดับเบิลคลิก **`INSTALL.bat`** ที่ root ของโปรเจค  
   (ติดตั้ง Python/venv/Playwright/ngrok + สร้างไอคอน Desktop อัตโนมัติ)
3. ดับเบิลคลิกไอคอน Desktop **Send Bill Launcher**
4. กรอก **Settings** เอง (Sheet / เพจ Facebook / Webhook / ขนส่ง / Welcome / Browser Profile) — ไม่ต้องพึ่ง AI

ถ้ายังตั้งค่าไม่ครบ Launcher จะเปิด Settings ให้อัตโนมัติตอนเริ่ม (first-run)

### ทางเลือก: รันจาก PowerShell

```powershell
cd C:\Bill_Automation_Kit
.\setup_windows.ps1 -InstallPrerequisites
```

### ตั้งค่าด้วยมือ (ถ้าต้องการ)

เทมเพลตอยู่ที่ `config_templates/` — รายละเอียด [SECRETS_CHECKLIST.md](SECRETS_CHECKLIST.md)

แชร์ Google Sheet ให้ `client_email` ในไฟล์ credentials  
ใส่สื่อต้อนรับที่ `product_images\<ชื่อเพจที่ตรง page_token>\`

### Settings — แท็บเพจ Facebook

1. สร้าง **Long-Lived User Token** นอกแอป (Graph Explorer / แลก token ด้วย App ID+Secret ของคุณเอง — ชุดแจกไม่เก็บ App Secret)
2. เปิด Settings → แท็บ **เพจ Facebook**
3. วาง Long-Lived User Token → กด **ดึงรายการเพจ…**
4. เลือกเพจที่ต้องการ → **นำเข้าที่เลือก** (ได้ชื่อเพจ / Page ID / Page Token อัตโนมัติ)
5. กด **บันทึกเพจ**

ถ้าเพจเป็นของ **Business** แล้วไม่โผล่ในรายการ: ใส่ **Page ID** ในช่อง「เพจ Business」→ กด **ดึงเพจนี้…** → **บันทึกเพจ**

ระบบเก็บเฉพาะ **Page Token** ของเพจที่เลือกลง `page_token.json` — ไม่เขียน User Token ลงไฟล์

### Settings — แท็บขนส่ง

กรอก User/Password ของ **Anousith** และ **HAL Express** แล้วบันทึก — ค่าถูก merge ลง `.env` สำหรับถ่ายบิล (ไม่ขึ้น git)

### Settings — แท็บ Welcome

1. เลือกเพจจากรายการที่นำเข้าแล้ว
2. แก้ `welcome_text` / `price_reply` / `promo_text` / `cod_reply` / `order_reply`
3. **เพิ่มไฟล์…** รูป/วิดีโอในกล่องสื่อต้อนรับ หรือสื่อโปรโม (คัดลอกเข้าโฟลเดอร์เพจอัตโนมัติ)
4. ตั้งสวิตช์ปิด auto-reply / generic / โปรโมทั้งระบบได้
5. กด **บันทึก Welcome** → `page_reply_config.json` (ข้อความ)

ไฟล์สื่ออยู่ที่ `product_images\<ชื่อเพจ>\` และ `promo_images\<ชื่อเพจ>\` — ไม่ต้องไปหาโฟลเดอร์เองถ้าใช้ปุ่มใน Settings

### Settings — แท็บ Browser Profile

1. เปิด Settings → แท็บ **7. Browser Profile**
2. ตรวจ path ของ Facebook / HAL (ค่าเริ่มต้นใช้ได้) หรือ Browse เลือกโฟลเดอร์อื่น → **บันทึก Browser Profile**
3. กด **เปิดเบราว์เซอร์ Facebook (ล็อกอิน)** หรือ **HAL** → ล็อกอินให้เสร็จ แล้วปิดหน้าต่างเบราว์เซอร์
4. ใช้ Send Bill / Capture ตามปกติ — launcher และสคริปต์อ่าน path จาก `user_settings.json` (HAL ยังได้จาก `HAL_USER_DATA_DIR` ใน `.env`)

อย่า commit โฟลเดอร์ `browser_profile` / `hal_browser_profile`

## เปิด Launcher

- **Desktop:** ไอคอน **Send Bill Launcher** (สร้างหลัง `INSTALL.bat`)
- หรือดับเบิลคลิก `no_api_send_bill_manual\run_launcher_ui.vbs`
- หรือ:

```powershell
cd C:\Bill_Automation_Kit\no_api_send_bill_manual
..\.venv\Scripts\pythonw.exe launcher_ui.py
```

## โฟลเดอร์สำคัญ

| path | บทบาท |
|------|--------|
| `settings/` | Settings UI + `config_io` |
| `config_templates/` | ตัวอย่าง config ว่าง (commit ได้) |
| `no_api_send_bill/` | ส่งบิลโหมด Playwright |
| `no_api_send_bill_manual/` | Launcher UI |
| `messenger_webhook_server.py` | Webhook + Order→PSID |
| `send_bill_from_sheet.py` | ส่งบิลโหมด Token |

## อัปเดตจากผู้พัฒนา

```powershell
cd C:\Bill_Automation_Kit
git pull
```

ไฟล์ `.env`, `page_token.json`, credentials, browser profile **ไม่ขึ้น git** — `pull` จะไม่ทับบัญชีคุณ

## Workflow ซิงก์โค้ด (ผู้พัฒนา)

ดู [docs/SYNC_FROM_PRODUCTION.md](docs/SYNC_FROM_PRODUCTION.md)

## เวอร์ชัน

- **เฟส 0** — scaffold ชุดแจก + เทมเพลต  
- **เฟส 1** — Settings UI (Sheet / เพจจาก User Token / Webhook·ngrok / checklist + first-run)  
- **One-click install** — `INSTALL.bat` + Desktop shortcuts อัตโนมัติ (ดู [docs/HANDOFF_ONE_CLICK_INSTALL.md](docs/HANDOFF_ONE_CLICK_INSTALL.md))  
- **เฟส 2** — Settings แท็บขนส่ง (.env) + Welcome ต่อเพจ (`page_reply_config.json`) + สื่อผ่าน UI  
- **ดึงเพจ Business ด้วย Page ID** — เมื่อ `/me/accounts` ไม่คืนเพจ  
- **Browser Profile ใน Settings** — แท็บ 7 ตั้ง path Facebook/HAL + ปุ่มเปิดเบราว์เซอร์ล็อกอินครั้งแรก; launcher/สคริปต์อ่านจาก `user_settings.json` (และ `HAL_USER_DATA_DIR` ใน `.env`)
