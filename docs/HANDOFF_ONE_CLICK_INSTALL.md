# Handoff: One-click install (สำหรับ AI บนเครื่องหลัก)

เอกสารนี้บอก **AI ที่ทำงานบนเครื่องหลัก / production** (`C:\Automation_Work` หรือ clone ของ `Bill_Automation_Kit` บนเครื่องนั้น) ว่าต้องแก้อะไร เพื่อให้ผู้ใช้ชุดแจก **ดับเบิลคลิกครั้งเดียวแล้วใช้ได้** โดยไม่ต้องพึ่ง AI ติดตั้งซ้ำบนเครื่องทดสอบ

Repo เป้าหมาย: `https://github.com/RockstarRoungphet/Bill_Automation_Kit.git`  
โฟลเดอร์: `C:\Bill_Automation_Kit` (ชุดแจกเท่านั้น — **ห้าม** ผสม secrets จาก `Automation_Work`)

---

## เป้าหมาย UX ที่ผู้ใช้ต้องการ

1. Clone / โหลดชุดแจกจาก Git
2. **ดับเบิลคลิก `INSTALL.bat`** ที่ root ของ repo
3. สคริปต์ติดตั้งอัตโนมัติ: Python (ถ้ายังไม่มี), ngrok (Webhook), venv, pip packages, Playwright Chromium, โฟลเดอร์ runtime, **ไอคอน Desktop** (รวม ngrok)
4. ผู้ใช้ดับเบิลคลิกไอคอน **Send Bill Launcher** → กรอก Settings เอง (Sheet / เพจ / Webhook)
5. ไม่ต้องให้ AI บนเครื่องทดสอบมานั่งรัน `setup_windows.ps1` อีก

---

## สิ่งที่ต้องมีในชุดแจก (implement แล้วบนเครื่องทดสอบ — ให้ซิงก์/merge เข้าเครื่องหลักแล้ว push)

| ไฟล์ | บทบาท |
|------|--------|
| `INSTALL.bat` | จุดเข้า one-click (ดับเบิลคลิกได้) → เรียก `setup_windows.ps1 -InstallPrerequisites -CreateDesktopShortcuts` |
| `setup_windows.ps1` | setup จริง + สร้าง Desktop shortcuts + รีเฟรช PATH หลังติดตั้ง Python + ใช้ `python -m pip` |
| `no_api_send_bill_manual/run_launcher_ui.bat` | หา `.venv` ของโฟลเดอร์นี้ก่อน แล้วค่อย `..\.venv` แล้วค่อย system Python |
| `README.md` | อธิบาย flow: clone → INSTALL.bat → ไอคอน Desktop → Settings |
| `docs/HANDOFF_ONE_CLICK_INSTALL.md` | ไฟล์นี้ |

ไอคอนที่สร้างบน Desktop:

- `Send Bill Launcher.lnk` → `no_api_send_bill_manual\run_launcher_ui.vbs` (ไอคอน `send_bill.ico,0`)
- ไม่สร้าง `Capture Bill Launcher.lnk` — ผู้ใช้กด **ຖ່າຍຮູບບິນ** ใน Send Bill Launcher

---

## Checklist ให้ AI เครื่องหลักทำ

1. เปิดโฟลเดอร์ชุดแจก `Bill_Automation_Kit` (ไม่ใช่ `Automation_Work` production ที่มี secrets)
2. ตรวจว่ามีไฟล์ด้านบนครบ — ถ้าเครื่องหลักยังไม่มี ให้ดึงจากเครื่องทดสอบ / หรือ implement ตามสเปกด้านล่าง
3. อัปเดต README หัวข้อติดตั้งครั้งแรกให้ขึ้นต้นด้วย **ดับเบิลคลิก `INSTALL.bat`**
4. `git status` — ตรวจว่าไม่มี `.env`, `page_token.json`, `google_credentials.json`, `auth.json`, `browser_profile/`
5. Commit เฉพาะไฟล์ installer/docs แล้ว **push เมื่อเจ้าของ repo สั่ง**
6. ทดสอบบนเครื่องสะอาด (หรือเครื่องทดสอบ): clone ใหม่ → ดับเบิลคลิก `INSTALL.bat` → เห็นไอคอน Desktop → เปิด Launcher แล้ว Settings first-run ทำงาน

---

## สเปก `setup_windows.ps1` ที่ต้องคงไว้

Parameters:

- `-InstallPrerequisites` — winget ติดตั้ง Python 3.12, ngrok (คัดลอกไป `%LOCALAPPDATA%\ngrok\` + PATH + ไอคอน Desktop), และ git ถ้าขาด
- `-CreateDesktopShortcuts` — สร้างไอคอน Desktop (default **เปิด** ถ้าไม่ใส่ `-SkipDesktopShortcuts`)
- `-SkipPlaywright` — ข้ามดาวน์โหลด Chromium
- `-SkipDesktopShortcuts` — ไม่สร้างไอคอน

หลัง winget ติดตั้ง Python ต้อง **Refresh PATH** และมี fallback หา `python.exe` ที่ `%LocalAppData%\Programs\Python\Python312\` เพราะ session เดิมมักยังไม่เห็น Python

อัปเกรด pip ด้วย:

```powershell
& $venvPy -m pip install -q --upgrade pip
```

อย่าใช้ `pip.exe install --upgrade pip` ตรงๆ (บางเครื่อง Windows error “To modify pip…”)

สร้าง shortcut ด้วย `WScript.Shell` COM → `%UserProfile%\Desktop\*.lnk`

---

## สเปก `INSTALL.bat`

- `cd` ไปโฟลเดอร์ของตัวเอง (`%~dp0`)
- เรียก:  
  `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1" -InstallPrerequisites -CreateDesktopShortcuts`
- แสดงข้อความสำเร็จ/ล้มเหลว + `pause` ให้ผู้ใช้อ่านได้
- **ห้าม** ฝัง token / Sheet ID / password ในไฟล์นี้

---

## สิ่งที่ยังไม่ต้องทำใน INSTALL (ผู้ใช้กรอกเองผ่าน Settings)

- Google Sheet ID / Service Account JSON
- Facebook page token
- WEBHOOK_VERIFY_TOKEN / ngrok domain
- auth.json / browser profile login

Launcher มี first-run เปิด Settings อัตโนมัติเมื่อ critical config ยังไม่ครบ — คงพฤติกรรมนี้ไว้

---

## อย่าทำ

- อย่าคัดลอก secrets จาก `Automation_Work` เข้าชุดแจก
- อย่าบังคับให้ผู้ใช้รันคำสั่งยาวๆ ใน PowerShell เป็นขั้นตอนหลัก (INSTALL.bat คือหลัก)
- อย่าแก้ production daily-bill บนเครื่องหลักเพื่อฟีเจอร์นี้ — ทำใน `Bill_Automation_Kit` เท่านั้น เว้นแต่เจ้าของสั่งชัดเจน
- อย่า commit ไฟล์ secret

---

## ข้อความสั้นๆ ส่งต่อให้ AI เครื่องหลัก (คัดลอกได้)

```
โปรเจค Bill_Automation_Kit ต้องรองรับ one-click install:

1) มี INSTALL.bat ที่ root — ดับเบิลคลิกแล้วรัน
   setup_windows.ps1 -InstallPrerequisites -CreateDesktopShortcuts
2) setup ต้องสร้างไอคอน Desktop: Send Bill Launcher เท่านั้น (ไม่สร้าง Capture Bill Launcher)
3) หลัง winget ติดตั้ง Python ต้อง refresh PATH + fallback หา python.exe
4) ใช้ python -m pip แทน pip.exe --upgrade pip
5) run_launcher_ui.bat ต้องหา .venv ของ manual แล้วค่อย ..\.venv
6) README เปลี่ยนเป็น: clone → ดับเบิลคลิก INSTALL.bat → เปิดไอคอน Desktop → กรอก Settings
7) ห้ามใส่ secrets ใน installer; ห้ามยุ่ง Automation_Work production
8) อ่านรายละเอียดเต็มที่ docs/HANDOFF_ONE_CLICK_INSTALL.md
```
