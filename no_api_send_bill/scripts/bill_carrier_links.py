"""เลือก URL ตรวจบิลตามขนส่ง (คอลัมน์ G ใน Sheet)."""
from __future__ import annotations

CARRIER_ANOUSITH = "ອານຸສິດ"
CARRIER_HAL = "ຮຸ່ງອາລຸນ"

ANOUSITH_BILL_URL_TEMPLATE = (
    "https://app.anousith.express/landing/search_tracking/search_item?_bill_detail={tracking_id}"
)
HAL_BILL_URL_TEMPLATE = "https://www.halexpress.la/parcel?search={tracking_id}"


def tracking_bill_url(carrier: str, tracking_id: str) -> str:
    """คืนลิงก์บิลตาม carrier; ค่าเริ่มต้น Anousith ถ้าไม่ใช่ HAL."""
    c = (carrier or "").strip()
    tid = (tracking_id or "").strip()
    if c == CARRIER_HAL:
        return HAL_BILL_URL_TEMPLATE.format(tracking_id=tid)
    return ANOUSITH_BILL_URL_TEMPLATE.format(tracking_id=tid)


def bill_tracking_customer_message(tracking_id: str, carrier: str = "") -> str:
    """ข้อความลาวมาตรฐานที่ส่งถึงลูกค้า (Facebook / WhatsApp / Messenger API / manual)."""
    tid = (tracking_id or "").strip()
    bill_link = tracking_bill_url(carrier, tid)
    return f"ເລກພັດສະດຸ: {tid}\nກວດເບິ່ງເຄື່ອງຮອດໃສແລ້ວ: {bill_link}"
