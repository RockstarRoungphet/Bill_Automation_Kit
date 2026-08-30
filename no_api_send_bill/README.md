# ส่งบิลพัสดุไป Messenger (เวอร์ชันไม่ใช้ API — ใช้การค้นหา)

เวอร์ชันนี้**ไม่ใช้ Facebook Graph API** แต่ใช้**เบราว์เซอร์อัตโนมัติ** (Playwright) เพื่อ:
- กรองเฉพาะบิลที่มีสถานะ **"📦ລໍສົ່ງບິນ"** (Column A) เท่านั้น
1. เปิด Facebook Business Suite Inbox ตามชื่อเพจ
2. ค้นหา Order number ในแชท
3. เปิดแชทที่ตรง
4. ส่งข้อความ + copy-paste รูปบิล

---

## ความแตกต่างจากเวอร์ชัน API

| หัวข้อ | เวอร์ชัน API (เดิม) | เวอร์ชันไม่ใช้ API (ใหม่) |
|--------|---------------------|---------------------------|
| จับคู่ลูกค้า | Order → PSID ผ่าน message_echo + order_psid.json | Order + ชื่อเพจ (Column I) → แปลงชื่อเพจ → page_id → เปิด Inbox → ค้นหา Order |
| การส่งข้อความ/รูป | Graph API (ส่งไป PSID) | เบราว์เซอร์อัตโนมัติ: เปิดแชท → วางข้อความ + copy-paste รูป → กดส่ง |
| ข้อมูลที่ใช้ | Order, Tracking ID (1 เพจต่อ token) | Order, ชื่อเพจ (Column I), Tracking ID + config ชื่อเพจ → page_id (รองรับหลายเพจ) |

---

## สิ่งที่ต้องมี

- **Google Sheet** มีคอลัมน์:
  - **Column A** = สถานะ (ต้องเป็น **"📦ລໍສົ່ງບິນ"** เท่านั้น — script จะกรองเฉพาะแถวนี้)
  - **Column D** = Order ID
  - **Column I** = ชื่อเพจ (เช่น "MallShop", "Kittools", "ຂາຍທຸກຢ່າງທີ່ຖືກແລະດີ")
  - **Column Z** = Tracking ID
- **ไฟล์ config**: `config/page_name_to_id.json` (แมปชื่อเพจ → page_id)
- **รูปบิล**: โฟลเดอร์ `bills/` (หรือ path ที่กำหนด) ชื่อไฟล์ = `{tracking_id}.png`
- **Python + Playwright**: ติดตั้งตาม [requirements.txt](requirements.txt)

---

## การติดตั้ง

### 1. ติดตั้ง Python dependencies

**วิธีที่ 1 — ใช้สคริปต์ setup (แนะนำ):**

```bash
cd /home/phetm/projects/Testing/no_api_send_bill
./setup.sh
```

**วิธีที่ 2 — ติดตั้งด้วยตนเอง:**

```bash
cd /home/phetm/projects/Testing/no_api_send_bill
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

**หมายเหตุ:** ระบบ Python บน Linux มักเป็น "externally-managed-environment" ดังนั้นต้องใช้ virtual environment (`.venv`) แทนการติดตั้งโดยตรง

### 2. ล็อกอิน Facebook (ทำครั้งเดียว)

Script จะใช้ **browser profile** (`browser_profile/`) เพื่อเก็บ session อัตโนมัติ — **เหมือน browser ปกติ**

**ครั้งแรกที่รัน:**
1. รัน script (เช่น `open_inbox_and_send.py`)
2. เบราว์เซอร์จะเปิดขึ้นมา → **ล็อกอิน Facebook** (ถ้ายังไม่ล็อกอิน)
3. กด Enter เพื่อดำเนินการต่อ
4. Session จะถูกบันทึกอัตโนมัติใน `browser_profile/`

**ครั้งต่อไป:**
- **ไม่ต้องล็อกอินอีก** — browser จะใช้ session ที่บันทึกไว้ (เหมือน browser ปกติ)
- Session จะคงอยู่ **นานมาก** (เหมือน browser ปกติ) จนกว่าจะ logout หรือ Facebook logout อัตโนมัติ

**หมายเหตุ:**
- Browser profile ถูกเก็บใน `browser_profile/` (ถูก ignore ใน git)
- ถ้า session หมดอายุ (เจอหน้า login) → ล็อกอินอีกครั้ง → session จะถูกบันทึกอัตโนมัติ
- ไม่ต้องใช้ `save_facebook_session.py` อีกต่อไป — browser profile จะจัดการให้อัตโนมัติ

### 3. ตั้งค่า config

ไฟล์ `config/page_name_to_id.json` เก็บ mapping ชื่อเพจ → page_id:

```json
{
  "MallShop": "105875185730098",
  "Kittools": "105443769107872",
  ...
}
```

**วิธีหา Page ID:**
1. เปิด Facebook Business Suite → เลือกเพจใน Inbox
2. ดู URL จะมี `selected_page_id=XXXXX` → นั่นคือ Page ID
3. เพิ่มชื่อเพจและ Page ID ลงใน `config/page_name_to_id.json`

**เพจที่มีอยู่แล้ว (9 เพจ):**
- ຂາຍທຸກຢ່າງທີ່ຖືກແລະດີ: 102675065910746
- MallShop: 105875185730098
- Kittools: 105443769107872
- Intimemall: 101758306149310
- Gmax Center: 842039133115348
- Jungle adventure: 409928307788548
- ໝໍ້ໜຶ້ງເຂົ້າໄຟຟ້າ: 115237838117791
- SolarShop: 108483499025364
- P&R Store: 102717679384176

---

## วิธีใช้งาน

### ขั้นที่ 1 — Export CSV จาก Google Sheet

1. เปิด Google Sheet
2. **File → Download → CSV (.csv)**
3. บันทึกไฟล์ CSV (เช่น `orders.csv`)

### ขั้นที่ 2 — (ถ้าต้องการรูปบิล) ถ่ายภาพบิล

ใช้สคริปต์เดิม `capture_bill_screenshot.py` จากโฟลเดอร์หลัก:

```bash
cd /home/phetm/projects/Testing
.venv/bin/python3 capture_bill_screenshot.py /path/to/downloaded.csv
```

รูปจะถูกเก็บที่ `bills/{tracking_id}.png`

### ขั้นที่ 3 — ส่งบิล

#### ส่งบิล 1 Order:

```bash
cd /home/phetm/projects/Testing/no_api_send_bill
.venv/bin/python3 scripts/open_inbox_and_send.py <order_id> <page_name> <tracking_id>
```

ตัวอย่าง:
```bash
.venv/bin/python3 scripts/open_inbox_and_send.py 023590 "MallShop" 8260381217360
```

#### ส่งบิลหลาย Order จาก CSV:

```bash
.venv/bin/python3 scripts/open_inbox_and_send.py --csv /path/to/orders.csv
```

#### ระบุโฟลเดอร์รูปบิล:

```bash
.venv/bin/python3 scripts/open_inbox_and_send.py --csv orders.csv --bills-dir ../bills
```

#### ระบุ browser profile directory (ถ้าไม่ใช้ browser_profile/):

```bash
.venv/bin/python3 scripts/open_inbox_and_send.py --csv orders.csv --user-data-dir my_profile
```

#### ทดสอบแบบไม่ส่งจริง (dry-run):

```bash
.venv/bin/python3 scripts/open_inbox_and_send.py --csv orders.csv --dry-run
```

**หมายเหตุ:** 
- ใช้ `.venv/bin/python3` แทน `python3` เพื่อให้ใช้ virtual environment ที่ติดตั้ง dependencies แล้ว
- Browser จะใช้ profile จาก `browser_profile/` อัตโนมัติ — session จะคงอยู่เหมือน browser ปกติ (ไม่ต้องล็อกอินทุกครั้ง)

---

## โครงสร้างไฟล์

```
no_api_send_bill/
├── README.md                    # เอกสารนี้
├── requirements.txt            # Python dependencies
├── setup.sh                    # สคริปต์ติดตั้ง dependencies
├── browser_profile/            # Browser profile (cookies, session) - สร้างอัตโนมัติ
├── config/
│   └── page_name_to_id.json    # Mapping ชื่อเพจ → page_id
└── scripts/
    ├── read_sheet.py           # อ่าน CSV จาก Sheet
    ├── ui_selectors.py          # Selector ของ Business Suite
    └── open_inbox_and_send.py  # สคริปต์หลัก: เปิด Inbox → ค้นหา → ส่งบิล
```

---

## Flow การทำงาน

1. **อ่าน CSV**: ดึง Order (Column D), ชื่อเพจ (Column I), Tracking ID (Column Z)
   - **กรองเฉพาะแถวที่ Column A = "📦ລໍສົ່ງບິນ"** เท่านั้น
2. **แปลงชื่อเพจ → page_id**: ใช้ `config/page_name_to_id.json`
3. **เปิดเบราว์เซอร์**: Playwright เปิด Chromium
4. **เปิด Inbox**: `https://business.facebook.com/latest/inbox?selected_page_id={page_id}`
5. **ค้นหา Order**: กรอก Order number ในช่องค้นหา → กด Enter
6. **เปิดแชท**: คลิกแชทที่ตรงกับ Order (จากรายการค้นหา)
7. **ส่งข้อความ**: พิมพ์ข้อความ (เลขพัสดุ + ลิงก์ Anousith)
8. **Copy-paste รูป**: อ่านไฟล์รูปจาก `bills/{tracking_id}.png` → copy-paste ลงช่องแชท
9. **กดส่ง**: คลิกปุ่มส่ง (หรือกด Enter)

---

## วิธีรับมือเมื่อ Facebook เปลี่ยน UI

### ถ้า script ไม่ทำงาน (element ไม่เจอ)

1. **ตรวจสอบ LOG ใน Terminal**: script จะแสดงข้อความชัดเจน เช่น:
   ```
   ❌ ไม่พบช่องค้นหา Inbox — อาจเป็นเพราะ Facebook เปลี่ยน UI
   กรุณาตรวจสอบ ui_selectors.py และอัปเดต
   ```

2. **เปิดไฟล์ `scripts/ui_selectors.py`**: ดู selector ที่ใช้ (CSS selector หรือ XPath)

3. **ตรวจสอบ UI ล่าสุด**:
   - เปิด Facebook Business Suite Inbox ด้วยเบราว์เซอร์
   - ใช้ Developer Tools (F12) → Inspect element
   - หา selector / XPath / data-attribute ของ element ที่ต้องการ

4. **อัปเดต `ui_selectors.py`**:
   - แก้ไข selector ที่ไม่ทำงาน
   - อัปเดต `UI_VERSION` และ `UI_VERSION_NOTES` เป็นวันที่ปัจจุบัน

5. **ทดสอบอีกครั้ง**: รัน script ด้วย `--dry-run` ก่อน

### Element ที่ต้องตรวจสอบ

- **ช่องค้นหา** (`SEARCH_INPUT_SELECTOR`)
- **รายการแชท** (`CONVERSATION_ITEM_PRIMARY_TEMPLATE`, `CONVERSATION_ITEM_FALLBACK_TEMPLATES`)
- **ช่องพิมพ์ข้อความ** (`MESSAGE_INPUT_SELECTOR`)
- **ปุ่มส่ง** (`SEND_BUTTON_SELECTOR`)

สคริปต์จะหา ช่องพิมพ์ข้อความ และ ปุ่มส่ง ภายใน `send_message_with_image()` เท่านั้น — ถ้าไม่เจอจะแสดงข้อความใน Terminal และ return False

---

## ข้อความที่ส่งให้ลูกค้า

รูปแบบข้อความ:
```
เลขพัสดุ: {tracking_id}
ตรวจสอบบิล/สถานะ: https://app.anousith.express/landing/search_tracking/search_item?_bill_detail={tracking_id}
```

พร้อมแนบรูปบิล (ถ้ามีไฟล์ `bills/{tracking_id}.png`)

---

## Troubleshooting

### ไม่พบ page_id สำหรับเพจ

- ตรวจสอบว่าชื่อเพจใน Column I ของ Sheet ตรงกับ key ใน `config/page_name_to_id.json` หรือไม่
- เพิ่ม mapping ใหม่ใน `config/page_name_to_id.json`

### ไม่พบรูปบิล

- ตรวจสอบว่าไฟล์รูปมีชื่อตรงกับ `{tracking_id}.png` (หรือ .jpg)
- ตรวจสอบ path ของโฟลเดอร์รูปบิล (default: `../bills/`)

### เบราว์เซอร์ไม่เปิด / ไม่ล็อกอิน

- script ใช้ `headless=False` เพื่อให้เห็นเบราว์เซอร์
- ถ้ายังไม่ล็อกอิน Facebook (ครั้งแรก):
  1. ล็อกอินในเบราว์เซอร์ที่เปิดขึ้นมา
  2. กด Enter เพื่อดำเนินการต่อ
  3. Session จะถูกบันทึกอัตโนมัติใน `browser_profile/`
- **ครั้งต่อไปจะไม่ต้องล็อกอินอีก** — browser จะใช้ session ที่บันทึกไว้ (เหมือน browser ปกติ)

### Session หมดอายุ

- ถ้า script แจ้งว่ายังไม่ล็อกอิน แม้จะมี browser profile:
  - Session อาจหมดอายุแล้ว (Facebook logout อัตโนมัติ)
  - ล็อกอินอีกครั้ง → session จะถูกบันทึกอัตโนมัติใน browser profile
- Browser profile ทำให้ session คงอยู่ **นานมาก** (เหมือน browser ปกติ) จนกว่าจะ logout หรือ Facebook logout อัตโนมัติ

### Element ไม่เจอ

- ดูส่วน "วิธีรับมือเมื่อ Facebook เปลี่ยน UI" ด้านบน
- อัปเดต selector ใน `scripts/ui_selectors.py`

---

## หมายเหตุ

- **การถ่ายภาพบิล**: ใช้สคริปต์เดิม `capture_bill_screenshot.py` จากโฟลเดอร์หลัก (`/home/phetm/projects/Testing/`) ได้
- **โฟลเดอร์รูปบิล**: ใช้ร่วมกับของเดิมได้ (`../bills/`) หรือระบุ path เองด้วย `--bills-dir`
- **การทดสอบ**: ใช้ `--dry-run` เพื่อดูว่าจะส่งอะไรบ้างโดยไม่ส่งจริง
- **Facebook Session**: 
  - ใช้ **browser profile** (`browser_profile/`) เพื่อเก็บ session อัตโนมัติ
  - Session จะคงอยู่ **นานมาก** (เหมือน browser ปกติ) จนกว่าจะ logout หรือ Facebook logout อัตโนมัติ
  - ไม่ต้องล็อกอินทุกครั้ง — browser จะใช้ session ที่บันทึกไว้

---

## สรุป

เวอร์ชันนี้เหมาะสำหรับ:
- ✅ ไม่ต้องการใช้ Facebook Graph API
- ✅ มีหลายเพจ (รองรับหลายพันเพจผ่าน config)
- ✅ ต้องการควบคุมการส่งผ่านเบราว์เซอร์ (เห็นการทำงานจริง)

ข้อควรระวัง:
- ⚠️ Facebook อาจเปลี่ยน UI → ต้องอัปเดต selector ใน `ui_selectors.py`
- ⚠️ ต้องล็อกอิน Facebook ในเบราว์เซอร์ (ยังไม่มี auto-login)
