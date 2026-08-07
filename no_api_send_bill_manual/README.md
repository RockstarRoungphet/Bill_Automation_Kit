# ส่งบิล Manual — ปลอดภัย 100% (AutoHotkey)

โปรแกรมโหลดข้อมูลจาก Google Sheet แล้ว **copy ลิงก์/เลข Order/ข้อความ/รูป** ไป clipboard  
**คุณเป็นคนเปิด Browser วาง (Ctrl+V) และกดส่งเอง** — ไม่มี automation บนหน้า Facebook  
สัญญาณจาก **AutoHotkey** (Enter / ดับเบิลคลิก / ทริปเปิลคลิก) ส่งไปที่ Python ผ่าน HTTP

## สิ่งที่ต้องมี

- **Python 3** + โปรเจกต์นี้ (โหลด Sheet, copy ไป clipboard, รอสัญญาณ)
- **AutoHotkey v2** ติดตั้งบน Windows ([ดาวน์โหลด](https://www.autohotkey.com/))
- ไฟล์ **send_bill_signal.ahk** ในโฟลเดอร์นี้
- **ถ้ารัน Python จาก WSL** และต้องการ copy รูปไปวางในแชท Windows ได้: บน Windows เปิด PowerShell/CMD แล้วรัน **`pip install Pillow pywin32`** ครั้งเดียว — เพราะตอนวางรูปโปรแกรมจะให้ Windows รัน `copy_image_win.py` ซึ่งต้องใช้สองแพ็กนี้

## ขั้นตอนการรัน (เรียงลำดับ)

| ลำดับ | ทำอะไร | หมายเหตุ |
|-------|--------|----------|
| **1** | ใส่ credentials (ครั้งเดียว) | ดูรายละเอียดในข้อ 1 ด้านล่าง |
| **2** | รัน **Python** ก่อน: `python run_manual.py` | เปิด server รอสัญญาณ + copy ข้อมูลไป clipboard |
| **3** | รัน **AutoHotkey**: ดับเบิลคลิก `send_bill_signal.ahk` | ให้ AHK ทำงานค้างไว้ตลอดที่ส่งบิล |
| **4** | เปิด Browser → วางลิงก์/Order/ข้อความ/รูป ตามที่โปรแกรมแจ้ง → กด Enter หรือ ดับเบิลคลิก ตามขั้น | ทำตาม flow ใน Facebook Inbox |

สรุป: **รัน Python ก่อน → รัน AHK → แล้วค่อยทำใน Browser**

### ใช้ Launcher UI (บน Windows)

**ครั้งแรกบนเครื่องใหม่:** จาก repo root (`Automation_Work`) รัน `.\setup_windows.ps1` แล้วคัดลอก secrets ตาม `SECRETS_CHECKLIST.md` (ดู `WINDOWS_QUICKSTART.md`)

รัน **`python launcher_ui.py`** จากโฟลเดอร์นี้ (หรือดับเบิลคลิก **`run_launcher_ui.vbs`**) — แนะนำใช้ Python จาก **root** `.venv`:

```powershell
cd C:\Automation_Work\no_api_send_bill_manual
..\.venv\Scripts\pythonw.exe launcher_ui.py
```

หน้าต่าง Launcher มี:
- **พื้นที่แสดงสถานะ** — อัปเดตตาม output จาก run_manual.py แบบ real-time
- ปุ่ม **รัน run_manual.py** — เริ่มโปรแกรมส่งบิล (สถานะจะโผล่ในหน้าต่าง)
- ปุ่ม **รัน send_bill_signal.ahk** — เปิดสคริปต์ AHK

ไม่ต้องเปิด Terminal แยก แค่กดปุ่มใน UI แล้วทำตามขั้นใน Browser ได้เลย

**สร้าง Shortcut บน Desktop:** ดับเบิลคลิก **`create_desktop_shortcut.vbs`** ครั้งเดียว จะมีไอคอน **"Send Bill Launcher"** บน Desktop — คลิกเปิด Launcher UI ได้เลย

---

## การใช้งาน (รายละเอียด)

1. **ใส่ credentials**  
   ใน `config/sheet_config.json` ตั้ง `credentials_path` เป็น `../no_api_send_bill/config/google_credentials.json` หรือคัดลอกไฟล์ key มาที่ `config/google_credentials.json`

2. **รัน Python ก่อน**  
   - **บน WSL หรือ Linux (ใช้ Terminal แบบ bash)** — ใช้คำสั่งนี้:
     ```bash
     cd no_api_send_bill_manual
     .venv/bin/python run_manual.py
     ```
     (ถ้าอยู่ในโฟลเดอร์ `no_api_send_bill_manual` อยู่แล้ว รันแค่ `.venv/bin/python run_manual.py`)
   - **บน Windows (CMD หรือ PowerShell)** — ใช้คำสั่งนี้:
     ```cmd
     cd C:\path\to\no_api_send_bill_manual
     .venv\Scripts\python run_manual.py
     ```
     แทน `C:\path\to\no_api_send_bill_manual` ด้วย path จริงของโฟลเดอร์บน Windows
   - **โฟลเดอร์อยู่บน WSL แต่ต้องการรัน Python จาก Windows** (เพื่อให้ clipboard รูปใช้ได้):
     - PowerShell: `cd \\wsl$\Ubuntu\home\phetm\projects\Testing\no_api_send_bill_manual` แล้ว `python run_manual.py`
     - CMD: `pushd \\wsl$\Ubuntu\home\phetm\projects\Testing\no_api_send_bill_manual` แล้ว `python run_manual.py`
     ใช้ Python บน Windows — ติดตั้ง: `pip install gspread google-auth pyperclip pillow pywin32 plyer`

3. **รันสคริปต์ AutoHotkey**  
   ดับเบิลคลิกที่ `send_bill_signal.ahk` (หรือคลิกขวา → Run Script)  
   ให้สคริปต์ AHK ทำงานค้างไว้ตลอดที่ส่งบิล

4. **ทำตามขั้นตอนใน Facebook Inbox**  
   - โปรแกรมจะ copy ลิงก์/เลข Order/ข้อความ/รูป ไป clipboard ตามลำดับ  
   - คุณเปิด Browser วาง (Ctrl+V) และกดส่งเอง  
   - หลังทำแต่ละขั้น โปรแกรมจะรับสัญญาณจาก Ctrl+V / Enter / ดับเบิลคลิก อัตโนมัติ (ไม่ต้องสลับไปดู Terminal)

## สัญญาณจาก AutoHotkey

| การกระทำ | ความหมาย |
|----------|----------|
| **Ctrl+V** | ต่อไป — วางข้อมูล = ทำขั้นถัดไปอัตโนมัติ |
| **Enter** | ต่อไป — เปิดลิงก์ใน address bar = ทำขั้นถัดไป |
| **ดับเบิลคลิก** | ต่อไป — ยืนยัน "ส่งแล้ว" หลังคลิกปุ่มส่ง |
| **ทริปเปิลคลิก** / **Ctrl+Alt+N** | ไม่พบผลลัพธ์ (ข้าม Order นี้) — รวมกรณี popup WhatsApp **"ไม่ได้ใช้ WhatsApp"** (กด **ตกลง** ก่อน แล้วกด Ctrl+Alt+N) |
| **Ctrl+Z** | ถอยกลับ 1 ขั้น (กดซ้ำได้เรื่อยๆ) |

หมายเหตุ: ทุกปุ่มยังทำงานปกติในหน้าต่างที่โฟกัส (เช่น Ctrl+V ยังวาง, Enter ยังเปิดลิงก์, Ctrl+Z ยัง undo ในแอป)

## เมื่อทำครบทุก Order

- โปรแกรมจะ **ใส่วันที่ปัจจุบัน** (รูปแบบ **D/M/YYYY**) ลง **คอลัมน์ R** ในแถวที่ตรงกับ Order ที่ส่งสำเร็จ (ในทุกชีตที่กำหนดใน config)
- จากนั้น **เล่นเสียง** และแสดง **แจ้งเตือน Windows (Toast)** มุมขวาล่าง

หมายเหตุ: Service account ใน credentials ต้องมีสิทธิ์ **แก้ไข** Sheet (ไม่ใช่แค่ดู) จึงจะอัปเดตคอลัมน์ R ได้

## โฟลเดอร์บิล

โปรแกรมใช้โฟลเดอร์ **`Testing/bills/`** เท่านั้น (ชื่อไฟล์: `{tracking_id}.png` หรือ `.jpg`)  
ชื่อไฟล์: `{tracking_id}.png` หรือ `.jpg`

## การวางรูป (Clipboard)

- **รัน Python บน Windows**: โปรแกรมจะ copy รูปลง clipboard (ทั้ง DIB และ PNG) — วางในแชท (Ctrl+V) ได้
- **รัน Python บน WSL/Linux**: รูปจะอยู่ที่ clipboard ฝั่ง Linux ถ้าไปกด Ctrl+V ใน Chrome บน Windows จะไม่เห็นรูป — แนะนำให้รัน `run_manual.py` บน Windows หรือถ้า copy รูปไม่สำเร็จ โปรแกรมจะ copy **path ไฟล์** แทน ให้ใช้ปุ่มแนบไฟล์ในแชทแล้วเลือกไฟล์จาก path นั้น

## Config

- `config/sheet_config.json` — sheet_id, sheet_names, credentials_path
- `config/page_name_to_id.json` — ชื่อเพจ → page_id (ใช้สร้างลิงก์ Inbox)

## พอร์ต

Python เปิด HTTP server ที่ **127.0.0.1:29582** เพื่อรับสัญญาณจาก AHK  
ถ้าพอร์ตนี้ถูกใช้อยู่ แก้ค่า `SIGNAL_PORT` ใน `run_manual.py` และ `PORT` ใน `send_bill_signal.ahk` ให้ตรงกัน
