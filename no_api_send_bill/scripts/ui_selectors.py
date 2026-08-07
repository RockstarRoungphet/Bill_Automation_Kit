#!/usr/bin/env python3
"""
เก็บ selector / XPath / data-attribute ของ Facebook Business Suite
ใช้สำหรับสคริปต์ open_inbox_and_send.py

⚠️ สำคัญ: ถ้า Facebook เปลี่ยน UI และ script ไม่ทำงาน ให้อัปเดต selector ในไฟล์นี้
อัปเดตล่าสุด: 2025-02-09
"""

# URL ของ Business Suite Inbox
# ใส่ทั้ง asset_id และ selected_page_id ให้ตรงกับ page_id เพื่อไม่ให้ Facebook ใช้ asset จาก session ก่อนหน้า (เช่น Intimemall)
# ใช้ path /latest/inbox/all/ ตามที่ Facebook redirect จริง
INBOX_BASE_URL = "https://business.facebook.com/latest/inbox"
INBOX_URL_TEMPLATE = "https://business.facebook.com/latest/inbox/all/?asset_id={page_id}&selected_page_id={page_id}"

# Selector สำหรับช่องค้นหาใน Inbox (ช่องค้นหาหลัก)
SEARCH_INPUT_SELECTOR = 'input[placeholder*="ค้นหา"], input[placeholder*="Search"], input[type="search"], input[aria-label*="ค้นหา"], input[aria-label*="Search"]'

# Selector สำหรับช่อง "ค้นหาในการสนทนาใน Messenger และ Instagram" (ต้องคลิกหลังจากกรอก Order ในช่องค้นหาหลัก)
# Element นี้จะปรากฏหลังจากกรอก Order number ในช่องค้นหาหลัก
SEARCH_IN_CONVERSATIONS_SELECTOR = '''
    div[role="button"]:has-text("ค้นหาในการสนทนา"),
    div[role="button"]:has-text("Search in conversations"),
    button:has-text("ค้นหาในการสนทนา"),
    button:has-text("Search in conversations"),
    [aria-label*="ค้นหาในการสนทนา"],
    [aria-label*="Search in conversations"],
    div:has-text("ค้นหาในการสนทนาใน Messenger"),
    div:has-text("Search in Messenger and Instagram conversations")
'''.strip()

# XPath สำหรับช่อง "ค้นหาในการสนทนา" (ครอบคลุมข้อความภาษาไทยและอังกฤษ)
SEARCH_IN_CONVERSATIONS_XPATH = '''
    //div[@role="button" and (
        contains(text(), "ค้นหาในการสนทนา") or 
        contains(text(), "Search in conversations") or
        contains(text(), "ค้นหาในการสนทนาใน Messenger")
    )] | 
    //button[
        contains(text(), "ค้นหาในการสนทนา") or 
        contains(text(), "Search in conversations")
    ] |
    //div[contains(text(), "ค้นหาในการสนทนาใน Messenger และ Instagram")]
'''.strip()

# Selector สำหรับแชทแต่ละรายการ (คลิกเพื่อเปิด) — ใช้วิธีที่เสถียรที่สุด
# หลัก: div._a6ag (class ที่ Facebook ใช้กับแถวแชท) + has-text(order_id)
# ไม่ใช้ tabindex เพราะ Facebook เปลี่ยน UI แล้วไม่น่าเชื่อถือ
CONVERSATION_ITEM_PRIMARY_TEMPLATE = 'div._a6ag:has-text("{order_id}")'
# Fallback เมื่อ primary ไม่เจอ (ใช้ตามลำดับ)
CONVERSATION_ITEM_FALLBACK_TEMPLATES = [
    'div[role="presentation"]:has-text("{order_id}")',
    'div._4bl9:has-text("{order_id}")',
    'div[role="button"]:has-text("{order_id}")',
]

# Selector สำหรับช่องพิมพ์ข้อความในแชท
MESSAGE_INPUT_SELECTOR = 'div[contenteditable="true"][role="textbox"], textarea[placeholder*="ข้อความ"], textarea[placeholder*="Message"], [contenteditable="true"][aria-label*="ข้อความ"], [contenteditable="true"][aria-label*="Message"]'

# Selector สำหรับปุ่มส่งข้อความ
# ใน Messenger อาจเป็น icon หรือ button ที่ไม่มี aria-label
SEND_BUTTON_SELECTOR = '''
    button[aria-label*="ส่ง"],
    button[aria-label*="Send"],
    button[type="submit"][aria-label*="ส่ง"],
    button[type="submit"][aria-label*="Send"],
    [data-testid*="send-button"],
    button[aria-label*="ส่งข้อความ"],
    button[aria-label*="Send message"],
    svg[aria-label*="ส่ง"] + button,
    svg[aria-label*="Send"] + button,
    div[role="button"][aria-label*="ส่ง"],
    div[role="button"][aria-label*="Send"]
'''.strip()

# XPath alternatives (ถ้า CSS selector ไม่ทำงาน)
SEARCH_INPUT_XPATH = '//input[contains(@placeholder, "ค้นหา") or contains(@placeholder, "Search")]'
MESSAGE_INPUT_XPATH = '//div[@contenteditable="true" and @role="textbox"] | //textarea[contains(@placeholder, "ข้อความ") or contains(@placeholder, "Message")]'
SEND_BUTTON_XPATH = '//button[contains(@aria-label, "ส่ง") or contains(@aria-label, "Send")]'

# Timeout สำหรับรอ element (วินาที)
ELEMENT_WAIT_TIMEOUT = 10
PAGE_LOAD_TIMEOUT = 30

# เวอร์ชัน UI ที่ selector เหล่านี้ใช้ได้
UI_VERSION = "2025-02-09"
UI_VERSION_NOTES = "อัปเดตตาม Facebook Business Suite UI ณ วันที่ 2025-02-09"
