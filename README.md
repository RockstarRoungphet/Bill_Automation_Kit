# Bill Automation Kit

โปรเจค**แจกแยก**สำหรับการส่งบิล / แจ้งเตือนผ่าน Facebook Messenger, WhatsApp (Playwright), และ Google Sheet

ชุดนี้**ไม่มี** token, password, โปรไฟล์ Chrome, Sheet ID หรือข้อความต้อนรับของใครคนใดคนหนึ่ง  
ผู้ใช้แต่ละคนต้องใส่บัญชีของตัวเอง

โปรเจค production ของผู้พัฒนา (`Automation_Work`) แยกต่างหาก — ไม่ผูกกับโฟลเดอร์นี้

## ความต้องการระบบ

- Windows 10/11
- Python 3.10+
- บัญชี Facebook Page + (ถ้าใช้ Token) Meta Developer App + Page Access Token
- Google Sheet + Service Account JSON
- (ถ้าใช้ Webhook) ngrok

## ติดตั้งครั้งแรก

```powershell
cd C:\Bill_Automation_Kit
.\setup_windows.ps1
# หรือ
.\setup_windows.ps1 -InstallPrerequisites
```

## ตั้งค่า (ชั่วคราว — ก่อนมี Settings UI)

คัดลอกเทมเพลต แล้วแก้เป็นค่าของคุณ:

```powershell
Copy-Item .env.example .env
Copy-Item config_templates\page_token.example.json page_token.json
Copy-Item config_templates\user_settings.example.json user_settings.json
# แก้ sheet id ใน:
#   no_api_send_bill\config\sheet_config.json
#   no_api_send_bill_manual\config\sheet_config.json
# วาง Google Service Account JSON เป็น:
#   no_api_send_bill\config\google_credentials.json
# แก้ชื่อเพจ / page id:
#   no_api_send_bill\config\page_name_to_id.json
# ข้อความ welcome ต่อเพจ:
#   page_reply_config.json  (ดู config_templates\page_reply_config.example.json)
```

แชร์ Google Sheet ให้ `client_email` ในไฟล์ credentials  
ใส่สื่อต้อนรับที่ `product_images\<ชื่อเพจที่ตรง page_token>\`

ดูรายละเอียดไฟล์ลับ: [SECRETS_CHECKLIST.md](SECRETS_CHECKLIST.md)

## เปิด Launcher

```powershell
cd C:\Bill_Automation_Kit\no_api_send_bill_manual
..\..\.venv\Scripts\pythonw.exe launcher_ui.py
# หรือ
..\..\.venv\Scripts\python.exe launcher_ui.py
```

หมายเหตุ path venv: ถ้า setup สร้างที่ root → ใช้ `..\..\.venv` จากภายใต้ `no_api_send_bill_manual` คือ `..\.venv` จริงๆ:

```powershell
cd C:\Bill_Automation_Kit\no_api_send_bill_manual
..\.venv\Scripts\pythonw.exe launcher_ui.py
```

## โฟลเดอร์สำคัญ

| path | บทบาท |
|------|--------|
| `config_templates/` | ตัวอย่าง config ว่าง (commit ได้) |
| `settings/` | ว่าง — จะใส่ Settings UI ในเฟสถัดไป |
| `no_api_send_bill/` | ส่งบิลโหมด Playwright (Inbox/WhatsApp) |
| `no_api_send_bill_manual/` | Launcher UI |
| `messenger_webhook_server.py` | Webhook + บันทึก Order→PSID |
| `send_bill_from_sheet.py` | ส่งบิลโหมด Token (Graph API) |

## อัปเดตจากผู้พัฒนา

```powershell
cd C:\Bill_Automation_Kit
git pull
```

ไฟล์ `.env`, `page_token.json`, credentials, browser profile **ไม่ขึ้น git** — `pull` จะไม่ทับบัญชีคุณ

## Workflow ซิงก์โค้ด (ผู้พัฒนา)

ดู [docs/SYNC_FROM_PRODUCTION.md](docs/SYNC_FROM_PRODUCTION.md)

## เวอร์ชัน scaffold

- **เฟส 0** — โครงโปรเจคแยก + เทมเพลต + คัดลอก core code สะอาด (ยังไม่มีหน้าต่าง Settings)
- **เฟส 1** (ต่อไป) — หน้าต่าง Settings กรอก Sheet / เพจ / token / ngrok
