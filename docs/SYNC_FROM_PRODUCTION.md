# Sync from production (`Automation_Work` → this kit)

โปรเจค production ที่ใช้งานจริง:

`C:\Automation_Work`

โปรเจคแจกนี้:

`C:\Bill_Automation_Kit`

## กฎ

1. **แก้บั๊ก / ฟีเจอร์บน production ก่อน** แล้วทดสอบใช้งานจริง
2. **ห้าม** คัดลอก secrets / profile / Sheet ID / ข้อมูลลูกค้า เข้าชุดแจก
3. พอร์ตเฉพาะ **ไฟล์โค้ด** (`.py`, `.ahk`, `.ps1` ที่ generic)
4. หลังคัดลอก ตรวจที่ชุดแจก:
   - ไม่มี `.env`, `page_token.json`, `auth.json`, `*credentials*`
   - ยังมี placeholders ใน `sheet_config` / `page_name_to_id` (ถ้าทับด้วยของ production ให้คืนจาก `config_templates/`)
5. Commit + push **เฉพาะ repo ชุดแจก**

## Allowlist แนะนำ (คัดลอกได้)

```
graph_media_send.py
messenger_webhook_server.py
send_bill_from_sheet.py
send_promo_within_24h.py
capture_bill_*.py
capture_playwright_nav.py
save_auth_state.py
requirements.txt
setup_windows.ps1
INSTALL.bat
docs/HANDOFF_ONE_CLICK_INSTALL.md
no_api_send_bill/scripts/*.py
no_api_send_bill_manual/launcher_ui.py
no_api_send_bill_manual/run_manual.py
no_api_send_bill_manual/run_launcher_ui.bat
no_api_send_bill_manual/run_launcher_ui.vbs
no_api_send_bill_manual/send_bill_signal.ahk
... (สคริปต์อื่นที่ไม่ผูกบัญชี)
```

## Denylist (ห้ามคัดลอกเข้าชุดแจก)

```
.env
auth.json
page_token.json
order_psid.json
*credentials*.json
browser_profile/
hal_browser_profile/
bill_images/* (เนื้อหารูปจริง)
sample_sheet_export.csv
product_images/<ชื่อเพจจริง>/* (สื่อจริง)
page_reply_config.json ที่มีข้อความธุรกิจจริง
sheet_config.json ที่มี sheet_id จริง
page_name_to_id.json ที่มี page id จริง
```

## คำสั่งตัวอย่าง (PowerShell)

```powershell
$prod = "C:\Automation_Work"
$kit  = "C:\Bill_Automation_Kit"

Copy-Item "$prod\send_bill_from_sheet.py" "$kit\send_bill_from_sheet.py" -Force
Copy-Item "$prod\no_api_send_bill\scripts\open_inbox_and_send.py" `
          "$kit\no_api_send_bill\scripts\open_inbox_and_send.py" -Force
# ... ทีละไฟล์ที่แก้

cd $kit
git status
# ตรวจ diff ไม่มี secret แล้วค่อย commit
```

## Settings UI

โมดูล Settings อยู่ (จะอยู่) ใต้ `settings/` — พัฒนาบนชุดแจก ไม่บังคับย้อนไปใส่ production
