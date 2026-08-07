# สรุปวิธีที่ใช้ได้จริง (จากการรันทดสอบ)

อัปเดตจากผลการรันสคริปต์จนสำเร็จเมื่อ **2025-02-09**

---

## 1. เปิด Inbox ตามเพจ

- **วิธีที่ใช้:** เปิด URL โดยใส่ทั้ง `asset_id` และ `selected_page_id` ให้ตรงกับ `page_id`
- **URL:** `https://business.facebook.com/latest/inbox/all/?asset_id={page_id}&selected_page_id={page_id}`
- **ที่มา:** `ui_selectors.INBOX_URL_TEMPLATE` — ใส่ทั้งสอง parameter เพื่อไม่ให้ Facebook ใช้ asset จาก session ก่อนหน้า (เช่น เปิดผิดเพจ)

---

## 2. ค้นหา Order ในช่องค้นหา

- **วิธีที่ใช้:** กรอก Order number ในช่องค้นหาหลัก แล้วกด Enter (หรือรอให้ผลค้นหาปรากฏ)
- **Selector ช่องค้นหา:** `input[placeholder*="ค้นหา"], input[placeholder*="Search"], ...` (ดู `ui_selectors.SEARCH_INPUT_SELECTOR`)

---

## 3. ปุ่ม "ค้นหาในการสนทนา"

- **วิธีที่ใช้:** คลิก element ที่มีข้อความ **"ค้นหาในการสนทนาใน Messenger และ Instagram"** (หรือ "Search in Messenger and Instagram conversations")
- **วิธีหา:** ใช้ **text locator** ใน Playwright เช่น `page.locator('text="ค้นหาในการสนทนา"').first` หรือ CSS `div[role="button"]:has-text("ค้นหาในการสนทนา")`
- **ผล:** หลังคลิก รายชื่อบุคคลที่มีข้อความที่ค้นหาจะโผล่ในรายการแชท

---

## 4. รายการแชท (Conversation list)

- **หมายเหตุ:** `div[role="list"]` อาจไม่ visible หรือโหลดช้า จึง timeout ได้
- **วิธีที่ใช้ได้:** ไม่พึ่งแค่ `div[role="list"]` แต่ใช้ **fallback** หาแชทที่ตรง Order โดยตรง
- **Selector ที่ใช้ได้:** `div[tabindex="0"]:has-text("{order_id}")`  
  เช่น `div[tabindex="0"]:has-text("023702")` จะเจอรายการแชทที่มีเลข Order 023702 ในข้อความ
- **ที่มา:** ใน `open_inbox_and_send.py` — ลำดับคือ ลอง XPath ใน list ก่อน แล้วถ้า timeout ค่อยใช้ `div[tabindex="0"]:has-text("023702")`

---

## 5. คลิกเปิดแชท

- **วิธีที่ใช้:** คลิก element ที่ได้จากข้อ 4 (รายการแชทที่มี Order number)
- **ตรวจสอบว่าเปิดแชทสำเร็จ:** ตรวจว่ามีช่องพิมพ์ข้อความ (message input) ปรากฏ

---

## 6. ช่องพิมพ์ข้อความ (Message input)

- **Selector ที่ใช้ได้:** `div[contenteditable="true"][role="textbox"]` หรือ `ui_selectors.MESSAGE_INPUT_SELECTOR` / `MESSAGE_INPUT_XPATH`
- **การพิมพ์:** ใช้ `message_input.fill(message_text)` หลังคลิก focus

---

## 7. แนบรูปบิล

ลำดับที่สคริปต์ลอง (จากผลรัน):

1. **Input file:** หา `input[type="file"]` แล้ว `set_input_files(path)` — ถ้า Facebook ซ่อนหรือไม่มี input นี้จะไม่เจอ
2. **Drag-and-drop:** อ่านไฟล์เป็น base64 ใน Python ส่งเข้า `page.evaluate(base64 => ...)` สร้าง `Uint8Array` → `Blob` → `File` → `DataTransfer` แล้ว dispatch `DragEvent('drop')` ไปที่ `[contenteditable="true"]` หรือ `div[role="textbox"]` — **วิธีนี้ใช้ได้โดยไม่พึ่ง fetch('file://...')**
3. **Clipboard API:** อ่านไฟล์เป็น base64 ใน Python ส่งเข้า `page.evaluate()` สร้าง `Blob`/`File` แล้ว `navigator.clipboard.write([ClipboardItem])` จากนั้นกด `Control+v` ที่ช่องแชท — ต้องให้ context มี `permissions: ["clipboard-read", "clipboard-write"]`

---

## 8. ปุ่มส่ง (Send)

- **หมายเหตุ:** ปุ่มส่งอาจหาไม่เจอจาก CSS/aria-label (Facebook เปลี่ยน structure ได้)
- **วิธีที่ใช้ได้:** กด **Enter** ที่ช่องพิมพ์ข้อความ — `message_input.press("Enter")`  
  Messenger รองรับการส่งด้วย Enter
- **ที่มา:** ในสคริปต์ถ้า `send_button` เป็น None จะ fallback เป็น `message_input.press("Enter")`

---

## สรุปลำดับที่ใช้ได้ในรอบทดสอบ

| ขั้นตอน              | วิธีที่ใช้ได้ |
|----------------------|----------------|
| เปิด Inbox           | URL มี `asset_id` + `selected_page_id` |
| ช่องค้นหา            | `SEARCH_INPUT_SELECTOR` / placeholder ค้นหา |
| ปุ่มค้นหาในการสนทนา  | Text locator "ค้นหาในการสนทนาใน Messenger และ Instagram" |
| รายการแชท            | Fallback: `div[tabindex="0"]:has-text("{order_id}")` |
| เปิดแชท              | คลิกรายการที่เจอจากขั้นก่อน |
| ช่องพิมพ์            | `div[contenteditable="true"][role="textbox"]` |
| แนบรูป               | ลำดับ: input file → drag-and-drop (หรือ clipboard ถ้า drag ไม่โผล่) |
| ส่งข้อความ           | กด **Enter** (fallback เมื่อหาปุ่มส่งไม่เจอ) |

---

## การรันแบบไม่ interactive

ถ้ารันในสภาพที่ไม่มี TTY (เช่น `timeout ... script` หรือ cron) สคริปต์จะไม่รอ `input()` แต่จะรอ 5 วินาทีแล้วปิดเบราว์เซอร์เอง เพื่อไม่ให้เกิด `EOFError` เมื่อ stdin ปิด
