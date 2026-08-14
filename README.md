# Bill Automation Kit

โปรเจค**แจกแยก**สำหรับการส่งบิล / แจ้งเตือนผ่าน Facebook Messenger, WhatsApp (Playwright), และ Google Sheet

ชุดนี้**ไม่มี** token, password, โปรไฟล์ Chrome, Sheet ID หรือข้อความต้อนรับของใครคนใดคนหนึ่ง  
ผู้ใช้แต่ละคนต้องใส่บัญชีของตัวเองผ่าน **Settings UI**

โปรเจค production ของผู้พัฒนา (`Automation_Work`) แยกต่างหาก — ไม่ผูกกับโฟลเดอร์นี้

## ความต้องการระบบ

- Windows 10/11
- Python 3.10+
- บัญชี Facebook Page + (ถ้าใช้ Token) Meta Developer App + Page Access Token
- Google Sheet + Service Account JSON
- (ถ้าใช้ Webhook) ngrok

## ติดตั้งครั้งแรก (แนะนำ — ดับเบิลคลิกอย่างเดียว)

1. Clone หรือ unzip โฟลเดอร์ `Bill_Automation_Kit`
2. ดับเบิลคลิก **`INSTALL.bat`** ที่ root ของโปรเจค  
   (ติดตั้ง Python/venv/Playwright + สร้างไอคอน Desktop อัตโนมัติ)
3. ดับเบิลคลิกไอคอน Desktop **Send Bill Launcher**
4. กรอก **Settings** เอง (Sheet / เพจ Facebook / Webhook) — ไม่ต้องพึ่ง AI

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
- **เฟส 1** — Settings UI (Sheet / เพจ·Token / Webhook·ngrok / checklist + first-run)  
- **One-click install** — `INSTALL.bat` + Desktop shortcuts อัตโนมัติ (ดู [docs/HANDOFF_ONE_CLICK_INSTALL.md](docs/HANDOFF_ONE_CLICK_INSTALL.md))  
- **เฟส 2+** — ข้อความ welcome, browser profile, ขนส่ง (ยังไม่ทำ)
