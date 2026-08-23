#!/usr/bin/env python3
"""
ส่งบิลพัสดุไป Messenger โดยใช้เบราว์เซอร์อัตโนมัติ (ไม่ใช้ API)
- เปิด Facebook Business Suite Inbox ตามชื่อเพจ
- ค้นหา Order number ในแชท
- เปิดแชทที่ตรง
- ส่งข้อความ + copy-paste รูปบิล

เกณฑ์ยืนยัน (หลัก + สำรอง):
- แชทโหลดแล้ว: (1) chat header เปลี่ยนจากเดิม + คงที่ 0.5s (2) ช่องพิมพ์เดิมหลุด + ช่องใหม่ visible (3) URL ไม่เปลี่ยน > 3s + ช่องพิมพ์ visible
- ส่งข้อความแล้ว: ช่อง compose ว่าง + รูป preview หาย (post-send verify)
- ไม่พบแชทจริง: ข้อความ "ไม่พบผลลัพธ์" ปรากฏต่อเนื่อง 2 ครั้ง

สิ่งที่เราควบคุมได้ (ทำให้ส่งได้แน่เท่าที่ทำได้):
- Re-query ช่องพิมพ์ก่อนใช้ทุกครั้ง + retry คลิกเมื่อ element หลุด (ลด race กับ React)
- ลองส่งซ้ำ 1 ครั้งถ้าครั้งแรกล้ม ( transient DOM/จังหวะ)
- ยืนยันหลังส่ง (compose ว่าง) แล้วลองกดส่งอีกครั้งถ้ายืนยันไม่ผ่าน

สิ่งที่เราควบคุมไม่ได้:
- Server/เน็ตล้มหรือช้า — ส่งไม่ถึง Facebook
- Facebook เปลี่ยน UI/selector — ต้องอัปเดต ui_selectors

ใช้:
  python3 open_inbox_and_send.py <order_id> <page_name> <tracking_id> [--carrier ຮຸ່ງອາລຸນ] [--bills-dir ../bill_images] [--dry-run]
  python3 open_inbox_and_send.py --csv <path_to_csv> [--bills-dir ../bill_images] [--dry-run]
  python3 open_inbox_and_send.py --sheet [sheet_id] [--sheet-name Sheet1] [--credentials path/to/key.json]
     ถ้าไม่ระบุ sheet_id จะอ่านจาก config/sheet_config.json
"""

import base64
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, List
from urllib.parse import urlparse, parse_qs

try:
    from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
except ImportError:
    print("❌ ต้องติดตั้ง Playwright ก่อน: pip install playwright && playwright install chromium")
    sys.exit(1)

# Import selectors และ config
SCRIPT_DIR = Path(__file__).parent
CONFIG_DIR = SCRIPT_DIR.parent / "config"
sys.path.insert(0, str(SCRIPT_DIR))
import ui_selectors
from bill_carrier_links import bill_tracking_customer_message

NOTIFY_DELIVERED_MESSAGE = "ຮອດແລ້ວເດີໄປຮັບເຄື່ອງແດ່ເຈົ້າ"
NOTIFY_STOCK_OUT_MESSAGE = "ເຄື່ອງເມິດແລ້ວເດີ ສາມາດຍົກເລີກ ຫຼື ຖ້າອີກ 1 ທິດເຄື່ອງມາຮອດເຮົາ ຫຼຸດລາຄາໃຫ້"
NOTIFY_STOCK_AVAILABLE_MESSAGE = "ມີເຄື່ອງແລ້ວເດີ ຖ້າຍັງຮັບແຈ້ງເດີ ເຮົາຈະລົດລາຄາໃຫ້ຕາມທີ່ແຈ້ງໄວ້"
NOTIFY_STOCK_OUT_RESULT = "📢ແຈ້ງສິນຄ້າໝົດແລ້ວ"
NOTIFY_STOCK_AVAILABLE_RESULT = "🔔ແຈ້ງມີສິນຄ້າແລ້ວ"

WHATSAPP_PAGE_NAME = "whatsapp"
MY_WHATSAPP_NUMBER = "+8562055597891"
WHATSAPP_COUNTRY_CODE = "856"

PAGE_NAME_TO_ID_FILE = CONFIG_DIR / "page_name_to_id.json"
DEFAULT_BILLS_DIR = Path(__file__).resolve().parent.parent.parent / "bill_images"
# User data directory สำหรับเก็บ browser profile (cookies, localStorage, session) - ทำให้ session คงอยู่เหมือน browser ปกติ
DEFAULT_USER_DATA_DIR = SCRIPT_DIR.parent / "browser_profile"
KIT_ROOT = SCRIPT_DIR.parent.parent
USER_SETTINGS_FILE = KIT_ROOT / "user_settings.json"


def _resolve_facebook_user_data_dir() -> Path:
    """Prefer facebook_user_data_dir from kit user_settings.json; else DEFAULT_USER_DATA_DIR."""
    if USER_SETTINGS_FILE.is_file():
        try:
            with open(USER_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = str((data or {}).get("facebook_user_data_dir") or "").strip()
            if raw:
                p = Path(raw)
                if not p.is_absolute():
                    p = KIT_ROOT / p
                return p.resolve()
        except Exception:
            pass
    return DEFAULT_USER_DATA_DIR.resolve()

def _agent_ui_snapshot(page: Page) -> dict:
    try:
        return page.evaluate(
            """() => {
              const txt = (s) => {
                const el = document.querySelector(s);
                return el ? (el.innerText || el.textContent || '').trim().slice(0, 120) : '';
              };
              return {
                dialogs: document.querySelectorAll('[role="dialog"], [aria-modal="true"]').length,
                composeChars: txt('div[contenteditable="true"][role="textbox"], [contenteditable="true"]').length,
                hasReplyYourselfText: !!document.body.innerText.match(/ตอบกลับด้วยตัวเอง|Reply yourself|Reply manually/i),
                hasConfirmReplyText: !!document.body.innerText.match(/(^|\\s)ตอบกลับ(\\s|$)|Reply/i),
              };
            }"""
        )
    except Exception as e:
        return {"snapshot_error": str(e)[:120]}

def _compose_draft_cleared(page: Page, image_attached: bool) -> bool:
    """True if composer has no text and (if image_attached) no img previews by current selectors."""
    try:
        msg_el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(
            f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}"
        )
        text_empty = True
        if msg_el:
            content = (msg_el.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
            text_empty = content == "" or content.replace("\n", "").strip() == ""
        image_gone = True
        if image_attached and msg_el:
            try:
                compose_imgs = page.query_selector_all(
                    'div[contenteditable="true"][role="textbox"] img, [contenteditable="true"] img'
                )
                image_gone = len(compose_imgs) == 0
            except Exception:
                image_gone = True
        return bool(text_empty and image_gone)
    except Exception:
        return False


def _pick_filtered_send_button(page: Page):
    """Return best send button handle (the actual message-send button, not AI/call buttons), or None."""
    # Keywords that disqualify a candidate (call, AI feature buttons, suggestions, etc.)
    REJECT_KEYWORDS = [
        "โทร", "สาย", "call", "phone",
        "ai", "เอไอ", "ผู้ช่วย", "assistant",
        "ต่อโดย", "forward", "ส่งต่อ",
        "auto", "อัตโนมัติ", "แนะนำ", "suggest",
    ]
    # Preferred exact / strong-match aria-labels (real send-message button)
    PREFERRED_EXACT = ["ส่ง", "send", "ส่งข้อความ", "send message", "ສົ່ງ"]

    def _score(aria: str, text: str) -> int:
        a = (aria or "").lower().strip()
        t = (text or "").lower().strip()
        # disqualify
        for kw in REJECT_KEYWORDS:
            if kw in a or kw in t:
                return -1
        # prefer exact match
        for ex in PREFERRED_EXACT:
            if a == ex or t == ex:
                return 100
        # prefer "ส่งข้อความ" containing
        if "ส่งข้อความ" in a or "send message" in a:
            return 80
        # generic 'ส่ง' / 'send' partial
        if "ส่ง" in a or "send" in a or "ສົ່ງ" in a:
            return 50
        return 10

    candidates = []
    try:
        all_btns = page.query_selector_all(ui_selectors.SEND_BUTTON_SELECTOR)
        for btn in all_btns:
            try:
                aria = btn.get_attribute("aria-label") or ""
                text = btn.evaluate("el => el.textContent?.trim() || ''") or ""
                sc = _score(aria, text)
                if sc < 0:
                    continue
                candidates.append((sc, btn))
            except Exception:
                continue
    except Exception:
        pass
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    try:
        btn = page.query_selector(f"xpath={ui_selectors.SEND_BUTTON_XPATH}")
        if btn:
            aria = btn.get_attribute("aria-label") or ""
            if _score(aria, "") < 0:
                return None
            return btn
    except Exception:
        pass
    return None


def _ensure_manual_reply_mode(page: Page) -> dict:
    """
    Handle Meta AI state:
    - press 'ตอบกลับด้วยตัวเอง' / 'Reply yourself'
    - confirm popup with 'ตอบกลับ' / 'Reply'
    """
    out = {"clicked_reply_yourself": False, "clicked_confirm_reply": False, "confirm_attempts": 0}
    # Try entering manual mode quickly; some runs need 2 rounds (first opens modal, second confirms).
    for _ in range(3):
        try:
            clicked_primary = page.evaluate(
                """() => {
                  const labels = ["ตอบกลับด้วยตัวเอง", "Reply yourself", "Reply manually"];
                  const candidates = document.querySelectorAll('button, [role="button"], a, div[role="button"]');
                  for (const t of labels) {
                    for (const el of candidates) {
                      const tx = (el.textContent || '').trim();
                      if (!tx || !tx.includes(t)) continue;
                      const st = window.getComputedStyle(el);
                      if (st.display === 'none' || st.visibility === 'hidden') continue;
                      const r = el.getBoundingClientRect();
                      if (r.width < 2 || r.height < 2) continue;
                      const cx = r.left + r.width / 2;
                      const cy = r.top + r.height / 2;
                      const topEl = document.elementFromPoint(cx, cy);
                      if (!(topEl === el || el.contains(topEl) || (topEl && topEl.contains && topEl.contains(el)))) continue;
                      el.click();
                      return true;
                    }
                  }
                  return false;
                }"""
            )
            out["clicked_reply_yourself"] = out["clicked_reply_yourself"] or bool(clicked_primary)
        except Exception:
            pass

        time.sleep(0.20)

        try:
            clicked_confirm = page.evaluate(
                """() => {
                  const roots = [...document.querySelectorAll('[role="dialog"], [aria-modal="true"]')];
                  if (!roots.length) return { ok: false, reason: "no_dialog" };
                  const visibleRoots = roots.filter(root => {
                    const st = window.getComputedStyle(root);
                    if (st.display === 'none' || st.visibility === 'hidden') return false;
                    const r = root.getBoundingClientRect();
                    return r.width >= 2 && r.height >= 2;
                  });
                  if (!visibleRoots.length) return { ok: false, reason: "no_visible_dialog" };
                  // Prefer top-most dialog
                  visibleRoots.sort((a, b) => {
                    const za = parseInt(window.getComputedStyle(a).zIndex || "0", 10) || 0;
                    const zb = parseInt(window.getComputedStyle(b).zIndex || "0", 10) || 0;
                    return zb - za;
                  });
                  const root = visibleRoots[0];
                  const candidates = root.querySelectorAll('button, [role="button"], a, div[role="button"]');
                  const isTopClickable = (el) => {
                    const r = el.getBoundingClientRect();
                    if (r.width < 2 || r.height < 2) return false;
                    const cx = r.left + r.width / 2;
                    const cy = r.top + r.height / 2;
                    const topEl = document.elementFromPoint(cx, cy);
                    if (!topEl) return false;
                    return topEl === el || el.contains(topEl) || (topEl.contains && topEl.contains(el));
                  };
                  // 1) explicit confirm labels in active dialog only
                  const labels = ["ตอบกลับ", "Reply"];
                  for (const t of labels) {
                    for (const el of candidates) {
                      const tx = (el.textContent || '').trim();
                      if (!tx || !tx.toLowerCase().includes(t.toLowerCase())) continue;
                      const st = window.getComputedStyle(el);
                      if (st.display === 'none' || st.visibility === 'hidden') continue;
                      if (!isTopClickable(el)) continue;
                      el.click();
                      return { ok: true, reason: "label_match", label: tx };
                    }
                  }
                  // 2) fallback: choose visible top-clickable button that is not cancel/not now
                  for (const el of [...candidates].reverse()) {
                    const tx = (el.textContent || '').trim();
                    if (!tx) continue;
                    const low = tx.toLowerCase();
                    if (/(ยกเลิก|cancel|ไม่ใช่ตอนนี้|not now)/i.test(low)) continue;
                    const st = window.getComputedStyle(el);
                    if (st.display === 'none' || st.visibility === 'hidden') continue;
                    if (!isTopClickable(el)) continue;
                    el.click();
                    return { ok: true, reason: "fallback_non_cancel", label: tx };
                  }
                  return { ok: false, reason: "no_confirm_button" };
                }"""
            )
            out["confirm_attempts"] += 1
            out["last_confirm_result"] = clicked_confirm
            out["clicked_confirm_reply"] = out["clicked_confirm_reply"] or bool((clicked_confirm or {}).get("ok"))
        except Exception:
            out["confirm_attempts"] += 1

        time.sleep(0.20)
        snap = _agent_ui_snapshot(page)
        # Done once AI reply strip and dialog are gone.
        if not snap.get("hasReplyYourselfText") and not snap.get("dialogs"):
            break
    return out


def _resolve_notify_mode(mode: Optional[str]) -> tuple[bool, str, str]:
    """
    Resolve notify mode configuration.
    Returns: (is_notify_mode, mode_label, notify_message)
    """
    if mode == "delivered":
        return True, "ແຈ້ງຮອດແລ້ວ", NOTIFY_DELIVERED_MESSAGE
    if mode == "stock_out":
        return True, "ແຈ້ງສິນຄ້າໝົດ", NOTIFY_STOCK_OUT_MESSAGE
    if mode == "stock_available":
        return True, "ແຈ້ງມີສິນຄ້າ", NOTIFY_STOCK_AVAILABLE_MESSAGE
    return False, "ส่งบิล", ""

# ---------------------------------------------------------------------------
# Stealth: ลดการตรวจจับ automation ให้มากที่สุด (รันก่อนโหลดทุกหน้า)
# ---------------------------------------------------------------------------
STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  try { delete Object.getPrototypeOf(navigator).webdriver; } catch {}

  if (!window.chrome) window.chrome = {};
  if (!window.chrome.runtime) window.chrome.runtime = { id: undefined };

  const oq = window.navigator.permissions && window.navigator.permissions.query
    ? window.navigator.permissions.query.bind(window.navigator.permissions)
    : null;
  if (oq) {
    window.navigator.permissions.query = (p) =>
      p.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : oq(p);
  }

  Object.defineProperty(navigator, 'plugins', {
    get: () => {
      const a = [
        { name:'Chrome PDF Plugin', filename:'internal-pdf-viewer', description:'Portable Document Format' },
        { name:'Chrome PDF Viewer', filename:'mhjfbmdgcfjbbpaeojofohoefgiehjai', description:'' },
        { name:'Native Client',     filename:'internal-nacl-plugin', description:'' },
      ];
      a.refresh = () => {};
      return a;
    }
  });

  Object.defineProperty(navigator, 'languages', { get: () => ['th-TH','th','lo','en-US','en'] });

  const gp = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return 'Google Inc. (NVIDIA)';
    if (p === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    return gp.call(this, p);
  };

  if (!navigator.connection) {
    Object.defineProperty(navigator, 'connection', {
      get: () => ({ effectiveType:'4g', rtt:50, downlink:10, saveData:false })
    });
  }
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

  for (const k of ['__playwright','__pw_manual','__PW_inspect',
    'cdc_adoQpoasnfa76pfcZLmcfl_Array','cdc_adoQpoasnfa76pfcZLmcfl_Promise',
    'cdc_adoQpoasnfa76pfcZLmcfl_Symbol']) {
    try { delete window[k]; } catch {}
  }
})();
"""

STEALTH_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
]


def _human_delay(min_ms: int = 200, max_ms: int = 800) -> float:
    """สุ่ม delay เล็กน้อยเพื่อเลียนแบบคนจริง (คืนค่าเป็นวินาที)"""
    ms = random.randint(min_ms, max_ms)
    t = ms / 1000.0
    time.sleep(t)
    return t


def _wa_metric(snap: dict, key: str, default: int = -1) -> int:
    """Read numeric probe field; 0 is valid (avoid `val or default` falsy bug)."""
    val = snap.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _wa_has_image_attached(snap: dict, baseline_blob: int = -1) -> bool:
    """True when WA media-draft preview is open (not ambient chat blob thumbnails).

    Do NOT treat bare docBlobImageCount > 0 as attached — chat avatars / link previews
    already use blob: URLs and caused false previewReady + wrong click path.
    """
    if _wa_metric(snap, "attachmentPreviewCount", 0) > 0:
        return True
    if _wa_metric(snap, "composeImgs", 0) > 0:
        return True
    if bool(snap.get("mediaPreviewOpen")):
        return True
    if bool(snap.get("mediaEditorVisible")):
        return True
    if baseline_blob >= 0 and _wa_metric(snap, "docBlobImageCount", 0) > baseline_blob:
        return True
    return False


def _wa_chat_outgoing_snapshot(page: Page) -> dict:
    """Count outgoing chat bubbles + whether last bubble has media (no message text logged)."""
    try:
        return page.evaluate(
            """() => {
              const main = document.querySelector('#main');
              if (!main) return {
                mainFound: false, outgoingCount: -1, lastOutgoingHasMedia: false,
                lastOutgoingTextLen: 0, lastOutgoingKeyHash: ''
              };
              const candidates = [...main.querySelectorAll(
                'div.message-out, [data-id].message-out, [data-testid="msg-container"]'
              )];
              const outgoing = [];
              const seen = new Set();
              for (const node of candidates) {
                const bubble = node.matches('.message-out')
                  ? node
                  : node.closest('.message-out');
                if (!bubble || seen.has(bubble)) continue;
                seen.add(bubble);
                outgoing.push(bubble);
              }
              let lastOutgoingHasMedia = false;
              let lastOutgoingTextLen = 0;
              let lastOutgoingKeyHash = '';
              if (outgoing.length) {
                const last = outgoing[outgoing.length - 1];
                lastOutgoingHasMedia = !!(last.querySelector(
                  'img[src], video, canvas, [data-testid="image-thumb"], [data-testid="media-thumb"] img, span[data-icon="media"]'
                ));
                lastOutgoingTextLen = (last.innerText || '').trim().length;
                const rawKey = last.getAttribute('data-id')
                  || last.querySelector('[data-id]')?.getAttribute('data-id')
                  || `${lastOutgoingTextLen}|${lastOutgoingHasMedia}|${last.getBoundingClientRect().top}`;
                let hash = 2166136261;
                for (let i = 0; i < rawKey.length; i++) {
                  hash ^= rawKey.charCodeAt(i);
                  hash = Math.imul(hash, 16777619);
                }
                lastOutgoingKeyHash = (hash >>> 0).toString(16);
              }
              return {
                mainFound: true,
                outgoingCount: outgoing.length,
                lastOutgoingHasMedia,
                lastOutgoingTextLen,
                lastOutgoingKeyHash
              };
            }"""
        )
    except Exception as e:
        return {
            "probeError": str(e)[:120],
            "mainFound": False,
            "outgoingCount": -1,
            "lastOutgoingHasMedia": False,
            "lastOutgoingTextLen": 0,
            "lastOutgoingKeyHash": "",
        }


def _wa_poll_chat_sent(
    page: Page,
    before: dict,
    expect_media: bool = False,
    expect_text: bool = True,
    max_iters: int = 24,
    interval: float = 0.25,
) -> Tuple[bool, dict]:
    """Poll until a new outgoing bubble appears in #main (real send confirmation)."""
    before_count = _wa_metric(before, "outgoingCount", 0)
    before_key = str(before.get("lastOutgoingKeyHash") or "")
    last_after = before
    for _ in range(max_iters):
        after = _wa_chat_outgoing_snapshot(page)
        last_after = after
        after_count = _wa_metric(after, "outgoingCount", 0)
        after_key = str(after.get("lastOutgoingKeyHash") or "")
        new_bubble = (
            (after_count > before_count and after_count >= 0)
            or (bool(after_key) and bool(before_key) and after_key != before_key)
            or (bool(after_key) and not before_key and after_count > 0)
        )
        if new_bubble:
            media_ok = (not expect_media) or bool(after.get("lastOutgoingHasMedia"))
            text_ok = (not expect_text) or _wa_metric(after, "lastOutgoingTextLen", 0) > 0
            if media_ok and text_ok:
                return True, after
        time.sleep(interval)
    return False, last_after


def _wa_build_verify_report(
    page: Page,
    had_image: bool,
    send_ok: bool,
    send_method: str,
    chat_before: Optional[dict] = None,
    chat_after: Optional[dict] = None,
    chat_verified: Optional[bool] = None,
) -> dict:
    """Break down post-send checks used to decide success (no message content)."""
    snap = _wa_probe_send_state(page)
    text_len = _wa_metric(snap, "composeTextLen", -1)
    attach_count = _wa_metric(snap, "attachmentPreviewCount", 0)
    footer_icons = snap.get("footerIconNames") or []
    mic_visible = any("mic" in str(i).lower() for i in footer_icons)
    send_visible = bool(snap.get("sendButtonInFooter"))
    # compose ว่าง = 0 chars; หลังส่งบางครั้ง element หาย ( -1 ) แต่ mic โผล่แทนปุ่มส่ง
    text_empty = text_len == 0 or (text_len == -1 and mic_visible and not send_visible)
    attachment_gone = attach_count == 0
    sent_ui_signal = mic_visible and not send_visible and text_empty
    if had_image:
        draft_cleared = bool((text_empty and attachment_gone) or sent_ui_signal)
        criteria = {
            "textEmpty": text_empty,
            "attachmentGone": attachment_gone,
            "sentUiSignal": sent_ui_signal,
            "sendAttemptOk": bool(send_ok),
            "sendMethod": send_method,
        }
        verified100 = bool(draft_cleared and send_ok and send_method not in ("", "none"))
    else:
        draft_cleared = bool(text_empty or sent_ui_signal)
        criteria = {
            "textEmpty": text_empty,
            "sentUiSignal": sent_ui_signal,
            "sendAttemptOk": bool(send_ok),
            "sendMethod": send_method,
        }
        verified100 = bool(draft_cleared and send_ok and send_method not in ("", "none"))
    if chat_verified is not None:
        verified100 = bool(verified100 and chat_verified)
    chat_block = {}
    if chat_before is not None:
        chat_block["before"] = chat_before
    if chat_after is not None:
        chat_block["after"] = chat_after
    if chat_verified is not None:
        chat_block["verifiedInChat"] = chat_verified
    return {
        "draftCleared": draft_cleared,
        "verified100": verified100,
        "criteria": criteria,
        "chat": chat_block,
        "signals": {
            "composeTextLen": text_len,
            "attachmentPreviewCount": attach_count,
            "sendButtonInFooter": send_visible,
            "micIconInFooter": mic_visible,
            "footerIconNames": footer_icons[:8],
        },
        "probe": snap,
    }


def _wa_probe_send_state(page: Page) -> dict:
    """Snapshot compose + send controls for debug (no PII)."""
    try:
        return page.evaluate(
            """() => {
              const footer = document.querySelector('footer');
              const ce = document.querySelector(
                'footer div[contenteditable="true"], div[contenteditable="true"][data-tab="10"]'
              );
              const composeText = ce
                ? (ce.innerText || ce.textContent || '').trim().length
                : -1;
              const composeImgs = ce ? ce.querySelectorAll('img').length : -1;
              let attachmentPreviewCount = 0;
              const footerIconNames = [];
              if (footer) {
                for (const sp of footer.querySelectorAll('span[data-icon]')) {
                  const n = sp.getAttribute('data-icon') || '';
                  if (n) footerIconNames.push(n);
                }
                attachmentPreviewCount = footer.querySelectorAll(
                  'img[src^="blob:"], img[src^="data:"], canvas, video'
                ).length;
              }
              let mediaNearCompose = 0;
              let mediaPreviewOpen = false;
              if (footer && footer.parentElement) {
                mediaNearCompose = footer.parentElement.querySelectorAll('img, video, canvas').length;
              }
              mediaPreviewOpen = !!document.querySelector(
                '[data-testid="media-viewer"], [data-animate-media-popup="true"], [data-testid="media-editor"]'
              );
              // Current WA media drawer often lacks old testids — detect editor toolbar icons
              const mediaEditorVisible = !!document.querySelector(
                'span[data-icon="media-editor-sticker"], span[data-icon="crop-rotate"], ' +
                'span[data-icon="emoji-input"], span[data-icon="media-editor-draw"], ' +
                '[data-testid="draw-entry"], [data-testid="media-canvas-wrapper"], ' +
                'span[data-icon="checkbox-round-checked"]'
              );
              const fileInputCount = document.querySelectorAll('input[type="file"]').length;
              // Real media draft previews almost always use blob:/data:image sources
              const docBlobImageCount = document.querySelectorAll(
                'img[src^="blob:"], img[src^="data:image"]'
              ).length;
              const allSendSpans = document.querySelectorAll(
                'span[data-icon="send"], span[data-icon="wds-ic-send-filled"]'
              );
              const footerSendSpans = footer
                ? footer.querySelectorAll('span[data-icon="send"], span[data-icon="wds-ic-send-filled"]').length
                : 0;
              let sendButtonInFooter = false;
              let sendButtonAria = '';
              const sendParents = [];
              const reject = /mic|attach|emoji|sticker|voice|โทร|call|plus|\\+/i;
              if (footer) {
                for (const btn of footer.querySelectorAll('button, [role="button"]')) {
                  const aria = (btn.getAttribute('aria-label') || '').trim();
                  const icon = btn.querySelector('span[data-icon]');
                  const iconName = icon ? icon.getAttribute('data-icon') || '' : '';
                  if (reject.test(aria) || reject.test(iconName)) continue;
                  const r = btn.getBoundingClientRect();
                  const st = window.getComputedStyle(btn);
                  const visible = st.display !== 'none' && st.visibility !== 'hidden' && r.width > 2 && r.height > 2;
                  const isSend = /send|ส่ง|ສົ່ງ/i.test(aria) || (iconName && iconName.includes('send'));
                  if (isSend && visible) {
                    sendButtonInFooter = true;
                    if (!sendButtonAria) sendButtonAria = aria || iconName;
                  }
                  if (isSend) {
                    sendParents.push({
                      inFooter: true,
                      tag: btn.tagName,
                      aria: aria.slice(0, 40),
                      iconName,
                      disabled: !!btn.disabled || btn.getAttribute('aria-disabled') === 'true',
                      visible,
                      w: Math.round(r.width),
                      h: Math.round(r.height),
                    });
                  }
                }
              }
              for (const sp of allSendSpans) {
                const btn = sp.closest('button, [role="button"]') || sp.parentElement;
                if (!btn) continue;
                const r = btn.getBoundingClientRect();
                const st = window.getComputedStyle(btn);
                const inFooter = !!(footer && footer.contains(btn));
                sendParents.push({
                  inFooter,
                  tag: btn.tagName,
                  disabled: !!btn.disabled || btn.getAttribute('aria-disabled') === 'true',
                  visible: st.display !== 'none' && st.visibility !== 'hidden' && r.width > 2 && r.height > 2,
                  w: Math.round(r.width),
                  h: Math.round(r.height),
                });
              }
              return {
                composeTextLen: composeText,
                composeImgs,
                attachmentPreviewCount,
                mediaNearCompose,
                mediaPreviewOpen,
                mediaEditorVisible,
                fileInputCount,
                docBlobImageCount,
                footerIconNames: footerIconNames.slice(0, 12),
                sendButtonInFooter,
                sendButtonAria,
                sendSpanTotal: allSendSpans.length,
                footerSendSpans,
                sendParents: sendParents.slice(0, 6),
              };
            }"""
        )
    except Exception as e:
        return {"probeError": str(e)[:120]}


def _wa_get_fresh_compose(page: Page):
    """ช่องพิมพ์ข้อความในแชทหลัก (#main) — ห้ามไปจับช่องค้นหา sidebar."""
    selectors = [
        '#main footer div[contenteditable="true"][data-tab="10"]',
        '#main footer div[contenteditable="true"]',
        '#main div[contenteditable="true"][data-tab="10"]',
        '#main div[title="พิมพ์ข้อความ"]',
        '#main div[title="Type a message"]',
        # fallback เก่า (ยังต้องอยู่ใน main ถ้าเป็นไปได้)
        'div[contenteditable="true"][data-tab="10"]',
        'footer div[contenteditable="true"]',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if not el:
                continue
            # ตัด element ใน #side ออก
            try:
                in_side = el.evaluate(
                    """el => {
                      const side = document.querySelector('#side');
                      return !!(side && side.contains(el));
                    }"""
                )
                if in_side:
                    continue
            except Exception:
                pass
            return el
        except Exception:
            pass
    return None


def _wa_click_exact_order_result(page: Page, order_id: str) -> dict:
    """คลิกแถวผลค้นหาที่ Order ID exact 100% (selector เดียวกับ scan + forms)."""
    oid = _wa_order_search_key(order_id)
    forms = _wa_order_id_forms(oid)
    try:
        pick = page.evaluate(
            """({ orderId, forms }) => {
              const side = document.querySelector('#side') || document.body;
              // ชุดเดียวกับ scan ใน _wa_search_open_chat_by_order_id
              const nodes = [...side.querySelectorAll(
                '[data-testid="cell-frame-container"], div[role="listitem"], div[tabindex="-1"]'
              )];
              const strip = (s) => (s || '').replace(/[\\u200e\\u200f\\u202a-\\u202e\\ufeff]/g, '');
              const formSet = new Set((forms || []).map(f => (f || '').toLowerCase()));
              const tokensEq = (text) => {
                const cleaned = strip(text).trim();
                if (!cleaned) return false;
                const toks = cleaned.match(/[A-Za-z0-9_\\-]+/g) || [];
                for (const t of toks) {
                  const tc = t.toLowerCase();
                  if (formSet.has(tc)) return true;
                  const compact = tc.replace(/[^a-z0-9]/g, '');
                  if (compact && formSet.has(compact)) return true;
                }
                return cleaned.split('\\n').some(l => {
                  const ls = l.trim().toLowerCase();
                  if (formSet.has(ls)) return true;
                  const c = ls.replace(/[^a-z0-9]/g, '');
                  return !!(c && formSet.has(c));
                });
              };
              const lineEq = (text) =>
                strip(text).split('\\n').some(l => {
                  const ls = l.trim().toLowerCase();
                  if (formSet.has(ls)) return true;
                  const c = ls.replace(/[^a-z0-9]/g, '');
                  return !!(c && formSet.has(c));
                });

              let bestIdx = -1;
              let bestScore = -1;
              let bestText = '';
              let bestY = 0;
              let bestCx = 0;
              let bestCy = 0;
              for (let i = 0; i < nodes.length; i++) {
                const n = nodes[i];
                const r = n.getBoundingClientRect();
                // message hit แถวเตี้ยได้; ตัด pane ยักษ์ / off-screen
                if (r.width < 40 || r.height < 16 || r.height > 220) continue;
                if (r.y < 40 || r.y > (window.innerHeight || 900)) continue;
                const text = (n.innerText || n.textContent || '').trim();
                if (!tokensEq(text)) continue;
                if (text.length > 500) continue;
                let score = 100;
                if (lineEq(text)) score += 50;
                if (text.length <= 40) score += 80;
                score += Math.max(0, 40 - Math.floor(r.y / 50));
                if (score > bestScore) {
                  bestScore = score;
                  bestIdx = i;
                  bestText = text.slice(0, 120);
                  bestY = Math.round(r.y);
                  bestCx = Math.round(r.x + r.width / 2);
                  bestCy = Math.round(r.y + Math.min(r.height, 40) / 2);
                }
              }
              if (bestIdx < 0) {
                return { ok: false, reason: 'no_exact_node', score: -1, nodeCount: nodes.length };
              }
              const target = nodes[bestIdx].closest('[data-testid="cell-frame-container"]')
                || nodes[bestIdx].closest('div[role="listitem"]')
                || nodes[bestIdx];
              try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
              const r2 = target.getBoundingClientRect();
              // คลิกฝั่งซ้าย (ชื่อ/avatar) — กลางแถวมักเป็น thumbnail รูป → เปิด media viewer
              const clickX = r2.x + Math.min(56, Math.max(24, r2.width * 0.18));
              const clickY = r2.y + Math.min(r2.height, 36) / 2;
              // หลีกเลี่ยงคลิก img ในแถว
              let clickEl = target.querySelector(
                '[data-testid="cell-frame-title"], [data-testid="cell-frame-primary-title"], ' +
                'span[title], [dir="auto"]'
              ) || target;
              if (clickEl.closest && clickEl.closest('img, video, canvas, [data-testid*="image"], [data-testid*="media"]')) {
                clickEl = target;
              }
              try {
                const opts = {
                  bubbles: true, cancelable: true, view: window, button: 0,
                  clientX: clickX,
                  clientY: clickY,
                };
                for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                  try { clickEl.dispatchEvent(new MouseEvent(type, opts)); } catch (e) {}
                }
                try { clickEl.click(); } catch (e) {}
              } catch (e) {}
              return {
                ok: true,
                index: bestIdx,
                via: 'dom_left_title',
                score: bestScore,
                textLen: bestText.length,
                hasLineEq: lineEq(bestText),
                y: Math.round(r2.y),
                cx: Math.round(clickX),
                cy: Math.round(clickY),
                nodeCount: nodes.length,
              };
            }""",
            {"orderId": oid, "forms": forms},
        ) or {"ok": False, "reason": "evaluate_empty"}
    except Exception as e:
        return {"ok": False, "reason": f"exc:{str(e)[:80]}"}

    if not pick.get("ok"):
        return pick

    # Playwright คลิกที่พิกัดฝั่งซ้ายของแถว (หลีกเลี่ยงรูป thumbnail)
    idx = int(pick.get("index", -1))
    if idx >= 0:
        try:
            cx, cy = pick.get("cx"), pick.get("cy")
            if cx is not None and cy is not None:
                handle = page.evaluate_handle(
                    """({x, y}) => {
                      let el = document.elementFromPoint(x, y);
                      if (!el) return null;
                      // ถ้ายืนบนรูป — เลื่อนไปซ้ายหาชื่อ
                      if (el.closest('img, video, canvas, [data-testid*="image"], [data-testid*="media"]')) {
                        el = document.elementFromPoint(Math.max(40, x - 80), y) || el;
                      }
                      return el.closest('[data-testid="cell-frame-container"]')
                        || el.closest('div[role="listitem"]')
                        || el;
                    }""",
                    {"x": float(cx), "y": float(cy)},
                )
                el = handle.as_element() if handle else None
                if el:
                    try:
                        el.click(timeout=2500, force=True)
                        pick["via"] = "playwright_left"
                    except Exception as e1:
                        page.mouse.click(float(cx), float(cy))
                        pick["via"] = f"mouse_left"
                        pick["playwrightErr"] = str(e1)[:60]
                else:
                    page.mouse.click(float(cx), float(cy))
                    pick["via"] = "mouse_left"
        except Exception as e:
            pick["playwrightErr"] = str(e)[:60]
    # ถ้า click แล้วเด้ง media viewer ปิดทันที
    time.sleep(0.15)
    if _wa_is_media_viewer_open(page):
        _wa_close_media_viewer(page)
        pick["hadViewer"] = True
    return pick


def _wa_focus_main_compose(page: Page):
    """blur ช่องค้นหา แล้วโฟกัส compose ใน #main."""
    try:
        page.evaluate(
            """() => {
              const side = document.querySelector('#side');
              if (side) {
                for (const inp of side.querySelectorAll('input, [contenteditable="true"]')) {
                  try { inp.blur(); } catch (e) {}
                }
              }
              const ce = document.querySelector(
                '#main footer div[contenteditable="true"], #main div[contenteditable="true"][data-tab="10"]'
              );
              if (ce) {
                ce.focus();
                try {
                  const r = document.createRange();
                  r.selectNodeContents(ce);
                  r.collapse(false);
                  const s = window.getSelection();
                  s.removeAllRanges();
                  s.addRange(r);
                } catch (e) {}
                return true;
              }
              return false;
            }"""
        )
    except Exception:
        pass
    return _wa_get_fresh_compose(page)


def _wa_attach_image_clipboard(page: Page, image_path: Path, msg_input=None) -> Tuple[bool, str]:
    """Attach bill image via clipboard paste (working method from reference pack)."""
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        # ClipboardItem is most reliable with image/png (same as working reference + FB path)
        mime = "image/png"

        copy_ok = page.evaluate(
            f"""
            async () => {{
                try {{
                    const byteCharacters = atob('{image_base64}');
                    const byteNumbers = new Array(byteCharacters.length);
                    for (let i = 0; i < byteCharacters.length; i++) {{
                        byteNumbers[i] = byteCharacters.charCodeAt(i);
                    }}
                    const byteArray = new Uint8Array(byteNumbers);
                    const blob = new Blob([byteArray], {{type: '{mime}'}});
                    const item = new ClipboardItem({{ '{mime}': blob }});
                    await navigator.clipboard.write([item]);
                    return true;
                }} catch (e) {{
                    return String(e && e.message ? e.message : e).slice(0, 120);
                }}
            }}
            """
        )
        if copy_ok is not True:
            return False, f"clipboard_write_failed:{copy_ok}"

        if msg_input:
            try:
                msg_input.click()
            except Exception:
                compose = _wa_focus_compose(page)
                if not compose:
                    return False, "compose_focus_failed"
        else:
            compose = _wa_focus_compose(page)
            if not compose:
                return False, "compose_focus_failed"

        _human_delay(200, 400)
        page.keyboard.press("Control+v")
        return True, f"clipboard_paste:{mime}"
    except Exception as e:
        return False, f"clipboard_exception:{str(e)[:120]}"


def _wa_attach_image_file(page: Page, image_path: Path) -> Tuple[bool, str]:
    """Fallback: attach via WhatsApp file input (less reliable than clipboard paste)."""
    try:
        # Open the attachment menu so WA creates/reveals its media file input.
        page.evaluate(
            """() => {
              const footer = document.querySelector('footer');
              if (!footer) return false;
              for (const el of footer.querySelectorAll('button, [role="button"]')) {
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                const icon = el.querySelector('span[data-icon]')?.getAttribute('data-icon') || '';
                if (/attach|แนบ|plus|เพิ่ม/.test(aria) || /attach|plus/.test(icon)) {
                  el.click();
                  return true;
                }
              }
              return false;
            }"""
        )
    except Exception:
        pass

    waited = 0.0
    while waited < 3.0:
        inputs = page.query_selector_all('input[type="file"]')
        for file_input in inputs:
            try:
                accept = (file_input.get_attribute("accept") or "").lower()
                if accept and "image" not in accept and "*/*" not in accept:
                    continue
                file_input.set_input_files(str(image_path.resolve()))
                return True, (accept or "file_input")[:120]
            except Exception:
                continue
        time.sleep(0.1)
        waited += 0.1
    return False, "image_file_input_not_found"


def _wa_wait_image_preview(
    page: Page,
    baseline_blob: int = 0,
    max_wait: float = 8.0,
) -> Tuple[bool, dict]:
    """Wait until media drawer / real draft image appears (relative to baseline blob count)."""
    waited = 0.0
    last_snap: dict = {}
    while waited < max_wait:
        last_snap = _wa_probe_send_state(page)
        if _wa_has_image_attached(last_snap, baseline_blob=baseline_blob):
            return True, last_snap
        time.sleep(0.15)
        waited += 0.15
    return False, last_snap


def _wa_find_media_send_button(page: Page):
    """Largest visible Send control (green media-drawer send is typically bigger than footer)."""
    try:
        handle = page.evaluate_handle(
            """() => {
              const reject = /mic|attach|emoji|sticker|voice|โทร|call|plus|\\+|back|ปิด|close/i;
              const nodes = [
                ...document.querySelectorAll(
                  'span[data-icon="send"], span[data-icon="wds-ic-send-filled"], ' +
                  'button[aria-label="Send"], button[aria-label="ส่ง"], ' +
                  'div[aria-label="Send"], div[aria-label="ส่ง"]'
                )
              ];
              let best = null;
              let bestScore = -1;
              for (const n of nodes) {
                const btn = n.closest('button, [role="button"]')
                  || (n.matches && n.matches('button, [role="button"]') ? n : n.parentElement);
                if (!btn) continue;
                const aria = (btn.getAttribute('aria-label') || '').trim();
                const icon = btn.querySelector('span[data-icon]');
                const iconName = icon ? (icon.getAttribute('data-icon') || '') : (n.getAttribute('data-icon') || '');
                if (reject.test(aria) || reject.test(iconName)) continue;
                const r = btn.getBoundingClientRect();
                const st = window.getComputedStyle(btn);
                if (r.width < 24 || r.height < 24) continue;
                if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) continue;
                if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') continue;
                // Prefer large lower-right media send over tiny header icons
                let score = r.width * r.height + r.y * 2 + r.x;
                if (/^(send|ส่ง|ສົ່ງ)$/i.test(aria)) score += 5000;
                if (iconName.includes('send')) score += 3000;
                if (r.width >= 40 && r.height >= 40) score += 2000;
                if (score > bestScore) {
                  bestScore = score;
                  best = btn;
                }
              }
              return best;
            }"""
        )
        el = handle.as_element() if handle else None
        if el:
            return el
    except Exception:
        pass
    return None


def _wa_send_media_once(page: Page) -> Tuple[bool, str]:
    """Send media draft once — no multi-method spam (avoids ยึกๆยักๆ click loops).

    Prefer green media-drawer Send (short force click). Fallback: Enter once.
    """
    # Wait briefly for the large media send button to paint
    btn = None
    waited = 0.0
    while waited < 3.0:
        btn = _wa_find_media_send_button(page)
        if btn:
            break
        time.sleep(0.1)
        waited += 0.1

    if btn:
        try:
            box = btn.bounding_box()
            if box and box.get("width", 0) >= 20:
                page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )
                return True, "media_mouse_click"
        except Exception:
            pass
        try:
            # Short timeout + force — never block ~30s on actionability
            btn.click(timeout=1500, force=True)
            return True, "media_force_click"
        except Exception:
            pass
        try:
            page.evaluate(
                "(el) => { if (el) { el.scrollIntoView({block:'center'}); el.click(); } }",
                btn,
            )
            return True, "media_js_click"
        except Exception:
            pass

    # Fallback like working reference: Enter once only
    try:
        page.keyboard.press("Enter")
        return True, "enter"
    except Exception as e:
        return False, f"enter_failed:{str(e)[:80]}"


def _wa_media_send_settled(page: Page, baseline_blob: int, max_wait: float = 4.0) -> Tuple[bool, dict]:
    """True when media drawer closed / draft not hanging after send click."""
    waited = 0.0
    last: dict = {}
    while waited < max_wait:
        last = _wa_probe_send_state(page)
        still_open = _wa_has_image_attached(last, baseline_blob=baseline_blob)
        # Footer back to normal chat (mic, no media send) is a strong signal
        icons = [str(i).lower() for i in (last.get("footerIconNames") or [])]
        mic_ok = any("mic" in i for i in icons)
        if not still_open or mic_ok:
            return True, last
        time.sleep(0.15)
        waited += 0.15
    return False, last


def _wa_find_send_button(page: Page):
    """Return actionable send button in footer, or None."""
    try:
        handle = page.evaluate_handle(
            """() => {
              const footer = document.querySelector('footer');
              if (!footer) return null;
              const reject = /mic|attach|emoji|sticker|voice|โทร|call|plus|\\+/i;
              const nodes = footer.querySelectorAll('button, [role="button"]');
              let best = null;
              let bestScore = -1;
              for (const btn of nodes) {
                const aria = (btn.getAttribute('aria-label') || '').trim();
                const icon = btn.querySelector('span[data-icon]');
                const iconName = icon ? icon.getAttribute('data-icon') || '' : '';
                if (reject.test(aria) || reject.test(iconName)) continue;
                const r = btn.getBoundingClientRect();
                if (r.width < 8 || r.height < 8) continue;
                const st = window.getComputedStyle(btn);
                if (st.display === 'none' || st.visibility === 'hidden') continue;
                if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') continue;
                let score = 0;
                if (/^(send|ส่ง|ສົ່ງ)$/i.test(aria)) score += 100;
                if (iconName.includes('send')) score += 80;
                if (/send|ส่ง|ສົ່ງ/i.test(aria)) score += 50;
                if (score > bestScore) {
                  bestScore = score;
                  best = btn;
                }
              }
              if (best && bestScore > 0) return best;
              for (const sp of footer.querySelectorAll('span[data-icon]')) {
                const iconName = sp.getAttribute('data-icon') || '';
                if (!iconName.includes('send')) continue;
                const btn = sp.closest('button, [role="button"]') || sp.parentElement;
                if (!btn) continue;
                const r = btn.getBoundingClientRect();
                if (r.width >= 8 && r.height >= 8) return btn;
              }
              return null;
            }"""
        )
        el = handle.as_element() if handle else None
        if el:
            return el
    except Exception:
        pass
    return None


def _wa_wait_compose_ready(page: Page, expect_attachment: bool = False, max_wait: float = 8.0) -> bool:
    """Poll until send control or attachment preview is ready."""
    waited = 0.0
    interval = 0.15
    last_snap = {}
    while waited < max_wait:
        snap = _wa_probe_send_state(page)
        last_snap = snap
        if snap.get("sendButtonInFooter") or _wa_find_send_button(page):
            return True
        if expect_attachment and _wa_metric(snap, "attachmentPreviewCount", 0) > 0:
            return True
        if not expect_attachment and _wa_metric(snap, "composeTextLen", 0) > 0:
            return True
        time.sleep(interval)
        waited += interval
    ready = bool(_wa_find_send_button(page))
    return ready


def _wa_poll_draft_cleared(page: Page, had_image: bool = False, max_iters: int = 14, interval: float = 0.15) -> bool:
    for _ in range(max_iters):
        if _wa_compose_draft_cleared(page, had_image=had_image):
            return True
        time.sleep(interval)
    return False


def _wa_send_draft(page: Page, had_image: bool = False) -> Tuple[bool, str]:
    """Send current WhatsApp compose draft with trusted pointer event first."""
    image_attached = had_image
    if image_attached:
        _wa_wait_compose_ready(page, expect_attachment=True, max_wait=8.0)

    def _try(method: str, fn) -> Tuple[bool, str]:
        before = _wa_probe_send_state(page)
        ok = False
        err = ""
        try:
            ok = bool(fn())
        except Exception as e:
            err = str(e)[:160]
        after = _wa_probe_send_state(page)
        cleared = _wa_poll_draft_cleared(page, had_image=image_attached, max_iters=14)
        if cleared:
            return True, method
        return False, method

    # 1) Trusted mouse click at the visible button center.
    # JS el.click() can clear the draft without producing an outgoing bubble.
    send_btn = _wa_find_send_button(page)
    if send_btn:
        def _mouse_click():
            box = send_btn.bounding_box()
            if not box:
                return False
            page.mouse.click(
                box["x"] + box["width"] / 2,
                box["y"] + box["height"] / 2,
            )
            return True
        ok, method = _try("mouse_click", _mouse_click)
        if ok:
            return True, method

    # 2) JS click fallback
    send_btn = _wa_find_send_button(page)
    if send_btn:
        def _js_click():
            page.evaluate(
                "(el) => { if (el) { el.scrollIntoView({block:'center'}); el.click(); } }",
                send_btn,
            )
            return True
        ok, method = _try("js_click", _js_click)
        if ok:
            return True, method

    # 3) Enter บน compose (focus ผ่าน JS ไม่ใช้ click)
    compose = _wa_focus_compose(page)
    if compose:
        def _enter():
            compose.press("Enter")
            return True
        ok, method = _try("enter", _enter)
        if ok:
            return True, method

    # 4) Playwright click ปุ่มส่ง
    send_btn = _wa_find_send_button(page)
    if send_btn:
        def _pw_click():
            send_btn.click(timeout=2000, force=True)
            return True
        ok, method = _try("pw_click", _pw_click)
        if ok:
            return True, method

    # 5) Enter retry
    compose = _wa_focus_compose(page)
    if compose:
        def _enter_retry():
            compose.press("Enter")
            return True
        ok, method = _try("enter_retry", _enter_retry)
        if ok:
            return True, method

    return False, "none"


def _wa_compose_draft_cleared(page: Page, had_image: bool = False) -> bool:
    """True when WhatsApp compose has no pending text/image draft."""
    try:
        snap = _wa_probe_send_state(page)
        if snap.get("probeError"):
            return False
        text_len = _wa_metric(snap, "composeTextLen", -1)
        attach_count = _wa_metric(snap, "attachmentPreviewCount", 0)
        footer_icons = snap.get("footerIconNames") or []
        mic_visible = any("mic" in str(i).lower() for i in footer_icons)
        send_visible = bool(snap.get("sendButtonInFooter"))
        text_ok = text_len == 0 or (text_len == -1 and mic_visible and not send_visible)
        if not had_image:
            return bool(text_ok)
        attach_ok = attach_count == 0
        sent_ui_signal = mic_visible and not send_visible and text_ok
        return bool((text_ok and attach_ok) or sent_ui_signal)
    except Exception:
        return False


def _wa_focus_compose(page: Page):
    """Focus compose without Playwright click (avoids 30s actionability timeout)."""
    compose = _wa_get_fresh_compose(page)
    if not compose:
        return None
    try:
        page.evaluate("(el) => { if (el) el.focus(); }", compose)
    except Exception:
        pass
    return compose


def load_page_name_to_id() -> dict:
    """โหลด mapping ชื่อเพจ → page_id จาก config"""
    if not PAGE_NAME_TO_ID_FILE.exists():
        print(f"❌ ไม่พบไฟล์ config: {PAGE_NAME_TO_ID_FILE}", file=sys.stderr)
        return {}
    try:
        with open(PAGE_NAME_TO_ID_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ ไม่สามารถโหลด config ได้: {e}", file=sys.stderr)
        return {}


def get_page_id(page_name: str, mapping: dict) -> Optional[str]:
    """แปลงชื่อเพจเป็น page_id"""
    return mapping.get(page_name.strip())

def get_business_page_names(mapping: dict) -> set:
    """ดึงรายชื่อเพจที่ใช้ business_id จาก config"""
    return set(mapping.get("__business_pages", []))


def _get_selected_item_id_from_url(url: str) -> Optional[str]:
    """ดึงค่า selected_item_id จาก URL ของ Business Suite Inbox"""
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        ids = qs.get("selected_item_id", [])
        return ids[0] if ids else None
    except Exception:
        return None

def _names_match(header_name: str, expected_name: str) -> bool:
    """ตรวจว่าชื่อจาก chat header ตรงกับชื่อลูกค้าจาก Google Sheet (Column E)
    ใช้ fuzzy match เพราะชื่ออาจต่างกันเล็กน้อย (script, spacing, nicknames)"""
    if not header_name or not expected_name:
        return False
    h = header_name.strip()
    e = expected_name.strip()
    if not h or not e:
        return False
    # Exact match
    if h == e:
        return True
    # Containment (one contains the other)
    if h in e or e in h:
        return True
    # First word match (handles "John Smith" vs "John S.")
    h_words = h.split()
    e_words = e.split()
    if h_words and e_words and len(h_words[0]) >= 2 and len(e_words[0]) >= 2:
        if h_words[0] == e_words[0]:
            return True
    return False

# JavaScript ดึงชื่อจาก chat header + spinner count ในครั้งเดียว (ลด IPC overhead)
# FB Business Suite ไม่มี [role="main"] — ค้นหา document-wide: heading → region → strong/h → link → span
_JS_CHAT_SIGNALS = """() => {
    let headerName = '';
    // skip ข้อความ UI ทั่วไป / banner โปรโมชัน ที่ไม่ใช่ชื่อแชท เช่น "22 chats ready for your offer"
    const skip = /ข้อความ|Messenger|Instagram|ค้นหา|Search|Learn more|ดูเพิ่มเติม|เชื่อมต่อ|Connect|ไม่ใช่ตอนนี้|เริ่มต้น|Inbox|chats? ready for your offer|charts? ready for your offer|^\\s*$/i;
    const ok = (t) => t && t.length >= 2 && t.length < 80 && !skip.test(t);
    const doc = document;
    for (const el of doc.querySelectorAll('[role="heading"]')) {
        const t = (el.textContent||'').trim();
        if (ok(t)) { headerName = t; break; }
    }
    if (!headerName) {
        for (const sel of ['strong', 'h1', 'h2', 'h3']) {
            for (const el of doc.querySelectorAll(sel)) {
                const t = (el.textContent||'').trim();
                if (ok(t)) { headerName = t; break; }
            }
            if (headerName) break;
        }
    }
    if (!headerName) {
        for (const r of doc.querySelectorAll('[role="region"]')) {
            const h = r.querySelector('[role="heading"], strong, h1, h2, h3');
            const t = (h ? h.textContent : r.textContent || '').trim();
            if (ok(t)) { headerName = t; break; }
        }
    }
    if (!headerName) {
        for (const a of doc.querySelectorAll('a')) {
            const t = (a.textContent||'').trim();
            if (ok(t)) { headerName = t; break; }
        }
    }
    if (!headerName) {
        for (const s of doc.querySelectorAll('span[dir="auto"]')) {
            const t = (s.textContent||'').trim();
            if (ok(t)) { headerName = t; break; }
        }
    }
    const spinners = doc.querySelectorAll('[role="progressbar"]').length +
                    doc.querySelectorAll('[data-visualcompletion="loading-state"]').length;
    return { headerName: headerName, spinners: spinners };
}"""


def build_inbox_url(page_name: str, page_id: str, business_page_names: set, selected_item_id: Optional[str] = None, thread_type: str = "FB_MESSAGE") -> str:
    """สร้าง URL สำหรับเปิด Inbox
    - ถ้าเพจอยู่ใน business_page_names → ใช้ ?business_id={page_id} (+ selected_item_id ถ้ามี)
    - ไม่เช่นนั้น → ใช้ ?asset_id={page_id}&selected_page_id={page_id} (+ selected_item_id ถ้ามี)
    - ถ้ามี selected_item_id → เพิ่ม &mailbox_id=&selected_item_id={selected_item_id}&thread_type={thread_type} เพื่อเปิดแชทเฉพาะคน (ป้องกันการเปิดแชทล่าสุดอัตโนมัติ)
    """
    base_url = "https://business.facebook.com/latest/inbox/all/"
    if page_name in business_page_names:
        # Business pages: ใช้แค่ business_id + selected_item_id (ไม่ต้องใช้ asset_id)
        url = f"{base_url}?business_id={page_id}"
        # เพิ่ม selected_item_id สำหรับ business pages (เพื่อป้องกันการเปิดแชทล่าสุด)
        if selected_item_id:
            url += f"&mailbox_id=&thread_type={thread_type}&selected_item_id={selected_item_id}"
    else:
        url = f"{base_url}?asset_id={page_id}&selected_page_id={page_id}"
        # ถ้ามี selected_item_id ให้เพิ่มเพื่อเปิดแชทเฉพาะคน (ป้องกันการเปิดแชทล่าสุดอัตโนมัติ)
        if selected_item_id:
            url += f"&mailbox_id=&selected_item_id={selected_item_id}&thread_type={thread_type}"
    
    return url


def get_initial_inbox_url(page_name: str, page_id: str, business_page_names: set, mapping: dict) -> str:
    """สร้าง URL สำหรับเปิดหน้า Inbox
    selected_item_id เป็นทางเลือก — ถ้าไม่มีใน config จะเปิด Inbox ของเพจนั้นโดยไม่เจาะจงแชท
    """
    raw_initial = mapping.get("__initial_selected_item_id")
    per_page = (mapping.get("__initial_selected_item_ids") or {}).get(page_name)
    selected_item_id = raw_initial or per_page
    if not selected_item_id:
        print(
            f"   ℹ️ ไม่มี selected_item_id สำหรับเพจ '{page_name}' — เปิด Inbox ปกติ"
        )
    return build_inbox_url(page_name, page_id, business_page_names, selected_item_id=selected_item_id or None)

def find_bill_image(bills_dir: Path, tracking_id: str) -> Optional[Path]:
    """หาไฟล์รูปบิลที่ตรงกับ tracking_id"""
    if not bills_dir or not bills_dir.is_dir():
        return None
    # Fast-path exact filenames first
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        img_path = bills_dir / f"{tracking_id}{ext}"
        if img_path.is_file():
            return img_path
    # Fallback: case-insensitive match (helps with .PNG/.JPG or mixed naming)
    t_norm = (tracking_id or "").strip().lower()
    for p in bills_dir.iterdir():
        try:
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            if p.stem.strip().lower() == t_norm:
                return p
        except Exception:
            continue
    return None

def _fmt_elapsed(seconds: float) -> str:
    """แสดงเวลาเป็น x.xxs"""
    return f"{seconds:.2f}s"


def _is_whatsapp_page(page_name: str) -> bool:
    return page_name.strip().lower() == WHATSAPP_PAGE_NAME


def _normalize_phone_for_whatsapp(phone: str) -> str:
    """แปลงเบอร์โทรเป็นรูปแบบสำหรับ WhatsApp (country code + number, ไม่มี +)"""
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith(WHATSAPP_COUNTRY_CODE):
        return phone
    if phone.startswith("0"):
        phone = phone[1:]
    return WHATSAPP_COUNTRY_CODE + phone


def _build_whatsapp_url(phone: str, text: str = "") -> str:
    from urllib.parse import quote
    normalized = _normalize_phone_for_whatsapp(phone)
    url = f"https://web.whatsapp.com/send?phone={normalized}"
    if text:
        url += f"&text={quote(text)}"
    return url


def _wa_is_login_page(page: Page) -> bool:
    """ตรวจว่าอยู่หน้า QR Code login ของ WhatsApp Web หรือไม่"""
    try:
        if page.query_selector('canvas[aria-label="Scan this QR code to link a device!"]'):
            return True
        if page.query_selector('canvas[aria-label]') and page.query_selector('div[data-ref]'):
            return True
        if page.query_selector('[data-testid="qrcode"]'):
            return True
        landing = page.query_selector('div._aigv')
        if landing and not page.query_selector('div#side'):
            inner = (landing.evaluate("el => el.innerText || ''") or "").strip()
            if "QR" in inner or "link" in inner.lower() or "เชื่อม" in inner:
                return True
    except Exception:
        pass
    return False


_WA_INVALID_PHONE_KEYWORDS = (
    "ไม่ได้ใช้ whatsapp",
    "ไม่ได้ลงทะเบียน",
    "ไม่ถูกต้อง",
    "invalid",
    "doesn't have",
    "does not have",
    "phone number shared",
    "is not on whatsapp",
    "not on whatsapp",
    "not registered on whatsapp",
    "ไม่มี whatsapp",
    "no whatsapp account",
)


def _wa_text_has_invalid_phone_marker(text: str) -> bool:
    t = (text or "").lower()
    return any(kw in t for kw in _WA_INVALID_PHONE_KEYWORDS)


def _wa_is_invalid_phone(page: Page) -> bool:
    """ตรวจว่า WhatsApp แสดง popup เบอร์ไม่มีบัญชี (เช่น 'ไม่ได้ใช้ WhatsApp')"""
    try:
        for sel in (
            'div[data-animate-modal-popup="true"]',
            'div._amk4',
            '[role="dialog"]',
        ):
            popup = page.query_selector(sel)
            if popup:
                txt = popup.evaluate("el => el.innerText || ''") or ""
                if _wa_text_has_invalid_phone_marker(txt):
                    return True
        body_txt = page.evaluate("() => document.body ? (document.body.innerText || '') : ''") or ""
        if _wa_text_has_invalid_phone_marker(body_txt):
            # ต้องมีบริบท modal/เบอร์ — ลด false positive จากข้อความทั่วไปในหน้า
            if "หมายเลข" in body_txt or "phone number" in body_txt.lower():
                return True
    except Exception:
        pass
    return False


def _wa_dismiss_invalid_phone_dialog(page: Page) -> bool:
    """กดปุ่มตกลง/OK บน popup เบอร์ไม่มี WhatsApp"""
    dismiss_labels = ("ตกลง", "OK", "Ok", "Got it", "เข้าใจแล้ว")
    try:
        for label in dismiss_labels:
            try:
                loc = page.get_by_role("button", name=label, exact=False)
                if loc.count() > 0:
                    loc.first.click(timeout=3000)
                    time.sleep(0.5)
                    return True
            except Exception:
                continue
        clicked = page.evaluate(
            """() => {
              const labels = ['ตกลง', 'OK', 'Got it', 'เข้าใจแล้ว'];
              const roots = document.querySelectorAll(
                '[role="dialog"], [data-animate-modal-popup="true"], div._amk4'
              );
              for (const root of roots) {
                const buttons = root.querySelectorAll('button, div[role="button"]');
                for (const b of buttons) {
                  const t = (b.innerText || b.textContent || '').trim();
                  if (labels.some(l => t === l || t.includes(l))) {
                    b.click();
                    return true;
                  }
                }
              }
              return false;
            }"""
        )
        if clicked:
            time.sleep(0.5)
            return True
    except Exception:
        pass
    return False


def _wa_handle_invalid_phone(page: Page, normalized: str) -> bool:
    """ถ้าเจอ popup เบอร์ไม่มี WhatsApp → กดตกลง แล้ว log; คืน True = ให้ caller ข้ามรายการ"""
    if not _wa_is_invalid_phone(page):
        return False
    _wa_dismiss_invalid_phone_dialog(page)
    print(f"   ❌ เบอร์ {normalized} ไม่ได้ใช้ WhatsApp — ข้ามรายการนี้")
    return True


def _wa_wait_for_login(page: Page, timeout_sec: int = 300) -> bool:
    """รอให้ผู้ใช้ scan QR Code จนกว่า WhatsApp Web จะพร้อม (หรือ timeout)
    หลัง scan QR → WhatsApp reload/navigate หน้า → ต้อง handle context destroyed
    หลัง login → WhatsApp sync ข้อมูล → ต้องรอจนกว่า sidebar (div#side) จะโผล่"""
    print(f"\n   🔐 WhatsApp Web ยังไม่ได้ล็อกอิน")
    print(f"   📱 กรุณา scan QR Code ด้วยแอป WhatsApp บนมือถือ")
    print(f"   ⏳ รอไม่เกิน {timeout_sec // 60} นาที...\n")
    start = time.time()
    dot_count = 0
    navigation_detected = False
    while time.time() - start < timeout_sec:
        try:
            # ตรวจว่า WhatsApp โหลดเสร็จ (sidebar ขึ้นแล้ว = sync เสร็จ พร้อมใช้งาน)
            side = page.query_selector('div#side')
            if side:
                if navigation_detected:
                    # หลัง navigation → รอเพิ่มให้ sync เสร็จสมบูรณ์
                    print(f"   🔄 กำลัง sync ข้อมูล WhatsApp...")
                    time.sleep(5)
                    # ตรวจอีกครั้งว่า sidebar ยังอยู่ (sync ไม่ได้หายไป)
                    try:
                        if page.query_selector('div#side'):
                            print(f"   ✅ WhatsApp Web ล็อกอิน + sync สำเร็จ! ({_fmt_elapsed(time.time() - start)})")
                            return True
                    except Exception:
                        time.sleep(3)
                        continue
                else:
                    print(f"   ✅ WhatsApp Web ล็อกอินสำเร็จ! ({_fmt_elapsed(time.time() - start)})")
                    return True
        except Exception as ctx_err:
            err_msg = str(ctx_err).lower()
            if "context was destroyed" in err_msg or "navigation" in err_msg or "destroyed" in err_msg:
                if not navigation_detected:
                    navigation_detected = True
                    print(f"   🔄 ตรวจพบ WhatsApp กำลัง reload หลัง scan QR — รอ sync ข้อมูล...")
                # รอให้ page settle หลัง navigation
                time.sleep(3)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    time.sleep(2)
                continue
            else:
                time.sleep(2)
                continue

        dot_count += 1
        if dot_count % 10 == 0:
            elapsed = int(time.time() - start)
            if navigation_detected:
                print(f"   🔄 WhatsApp กำลัง sync... ({elapsed}s)")
            else:
                print(f"   ⏳ รอ scan QR Code... ({elapsed}s)")
        time.sleep(2)
    print(f"\n   ❌ หมดเวลา {timeout_sec}s — WhatsApp Web ไม่พร้อม")
    return False


def _wa_order_search_key(order_id: str) -> str:
    """Order ID จากคอลัมน์ D ใช้ค้นหา WhatsApp (trim เท่านั้น)."""
    return (order_id or "").strip()


def _wa_order_id_forms(order_id: str) -> list[str]:
    """รูปแบบเทียบ exact: ต้นฉบับ + แบบยุบตัวอักษร/เลข (X-023992 ≡ X023992)."""
    oid = _wa_order_search_key(order_id)
    if not oid:
        return []
    forms = {oid.casefold()}
    compact = re.sub(r"[^a-zA-Z0-9]", "", oid).casefold()
    if compact:
        forms.add(compact)
    return list(forms)


def _wa_order_search_queries(order_id: str) -> list[str]:
    """คำค้นหาหลายแบบ — ยังเลือกคลิกด้วย exact form ของ order จริงเท่านั้น."""
    oid = _wa_order_search_key(order_id)
    if not oid:
        return []
    out: list[str] = []
    for q in (oid, oid.replace("-", ""), re.sub(r"(?i)^x-?", "", oid)):
        q = (q or "").strip()
        if q and q not in out:
            out.append(q)
    return out


def _wa_strip_bidi(text: str) -> str:
    """ลบเครื่องหมายทิศทางข้อความที่ WA แทรกใน preview."""
    return re.sub(r"[\u200e\u200f\u202a-\u202e\ufeff]", "", text or "")


def _wa_text_has_exact_order_id(text: str, order_id: str) -> bool:
    """True เฉพาะเมื่อมีโทเคนเท่ากับ order_id 100% — ห้ามเป็น prefix ของเลขยาวกว่า.

    ตัวอย่าง order = 020123
      - "…\\n020123"        → True  (คลิกได้)
      - "…\\n020123456"     → False (ห้าม — แม้ WA ไฮไลต์ 020123 ด้านใน)
      - "order 020123 ok"  → True
    order = X-023992  เทียบเท่า X023992 (ไม่มี dash)
    """
    forms = set(_wa_order_id_forms(order_id))
    if not forms:
        return False
    cleaned = _wa_strip_bidi(text).strip()
    if not cleaned:
        return False
    tokens = re.findall(r"[A-Za-z0-9_\-]+", cleaned)
    for t in tokens:
        tc = t.casefold()
        if tc in forms:
            return True
        tcompact = re.sub(r"[^a-z0-9]", "", tc)
        if tcompact and tcompact in forms:
            return True
    for line in cleaned.splitlines():
        ls = line.strip().casefold()
        if ls in forms:
            return True
        lcompact = re.sub(r"[^a-z0-9]", "", ls)
        if lcompact and lcompact in forms:
            return True
    return False


def _wa_exact_order_score(text: str, order_id: str) -> int:
    """คะแนนเลือกผล exact — สูงสุดเมื่อมีบรรทัด = order id ทั้งหมด."""
    if not _wa_text_has_exact_order_id(text, order_id):
        return 0
    oid = _wa_order_search_key(order_id)
    forms = set(_wa_order_id_forms(order_id))
    cleaned = _wa_strip_bidi(text)
    score = 100  # base: token exact ผ่าน
    for line in cleaned.splitlines():
        ls = line.strip().casefold()
        if ls in forms or re.sub(r"[^a-z0-9]", "", ls) in forms:
            score += 50  # บรรทัด preview = order id ตรงตัว
            break
    # ผลในหมวด "ข้อความ" มักเป็นแค่บรรทัด Order ID สั้น ๆ — ให้คะแนนสูงกว่าแถวแชทที่ preview ยาว
    stripped_all = cleaned.strip()
    if len(stripped_all) <= max(len(oid) + 8, 24):
        score += 80
    # ลงโทษถ้ายังมีโทเคนตัวเลขยาวกว่า oid (แถวมีทั้ง exact และ partial — ยังเลือกได้แต่อยู่รอง)
    tokens = re.findall(r"[A-Za-z0-9_\-]+", cleaned)
    oid_digits = re.sub(r"\D", "", oid)
    for t in tokens:
        if t.isdigit() and oid_digits and len(t) > len(oid_digits) and t.startswith(oid_digits):
            score -= 5
    return score


def _wa_is_media_viewer_open(page: Page) -> bool:
    """ตรวจว่าเปิด full-screen media viewer (รูปที่ส่งแล้ว) อยู่หรือไม่."""
    try:
        return bool(
            page.evaluate(
                """() => {
                  if (document.querySelector(
                    '[data-testid="media-viewer"], [data-animate-media-viewer="true"], ' +
                    '[data-testid="media-canvas-wrapper"]'
                  )) return true;
                  // ปุ่มควบคุม viewer: zoom / download / close ที่มุมบน
                  const icons = [...document.querySelectorAll('span[data-icon]')].map(
                    el => el.getAttribute('data-icon') || ''
                  );
                  const viewerIcons = icons.filter(i =>
                    /x-viewer|media-canvas|download|forward|star-btn|react|pin-ref|reply|zoom/i.test(i)
                  );
                  return viewerIcons.length >= 3;
                }"""
            )
        )
    except Exception:
        return False


def _wa_close_media_viewer(page: Page) -> bool:
    """ปิด media viewer ถ้าเปิดอยู่ (กด X หรือ Escape) — ห้ามค้างดูรูปบิลเก่า."""
    closed_any = False
    for _ in range(4):
        if not _wa_is_media_viewer_open(page):
            break
        try:
            clicked = page.evaluate(
                """() => {
                  const sels = [
                    'span[data-icon="x-viewer"]',
                    'span[data-icon="x"]',
                    'button[aria-label*="Close" i]',
                    'button[aria-label*="ปิด" i]',
                    'div[role="button"][aria-label*="Close" i]',
                    'div[role="button"][aria-label*="ปิด" i]',
                    '[data-testid="media-viewer"] span[data-icon="x"]',
                    '[data-testid="media-viewer"] span[data-icon="x-viewer"]',
                  ];
                  for (const s of sels) {
                    const el = document.querySelector(s);
                    if (!el) continue;
                    const btn = el.closest('button, [role="button"]') || el;
                    const r = btn.getBoundingClientRect();
                    if (r.width < 8 || r.height < 8) continue;
                    try { btn.click(); return s; } catch (e) {}
                  }
                  return '';
                }"""
            )
            if clicked:
                closed_any = True
                time.sleep(0.2)
                continue
        except Exception:
            pass
        try:
            page.keyboard.press("Escape")
            closed_any = True
            time.sleep(0.25)
        except Exception:
            break
    return closed_any and not _wa_is_media_viewer_open(page)


def _wa_dismiss_blocking_dialogs(page: Page) -> str:
    """ปิด popup ขัดขวาง (เช่น 'ทิ้งการเลือกหรือไม่') — คืนชื่อ action ที่กด.

    ห้ามจับปุ่ม media-cancel (มีคำ Cancel ซ้อน) — ให้ _wa_close_media_viewer จัดการ.
    """
    # ปิด media viewer ก่อนเสมอ
    if _wa_is_media_viewer_open(page):
        _wa_close_media_viewer(page)
    try:
        hit = page.evaluate(
            """() => {
              const texts = (document.body && document.body.innerText) || '';
              const looks =
                /ทิ้งการเลือก|Discard selection|Discard message|ทิ้งข้อความ|Unsent/i.test(texts);
              if (!looks) return '';
              const buttons = [...document.querySelectorAll(
                'button, [role="button"], div[role="button"]'
              )];
              const labelOf = (el) =>
                ((el.innerText || el.textContent || el.getAttribute('aria-label') || '') + '').trim();
              // เทียบ exact เท่านั้น — ห้าม /Cancel/ แบบ substring (จะโดน media-cancel)
              for (const prefer of [
                /^(ยกเลิก|Cancel)$/i,
                /^(ทิ้ง|Discard)$/i,
              ]) {
                for (const b of buttons) {
                  const t = labelOf(b);
                  if (!t || t.length > 24) continue;
                  if (!prefer.test(t)) continue;
                  // ตัด media-* ออก
                  if (/media/i.test(t)) continue;
                  const r = b.getBoundingClientRect();
                  if (r.width < 20 || r.height < 12) continue;
                  const inDlg = !!(b.closest('[role="dialog"], [data-animate-modal-popup="true"]'));
                  if (!inDlg && !looks) continue;
                  try { b.click(); return t.slice(0, 30); } catch (e) {}
                }
              }
              return '';
            }"""
        ) or ""
        if hit:
            time.sleep(0.25)
        return str(hit or "")
    except Exception:
        return ""


def _wa_scan_search_result_rows(page: Page) -> list:
    """สแกนผลค้นหา — รวมแถวหมวด 'ข้อความ' (message hit) ที่เตี้ยกว่าแถวแชท."""
    try:
        return (
            page.evaluate(
                """() => {
                  const side = document.querySelector('#side') || document.body;
                  const vh = window.innerHeight || 900;
                  // แถวที่มองเห็นได้จริงใน sidebar (กัน parent ยักษ์)
                  const nodes = side.querySelectorAll(
                    '[data-testid="cell-frame-container"], div[role="listitem"], div[tabindex="-1"], div[role="row"]'
                  );
                  const out = [];
                  const seen = new Set();
                  for (const n of nodes) {
                    const r = n.getBoundingClientRect();
                    if (r.width < 40 || r.height < 16 || r.height > 220) continue;
                    if (r.y < 40 || r.bottom < 60 || r.y > vh) continue;
                    // ต้องอยู่ใน #side
                    if (!side.contains(n)) continue;
                    const text = (n.innerText || n.textContent || '').trim();
                    if (!text || text.length < 2 || text.length > 500) continue;
                    const first = text.split('\\n')[0].trim();
                    if (/^(messages|ข้อความ|chats|แชท|contacts|ผู้ติดต่อ|people|communities|ทั้งหมด|unread|ยังไม่ได้อ่าน)$/i.test(first)
                        && text.split('\\n').length <= 1) {
                      continue;
                    }
                    const key = text.slice(0, 120) + '|' + Math.round(r.y) + '|' + Math.round(r.height);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push({
                      text: text.slice(0, 400),
                      y: Math.round(r.y),
                      x: Math.round(r.x + r.width / 2),
                      cy: Math.round(r.y + Math.min(r.height, 40) / 2),
                      h: Math.round(r.height),
                      isShort: text.length <= 40,
                    });
                  }
                  return out;
                }"""
            )
            or []
        )
    except Exception:
        return []


def _wa_ensure_home(page: Page, force_reload: bool = False) -> bool:
    """เปิด/อยู่ที่หน้าหลัก WhatsApp Web (sidebar พร้อม) — ไม่ใช้ /send?phone= cold link."""
    try:
        on_home = False
        if not force_reload:
            try:
                url = (page.url or "").lower()
                if "web.whatsapp.com" in url and page.query_selector("div#side"):
                    on_home = True
            except Exception:
                on_home = False
        if not on_home:
            print("   🌐 เปิด WhatsApp Web (หน้าหลัก)...")
            try:
                page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded", timeout=30000)
            except Exception as nav_err:
                if "destroyed" in str(nav_err).lower() or "navigation" in str(nav_err).lower():
                    time.sleep(3)
                else:
                    raise
            time.sleep(1.5)

        try:
            if _wa_is_login_page(page):
                if not _wa_wait_for_login(page):
                    return False
                time.sleep(3)
        except Exception:
            if not _wa_wait_for_login(page):
                return False

        # รอ sidebar
        for i in range(60):
            try:
                if page.query_selector("div#side"):
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        print("   ❌ WhatsApp Web ไม่พร้อม (ไม่พบ sidebar)")
        return False
    except Exception as e:
        print(f"   ❌ เปิด WhatsApp หน้าหลักไม่สำเร็จ: {e}")
        return False


def _wa_probe_search_ui(page: Page) -> dict:
    """Snapshot of side panel search-related DOM (no message content / PII)."""
    try:
        return page.evaluate(
            """() => {
              const side = document.querySelector('#side');
              if (!side) return { side: false };
              const ce = [...side.querySelectorAll('[contenteditable="true"]')].map(el => ({
                tab: el.getAttribute('data-tab') || '',
                role: el.getAttribute('role') || '',
                title: (el.getAttribute('title') || '').slice(0, 60),
                aria: (el.getAttribute('aria-label') || '').slice(0, 80),
                w: Math.round(el.getBoundingClientRect().width),
                h: Math.round(el.getBoundingClientRect().height),
              }));
              const icons = [...side.querySelectorAll('span[data-icon]')].map(
                el => el.getAttribute('data-icon') || ''
              ).filter(Boolean).slice(0, 20);
              const placeholders = [...side.querySelectorAll('div, span')].slice(0, 0);
              // lightweight: look for search-related aria/titles
              const searchish = [];
              for (const el of side.querySelectorAll('[aria-label], [title], [data-icon]')) {
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                const title = (el.getAttribute('title') || '').toLowerCase();
                const icon = el.getAttribute('data-icon') || el.querySelector?.('span[data-icon]')?.getAttribute('data-icon') || '';
                if (/search|ค้นหา|filter/.test(aria + ' ' + title) || /search/.test(icon)) {
                  searchish.push({
                    tag: el.tagName,
                    aria: (el.getAttribute('aria-label') || '').slice(0, 60),
                    title: (el.getAttribute('title') || '').slice(0, 60),
                    icon: String(icon).slice(0, 40),
                  });
                  if (searchish.length >= 8) break;
                }
              }
              return {
                side: true,
                sideW: Math.round(side.getBoundingClientRect().width),
                contentEditables: ce.slice(0, 8),
                footerIconsSample: icons,
                searchish: searchish,
              };
            }"""
        )
    except Exception as e:
        return {"probeError": str(e)[:120]}


def _wa_get_search_box(page: Page):
    """ช่องค้นหา sidebar (Search or start new chat).

    UI ใหม่ของ WA Web ใช้ <input> (ไม่ใช่ contenteditable) — ยืนยันจาก runtime probe.
    """
    selectors = [
        # New WA Web (2024+): native <input>
        'div#side input[aria-label="ค้นหาหรือเริ่มแชทใหม่"]',
        'div#side input[placeholder="ค้นหาหรือเริ่มแชทใหม่"]',
        'input[aria-label="ค้นหาหรือเริ่มแชทใหม่"]',
        'input[placeholder="ค้นหาหรือเริ่มแชทใหม่"]',
        'div#side input[aria-label*="Search or start new chat" i]',
        'div#side input[placeholder*="Search or start new chat" i]',
        'div#side input[aria-label*="ค้นหา"]',
        'div#side input[placeholder*="ค้นหา"]',
        'div#side input[type="text"]',
        'div#side input[type="search"]',
        'div#side input[role="textbox"]',
        # Legacy: contenteditable search
        'div#side div[contenteditable="true"][data-tab="3"]',
        'div#side div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"][data-tab="3"]',
        'div[title="Search or start new chat"]',
        'div[title="ค้นหาหรือเริ่มแชทใหม่"]',
        'div[aria-label="Search input textbox"]',
        'div[aria-label="Search or start new chat"]',
        'div#side [contenteditable="true"]',
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if not el:
                continue
            # Prefer visible searchable inputs over zero-size nodes
            try:
                box = el.bounding_box()
                if box and (box.get("width", 0) < 20 or box.get("height", 0) < 10):
                    continue
            except Exception:
                pass
            return el
        except Exception:
            pass
    # Last resort: any INPUT in side whose aria/placeholder mentions search
    try:
        handle = page.evaluate_handle(
            """() => {
              const side = document.querySelector('#side');
              if (!side) return null;
              for (const inp of side.querySelectorAll('input')) {
                const aria = (inp.getAttribute('aria-label') || '').toLowerCase();
                const ph = (inp.getAttribute('placeholder') || '').toLowerCase();
                const r = inp.getBoundingClientRect();
                if (r.width < 40 || r.height < 12) continue;
                if (/search|ค้นหา|filter|แชท/.test(aria + ' ' + ph)) return inp;
              }
              // fallback: first sizable text/search input in side
              for (const inp of side.querySelectorAll('input[type="text"], input[type="search"], input:not([type])')) {
                const r = inp.getBoundingClientRect();
                if (r.width >= 80 && r.height >= 16) return inp;
              }
              return null;
            }"""
        )
        el = handle.as_element() if handle else None
        if el:
            return el
    except Exception:
        pass
    return None


def _wa_clear_search_box(page: Page) -> None:
    """เคลียร์ช่องค้นหา sidebar หลังจบรายการ (ลดผลค้าง)."""
    _wa_dismiss_blocking_dialogs(page)
    try:
        box = _wa_get_search_box(page)
        if box:
            try:
                box.click(timeout=2000)
            except Exception:
                try:
                    box.click(timeout=1500, force=True)
                except Exception:
                    pass
            _human_delay(50, 120)
            try:
                tag = (box.evaluate("el => (el.tagName || '').toLowerCase()") or "")
            except Exception:
                tag = ""
            if tag == "input":
                try:
                    box.fill("")
                except Exception:
                    page.keyboard.press("Control+a")
                    page.keyboard.press("Backspace")
            else:
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
        page.keyboard.press("Escape")
        time.sleep(0.2)
    except Exception:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass


def _wa_paste_search_query(page: Page, box, query: str) -> dict:
    """ใส่คำค้นในช่องค้นหาแบบ paste (Ctrl+V) — วิธีเดียวกับผู้ใช้วาง Order แล้วพบผล.

    fill()/type() หลายรอบทำให้ WA ไม่อัปเดตผลค้นหา (ขึ้น 'ไม่พบ…') ทั้งที่วางมือเจอ.
    """
    q = (query or "").strip()
    method = "none"
    try:
        # clipboard text (permission เปิดจาก context แล้ว)
        page.evaluate(
            """async (text) => {
              try {
                await navigator.clipboard.writeText(text);
                return true;
              } catch (e) {
                // fallback: execCommand copy จาก textarea ชั่วคราว
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.left = '-9999px';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                let ok = false;
                try { ok = document.execCommand('copy'); } catch (e2) {}
                document.body.removeChild(ta);
                return ok;
              }
            }""",
            q,
        )
        method = "clipboard_ready"
        try:
            box.click(timeout=3000)
        except Exception:
            box.click(timeout=2000, force=True)
        _human_delay(60, 120)
        page.keyboard.press("Control+a")
        _human_delay(30, 60)
        page.keyboard.press("Backspace")
        _human_delay(40, 80)
        page.keyboard.press("Control+v")
        method = "ctrl_v"
        _human_delay(400, 700)
    except Exception as e:
        # fallback สุดท้าย
        try:
            tag = (box.evaluate("el => (el.tagName || '').toLowerCase()") or "")
            if tag == "input":
                box.fill(q)
                method = "fill_fallback"
            else:
                page.keyboard.insert_text(q)
                method = "insert_fallback"
        except Exception as e2:
            return {"ok": False, "method": method, "error": f"{str(e)[:60]}|{str(e2)[:40]}"}

    typed = ""
    typed_len = -1
    try:
        tag = (box.evaluate("el => (el.tagName || '').toLowerCase()") or "")
        if tag == "input":
            typed = (box.evaluate("el => el.value || ''") or "").strip()
        else:
            typed = (box.evaluate("el => (el.innerText || el.textContent || '')") or "").strip()
        typed_len = len(typed)
    except Exception:
        pass
    # ถ้า paste ไม่ติดค่า — ลอง fill ตรง
    if typed_len != len(q):
        try:
            tag = (box.evaluate("el => (el.tagName || '').toLowerCase()") or "")
            if tag == "input":
                box.fill(q)
                method = f"{method}+fill"
                typed = (box.evaluate("el => el.value || ''") or "").strip()
                typed_len = len(typed)
        except Exception:
            pass
    return {"ok": typed_len == len(q) or (q and q in typed), "method": method, "typedLen": typed_len, "expectedLen": len(q)}


def _wa_search_open_chat_by_order_id(page: Page, order_id: str, max_wait: float = 6.0) -> Tuple[bool, str]:
    """ค้นหา Order ID ในช่องค้นหา WA → เปิดเฉพาะผลที่ token ตรง 100%.

    Returns:
        (True, detail)  — เปิดแชทเดิมได้
        (False, reason) — no_prior_chat | search_box_missing | compose_not_ready | …
    """
    oid = _wa_order_search_key(order_id)
    if not oid:
        return False, "empty_order_id"

    # ปิด popup ขัด (ทิ้งการเลือก ฯลฯ) ก่อนค้น
    _wa_dismiss_blocking_dialogs(page)


    box = _wa_get_search_box(page)
    search_btn_clicked = False
    if not box:
        # บางธีมต้องกดปุ่ม search ก่อน
        try:
            search_btn_clicked = bool(
                page.evaluate(
                    """() => {
                  const side = document.querySelector('#side');
                  if (!side) return false;
                  for (const el of side.querySelectorAll('button, [role="button"], span[data-icon]')) {
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    const icon = el.getAttribute('data-icon')
                      || el.querySelector('span[data-icon]')?.getAttribute('data-icon') || '';
                    if (/search|ค้นหา/.test(aria) || /search/.test(icon)) {
                      (el.closest('button, [role="button"]') || el).click();
                      return true;
                    }
                  }
                  return false;
                }"""
                )
            )
            time.sleep(0.4)
            box = _wa_get_search_box(page)
        except Exception:
            box = None
    if not box:
        return False, "search_box_missing"

    # ใช้ Order ตรงตามชีตก่อน (วางแบบ user) — variants เป็นแผนสำรอง
    queries = _wa_order_search_queries(oid)
    best_pick = None
    best_score = 0
    rejected_partial = 0
    query_used = ""

    for qi, query in enumerate(queries):
        box = _wa_get_search_box(page) or box
        try:
            paste_info = _wa_paste_search_query(page, box, query)
            if not paste_info.get("ok"):
                continue
        except Exception as e:
            continue

        # รอผล — คลิกเฉพาะแถวที่ match exact forms ของ order จริง (ไม่ใช่แค่คำค้น)
        t0 = time.time()
        q_wait = max_wait if qi == 0 else min(max_wait, 4.0)
        best_pick = None
        rejected_partial = 0
        while time.time() - t0 < q_wait:
            _wa_dismiss_blocking_dialogs(page)
            rows = _wa_scan_search_result_rows(page)

            exact = []
            rejected_partial = 0
            for row in rows:
                txt = row.get("text") or ""
                score = _wa_exact_order_score(txt, oid)
                if score <= 0:
                    compact_oid = re.sub(r"[^A-Za-z0-9]", "", oid)
                    compact_txt = re.sub(r"[^A-Za-z0-9]", "", _wa_strip_bidi(txt))
                    if compact_oid and compact_oid in compact_txt:
                        rejected_partial += 1
                    continue
                # ชอบแถวสั้น (หมวดข้อความ) + อยู่สูงกว่านิด (ใกล้กล่องค้นหา)
                if row.get("isShort"):
                    score += 10
                if row.get("h") and int(row.get("h") or 0) < 48:
                    score += 5
                exact.append((score, row))

            if exact:
                exact.sort(key=lambda x: (-x[0], x[1].get("y", 0)))
                best_pick = exact[0][1]
                best_score = exact[0][0]
                query_used = query
                break
            time.sleep(0.25)

        if best_pick:
            break

    if not best_pick:
        try:
            partial_hint = page.evaluate(
                """(orderId) => {
                  const side = document.querySelector('#side') || document.body;
                  const body = (side.innerText || '').slice(0, 1200);
                  const compact = orderId.replace(/[^A-Za-z0-9]/g, '');
                  return body.includes(orderId)
                    || (compact && body.replace(/[^A-Za-z0-9]/g, '').includes(compact));
                }""",
                oid,
            )
        except Exception:
            partial_hint = False
        if partial_hint or rejected_partial:
            print(
                f"   ⚠️ มีผลค้นหาคล้าย '{oid}' แต่ไม่ตรง 100% "
                f"(เช่น 020123 vs 020123456) — ไม่คลิก"
            )
        else:
            print(f"   ⏭️ ไม่พบ Order ID '{oid}' ใน search — ข้าม")
        return False, "search_not_found"

    # คลิก DOM element ของแถว exact (ไม่ใช้ mouse พิกัด — มักไม่โดนแถว)
    print(f"   🖱️ คลิกผลค้นหาที่ Order ID ตรง 100%..." + (f" (query={query_used})" if query_used != oid else ""))
    click_info = _wa_click_exact_order_result(page, oid)
    if not click_info.get("ok"):
        # fallback พิกัด row ที่เลือกไว้ตอน scan
        try:
            # คลิกฝั่งซ้ายแถว — ไม่ใช่จุดกลาง (กลางอาจเป็น thumbnail)
            page.mouse.click(float(best_pick["x"]) - 80, float(best_pick["cy"]))
            click_info = {"ok": True, "via": "mouse_fallback_left", "score": best_score}
            time.sleep(0.15)
            if _wa_is_media_viewer_open(page):
                _wa_close_media_viewer(page)
        except Exception as e:
            return False, f"click_failed:{str(e)[:80]}"

    _human_delay(400, 700)
    _wa_close_media_viewer(page)
    _wa_dismiss_blocking_dialogs(page)

    # รอแชทโหลด: Order อาจยังไม่อยู่ใน #main ทันทีหลังคลิก result (virtual list)
    switched = False
    compose = None
    has_oid_main = False
    for i in range(70):
        if _wa_is_media_viewer_open(page):
            _wa_close_media_viewer(page)
        _wa_dismiss_blocking_dialogs(page)
        try:
            in_main = page.evaluate(
                """({ orderId, forms }) => {
                  const main = document.querySelector('#main');
                  if (!main) return { hasMain: false, hasOid: false, hasCompose: false, header: '' };
                  // โหลดยาวขึ้น — แชทยาว/virtual scroll อาจไม่โผล่ใน 4k แรก
                  const t = (main.innerText || '').slice(0, 20000);
                  const titles = [...main.querySelectorAll('[title], [aria-label]')]
                    .map(el => (el.getAttribute('title') || '') + ' ' + (el.getAttribute('aria-label') || ''))
                    .join('\\n').slice(0, 4000);
                  const strip = (s) => (s || '').replace(/[\\u200e\\u200f\\u202a-\\u202e\\ufeff]/g, '');
                  const cleaned = strip(t + '\\n' + titles);
                  const formSet = new Set((forms || []).map(f => (f || '').toLowerCase()));
                  const toks = cleaned.match(/[A-Za-z0-9_\\-]+/g) || [];
                  let hasOid = false;
                  for (const x of toks) {
                    const xl = x.toLowerCase();
                    if (formSet.has(xl)) { hasOid = true; break; }
                    const c = xl.replace(/[^a-z0-9]/g, '');
                    if (c && formSet.has(c)) { hasOid = true; break; }
                  }
                  // compact full-text includes form (เช่น X-023992 ในข้อความยาว)
                  if (!hasOid) {
                    const compact = cleaned.toLowerCase().replace(/[^a-z0-9]/g, '');
                    for (const f of formSet) {
                      const fc = f.replace(/[^a-z0-9]/g, '');
                      if (fc && compact.includes(fc)) { hasOid = true; break; }
                    }
                  }
                  const ce = main.querySelector(
                    'footer div[contenteditable="true"], div[contenteditable="true"][data-tab="10"]'
                  );
                  const header = (main.querySelector('header')?.innerText || '').slice(0, 80);
                  return { hasMain: true, hasOid, hasCompose: !!ce, header };
                }""",
                {"orderId": oid, "forms": _wa_order_id_forms(oid)},
            ) or {}
        except Exception:
            in_main = {}
        has_oid_main = bool(in_main.get("hasOid"))
        compose = _wa_focus_main_compose(page)
        if has_oid_main and compose:
            switched = True
            break
        time.sleep(0.2)

    if not (compose and has_oid_main):
        print(f"   ⚠️ คลิกแล้วแต่แชทที่เปิดไม่มี Order '{oid}' ในประวัติ — ไม่ส่ง (กันส่งผิดคน)")
        return False, "wrong_chat_opened"

    print(f"   ✅ พบ Order ID '{oid}' — เปิดแชทแล้ว (พร้อมพิมพ์)")
    return True, "opened"


def _wa_send_content_in_open_chat(
    page: Page,
    message_text: str,
    image_path: Optional[Path] = None,
    fn_start: Optional[float] = None,
) -> Tuple[bool, Optional[str]]:
    """ส่งรูป+caption หรือข้อความอย่างเดียว ในแชทที่เปิดอยู่แล้ว (ไม่ navigate)."""
    if fn_start is None:
        fn_start = time.time()


    # ถ้าค้าง viewer รูปเก่า — ปิดก่อน ไม่งั้นวาง/ส่งไม่ได้
    if _wa_is_media_viewer_open(page):
        _wa_close_media_viewer(page)

    msg_input = _wa_focus_main_compose(page) or _wa_get_fresh_compose(page)
    if not msg_input:
        print("   ❌ ไม่พบช่องพิมพ์ในแชทที่เปิด")
        return False, None

    # ถ้ามีรูป: ใส่ข้อความเป็น caption ก่อน paste รูป
    wa_image_sent = False
    if image_path and image_path.is_file():
        print(f"   📎 แนบรูป: {image_path.name} (copy-paste)")
        try:
            try:
                existing = (msg_input.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
            except Exception:
                existing = ""
            if message_text and not existing:
                try:
                    msg_input.click()
                except Exception:
                    _wa_focus_compose(page)
                _human_delay(80, 160)
                page.keyboard.insert_text(message_text)
                _human_delay(150, 300)
                msg_input = _wa_get_fresh_compose(page)

            baseline_blob = _wa_metric(_wa_probe_send_state(page), "docBlobImageCount", 0)
            attach_ok, attach_detail = _wa_attach_image_clipboard(page, image_path, msg_input)
            attach_method = "clipboard"
            if not attach_ok:
                print(f"   ⚠️ clipboard ไม่สำเร็จ ({attach_detail}) — ลอง file input")
                attach_ok, attach_detail = _wa_attach_image_file(page, image_path)
                attach_method = "file_input"

            if attach_ok:
                print(f"   📋 ใส่รูปผ่าน {attach_method}...")
                print("   ⏳ รอ media preview (รูปบิล)...")
                _human_delay(450, 900)
                preview_ready, _pre = _wa_wait_image_preview(
                    page, baseline_blob=baseline_blob, max_wait=8.0
                )
                if not preview_ready:
                    print("   ❌ WA ไม่แสดง preview รูป — ไม่กดส่งข้อความเปล่า")
                    wa_image_sent = False
                else:
                    action_ok, send_method = _wa_send_media_once(page)
                    settled, _post = _wa_media_send_settled(page, baseline_blob=baseline_blob, max_wait=5.0)
                    if action_ok and not settled:
                        try:
                            page.keyboard.press("Enter")
                            send_method = f"{send_method}+enter_retry"
                        except Exception:
                            pass
                        settled, _post = _wa_media_send_settled(
                            page, baseline_blob=baseline_blob, max_wait=4.0
                        )
                    if not settled:
                        btn2 = _wa_find_media_send_button(page)
                        if btn2:
                            try:
                                btn2.click(timeout=1500, force=True)
                                send_method = f"{send_method}+force_retry"
                            except Exception:
                                try:
                                    box = btn2.bounding_box()
                                    if box:
                                        page.mouse.click(
                                            box["x"] + box["width"] / 2,
                                            box["y"] + box["height"] / 2,
                                        )
                                        send_method = f"{send_method}+mouse_retry"
                                except Exception:
                                    pass
                            settled, _post = _wa_media_send_settled(
                                page, baseline_blob=baseline_blob, max_wait=4.0
                            )
                    if action_ok and settled:
                        print(f"   ✅ ส่งรูปแล้ว ({send_method}/{attach_method})")
                        wa_image_sent = True
                    else:
                        print(f"   ⚠️ ส่งรูปไม่ยืนยัน (method={send_method})")
                        wa_image_sent = False
            else:
                print(f"   ⚠️ แนบรูปไม่สำเร็จ ({attach_detail})")
        except Exception as e:
            print(f"   ⚠️ แนบรูปไม่สำเร็จ: {e}")

        if wa_image_sent:
            print(f"   ℹ️ ข้อความ/ลิงก์ส่งเป็น caption กับรูปแล้ว")
            print(f"   ✅ ส่ง WhatsApp สำเร็จ ({_fmt_elapsed(time.time() - fn_start)})")
            return True, None

        print("   ❌ ส่งรูป WhatsApp ไม่สำเร็จ — ไม่ส่งข้อความแทน")
        return False, None

    # ข้อความอย่างเดียว
    _human_delay(200, 400)
    msg_input = _wa_get_fresh_compose(page)
    if not msg_input:
        print("   ❌ ไม่พบช่องพิมพ์")
        return False, None
    try:
        content = (msg_input.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
    except Exception:
        content = ""
    if not content:
        try:
            msg_input.click()
        except Exception:
            _wa_focus_compose(page)
        _human_delay(80, 160)
        page.keyboard.insert_text(message_text)
        _human_delay(150, 300)

    send_ok, send_method = _wa_send_draft(page, had_image=False)
    if send_ok:
        print(f"   ✅ ส่ง WhatsApp สำเร็จ ({send_method}, {_fmt_elapsed(time.time() - fn_start)})")
        return True, None
    print(f"   ❌ ส่งข้อความไม่สำเร็จ (method={send_method})")
    return False, None


def send_via_whatsapp(
    page: Page,
    phone: str,
    message_text: str,
    image_path: Optional[Path] = None,
    dry_run: bool = False,
    order_id: Optional[str] = None,
    tracking_id: Optional[str] = None,
    already_on_home: bool = False,
) -> Tuple[bool, Optional[str]]:
    """ส่งข้อความ (+ รูปถ้ามี) ผ่าน WhatsApp Web โดยค้นหา Order ID แล้วเปิดแชท.

    Order ID อยู่เฉพาะในข้อความที่เคยคุย — เจอใน search = เปิดส่งได้ / ไม่เจอ = ข้าม

    Returns:
        (True, None) on success
        (False, "search_not_found") when Order ID not in search results
        (False, "no_whatsapp") reserved
        (False, None) on other failure
    """
    oid = _wa_order_search_key(order_id or "")
    phone_disp = ""
    try:
        if phone:
            phone_disp = _normalize_phone_for_whatsapp(phone)
    except Exception:
        phone_disp = (phone or "")[:20]

    if dry_run:
        print(f"[DRY-RUN] WhatsApp Order {oid or '?'} → search + send: {message_text[:60]}...")
        return True, None

    if not oid:
        print("   ❌ ไม่มี Order ID สำหรับค้นหา WhatsApp")
        return False, None

    fn_start = time.time()
    print(f"\n   📱 WhatsApp → Order `{oid}`" + (f" (เบอร์ {phone_disp})" if phone_disp else ""))

    try:
        if not already_on_home:
            if not _wa_ensure_home(page):
                return False, None
        else:
            # ยังต้องมี sidebar
            try:
                if not page.query_selector("div#side"):
                    if not _wa_ensure_home(page):
                        return False, None
            except Exception:
                if not _wa_ensure_home(page):
                    return False, None

        print(f"   🔍 ค้นหา Order ID: {oid}")
        opened, detail = _wa_search_open_chat_by_order_id(page, oid)
        if not opened:
            if detail in ("search_not_found", "no_prior_chat"):
                _wa_clear_search_box(page)
                return False, "search_not_found"
            print(f"   ❌ เปิดแชทไม่สำเร็จ ({detail})")
            _wa_clear_search_box(page)
            return False, None

        # เอาโฟกัสออกจากช่องค้นหา → พร้อมพิมพ์/แนบใน #main (อย่ากด Esc แรง ๆ อาจยกเลิกแชท)
        _wa_focus_main_compose(page)
        time.sleep(0.2)

        ok, reason = _wa_send_content_in_open_chat(
            page, message_text, image_path=image_path, fn_start=fn_start
        )
        _wa_clear_search_box(page)
        return ok, reason

    except Exception as e:
        print(f"   ❌ เกิดข้อผิดพลาด WhatsApp: {e}")
        import traceback
        print(f"   รายละเอียด: {traceback.format_exc()}")
        try:
            _wa_clear_search_box(page)
        except Exception:
            pass
        return False, None


def _fuzzy_pick_chat(items_with_text: list, customer_name: str):
    """เลือกแชทที่ตรงกับชื่อลูกค้ามากที่สุด (fuzzy)
    items_with_text: [(element, text), ...]
    customer_name: ชื่อจากคอลัมน์ E
    Returns: (best_element, best_score, best_text) หรือ (None, 0, "")
    """
    if not customer_name or not items_with_text:
        return (None, 0, "")
    name_lower = customer_name.lower().strip()
    name_words = set(name_lower.split())

    best_item = None
    best_score = 0
    best_txt = ""

    for item, txt in items_with_text:
        # ชื่อ Facebook อยู่บรรทัดแรกของ item text
        first_line = txt.split("\n")[0].strip().lower() if txt else ""
        chat_words = set(first_line.split())

        # คะแนน: จำนวนคำที่ตรงกัน + bonus ถ้า substring ตรง
        word_overlap = len(name_words & chat_words)
        score = word_overlap
        if name_lower in first_line or first_line in name_lower:
            score += 3

        if score > best_score:
            best_score = score
            best_item = item
            best_txt = txt

    return (best_item, best_score, best_txt)


def _dismiss_fb_error_dialog(page: Page) -> bool:
    """ตรวจจับ dialog ข้อผิดพลาดของ Facebook ("ไม่สามารถดำเนินการตามคำขอของคุณได้") แล้วกด ตกลง/OK ปิด
    คืนค่า True ถ้าเจอ dialog และปิดสำเร็จ, False ถ้าไม่เจอ"""
    try:
        ok_btn = page.query_selector('div[role="dialog"] div[role="button"]:has-text("ตกลง"), div[role="dialog"] div[role="button"]:has-text("OK")')
        if ok_btn and ok_btn.is_visible():
            ok_btn.click()
            time.sleep(0.5)
            return True
        close_btn = page.query_selector('div[role="dialog"] div[aria-label="Close"], div[role="dialog"] div[aria-label="ปิด"]')
        if close_btn and close_btn.is_visible():
            close_btn.click()
            time.sleep(0.5)
            return True
    except Exception:
        pass
    return False


def open_inbox_and_search_order(page: Page, inbox_url: str, order_id: str, skip_navigate: bool = False, skip_search_button: bool = False, customer_name: str = "") -> Tuple[bool, Optional[str]]:
    """เปิด Inbox ของเพจและค้นหา Order number
    inbox_url: URL สำหรับเปิด Inbox (สร้างจาก build_inbox_url)
    skip_navigate: ถ้า True จะข้ามการ navigate (เพราะอยู่ในหน้า Inbox อยู่แล้ว)
    skip_search_button: ถ้า True = ค้นหาครั้งที่ 2 ขึ้นไป — ปุ่ม "ค้นหาในการสนทนา" ไม่ปรากฏอีก แค่กรอก Order + Enter แล้วรอผลอัปเดต
    customer_name: ชื่อลูกค้าจากคอลัมน์ E (ใช้ fuzzy match เมื่อมีหลายผลค้นหา)
    Returns: (True, None) เมื่อสำเร็จ; (False, "no_results") เมื่อยืนยันว่าไม่มีผลลัพธ์; (False, "not_found") เมื่อไม่เจอแชท/ผิดพลาด
    """

    fn_start = time.time()
    
    try:
        if skip_navigate:
            # ข้ามการ navigate เพราะอยู่ในหน้า Inbox อยู่แล้ว (จากขั้นตอนตรวจสอบ login)

            print(f"🌐 อยู่ในหน้า Inbox แล้ว (ข้ามการ navigate ซ้ำ)")
            # กำหนด t_before_search สำหรับกรณี skip_navigate (ใช้ใน log ด้านล่าง)
            t_before_search = time.time()

        else:
            print(f"🌐 กำลังเปิด Inbox: {inbox_url}")

            t0 = time.time()
            # เปลี่ยนจาก "networkidle" เป็น "domcontentloaded" เพื่อลดเวลารอ (networkidle อาจรอนานเกินไป)
            page.goto(inbox_url, wait_until="domcontentloaded", timeout=ui_selectors.PAGE_LOAD_TIMEOUT * 1000)
            t_nav = time.time()
            nav_time = t_nav - t0

            # Dynamic wait: รอให้ search input พร้อมแทน fixed sleep 1.5s

            t_wait_search_ready = time.time()
            search_ready = False
            # ใช้ wait_for_selector แทน polling เพื่อให้เร็วกว่าและรอได้นานขึ้น (สูงสุด 5s)
            try:
                page.wait_for_selector(ui_selectors.SEARCH_INPUT_SELECTOR, timeout=5000)
                search_ready = True
            except:
                search_ready = False
            dynamic_wait_time = time.time() - t_wait_search_ready

            t_before_print_nav = time.time()

            print(f"   ⏱️ เปิด Inbox รวม: {_fmt_elapsed(time.time() - t0)} (navigate: {_fmt_elapsed(t_nav - t0)}, wait ready: {_fmt_elapsed(dynamic_wait_time)})")

            t_after_print_nav = time.time()
            t_before_search = time.time()

        # ค้นหา Order number
        t0 = time.time()
        print(f"🔍 กำลังค้นหา Order: {order_id}")


        t_find_input = time.time()

        search_input = None
        try:
            search_input = page.wait_for_selector(
                ui_selectors.SEARCH_INPUT_SELECTOR,
                timeout=ui_selectors.ELEMENT_WAIT_TIMEOUT * 1000
            )
        except Exception:
            pass

        if not search_input:
            try:
                search_input = page.wait_for_selector(
                    f"xpath={ui_selectors.SEARCH_INPUT_XPATH}",
                    timeout=3000
                )
            except Exception:
                pass

        if not search_input:
            if _dismiss_fb_error_dialog(page):
                print("   ⚠️ Facebook แสดง error dialog — ปิดแล้ว กำลัง navigate ใหม่...")
                try:
                    page.goto(inbox_url, wait_until="domcontentloaded", timeout=ui_selectors.PAGE_LOAD_TIMEOUT * 1000)
                    page.wait_for_selector(ui_selectors.SEARCH_INPUT_SELECTOR, timeout=10000)
                    search_input = page.query_selector(ui_selectors.SEARCH_INPUT_SELECTOR)
                except Exception:
                    pass
            if not search_input:
                print("❌ ไม่พบช่องค้นหา")
                return (False, "not_found")
        
        find_input_time = time.time() - t_find_input
        print(f"   ⏱️ หาช่องค้นหา: {_fmt_elapsed(find_input_time)}")

        if not skip_navigate:
            time.sleep(0.3)

        # ก่อนค้นหาใหม่: จำ element เก่าไว้เพื่อตรวจว่าผลค้นหาเปลี่ยนจริง
        _old_result_handles = []
        if skip_search_button:
            try:
                _old_result_handles = page.query_selector_all('div._a6ag')
            except Exception:
                pass

        t_fill = time.time()
        search_input.click()
        _human_delay(80, 200)
        search_input.fill(order_id)
        _human_delay(80, 200)
        search_input.press("Enter")
        fill_time = time.time() - t_fill

        print(f"   ⏱️ กรอก Order + กด Enter: {_fmt_elapsed(fill_time)}")
        
        if skip_search_button:
            # ค้นหาครั้งที่ 2+: ต้องรอให้ผลค้นหาเก่าหายไปก่อน (ป้องกัน stale results)
            _t_refresh = time.time()
            _refreshed = False
            for _ in range(60):  # สูงสุด 3 วินาที (0.05s x 60)
                time.sleep(0.05)
                try:
                    if _old_result_handles:
                        _first_alive = _old_result_handles[0].evaluate("el => el.isConnected")
                        if not _first_alive:
                            _refreshed = True
                            break
                    _new_items = page.query_selector_all('div._a6ag')
                    if len(_new_items) != len(_old_result_handles):
                        _refreshed = True
                        break
                    if not _old_result_handles and (time.time() - _t_refresh) > 0.5:
                        _refreshed = True
                        break
                except Exception:
                    _refreshed = True
                    break
            _refresh_ms = int((time.time() - _t_refresh) * 1000)
            print(f"   (ค้นหาครั้งถัดไป — รอผลอัปเดต: {'OK' if _refreshed else 'timeout'} {_refresh_ms}ms)")
        else:
            # ค้นหาครั้งแรก: รอปุ่ม + คลิก + รอรายชื่อ

            t_wait_search = time.time()
            search_btn_ready = False
            for sel, to_ms in [
                ('div[role="button"]:has-text("ค้นหาในการสนทนา")', 2000),
                ('div[role="button"]:has-text("Search in conversations")', 500),
            ]:
                try:
                    page.wait_for_selector(sel, timeout=to_ms)
                    search_btn_ready = True
                    break
                except Exception:
                    pass
            actual_wait = time.time() - t_wait_search

            print(f"   ⏱️ รอผลค้นหา (ปุ่ม \"ค้นหาในการสนทนา\"): {_fmt_elapsed(actual_wait)} (พร้อม: {'✅' if search_btn_ready else '❌'})")
            print(f"   ⏱️ ขั้นค้นหา Order รวม: {_fmt_elapsed(time.time() - t0)}")
            t0 = time.time()
            print(f"🖱️ กำลังคลิก \"ค้นหาในการสนทนา\"...")
            clicked = False
            
            search_texts = [
                "ค้นหาในการสนทนา",
                "Search in conversations",
                "ค้นหาในการสนทนาใน Messenger และ Instagram"
            ]
            for search_text in search_texts:
                try:
                    locator = page.locator(f'text="{search_text}"').first
                    if locator.count() > 0:
                        locator.click()
                        _human_delay(100, 250)
                        print(f"   ✅ คลิกแล้ว")
                        clicked = True
                        break
                except:
                    continue
            
            if not clicked:
                try:
                    search_in_conversations = page.wait_for_selector(
                        ui_selectors.SEARCH_IN_CONVERSATIONS_SELECTOR,
                        timeout=3 * 1000
                    )
                    if search_in_conversations:
                        search_in_conversations.click()
                        _human_delay(200, 400)
                        print("   ✅ คลิกแล้ว (ใช้ CSS selector)")
                        clicked = True
                except:
                    pass
            
            if not clicked:
                print("   ⚠️ ไม่พบปุ่ม \"ค้นหาในการสนทนา\" — ลองค้นหาแชทโดยตรง...")
                print("   (อาจเป็นเพราะ Facebook UI เปลี่ยน — กรุณาตรวจสอบ ui_selectors.py)")
            
            print(f"   ⏱️ ขั้นคลิก \"ค้นหาในการสนทนา\" รวม: {_fmt_elapsed(time.time() - t0)}")
        
        t0 = time.time()

        # ตรวจสอบ URL ว่าเรายังอยู่ในหน้า Inbox (ไม่ใช่หน้า Automated Responses)
        current_url = page.url
        print(f"   📍 URL: {current_url}")
        if "automated_responses" in current_url.lower():
            print("⚠️ ไปที่หน้า Automated Responses โดยไม่ตั้งใจ — กลับไปหน้า Inbox")
            # เปลี่ยนจาก "networkidle" เป็น "domcontentloaded" เพื่อลดเวลารอ (networkidle อาจรอนานเกินไป)
            page.goto(inbox_url, wait_until="domcontentloaded", timeout=ui_selectors.PAGE_LOAD_TIMEOUT * 1000)
            time.sleep(2)
            # ค้นหาใหม่
            search_input = page.wait_for_selector(ui_selectors.SEARCH_INPUT_SELECTOR, timeout=5 * 1000)
            if search_input:
                search_input.fill(order_id)
                search_input.press("Enter")
                time.sleep(2)
                # คลิก "ค้นหาในการสนทนา" อีกครั้ง
                locator = page.locator('text="ค้นหาในการสนทนา"').first
                if locator.count() > 0:
                    locator.click()
                    time.sleep(3)
        
        # รอแบบไดนามิก: ตรวจทุก 0.05s จนเจอแชท หรือ "ไม่พบผลลัพธ์" หรือครบ 5 วินาที (ไม่รอตายตัว)
        no_results_texts = ["ไม่พบผลลัพธ์", "No results found", "ไม่พบผลลัพธ์สำหรับ"]
        conversation_item = None
        primary_selector = ui_selectors.CONVERSATION_ITEM_PRIMARY_TEMPLATE.format(order_id=order_id)
        t_find = time.time()
        no_results_consecutive = 0
        POLL_INTERVAL = 0.05
        MAX_WAIT = 5
        max_iterations = int(MAX_WAIT / POLL_INTERVAL)
        MIN_ITERATIONS_BEFORE_NO_RESULTS = 20  # 1 วินาที — ไม่นับ "ไม่พบผลลัพธ์" ในช่วงแรก (กัน false positive จากผลเก่า/โหลด)
        print(f"🔍 กำลังหาแชทที่มี Order {order_id}...")
        for iteration in range(max_iterations):
            # เช็คแชทก่อน: ถ้าเจอให้ break ทันที
            try:
                conversation_item = page.query_selector(primary_selector)
                if conversation_item:
                    break
            except Exception:
                pass
            if not conversation_item:
                try:
                    _matching_kw = ["ข้อความที่ตรงกัน", "matching message", "matched message"]
                    all_items = page.query_selector_all('div._a6ag')
                    if len(all_items) == 1:
                        item_text = all_items[0].evaluate("el => el.textContent || ''")
                        if any(kw in item_text for kw in _matching_kw):
                            conversation_item = all_items[0]
                            print(f"   ✅ พบแชท (ผ่าน 'ข้อความที่ตรงกัน' - early exit) ({_fmt_elapsed(time.time() - t_find)})")
                            break
                    elif len(all_items) > 1:
                        # หลายผลลัพธ์ → ตรวจว่ามี "ข้อความที่ตรงกัน" กี่รายการ
                        matched_in_loop = []
                        for _it in all_items:
                            try:
                                _txt = _it.evaluate("el => el.textContent || ''")
                                if any(kw in _txt for kw in _matching_kw):
                                    matched_in_loop.append((_it, _txt))
                            except Exception:
                                pass
                        if len(matched_in_loop) == 1:
                            conversation_item = matched_in_loop[0][0]
                            print(f"   ✅ พบแชท (1 'ข้อความที่ตรงกัน' จาก {len(all_items)} รายการ - early exit) ({_fmt_elapsed(time.time() - t_find)})")
                            break
                        elif len(matched_in_loop) > 1 and customer_name:
                            best_item, best_score, _ = _fuzzy_pick_chat(matched_in_loop, customer_name)
                            if best_item and best_score > 0:
                                conversation_item = best_item
                                print(f"   ✅ พบแชท (fuzzy match score={best_score} - early exit) ({_fmt_elapsed(time.time() - t_find)})")
                                break
                except Exception:
                    pass

            # เช็ค "ไม่พบผลลัพธ์" หลังผ่าน 1s แล้วเท่านั้น (กัน误判จากผลเก่า/โหลด)
            if iteration >= MIN_ITERATIONS_BEFORE_NO_RESULTS:
                see_no_results = False
                for text in no_results_texts:
                    try:
                        if page.locator(f'text="{text}"').first.count() > 0:
                            see_no_results = True
                            break
                    except Exception:
                        pass
                if see_no_results:
                    no_results_consecutive += 1
                    if no_results_consecutive >= 2:
                        time.sleep(0.2)
                        still = False
                        for text in no_results_texts:
                            try:
                                if page.locator(f'text="{text}"').first.count() > 0:
                                    still = True
                                    break
                            except Exception:
                                pass
                        if still:
                            print(f"❌ ไม่พบผลลัพธ์สำหรับ Order {order_id}")
                            print("   Facebook แสดงข้อความ 'ไม่พบผลลัพธ์' — ไม่มีแชทที่ตรงกับ Order นี้")
                            return (False, "no_results")
                else:
                    no_results_consecutive = 0

            time.sleep(POLL_INTERVAL)

        if not conversation_item:
            
            # Fallback: เมื่อ Facebook แสดง "X ข้อความที่ตรงกัน" โดยไม่แสดง order text ใน list item
            matching_keywords = ["ข้อความที่ตรงกัน", "matching message", "matched message"]
            try:
                all_items = page.query_selector_all('div._a6ag')

                if len(all_items) == 1:
                    item_text = all_items[0].evaluate("el => el.textContent || ''")
                    if any(kw in item_text for kw in matching_keywords):
                        conversation_item = all_items[0]
                        print(f"   ✅ พบแชท (ผ่าน 'ข้อความที่ตรงกัน') ({_fmt_elapsed(time.time() - t_find)})")

                elif len(all_items) > 1:
                    # หลายผลลัพธ์: แยกรายการที่มี "ข้อความที่ตรงกัน" ออกจากรายการที่แสดง Order อื่น
                    matched_msg_items = []
                    order_text_items = []
                    for item in all_items:
                        try:
                            txt = item.evaluate("el => el.textContent || ''")
                        except Exception:
                            continue
                        if any(kw in txt for kw in matching_keywords):
                            matched_msg_items.append((item, txt))
                        else:
                            order_text_items.append((item, txt))

                    if len(matched_msg_items) == 1:
                        conversation_item = matched_msg_items[0][0]
                        print(f"   ✅ พบแชท (1 'ข้อความที่ตรงกัน' จาก {len(all_items)} รายการ) ({_fmt_elapsed(time.time() - t_find)})")

                    elif len(matched_msg_items) > 1 and customer_name:
                        # หลายรายการที่มี "ข้อความที่ตรงกัน" → ใช้ชื่อลูกค้า fuzzy match
                        best_item, best_score, best_txt = _fuzzy_pick_chat(matched_msg_items, customer_name)
                        if best_item and best_score > 0:
                            conversation_item = best_item
                            print(f"   ✅ พบแชท (fuzzy match score={best_score}, จาก {len(matched_msg_items)} ตัวเลือก) ({_fmt_elapsed(time.time() - t_find)})")
                        else:
                            print(f"   ⚠️ พบ {len(matched_msg_items)} รายการ 'ข้อความที่ตรงกัน' แต่ fuzzy match ไม่สามารถระบุได้")

                    elif len(matched_msg_items) > 1:
                        print(f"   ⚠️ พบ {len(matched_msg_items)} รายการ 'ข้อความที่ตรงกัน' — ไม่มีชื่อลูกค้าสำหรับ fuzzy match")

                    elif len(matched_msg_items) == 0 and customer_name:
                        # ไม่มี "ข้อความที่ตรงกัน" เลย → ลอง fuzzy match กับทุกรายการ
                        all_with_text = [(item, item.evaluate("el => el.textContent || ''")) for item in all_items]
                        best_item, best_score, best_txt = _fuzzy_pick_chat(all_with_text, customer_name)
                        if best_item and best_score > 0:
                            conversation_item = best_item
                            print(f"   ✅ พบแชท (fuzzy match score={best_score}) ({_fmt_elapsed(time.time() - t_find)})")

            except Exception as e:
                pass
        
        if not conversation_item:
            for template_idx, template in enumerate(ui_selectors.CONVERSATION_ITEM_FALLBACK_TEMPLATES):
                sel = template.format(order_id=order_id)
                try:
                    conversation_item = page.wait_for_selector(sel, timeout=1 * 1000)
                    if conversation_item:
                        break
                except Exception as e:
                    continue
        
        find_time = time.time() - t_find
        if conversation_item:
            item_text = conversation_item.inner_text() if hasattr(conversation_item, 'inner_text') else ""
            print(f"   ✅ พบแชท ({_fmt_elapsed(find_time)})")
            print(f"   ข้อความ: {item_text[:100]}...")

        print(f"   ⏱️ ขั้นหาแชท รวม: {_fmt_elapsed(time.time() - t0)}")
        
        # คลิกแชทที่เจอ
        t0 = time.time()
        if conversation_item:

            try:
                # ดึง selected_item_id ก่อนคลิก (แชทเริ่มต้นที่เปิดหน้ามาครั้งแรก)
                initial_selected_id = _get_selected_item_id_from_url(page.url)

                # ตรวจสอบว่าเป็น element ที่คลิกได้จริง
                item_text = conversation_item.inner_text() if hasattr(conversation_item, 'inner_text') else ""
                print(f"   🖱️ คลิกแชท: {item_text[:100]}...")
                
                # จับ reference ของ message_input ตัวเก่า **ก่อน** คลิก
                _old_msg_input = None
                try:
                    _old_msg_input = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                except Exception:
                    pass

                # ลองหลายวิธีในการคลิก
                clicked = False
                t_before_click = time.time()
                try:
                    conversation_item.click()
                    clicked = True
                except:
                    try:
                        page.evaluate("(element) => element.click()", conversation_item)
                        clicked = True
                    except:
                        try:
                            conversation_item.scroll_into_view_if_needed()
                            conversation_item.click()
                            clicked = True
                        except:
                            pass
                t_after_click = time.time()
                
                if not clicked:
                    print("   ❌ ไม่สามารถคลิกแชทได้")
                    return (False, "not_found")

                print("   ✅ คลิกแชทแล้ว — รอแชทใหม่โหลด...")

                # จำชื่อ header เก่า (ก่อนโหลดแชทใหม่)
                _initial_header = ""
                try:
                    _sig = page.evaluate(_JS_CHAT_SIGNALS)
                    _initial_header = _sig.get("headerName", "") if isinstance(_sig, dict) else ""
                except Exception:
                    pass
                print(f"   📛 header ก่อนคลิก: '{_initial_header}'")

                chat_ready = False
                t_wait_chat = time.time()
                _ready_reason = ""
                _last_printed_header = ""
                _header_changed_at = None  # เมื่อไหร่ที่ header เปลี่ยนเป็นชื่อใหม่ (ใช้สำหรับ fallback ไม่รอ spinner)

                for poll_i in range(200):  # สูงสุด 20 วินาที (0.1s x 200)
                    time.sleep(0.1)
                    _elapsed = time.time() - t_wait_chat

                    # === ดึงสัญญาณทั้งหมดในครั้งเดียว (1 evaluate call ต่อ loop) ===
                    _signals = {"headerName": "", "spinners": 0}
                    try:
                        _signals = page.evaluate(_JS_CHAT_SIGNALS) or _signals
                    except Exception:
                        pass
                    _header = _signals.get("headerName", "")
                    _has_spinner = _signals.get("spinners", 0) > 0

                    # ===== PRIMARY: ชื่อ header เปลี่ยนจากเดิม + ไม่มี spinner =====
                    # เร็วที่สุด: ชื่อเปลี่ยน = Facebook navigate ไปแชทใหม่เสร็จแล้ว
                    if _header and len(_header) >= 2 and _header != _initial_header:
                        if _header_changed_at is None:
                            _header_changed_at = time.time()
                        if not _has_spinner:
                            chat_ready = True
                            _ready_reason = f"header changed: '{_header}'"
                            break
                        # Fallback: header เปลี่ยนแล้วและคงอยู่ >= 0.5s → ไม่รอ spinner (FB บางที spinner หายช้า)
                        if time.time() - _header_changed_at >= 0.5:
                            chat_ready = True
                            _ready_reason = f"header changed (stable 0.5s): '{_header}'"
                            break

                    # ===== SECONDARY: old element ถูกทำลาย + ไม่มี spinner =====
                    if _old_msg_input:
                        try:
                            if not _old_msg_input.evaluate("el => el.isConnected"):
                                if not _has_spinner:
                                    _new_el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                                    if _new_el and _new_el.is_visible():
                                        chat_ready = True
                                        _ready_reason = "old detached + new visible"
                                        break
                        except Exception:
                            if not _has_spinner:
                                _new_el = None
                                try:
                                    _new_el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                                except Exception:
                                    pass
                                if _new_el:
                                    chat_ready = True
                                    _ready_reason = "old eval error + new found"
                                    break

                    # ===== TERTIARY: URL ไม่เปลี่ยน > 3s → same chat =====
                    if _elapsed > 3.0:
                        _cur_url_id = _get_selected_item_id_from_url(page.url)
                        if _cur_url_id == initial_selected_id:
                            _new_el = None
                            try:
                                _new_el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                            except Exception:
                                pass
                            if _new_el:
                                try:
                                    if _new_el.is_visible():
                                        chat_ready = True
                                        _ready_reason = f"same chat (URL unchanged {_elapsed:.1f}s)"
                                        break
                                except Exception:
                                    pass

                current_url_after = page.url
                print(f"   📍 URL หลังคลิก: {current_url_after}")

                if chat_ready:
                    total_time = time.time() - fn_start
                    click_open_time = time.time() - t0
                    print(f"✅ เปิดแชทสำเร็จ — {_ready_reason} ({_fmt_elapsed(time.time() - t_wait_chat)})")
                    print(f"   ⏱️ ขั้นคลิกแชท + เปิด รวม: {_fmt_elapsed(click_open_time)}")
                    print(f"   ⏱️ เปิด Inbox + ค้นหา + เปิดแชท รวม: {_fmt_elapsed(total_time)}")
                    return (True, None)

                # Fallback: timeout 20s
                print(f"   ⚠️ รอแชทโหลดเกิน 20s — ลองหา input สุดท้าย...")
                try:
                    message_input = page.wait_for_selector(ui_selectors.MESSAGE_INPUT_SELECTOR, timeout=5000)
                    if message_input:
                        total_time = time.time() - fn_start
                        print(f"✅ เปิดแชทสำเร็จ — พบช่องพิมพ์ข้อความ (fallback)")
                        print(f"   ⏱️ เปิด Inbox + ค้นหา + เปิดแชท รวม: {_fmt_elapsed(total_time)}")
                        return (True, None)
                except:
                    pass
                
                print(f"⚠️ ไม่พบช่องพิมพ์ข้อความ — timeout")
                return (False, "not_found")
            except Exception as e:
                print(f"❌ ไม่สามารถคลิกแชทได้: {e}")
                import traceback
                print(f"   รายละเอียด: {traceback.format_exc()}")
                return (False, "not_found")
        else:


            print(f"❌ ไม่พบแชทที่ตรงกับ Order {order_id}")
            print("   กรุณาตรวจสอบว่า:")
            print("   1. มีแชทที่มี Order number นี้จริงหรือไม่")
            print("   2. Facebook UI เปลี่ยนไปหรือไม่ (ตรวจสอบ ui_selectors.py)")
            print("   3. รายชื่อบุคคลปรากฏแล้วหรือยัง (อาจต้องรอนานขึ้น)")

            return (False, "not_found")
    
    except Exception as e:


        print(f"❌ เกิดข้อผิดพลาดขณะเปิด Inbox หรือค้นหา: {e}")
        return (False, "not_found")


def _get_fresh_message_input(page: Page):
    """Re-query ช่องพิมพ์ข้อความที่ยังต่อกับ DOM (ลด Element is not attached to the DOM).
    คืนค่า element หรือ None ถ้าไม่พบหลัง retry 5 ครั้ง."""
    for _ in range(5):
        try:
            el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
            if el and el.evaluate("el => el.isConnected"):
                return el
        except Exception:
            pass
        time.sleep(0.15)
    return None


def send_message_with_image(
    page: Page,
    tracking_id: str,
    image_path: Optional[Path],
    dry_run: bool = False,
    carrier: str = "",
) -> bool:
    """ส่งข้อความพร้อมรูปบิล
    เกณฑ์ยืนยัน: (1) แชทโหลดแล้ว = chat header เปลี่ยนใน open_inbox_and_search_order
    (2) ส่งแล้ว = ช่อง compose ว่าง + รูป preview หาย (post-send verify)"""

    message_text = bill_tracking_customer_message(tracking_id, carrier)
    
    if dry_run:
        print(f"[DRY-RUN] จะส่งข้อความ: {message_text}")
        if image_path:
            print(f"[DRY-RUN] จะแนบรูป: {image_path}")
        return True
    
    send_fn_start = time.time()
    print(f"\n📤 กำลังส่งข้อความและรูปบิล...")
    print(f"   ข้อความ: {message_text[:50]}...")
    if image_path:
        print(f"   รูปบิล: {image_path.name}")

    try:
        # If AI agent is replying, switch to manual reply mode first (skip otherwise to reduce latency).
        pre_snap = _agent_ui_snapshot(page)
        if pre_snap.get("hasReplyYourselfText") or pre_snap.get("hasConfirmReplyText") or int(pre_snap.get("dialogs") or 0) > 0:
            _ensure_manual_reply_mode(page)
        # หาช่องพิมพ์ข้อความ
        t0 = time.time()
        print("   🔍 หาช่องพิมพ์ข้อความ...")

        message_input = None
        for _stable_retry in range(3):
            # Fast-path: if AI popup/dialog present, handle it immediately (avoid 10s blocking waits).
            _snap_pre_wait = _agent_ui_snapshot(page)
            if (
                _snap_pre_wait.get("hasReplyYourselfText")
                or _snap_pre_wait.get("hasConfirmReplyText")
                or int(_snap_pre_wait.get("dialogs") or 0) > 0
            ):
                _ensure_manual_reply_mode(page)

            _el = _get_fresh_message_input(page)
            if not _el:
                try:
                    _el = page.wait_for_selector(
                        ui_selectors.MESSAGE_INPUT_SELECTOR,
                        timeout=1500,
                    )
                except Exception:
                    pass
            if not _el:
                try:
                    _el = page.wait_for_selector(
                        f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}",
                        timeout=1500,
                    )
                except Exception:
                    pass
            if not _el:
                continue
            time.sleep(0.10)
            try:
                if _el.evaluate("el => el.isConnected"):
                    message_input = _el
                    break
            except Exception:
                pass
            print(f"   ⚠️ ช่องพิมพ์ไม่ stable (retry {_stable_retry+1}/3)")

        if not message_input:
            print("   ❌ ไม่พบช่องพิมพ์ข้อความ")
            snap_miss = _agent_ui_snapshot(page)
            print("   ⚠️ อาจยังไม่ได้เปิดแชท — กรุณาตรวจสอบว่าเปิดแชทสำเร็จแล้วหรือไม่")

            # If AI handoff/popup is still on screen, switch to manual mode and retry input once immediately.
            if snap_miss.get("hasReplyYourselfText") or snap_miss.get("hasConfirmReplyText") or int(snap_miss.get("dialogs") or 0) > 0:
                _ensure_manual_reply_mode(page)
                for _retry_after_manual in range(12):
                    time.sleep(0.20)
                    message_input = _get_fresh_message_input(page)
                    if message_input:
                        break
                if not message_input:
                    return False
            else:
                return False
        
        find_input_time = time.time() - t0
        print("   ✅ พบช่องพิมพ์ข้อความ (stable)")
        print(f"   ⏱️ หาช่องพิมพ์: {_fmt_elapsed(find_input_time)}")

        # พิมพ์ข้อความ — ใช้ insertText เพื่อ trigger React input event
        # Re-query + retry คลิก: บางรัน element หลุดระหว่างได้ handle กับคลิก (race กับ React)
        t0 = time.time()
        print("   ⌨️ พิมพ์ข้อความ...")
        click_ok = False
        for _click_attempt in range(3):
            message_input = _get_fresh_message_input(page)
            if not message_input:
                time.sleep(0.2)
                continue
            try:
                message_input.click()
                click_ok = True
                break
            except Exception as e:
                err_str = str(e).lower()
                if "not attached" in err_str or "detached" in err_str:
                    if _click_attempt < 2:
                        print("   ⚠️ ช่องพิมพ์หลุดก่อนคลิก — ลองใหม่...")
                    time.sleep(0.25)
                    continue
                raise
        if not click_ok:
            print("   ❌ ไม่พบช่องพิมพ์ก่อนพิมพ์ข้อความ")
            return False

        _human_delay(80, 200)
        page.keyboard.press("Control+a")
        _human_delay(30, 60)
        page.keyboard.press("Backspace")
        _human_delay(30, 60)
        page.keyboard.insert_text(message_text)
        _human_delay(200, 400)

        input_content = ""
        try:
            input_content = (message_input.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
        except Exception:
            pass

        if not input_content:
            print("   ⚠️ insertText ไม่เข้า → re-query element แล้วลองใหม่")
            message_input = None
            for _rq in range(5):
                time.sleep(0.3)
                try:
                    _fresh = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                    if _fresh and _fresh.evaluate("el => el.isConnected"):
                        message_input = _fresh
                        break
                except Exception:
                    pass
            if not message_input:
                print("   ❌ ไม่พบช่องพิมพ์ใหม่หลัง re-query")
                return False

            message_input.click()
            _human_delay(80, 200)
            page.keyboard.press("Control+a")
            _human_delay(30, 60)
            page.keyboard.press("Backspace")
            _human_delay(30, 60)
            page.keyboard.insert_text(message_text)
            _human_delay(200, 400)
            try:
                input_content = (message_input.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
            except Exception:
                pass

            if not input_content:
                print("   ⚠️ insertText ยังไม่เข้า → ลอง type ทีละตัว")
                message_input.click()
                _human_delay(50, 100)
                page.keyboard.type(message_text, delay=15)
                _human_delay(200, 400)

        fill_msg_time = time.time() - t0
        print(f"   ✅ พิมพ์ข้อความเสร็จ ({_fmt_elapsed(fill_msg_time)})")

        # Copy-paste รูป (ถ้ามี) - ใช้ try-except เพื่อไม่ให้ crash ถ้าแนบรูปไม่สำเร็จ
        # สำคัญ: แม้แนบรูปไม่สำเร็จ ต้องส่งข้อความเสมอ
        image_attached = False
        if image_path and image_path.exists():
            # ใช้ try-except รอบการแนบรูปทั้งหมด เพื่อไม่ให้ crash
            try:
                t0 = time.time()
                print(f"   📎 แนบรูป: {image_path.name} (copy-paste จากไฟล์)")
                
                # ใช้ ClipboardItem API - เหมือนกับการ copy จาก Windows File Explorer แล้ว paste
                try:
                    # อ่านไฟล์รูป
                    t_read = time.time()
                    with open(image_path, "rb") as f:
                        image_data = f.read()
                        image_base64 = base64.b64encode(image_data).decode('utf-8')
                    print(f"   ⏱️ อ่านไฟล์รูป: {_fmt_elapsed(time.time() - t_read)}")
                    
                    # Copy รูปไป clipboard (เหมือน copy จาก file explorer)
                    t_clipboard = time.time()
                    result = page.evaluate(f"""
                        async () => {{
                            try {{
                                // แปลง base64 เป็น Uint8Array
                                const byteCharacters = atob('{image_base64}');
                                const byteNumbers = new Array(byteCharacters.length);
                                for (let i = 0; i < byteCharacters.length; i++) {{
                                    byteNumbers[i] = byteCharacters.charCodeAt(i);
                                }}
                                const byteArray = new Uint8Array(byteNumbers);
                                
                                // สร้าง Blob และ File object (เหมือน copy จาก file explorer)
                                const blob = new Blob([byteArray], {{type: 'image/png'}});
                                const file = new File([blob], '{image_path.name}', {{type: 'image/png'}});
                                
                                // สร้าง ClipboardItem จาก File object (เหมือน copy จาก file explorer)
                                const item = new ClipboardItem({{
                                    'image/png': file
                                }});
                                
                                // Copy ไป clipboard (เหมือน copy จาก file explorer)
                                await navigator.clipboard.write([item]);
                                return true;
                            }} catch (e) {{
                                console.error('Clipboard error:', e);
                                return false;
                            }}
                        }}
                    """)
                    print(f"   ⏱️ Copy ไป clipboard: {_fmt_elapsed(time.time() - t_clipboard)}")
                    
                    if result:
                        # Paste ลงช่องแชท (เหมือน paste จาก clipboard)
                        # Re-query ช่องพิมพ์ก่อน paste — handle เดิมอาจหลุดหลังพิมพ์ข้อความ
                        paste_input = _get_fresh_message_input(page)
                        if not paste_input:
                            print("   ⚠️ ไม่พบช่องพิมพ์ก่อน paste รูป — ข้ามแนบรูป")
                        else:
                            t_paste = time.time()
                            print("   📋 Paste รูปลงช่องแชท...")
                            paste_ok = False
                            try:
                                paste_input.click()
                                _human_delay(100, 250)
                                paste_input.press("Control+v")
                                paste_ok = True
                            except Exception as e:
                                print(f"   ⚠️ ไม่สามารถแนบรูปได้: {e}")
                            print(f"   ⏱️ Paste รูป: {_fmt_elapsed(time.time() - t_paste)}")
                            if paste_ok:
                                # รอให้รูปอัพโหลด (ใช้ dynamic check แทน fixed 5 วินาที)
                                t_upload = time.time()
                                print("   ⏳ รอรูปอัพโหลด...")

                                # ตรวจสอบว่า upload เสร็จหรือยัง (ดูจากปุ่มส่งจริง enable) — ใช้ picker ที่กรอง AI/call ออก
                                upload_complete = False
                                for i in range(30):
                                    try:
                                        real_send_btn = _pick_filtered_send_button(page)
                                        if real_send_btn:
                                            is_disabled = real_send_btn.get_attribute("disabled") or real_send_btn.get_attribute("aria-disabled") == "true"
                                            if not is_disabled:
                                                upload_complete = True
                                                break
                                    except Exception:
                                        pass
                                    time.sleep(0.05)
                                
                                upload_time = time.time() - t_upload
                                if upload_complete:
                                    print(f"   ✅ รูปอัพโหลดเสร็จ ({_fmt_elapsed(upload_time)})")
                                else:
                                    print(f"   ⚠️ รอรูปอัพโหลดเกินเวลา ({_fmt_elapsed(upload_time)}) — ส่งต่อ")

                                image_attached = True
                                attach_time = time.time() - t0
                                print(f"   ✅ แนบรูปสำเร็จ ({_fmt_elapsed(attach_time)})")
                            else:
                                print("   💡 จะส่งเฉพาะข้อความ (ไม่มีรูป)")

                    else:
                        print("   ⚠️ Clipboard API ไม่สำเร็จ")
                except Exception as e:
                    print(f"   ⚠️ ไม่สามารถแนบรูปได้: {e}")
                    print("   💡 จะส่งเฉพาะข้อความ (ไม่มีรูป)")
                
                if not image_attached:
                    print("   ⚠️ ไม่สามารถแนบรูปได้ — จะส่งเฉพาะข้อความ")
            except Exception as e:
                print(f"   ⚠️ เกิดข้อผิดพลาดขณะแนบรูป: {e}")
                print("   💡 จะส่งเฉพาะข้อความ (ไม่มีรูป)")
                # ไม่ return False - ให้ส่งข้อความต่อไป
        
        # กดส่ง
        t_find_send = time.time()
        print("   🔍 หาปุ่มส่ง...")

        send_button = None
        
        # ใช้ picker ที่ score-based (กรอง AI/call/forward ออก, prefer exact "ส่ง" match)
        t_sel1 = time.time()
        send_button = _pick_filtered_send_button(page)
        if send_button:
            try:
                _aria_dbg = send_button.get_attribute("aria-label") or ""
                print(f"   ✅ พบปุ่มส่ง ({_aria_dbg!r}) ({_fmt_elapsed(time.time() - t_sel1)})")
            except Exception:
                print(f"   ✅ พบปุ่มส่ง ({_fmt_elapsed(time.time() - t_sel1)})")
        
        find_send_time = time.time() - t_find_send
        print(f"   ⏱️ หาปุ่มส่ง: {_fmt_elapsed(find_send_time)}")

        # ถ้ามีรูปแนบ ให้รอให้ปุ่มส่ง enable ก่อน (ปุ่มส่งจะ disable ขณะอัพโหลดรูป)
        t_wait_enable = time.time()
        print("   🖱️ ส่งข้อความ...")
        send_success = False
        
        if image_attached:
            print("   ⏳ รอปุ่มส่ง enable (ปุ่ม disable ขณะอัพโหลดรูป)...")

            max_wait = 8
            wait_interval = 0.1
            waited = 0
            
            while waited < max_wait:
                try:
                    send_button = _pick_filtered_send_button(page)
                    if send_button:
                        is_disabled = send_button.get_attribute("disabled") or send_button.get_attribute("aria-disabled") == "true"
                        if not is_disabled:
                            enable_wait_time = time.time() - t_wait_enable
                            print(f"   ✅ ปุ่มส่ง enable ({_fmt_elapsed(enable_wait_time)})")
                            break
                    time.sleep(wait_interval)
                    waited += wait_interval
                except Exception:
                    time.sleep(wait_interval)
                    waited += wait_interval
            
            if waited >= max_wait:
                enable_wait_time = time.time() - t_wait_enable
                print(f"   ⚠️ รอปุ่มส่ง enable เกินเวลา ({_fmt_elapsed(enable_wait_time)}) — ส่งต่อ")

        else:
            enable_wait_time = time.time() - t_wait_enable
            print(f"   ⏱️ ไม่มีรูปแนบ — ข้ามรอ enable ({_fmt_elapsed(enable_wait_time)})")

        # Mirror send_message_text_only (ແຈ້ງຮອດແລ້ວ): Enter-first; multiple click strategies as fallback.
        send_method_used = None
        t_send_phase = time.time()

        def _poll_cleared(max_iters: int, interval: float = 0.15) -> bool:
            for _i in range(max_iters):
                if _compose_draft_cleared(page, image_attached):
                    return True
                time.sleep(interval)
            return False

        try:
            print("   ⌨️ ส่งด้วย Enter...")
            _enter_el = _get_fresh_message_input(page)
            if _enter_el:
                _enter_el.press("Enter")
                # Poll: image case takes longer for FB to remove preview/clear compose
                if _poll_cleared(max_iters=14 if image_attached else 5):
                    send_success = True
                    send_method_used = "enter"
                    print(f"   ✅ กดส่งแล้ว (Enter) ({_fmt_elapsed(time.time() - t_send_phase)})")
                else:
                    print("   ⚠️ Enter แล้ว compose ยังไม่ว่าง — จะลองคลิกปุ่มส่ง")
            else:
                print("   ❌ ไม่พบช่องพิมพ์สำหรับ Enter")
        except Exception as e:
            print(f"   ⚠️ ไม่สามารถกด Enter ได้: {e}")

        # Fallback 1: Playwright click on send button (with actionability check)
        if not send_success:
            send_button_final = send_button or _pick_filtered_send_button(page)
            try:
                hd_state = page.evaluate(
                    """() => {
                      const all = document.querySelectorAll('button, [role="button"], [aria-label]');
                      const matches = [];
                      for (const b of all) {
                        const a = (b.getAttribute('aria-label') || '').toLowerCase();
                        const t = (b.textContent || '').trim().toLowerCase();
                        if (!(a.includes('send') || a.includes('ส่ง') || a.includes('ສົ່ງ') || t.includes('ส่ง'))) continue;
                        const r = b.getBoundingClientRect();
                        if (r.width < 1 || r.height < 1) continue;
                        matches.push({
                          aria: b.getAttribute('aria-label') || '',
                          text: (b.textContent || '').trim().slice(0, 40),
                          tag: b.tagName,
                          role: b.getAttribute('role') || '',
                          disabled: !!b.disabled || b.getAttribute('aria-disabled') === 'true',
                          x: (r.left + r.width/2) | 0,
                          y: (r.top + r.height/2) | 0,
                          w: r.width | 0,
                        });
                      }
                      // also detect attachment preview siblings of contenteditable
                      const ce = document.querySelector('div[contenteditable="true"][role="textbox"], [contenteditable="true"]');
                      let preview = {imgs: 0, files: 0, parentImgs: 0};
                      if (ce) {
                        let p = ce.parentElement;
                        for (let i = 0; i < 5 && p; i++) {
                          const cnt = p.querySelectorAll('img').length;
                          if (cnt > preview.parentImgs) preview.parentImgs = cnt;
                          p = p.parentElement;
                        }
                      }
                      return {found: matches.length, matches: matches.slice(0, 8), preview};
                    }"""
                )
            except Exception as _e:
                hd_state = {"err": str(_e)[:120]}
            if send_button_final:
                try:
                    t_click = time.time()
                    print("   🖱️ คลิกปุ่มส่ง (Playwright)...")
                    send_button_final.click(timeout=2000)
                    if _poll_cleared(max_iters=14 if image_attached else 5):
                        send_success = True
                        send_method_used = "playwright_click"
                        print(f"   ✅ กดส่งแล้ว (PW click) ({_fmt_elapsed(time.time() - t_click)})")
                except Exception as e:
                    print(f"   ⚠️ Playwright click ล้ม: {e}")

        # Fallback 2: JS click (bypass actionability check; useful if overlay blocks pointer)
        if not send_success:
            send_button_final = _pick_filtered_send_button(page)
            if send_button_final:
                try:
                    t_jsclick = time.time()
                    print("   🖱️ คลิกปุ่มส่ง (JS evaluate)...")
                    page.evaluate(
                        """(el) => {
                          if (el) {
                            el.scrollIntoView({ behavior: 'instant', block: 'center' });
                            el.click();
                          }
                        }""",
                        send_button_final,
                    )
                    if _poll_cleared(max_iters=14 if image_attached else 5):
                        send_success = True
                        send_method_used = "js_click"
                        print(f"   ✅ กดส่งแล้ว (JS click) ({_fmt_elapsed(time.time() - t_jsclick)})")
                except Exception as e:
                    print(f"   ⚠️ JS click ล้ม: {e}")

        
        # Post-send verification: ตรวจว่าข้อความและรูปถูกส่งจริง (ช่อง compose ว่าง / รูป preview หายไป) — poll แทนรอคงที่
        verified = False
        if send_success:
            time.sleep(0.3)
            for _ in range(5):
                text_empty = False
                image_gone = True  # ถ้าไม่มีรูปแนบ ถือว่าผ่าน
                try:
                    msg_el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                    if msg_el:
                        content = (msg_el.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
                        text_empty = content == "" or content.replace("\n", "").strip() == ""
                    # ถ้ามีรูปแนบ: ตรวจว่ารูป preview ในช่อง compose หายไป (ส่งไปแล้ว)
                    if image_attached and msg_el:
                        try:
                            compose_imgs = page.query_selector_all('div[contenteditable="true"][role="textbox"] img, [contenteditable="true"] img')
                            image_gone = len(compose_imgs) == 0
                        except Exception:
                            image_gone = True
                    if text_empty and image_gone:
                        verified = True
                        break
                except Exception:
                    pass
                if _ < 4:
                    time.sleep(0.15)
            if not verified:
                # ลองกดส่งอีก 1 ครั้ง
                print("   🔄 ยืนยันไม่ได้ — ลองกดส่งอีกครั้ง...")
                try:
                    send_btn = None
                    try:
                        all_btns = page.query_selector_all(ui_selectors.SEND_BUTTON_SELECTOR)
                        for btn in all_btns:
                            try:
                                aria = (btn.get_attribute("aria-label") or "").lower()
                                text = btn.evaluate("el => el.textContent?.trim() || ''").lower()
                                if any(kw in aria for kw in ["โทร", "สาย", "call", "phone"]) or any(kw in text for kw in ["โทร", "สาย", "call", "phone"]):
                                    continue
                                send_btn = btn
                                break
                            except Exception:
                                continue
                    except Exception:
                        pass
                    if send_btn:
                        page.evaluate("(el) => el && el.click()", send_btn)
                    else:
                        message_input = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                        if message_input:
                            message_input.press("Enter")
                    time.sleep(0.8)
                    # ตรวจอีกครั้ง
                    try:
                        msg_el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                        if msg_el:
                            content = (msg_el.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
                            text_empty = content == "" or content.replace("\n", "").strip() == ""
                        if image_attached and msg_el:
                            try:
                                compose_imgs = page.query_selector_all('div[contenteditable="true"][role="textbox"] img, [contenteditable="true"] img')
                                image_gone = len(compose_imgs) == 0
                            except Exception:
                                image_gone = True
                        verified = text_empty and image_gone
                    except Exception:
                        pass
                except Exception:
                    pass
            if verified:
                print(f"   ⏱️ ขั้นหาปุ่ม+ส่ง รวม: {_fmt_elapsed(time.time() - t_find_send)}")
                print(f"   ⏱️ ขั้นส่งข้อความและรูป รวม: {_fmt_elapsed(time.time() - send_fn_start)}")
                if image_attached:
                    print("   ✅ ส่งข้อความ+รูปสำเร็จ (ยืนยัน)")
                else:
                    print("   ✅ ส่งข้อความสำเร็จ ไม่มีรูป (ยืนยัน)")
                return True
            else:
                print("   ⚠️ กดส่งแล้วแต่ยืนยันไม่ได้ (ช่อง compose ไม่ว่างหรือรูปยังอยู่)")
                return False
        else:
            print("   ❌ ไม่สามารถส่งข้อความได้")
            return False
    
    except Exception as e:
        print(f"   ❌ เกิดข้อผิดพลาดขณะส่งข้อความ: {e}")
        import traceback
        print(f"   รายละเอียด: {traceback.format_exc()}")
        return False


def send_message_text_only(page: Page, message_text: str, dry_run: bool = False) -> bool:
    """ส่งข้อความอย่างเดียว (ไม่แนบรูป) — ใช้กับโหมดແຈ້ງຮອດແລ້ວ
    วิธีส่ง: พิมพ์ข้อความ → กด Enter (เสถียรที่สุดบน Facebook Business Suite)
    ยืนยัน: ช่องพิมพ์ว่าง + ข้อความปรากฏในแชท"""
    if dry_run:
        print(f"[DRY-RUN] จะส่งข้อความ: {message_text[:60]}...")
        return True

    send_fn_start = time.time()
    print(f"\n   กำลังส่งข้อความ: {message_text[:60]}...")

    try:
        # Same AI-guard strategy as send_message_with_image:
        # if AI handoff/popup exists, switch to manual mode before touching compose.
        pre_snap = _agent_ui_snapshot(page)
        if pre_snap.get("hasReplyYourselfText") or pre_snap.get("hasConfirmReplyText") or int(pre_snap.get("dialogs") or 0) > 0:
            _ensure_manual_reply_mode(page)

        # หาช่องพิมพ์ข้อความ — ต้องเป็น element ที่ stable (ไม่กำลังถูก React ทำลาย)
        t0 = time.time()
        message_input = None
        for _stable_retry in range(3):
            _el = None
            try:
                _el = page.wait_for_selector(ui_selectors.MESSAGE_INPUT_SELECTOR, timeout=ui_selectors.ELEMENT_WAIT_TIMEOUT * 1000)
            except Exception:
                pass
            if not _el:
                try:
                    _el = page.wait_for_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}", timeout=ui_selectors.ELEMENT_WAIT_TIMEOUT * 1000)
                except Exception:
                    pass
            if not _el:
                break
            # ตรวจว่า element stable: รอ 0.15s แล้วเช็คว่ายังอยู่ใน DOM
            time.sleep(0.15)
            try:
                if _el.evaluate("el => el.isConnected"):
                    message_input = _el
                    break
            except Exception:
                pass
            print(f"   ⚠️ ช่องพิมพ์ไม่ stable (retry {_stable_retry+1}/3)")

        if not message_input:
            print("   ไม่พบช่องพิมพ์ข้อความ")
            snap_miss = _agent_ui_snapshot(page)
            # If AI handoff/popup still present, recover once immediately.
            if snap_miss.get("hasReplyYourselfText") or snap_miss.get("hasConfirmReplyText") or int(snap_miss.get("dialogs") or 0) > 0:
                _ensure_manual_reply_mode(page)
                for _retry_after_manual in range(12):
                    time.sleep(0.20)
                    message_input = _get_fresh_message_input(page)
                    if message_input:
                        break
                if not message_input:
                    return False
            else:
                return False
        print(f"   พบช่องพิมพ์ ({_fmt_elapsed(time.time() - t0)})")

        # คลิกช่องพิมพ์ + เคลียร์เนื้อหาเดิม
        message_input.click()
        _human_delay(100, 250)
        page.keyboard.press("Control+a")
        _human_delay(50, 100)
        page.keyboard.press("Backspace")
        _human_delay(50, 100)

        # insertText — trigger React input event
        page.keyboard.insert_text(message_text)
        _human_delay(200, 400)

        # ยืนยันว่า React รับข้อความจริง
        input_content = ""
        try:
            input_content = (message_input.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
        except Exception:
            pass

        # ถ้า insertText ไม่เข้า → element อาจ detached → re-query + retry
        if not input_content:
            print("   ⚠️ insertText ไม่เข้า → re-query element แล้วลองใหม่")
            # Re-query element ใหม่ (ตัวเก่าอาจถูก React ทำลายแล้ว)
            message_input = None
            for _rq in range(5):
                time.sleep(0.3)
                try:
                    _fresh = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                    if _fresh and _fresh.evaluate("el => el.isConnected"):
                        message_input = _fresh
                        break
                except Exception:
                    pass
            if not message_input:
                print("   ❌ ไม่พบช่องพิมพ์ใหม่หลัง re-query")
                return False

            message_input.click()
            _human_delay(100, 200)
            page.keyboard.press("Control+a")
            _human_delay(50, 100)
            page.keyboard.press("Backspace")
            _human_delay(50, 100)
            page.keyboard.insert_text(message_text)
            _human_delay(200, 400)
            try:
                input_content = (message_input.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
            except Exception:
                pass

            if not input_content:
                # Fallback สุดท้าย: ลอง type ทีละตัว
                print("   ⚠️ insertText ยังไม่เข้า → ลอง type ทีละตัว")
                message_input.click()
                _human_delay(50, 100)
                page.keyboard.type(message_text, delay=15)
                _human_delay(200, 400)
                try:
                    input_content = (message_input.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
                except Exception:
                    pass
                if not input_content:
                    print("   ❌ ไม่สามารถพิมพ์ข้อความลงช่องได้")
                    return False

        print(f"   พิมพ์ข้อความเสร็จ (ยืนยันมีข้อความในช่อง: {len(input_content)} ตัวอักษร)")

        def _verify_sent():
            """ตรวจว่าข้อความถูกส่งแล้ว (ช่องพิมพ์ว่าง)"""
            time.sleep(0.5)
            for i in range(12):
                try:
                    msg_el = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR) or page.query_selector(f"xpath={ui_selectors.MESSAGE_INPUT_XPATH}")
                    if msg_el:
                        content = (msg_el.evaluate("el => el.innerText || el.textContent || ''") or "").strip()
                        if content == "" or content.replace("\n", "").strip() == "":
                            return True
                except Exception:
                    pass
                time.sleep(0.2)
            return False

        # ส่งด้วย Enter
        page.keyboard.press("Enter")
        print("   กดส่ง (Enter)")

        v1 = _verify_sent()
        if v1:
            print(f"   ส่งข้อความสำเร็จ (ยืนยัน) ({_fmt_elapsed(time.time() - send_fn_start)})")
            return True

        # Enter ไม่สำเร็จ → ข้อความยังค้าง → ลองคลิกปุ่มส่ง
        print("   ⚠️ Enter ไม่สำเร็จ (ข้อความยังค้าง) → ลองคลิกปุ่มส่ง...")

        send_button = _pick_filtered_send_button(page)

        if send_button:
            try:
                send_button.click()
                print("   กดปุ่มส่ง (Playwright click)")
            except Exception:
                try:
                    page.evaluate("""(el) => {
                        if (el) { el.scrollIntoView({ behavior: 'instant', block: 'center' }); el.click(); }
                    }""", send_button)
                    print("   กดปุ่มส่ง (JS click)")
                except Exception:
                    pass

            v2 = _verify_sent()
            if v2:
                print(f"   ส่งข้อความสำเร็จ (ยืนยัน ครั้งที่ 2) ({_fmt_elapsed(time.time() - send_fn_start)})")
                return True

        print("   ❌ ส่งข้อความไม่สำเร็จ (ข้อความยังค้างในช่องพิมพ์)")
        return False

    except Exception as e:
        print(f"   เกิดข้อผิดพลาดขณะส่งข้อความ: {e}")
        import traceback
        print(f"   รายละเอียด: {traceback.format_exc()}")
        return False


def send_bill_single(
    order_id: str,
    page_name: str,
    tracking_id: str,
    bills_dir: Path,
    user_data_dir: Optional[Path] = None,
    dry_run: bool = False,
    carrier: str = "",
) -> bool:
    """ส่งบิลสำหรับ 1 Order"""

    overall_start = time.time()
    print(f"\n📦 Order: {order_id} | เพจ: {page_name} | Tracking: {tracking_id}")
    
    # โหลด config

    mapping = load_page_name_to_id()
    page_id = get_page_id(page_name, mapping)
    
    if not page_id:
        print(f"❌ ไม่พบ page_id สำหรับเพจ: {page_name}")
        print(f"   กรุณาตรวจสอบ config/page_name_to_id.json")
        return False
    
    business_page_names = get_business_page_names(mapping)
    
    # หารูปบิล
    image_path = find_bill_image(bills_dir, tracking_id)
    if not image_path:
        print(f"❌ ไม่พบรูปบิล — ไม่ส่ง Order {order_id} tracking={tracking_id}")
        print(f"   โฟลเดอร์: {bills_dir}")
        return False
    else:
        try:
            img_size = image_path.stat().st_size
        except Exception:
            img_size = -1
    
    if dry_run:
        print(f"[DRY-RUN] จะส่งบิลไปยังเพจ {page_name} (page_id: {page_id})")
        return True
    
    # เปิดเบราว์เซอร์
    with sync_playwright() as p:
        t_browser = time.time()
        if user_data_dir:
            user_data_dir.mkdir(parents=True, exist_ok=True)
            print(f"📂 ใช้ browser profile จาก: {user_data_dir}")
            print("   (session จะคงอยู่เหมือน browser ปกติ — ไม่ต้องล็อกอินทุกครั้ง)")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                channel="chrome",
                headless=False,
                viewport={"width": 1600, "height": 1000},
                permissions=["clipboard-read", "clipboard-write"],
                args=STEALTH_CHROME_ARGS,
                ignore_default_args=["--enable-automation", "--enable-blink-features=IdleDetection"],
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                color_scheme="light",
            )
            context.add_init_script(STEALTH_INIT_SCRIPT)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1600, "height": 1000})
        else:
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=STEALTH_CHROME_ARGS,
                ignore_default_args=["--enable-automation", "--enable-blink-features=IdleDetection"],
            )
            context = browser.new_context(
                viewport={"width": 1600, "height": 1000},
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                color_scheme="light",
            )
            context.add_init_script(STEALTH_INIT_SCRIPT)
            page = context.new_page()
            page.set_viewport_size({"width": 1600, "height": 1000})
        print(f"   ⏱️ เปิดเบราว์เซอร์: {_fmt_elapsed(time.time() - t_browser)}")
        
        try:
            # ตรวจสอบว่ายังล็อกอินอยู่หรือไม่ + navigate ไปหน้า Inbox (รวมเป็นขั้นตอนเดียว)
            t_check_login = time.time()
            print("🔍 ตรวจสอบล็อกอิน + เปิด Inbox...")
            # ใช้ get_initial_inbox_url เพื่อเปิดแชทด้วย selected_item_id (ไม่เปิดแชทล่าสุด)
            inbox_url = get_initial_inbox_url(page_name, page_id, business_page_names, mapping)

            t_navigate = time.time()
            # ใช้ domcontentloaded เพื่อให้หน้าโหลดเสร็จก่อน — ลดการกระตุกของ UI

            page.goto(inbox_url, wait_until="domcontentloaded", timeout=ui_selectors.PAGE_LOAD_TIMEOUT * 1000)
            t_after_nav = time.time()
            nav_time = t_after_nav - t_navigate

            print(f"   ⏱️ Navigate ไป Inbox: {_fmt_elapsed(nav_time)}")
            
            t_wait_ready = time.time()
            login_or_ready = False
            ready_method = "timeout"
            # ใช้ wait_for_load_state เพื่อรอให้หน้าโหลดเสร็จก่อน — ลดการกระตุก
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except:
                pass
            # ตรวจสอบสถานะหลังจากหน้าโหลดเสร็จแล้ว
            for i in range(30):  # ลดจาก 60 เป็น 30 iterations (3s แทน 6s) เพราะหน้าโหลดเสร็จแล้ว
                current_url = page.url
                if "login" in current_url.lower():
                    login_or_ready = True
                    ready_method = "login_page_detected"
                    break
                if page.query_selector('input[type="password"], input[name="pass"]'):
                    login_or_ready = True
                    ready_method = "password_input_found"
                    break
                if page.query_selector(ui_selectors.SEARCH_INPUT_SELECTOR):
                    login_or_ready = True
                    ready_method = "inbox_ready"
                    break
                time.sleep(0.1)
            
            actual_ready_wait = time.time() - t_wait_ready
            print(f"   ⏱️ รอหน้าพร้อม: {_fmt_elapsed(actual_ready_wait)} ({ready_method})")
            
            is_login_page = ready_method in ("login_page_detected", "password_input_found")
            
            if is_login_page:
                print("⚠️ ยังไม่ล็อกอิน — กรุณาล็อกอิน Facebook ในเบราว์เซอร์ที่เปิดขึ้นมา")
                print("   💡 Session จะถูกบันทึกอัตโนมัติใน browser profile — ไม่ต้องล็อกอินอีกครั้ง")
                if sys.stdin.isatty():
                    print("   หลังจากล็อกอินแล้ว กด Enter เพื่อดำเนินการต่อ...")
                    input()
                else:
                    print("   รอให้ล็อกอิน (สูงสุด 120 วินาที)...")
                    for _ in range(120):
                        time.sleep(1)
                        if page.query_selector(ui_selectors.SEARCH_INPUT_SELECTOR):
                            break
                page.goto(inbox_url, wait_until="domcontentloaded", timeout=ui_selectors.PAGE_LOAD_TIMEOUT * 1000)
            else:
                print(f"   ✅ ยังล็อกอินอยู่")
                
                # ตรวจสอบว่าแชทที่เปิดด้วย selected_item_id มีอยู่จริงหรือไม่ (error handling)
                # ข้าม check นี้สำหรับ business pages เพราะไม่ใช้ selected_item_id
                if page_name not in business_page_names:
                    # รอให้หน้าโหลดเสร็จก่อนตรวจสอบ
                    try:
                        page.wait_for_selector(ui_selectors.SEARCH_INPUT_SELECTOR, timeout=5000)
                    except:
                        pass
                    
                    # ตรวจสอบว่าแชทเปิดสำเร็จ (มี message input) หรือไม่
                    chat_opened = False
                    try:
                        message_input = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR)
                        if message_input:
                            chat_opened = True
                    except:
                        pass
                    
                    if not chat_opened:
                        # ไม่พบแชทที่เปิดด้วย selected_item_id - อาจยังไม่มีแชทกับเพจนี้
                        selected_item_id = mapping.get("__initial_selected_item_id") or mapping.get("__initial_selected_item_ids", {}).get(page_name)
                        print(f"⚠️ ไม่พบแชทที่เปิดด้วย selected_item_id ({selected_item_id}) สำหรับเพจ '{page_name}'")
                        print(f"   💡 กรุณาใช้ Facebook ชื่อ \"ເພັດເມືອງໄຊ ດາໜູພັນ\" ทักไปหาเพจ '{page_name}' เพื่อสร้างแชทก่อน")
                        print(f"   📝 หลังจากทักแล้ว ให้รัน script อีกครั้ง")
                        return False
            
            print(f"   ⏱️ ขั้นตรวจสอบล็อกอิน + เปิด Inbox รวม: {_fmt_elapsed(time.time() - t_check_login)}")
            
            # เปิด Inbox และค้นหา Order -- ข้ามการ navigate ซ้ำ (อยู่ในหน้า Inbox อยู่แล้ว!)
            t_before_open = time.time()
            open_success, _ = open_inbox_and_search_order(page, inbox_url, order_id, skip_navigate=True)
            if not open_success:
                return False
            t_after_open = time.time()
            open_time = t_after_open - t_before_open
            
            # ส่งข้อความและรูป (send_message_with_image จะหา ช่องพิมพ์ + ปุ่มส่ง เอง — ไม่ต้องตรวจล่วงหน้า)
            t_before_send = time.time()
            print(f"\n{'='*60}")
            print(f"📤 เริ่มส่งบิลสำหรับ Order {order_id}")
            print(f"{'='*60}")
            success = send_message_with_image(page, tracking_id, image_path, dry_run=False, carrier=carrier)
            
            overall_elapsed = time.time() - overall_start
            print(f"\n{'='*60}")
            if success:
                print(f"✅ ส่งบิลสำเร็จสำหรับ Order {order_id}")
            else:
                print(f"❌ ส่งบิลไม่สำเร็จสำหรับ Order {order_id}")
            print(f"⏱️ เวลารวมทั้งหมด: {_fmt_elapsed(overall_elapsed)}")
            if not success:
                print("   กรุณาตรวจสอบ:")
                print("   1. เปิดแชทสำเร็จหรือไม่")
                print("   2. มีช่องพิมพ์ข้อความหรือไม่")
                print("   3. มีปุ่มส่งหรือไม่")
            print(f"{'='*60}\n")
            
            return success
        
        finally:
            # เก็บเบราว์เซอร์ไว้เปิดเพื่อดูผลลัพธ์ (หรือปิดได้ถ้าต้องการ)
            if not dry_run:
                if sys.stdin.isatty():
                    print("⏸️ กด Enter เพื่อปิดเบราว์เซอร์...")
                    input()
                else:
                    print("⏸️ รันแบบไม่ interactive — รอ 5 วินาทีแล้วปิดเบราว์เซอร์...")
                    time.sleep(5)
            # ปิด context (ถ้าใช้ launch_persistent_context จะปิด browser ด้วย)
            if user_data_dir:
                context.close()
            else:
                browser.close()

def send_bill_from_rows(
    rows: List[Tuple[str, str, str, str]],
    bills_dir: Path,
    user_data_dir: Optional[Path] = None,
    dry_run: bool = False,
    notify_mode: Optional[str] = None,
    customer_name_map: Optional[dict] = None,
    phone_map: Optional[dict] = None,
) -> List[Tuple[str, str]]:
    """ส่งจากรายการ (order_id, page_name, tracking_id, carrier) หรือ (order_id, page_name, sheet_name, carrier) เมื่อโหมดแจ้งแบบ text-only"""
    run_start = time.time()
    is_notify_mode, notify_label, notify_message = _resolve_notify_mode(notify_mode)
    from collections import defaultdict
    mapping = load_page_name_to_id()
    grouped_by_page: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    skipped_unknown: dict[str, int] = defaultdict(int)
    for order_id, page_name, third, carrier in rows:
        if _is_whatsapp_page(page_name) or get_page_id(page_name, mapping):
            grouped_by_page[page_name].append((order_id, third, carrier))
        else:
            skipped_unknown[page_name] += 1

    if skipped_unknown:
        skipped_n = sum(skipped_unknown.values())
        print(
            f"⏭️ ข้าม {skipped_n} รายการ จากเพจที่ไม่มีใน Settings (ไม่ใช้ในโปรเจกต์นี้):"
        )
        for name, n in skipped_unknown.items():
            print(f"   - {name}: {n} รายการ")

    skipped_no_image: dict[str, int] = defaultdict(int)
    if not is_notify_mode:
        kept: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for page_name, orders in grouped_by_page.items():
            for order_id, tracking_id, carrier in orders:
                if find_bill_image(bills_dir, tracking_id):
                    kept[page_name].append((order_id, tracking_id, carrier))
                else:
                    skipped_no_image[page_name] += 1
                    print(
                        f"❌ ไม่พบรูปบิล — ไม่ส่ง Order {order_id} tracking={tracking_id} (เพจ {page_name})"
                    )
        grouped_by_page = kept
        if skipped_no_image:
            print(
                f"⏭️ ไม่ส่ง {sum(skipped_no_image.values())} รายการ เพราะไม่พบรูปบิล"
            )

    if not grouped_by_page:
        print(f"ไม่พบรายการที่จะ{notify_label} (เพจใน Settings และมีรูปบิล) — ไม่เปิดเบราว์เซอร์")
        return []

    total_pages = len(grouped_by_page)
    total_orders = sum(len(v) for v in grouped_by_page.values())

    print(f"พบ {total_orders} รายการที่จะ{notify_label} (จาก {total_pages} เพจ)")
    for page_name, orders in grouped_by_page.items():
        print(f"   เพจ '{page_name}': {len(orders)} รายการ")
    print()
    
    success_count = 0
    fail_count = 0
    wa_skipped_no_whatsapp = 0
    wa_skipped_search_not_found = 0
    per_order_times: list = []
    successful_sends: List[Tuple[str, str]] = []
    
    with sync_playwright() as p:
        t_browser = time.time()
        if user_data_dir:
            user_data_dir.mkdir(parents=True, exist_ok=True)
            print(f"📂 ใช้ browser profile จาก: {user_data_dir}")
            print("   (session จะคงอยู่เหมือน browser ปกติ — ไม่ต้องล็อกอินทุกครั้ง)")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                channel="chrome",
                headless=False,
                viewport={"width": 1600, "height": 1000},
                permissions=["clipboard-read", "clipboard-write"],
                args=STEALTH_CHROME_ARGS,
                ignore_default_args=["--enable-automation", "--enable-blink-features=IdleDetection"],
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                color_scheme="light",
            )
            context.add_init_script(STEALTH_INIT_SCRIPT)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_viewport_size({"width": 1600, "height": 1000})
        else:
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=STEALTH_CHROME_ARGS,
                ignore_default_args=["--enable-automation", "--enable-blink-features=IdleDetection"],
            )
            context = browser.new_context(
                viewport={"width": 1600, "height": 1000},
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                color_scheme="light",
            )
            context.add_init_script(STEALTH_INIT_SCRIPT)
            page = context.new_page()
            page.set_viewport_size({"width": 1600, "height": 1000})
        browser_time = time.time() - t_browser
        print(f"   ⏱️ เปิดเบราว์เซอร์: {_fmt_elapsed(browser_time)}")

        # ตรวจสอบว่ายังล็อกอินอยู่หรือไม่ (ใช้ page_id ของเพจแรกที่ไม่ใช่ WhatsApp)
        mapping = load_page_name_to_id()
        business_page_names = get_business_page_names(mapping)
        first_page_name = None
        first_page_id = None
        for _pn in grouped_by_page.keys():
            if _is_whatsapp_page(_pn):
                continue
            _pid = get_page_id(_pn, mapping)
            if _pid:
                first_page_name = _pn
                first_page_id = _pid
                break
        if first_page_name and mapping:
            if first_page_id:
                # ใช้ get_initial_inbox_url เพื่อเปิดแชทด้วย selected_item_id (ไม่เปิดแชทล่าสุด)
                inbox_url = get_initial_inbox_url(first_page_name, first_page_id, business_page_names, mapping)

                # ใช้ domcontentloaded เพื่อให้หน้าโหลดเสร็จก่อน — ลดการกระตุกของ UI

                page.goto(inbox_url, wait_until="domcontentloaded", timeout=ui_selectors.PAGE_LOAD_TIMEOUT * 1000)

                t_wait_ready = time.time()
                login_or_ready = False
                # ใช้ wait_for_load_state เพื่อรอให้หน้าโหลดเสร็จก่อน — ลดการกระตุก
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=3000)
                except:
                    pass
                # ตรวจสอบสถานะหลังจากหน้าโหลดเสร็จแล้ว
                for _ in range(30):  # ลดจาก 60 เป็น 30 iterations (3s แทน 6s) เพราะหน้าโหลดเสร็จแล้ว
                    current_url = page.url
                    if "login" in current_url.lower() or page.query_selector('input[type="password"], input[name="pass"]'):
                        login_or_ready = True
                        break
                    if page.query_selector(ui_selectors.SEARCH_INPUT_SELECTOR):
                        login_or_ready = True
                        break
                    time.sleep(0.1)
                current_url = page.url
                if "login" in current_url.lower() or page.query_selector('input[type="password"], input[name="pass"]'):
                    print("⚠️ ยังไม่ล็อกอิน — กรุณาล็อกอิน Facebook ในเบราว์เซอร์ที่เปิดขึ้นมา")
                    print("   💡 Session จะถูกบันทึกอัตโนมัติใน browser profile — ไม่ต้องล็อกอินอีกครั้ง")
                    if sys.stdin.isatty():
                        print("   หลังจากล็อกอินแล้ว กด Enter เพื่อดำเนินการต่อ...")
                        input()
                    else:
                        print("   รอให้ล็อกอิน (สูงสุด 120 วินาที)...")
                        for _ in range(120):
                            time.sleep(1)
                            if page.query_selector(ui_selectors.SEARCH_INPUT_SELECTOR):
                                break
                
                # ตรวจสอบว่าแชทที่เปิดด้วย selected_item_id มีอยู่จริงหรือไม่ (error handling)
                # ข้าม check นี้สำหรับ business pages เพราะไม่ใช้ selected_item_id
                if first_page_name not in business_page_names:
                    # รอให้หน้าโหลดเสร็จก่อนตรวจสอบ
                    try:
                        page.wait_for_selector(ui_selectors.SEARCH_INPUT_SELECTOR, timeout=5000)
                    except:
                        pass
                    
                    # ตรวจสอบว่าแชทเปิดสำเร็จ (มี message input) หรือไม่
                    chat_opened = False
                    try:
                        message_input = page.query_selector(ui_selectors.MESSAGE_INPUT_SELECTOR)
                        if message_input:
                            chat_opened = True
                    except:
                        pass
                    
                    if not chat_opened:
                        # ไม่พบแชทที่เปิดด้วย selected_item_id - อาจยังไม่มีแชทกับเพจนี้
                        selected_item_id = mapping.get("__initial_selected_item_id") or mapping.get("__initial_selected_item_ids", {}).get(first_page_name)
                        print(f"⚠️ ไม่พบแชทที่เปิดด้วย selected_item_id ({selected_item_id}) สำหรับเพจ '{first_page_name}'")
                        print(f"   💡 กรุณาใช้ Facebook ชื่อ \"ເພັດເມືອງໄຊ ດາໜູພັນ\" ทักไปหาเพจ '{first_page_name}' เพื่อสร้างแชทก่อน")
                        print(f"   📝 หลังจากทักแล้ว ให้รัน script อีกครั้ง")
                        # ไม่ return False ที่นี่ เพราะอาจเป็นเพจแรกที่ยังไม่ได้ process order - ให้ continue ไปก่อน
        
        mapping = load_page_name_to_id()
        # ค่า delay จาก config (ลดความเสี่ยง automation) — หน่วยวินาที
        delay_order_min = float(mapping.get("__delay_between_orders_min", 1))
        delay_order_max = float(mapping.get("__delay_between_orders_max", 3))
        # ระหว่างเพจ: default 5–15 วินาที
        delay_between_pages_min = float(mapping.get("__delay_between_pages_min_sec", 1))
        delay_between_pages_max = float(mapping.get("__delay_between_pages_max_sec", 3))

        try:
            page_idx = 0
            for page_name, orders_in_page in grouped_by_page.items():
                page_idx += 1

                t_before_page = time.time()


                is_wa = _is_whatsapp_page(page_name)
                page_id = None if is_wa else get_page_id(page_name, mapping)
                if not is_wa and not page_id:
                    continue

                print(f"\n{'='*60}")
                if is_wa:
                    print(f"📱 [{page_idx}/{total_pages}] WhatsApp ({len(orders_in_page)} รายการ)")
                else:
                    print(f"📄 [{page_idx}/{total_pages}] เพจ: {page_name} ({len(orders_in_page)} รายการ)")
                print(f"{'='*60}")
                
                # --- WhatsApp flow (search Order ID แชทเดิมก่อนส่ง — กัน cold message) ---
                if is_wa:
                    if not dry_run:
                        if not _wa_ensure_home(page):
                            print("   ❌ WhatsApp Web ไม่พร้อม — ข้ามทุกแถว WhatsApp")
                            for order_id, _, __ in orders_in_page:
                                fail_count += 1
                            continue

                    order_idx = 0
                    for order_id, order_key, carrier in orders_in_page:
                        order_idx += 1
                        order_start = time.time()
                        phone = (phone_map or {}).get(order_id, "")

                        if dry_run:
                            print(
                                f"[DRY-RUN] [{order_idx}/{len(orders_in_page)}] Order {order_id} → "
                                f"ค้นหา exact Order ID ใน WhatsApp แล้วส่ง"
                            )
                            success_count += 1
                            continue

                        print(f"\n{'='*60}")
                        print(f"📤 [{order_idx}/{len(orders_in_page)}] Order {order_id} → WhatsApp (ค้นหา Order ID)")
                        if phone:
                            try:
                                print(f"   📞 เบอร์ใน Sheet: {_normalize_phone_for_whatsapp(phone)}")
                            except Exception:
                                print(f"   📞 เบอร์ใน Sheet: {phone}")
                        print(f"{'='*60}")

                        if is_notify_mode:
                            wa_msg = notify_message
                            wa_image = None
                        else:
                            wa_msg = bill_tracking_customer_message(order_key, carrier)
                            wa_image = find_bill_image(bills_dir, order_key)
                            if wa_image:
                                print(f"   🖼️ พบรูปบิล: {wa_image}")
                            else:
                                print(f"   ⚠️ ไม่พบรูปบิล: bills_dir={bills_dir} (exists={bills_dir.is_dir() if bills_dir else False}), tracking={order_key}")

                        send_ok, wa_fail_reason = send_via_whatsapp(
                            page,
                            phone or "",
                            wa_msg,
                            image_path=wa_image,
                            dry_run=False,
                            order_id=str(order_id),
                            tracking_id=str(order_key),
                            already_on_home=True,
                        )
                        order_time = time.time() - order_start
                        if send_ok:
                            success_count += 1
                            successful_sends.append((order_id, order_key))
                            per_order_times.append((order_id, order_time, True))
                            print(f"✅ ส่งสำเร็จ: Order {order_id} (⏱️ {_fmt_elapsed(order_time)})")
                        else:
                            fail_count += 1
                            if wa_fail_reason == "no_whatsapp":
                                wa_skipped_no_whatsapp += 1
                            if wa_fail_reason in ("search_not_found", "no_prior_chat"):
                                wa_skipped_search_not_found += 1
                            per_order_times.append((order_id, order_time, False))
                            if wa_fail_reason in ("search_not_found", "no_prior_chat"):
                                print(f"⏭️ ข้าม (ไม่พบ Order ID ใน search): Order {order_id} (⏱️ {_fmt_elapsed(order_time)})")
                            elif wa_fail_reason == "no_whatsapp":
                                print(f"⏭️ ข้าม (ไม่มี WhatsApp): Order {order_id} (⏱️ {_fmt_elapsed(order_time)})")
                            else:
                                print(f"❌ ส่งไม่สำเร็จ: Order {order_id} (⏱️ {_fmt_elapsed(order_time)})")

                        if order_idx < len(orders_in_page) and not dry_run:
                            delay = random.uniform(delay_order_min, delay_order_max)
                            print(f"   ⏳ รอ {delay:.1f} วินาที ก่อน Order ถัดไป...")
                            time.sleep(delay)

                    if page_idx < total_pages and not dry_run:
                        delay_sec = random.uniform(delay_between_pages_min, delay_between_pages_max)
                        print(f"\n⏳ พัก {delay_sec:.0f} วินาที ก่อนเปลี่ยนเพจถัดไป...")
                        time.sleep(delay_sec)
                    continue
                
                # --- Facebook flow (เดิม) ---
                # Order แรกในเพจ: navigate ไปหน้า Inbox
                order_idx = 0
                for order_id, order_key, carrier in orders_in_page:
                    order_idx += 1
                    order_start = time.time()

                    if not is_notify_mode:
                        image_path = find_bill_image(bills_dir, order_key)
                    else:
                        image_path = None

                    if dry_run:
                        if is_notify_mode:
                            print(f"[DRY-RUN] [{order_idx}/{len(orders_in_page)}] Order {order_id} → เพจ {page_name} ({notify_label})")
                        else:
                            print(f"[DRY-RUN] [{order_idx}/{len(orders_in_page)}] Order {order_id} → เพจ {page_name} → Tracking {order_key} (carrier={carrier!r})")
                        success_count += 1
                        continue
                    
                    # Order แรกของเพจแรก: อยู่หน้า Inbox แล้ว (จาก login check), Order แรกของเพจอื่น: ต้อง navigate, Order ถัดไปในเพจเดียวกัน: skip_navigate=True
                    skip_nav = (page_idx == 1 and order_idx == 1) or (order_idx > 1)
                    skip_search_btn = order_idx > 1  # ปุ่ม "ค้นหาในการสนทนา" โผล่แค่ครั้งแรก ครั้งที่ 2 ขึ้นไปไม่กด
                    # ใช้ get_initial_inbox_url ทุกครั้ง (รวมเพจ 2 เป็นต้นไป) เพื่อให้เปิดแชท selected_item_id แทนแชทล่าสุด
                    inbox_url = get_initial_inbox_url(page_name, page_id, business_page_names, mapping)

                    t_before_open_inbox = time.time()

                    cust_name = (customer_name_map or {}).get(order_id, "")
                    open_inbox_result, open_inbox_reason = open_inbox_and_search_order(page, inbox_url, order_id, skip_navigate=skip_nav, skip_search_button=skip_search_btn, customer_name=cust_name)
                    if not open_inbox_result and open_inbox_reason in ("not_found", "no_results"):
                        print(f"   🔄 ลองค้นหา Order {order_id} อีกครั้ง...")
                        open_inbox_result, open_inbox_reason = open_inbox_and_search_order(page, inbox_url, order_id, skip_navigate=False, skip_search_button=False, customer_name=cust_name)

                    t_after_open_inbox = time.time()
                    open_inbox_time = t_after_open_inbox - t_before_open_inbox

                    if not open_inbox_result:

                        t_before_continue = time.time()

                        fail_count += 1
                        order_time_calc = time.time() - order_start


                        per_order_times.append((order_id, order_time_calc, False))
                        print(f"❌ ส่งไม่สำเร็จ: Order {order_id} (⏱️ {_fmt_elapsed(order_time_calc)})")

                        t_after_print = time.time()

                        continue
                    
                    # ส่งข้อความ (และรูปถ้าไม่ใช่โหมดແຈ້ງຮອດແລ້ວ)
                    t_before_print_send = time.time()
                    print(f"\n{'='*60}")
                    print(f"📤 [{order_idx}/{len(orders_in_page)}] Order {order_id} (เพจ: {page_name})")
                    print(f"{'='*60}")
                    t_after_print_send = time.time()

                    # === PRE-SEND VERIFICATION: ตรวจว่าแชทที่เปิดอยู่เป็นแชทที่ถูกต้อง ===
                    # ใช้ chat header name เป็นสัญญาณหลัก (URL selected_item_id ไม่น่าเชื่อถือ — เปลี่ยนก่อน DOM โหลดเสร็จ)
                    _header_before_send = ""
                    try:
                        _sig_presend = page.evaluate(_JS_CHAT_SIGNALS)
                        _header_before_send = _sig_presend.get("headerName", "") if isinstance(_sig_presend, dict) else ""
                    except Exception:
                        pass
                    print(f"   🔒 Pre-send check: header='{_header_before_send[:40]}'")

                    t_before_send_message = time.time()
                    if is_notify_mode:
                        send_ok = send_message_text_only(page, notify_message, dry_run=False)
                    else:
                        send_ok = send_message_with_image(page, order_key, image_path, dry_run=False, carrier=carrier)
                    if not send_ok:
                        print("   🔄 ลองส่งอีกครั้ง (ครั้งที่ 2)...")
                        if is_notify_mode:
                            send_ok = send_message_text_only(page, notify_message, dry_run=False)
                        else:
                            send_ok = send_message_with_image(page, order_key, image_path, dry_run=False, carrier=carrier)
                    if send_ok:
                        order_time = time.time() - order_start
                        success_count += 1
                        successful_sends.append((order_id, order_key))
                        per_order_times.append((order_id, order_time, True))
                        print(f"✅ ส่งสำเร็จ: Order {order_id} (⏱️ {_fmt_elapsed(order_time)})")

                    else:
                        order_time = time.time() - order_start
                        fail_count += 1
                        per_order_times.append((order_id, order_time, False))
                        print(f"❌ ส่งไม่สำเร็จ: Order {order_id} (⏱️ {_fmt_elapsed(order_time)})")

                    # รอระหว่าง Order ในเพจเดียวกัน (delay สุ่ม ลดความเสี่ยง automation)
                    if order_idx < len(orders_in_page) and not dry_run:
                        delay = random.uniform(delay_order_min, delay_order_max)
                        print(f"   ⏳ รอ {delay:.1f} วินาที ก่อน Order ถัดไป...")
                        time.sleep(delay)

                t_after_page = time.time()

                # พักระหว่างเพจ (delay สุ่ม ลดความเสี่ยง automation)
                if page_idx < total_pages and not dry_run:
                    delay_sec = random.uniform(delay_between_pages_min, delay_between_pages_max)
                    if delay_sec >= 60:
                        print(f"\n⏳ พัก {delay_sec / 60:.1f} นาที ก่อนเปลี่ยนเพจถัดไป...")
                    else:
                        print(f"\n⏳ พัก {delay_sec:.0f} วินาที ก่อนเปลี่ยนเพจถัดไป...")
                    time.sleep(delay_sec)

            csv_elapsed = time.time() - run_start
            print(f"\n{'='*60}")
            print(f"📊 สรุปผล{notify_label}")
            print(f"{'='*60}")
            print(f"   ส่งสำเร็จ: {success_count} รายการ")
            print(f"   ไม่สำเร็จ: {fail_count} รายการ")
            if wa_skipped_no_whatsapp:
                print(f"   ข้าม (เบอร์ไม่มี WhatsApp): {wa_skipped_no_whatsapp} รายการ")
            if wa_skipped_search_not_found:
                print(f"   ข้าม (ไม่พบ Order ID ใน search): {wa_skipped_search_not_found} รายการ")
            print(f"   ⏱️ เวลารวมทั้งหมด: {_fmt_elapsed(csv_elapsed)}")
            if per_order_times:
                times_only = [t for _, t, _ in per_order_times]
                avg_time = sum(times_only) / len(times_only)
                fastest = min(times_only)
                slowest = max(times_only)
                print(f"   ⏱️ เฉลี่ย/รายการ: {_fmt_elapsed(avg_time)}")
                print(f"   ⏱️ เร็วสุด: {_fmt_elapsed(fastest)}")
                print(f"   ⏱️ ช้าสุด: {_fmt_elapsed(slowest)}")
                print(f"\n   📋 รายละเอียดแต่ละ Order:")
                for oid, elapsed, ok in per_order_times:
                    status = "✅" if ok else "❌"
                    print(f"      {status} Order {oid}: {_fmt_elapsed(elapsed)}")
            print(f"{'='*60}")
        
        finally:
            if not dry_run:
                if sys.stdin.isatty():
                    print("⏸️ กด Enter เพื่อปิดเบราว์เซอร์...")
                    input()
                else:
                    time.sleep(3)
            if user_data_dir:
                context.close()
            else:
                browser.close()

    return successful_sends


def send_bill_from_csv(csv_path: str, bills_dir: Path, user_data_dir: Optional[Path] = None, dry_run: bool = False) -> None:
    """ส่งบิลจากไฟล์ CSV"""
    sys.path.insert(0, str(SCRIPT_DIR))
    from read_sheet import read_rows_from_csv
    rows = read_rows_from_csv(csv_path)
    if not rows:
        print("❌ ไม่พบข้อมูลใน CSV")
        return
    send_bill_from_rows(rows, bills_dir, user_data_dir, dry_run)


def send_bill_from_sheet(
    sheet_id: str,
    bills_dir: Path,
    user_data_dir: Optional[Path] = None,
    dry_run: bool = False,
    sheet_name: Optional[str] = None,
    sheet_names: Optional[List[str]] = None,
    credentials_path: Optional[str] = None,
    notify_delivered: bool = False,
    notify_stock_out: bool = False,
    notify_stock_available: bool = False,
) -> None:
    """ส่งบิลจาก Google Sheet โดยตรง (ต้องแชร์ Sheet ให้ Service Account แล้ว)
    ถ้า notify_delivered=True กรองคอลัมน์ A = 🏁ຮອດປາຍທາງແລ້ວ ຫຼື 💬ແຈ້ງຮອດແລ້ວ ส่งข้อความแจ้งถึง แล้วบันทึก Column V
    มิฉะนั้นกรอง ລໍຈັດສົ່ງ หลังส่งสำเร็จบันทึกวันที่ลง Column R
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    from read_sheet import (
        read_rows_from_google_sheet,
        batch_update_send_dates,
        batch_update_notified_delivered,
        NOTIFY_DELIVERED_STATUSES,
        NOTIFY_STOCK_OUT_STATUSES,
        NOTIFY_STOCK_AVAILABLE_STATUSES,
    )
    rows: List[Tuple[str, str, str, str]] = []
    row_map: dict = {}
    customer_name_map: dict = {}
    phone_map: dict = {}
    notify_mode = None
    required_status = None
    notify_result_value = "💬ແຈ້ງຮອດແລ້ວ"
    if notify_delivered:
        notify_mode = "delivered"
        required_status = NOTIFY_DELIVERED_STATUSES
        notify_result_value = "💬ແຈ້ງຮອດແລ້ວ"
    elif notify_stock_out:
        notify_mode = "stock_out"
        required_status = NOTIFY_STOCK_OUT_STATUSES
        notify_result_value = NOTIFY_STOCK_OUT_RESULT
    elif notify_stock_available:
        notify_mode = "stock_available"
        required_status = NOTIFY_STOCK_AVAILABLE_STATUSES
        notify_result_value = NOTIFY_STOCK_AVAILABLE_RESULT
    if sheet_names:
        for name in sheet_names:
            part = read_rows_from_google_sheet(
                sheet_id,
                sheet_name=name,
                credentials_path=credentials_path,
                row_map=row_map,
                required_status=required_status,
                customer_name_map=customer_name_map,
                phone_map=phone_map,
            )
            if part:
                print(f"   📄 ชีต '{name}': พบ {len(part)} รายการ")
            rows.extend(part)
    else:
        rows = read_rows_from_google_sheet(
            sheet_id,
            sheet_name=sheet_name or "Sheet1",
            credentials_path=credentials_path,
            row_map=row_map,
            required_status=required_status,
            customer_name_map=customer_name_map,
            phone_map=phone_map,
        )
    if not rows:
        print("❌ ไม่พบข้อมูลใน Google Sheet (ตรวจสอบ Sheet ID การแชร์ให้ Service Account และชื่อชีต)")
        return
    if phone_map:
        print(f"📱 พบ {len(phone_map)} รายการ WhatsApp")
    if sheet_names:
        print(f"📋 รวมจาก {len(sheet_names)} ชีต: {len(rows)} รายการ\n")
    successful_sends = send_bill_from_rows(
        rows,
        bills_dir,
        user_data_dir,
        dry_run,
        notify_mode=notify_mode,
        customer_name_map=customer_name_map,
        phone_map=phone_map,
    )

    if successful_sends and row_map and not dry_run:
        if notify_mode:
            updates = []
            for oid, sn in successful_sends:
                info = row_map.get((oid, sn))
                if info:
                    _, row_num = info
                    updates.append((sn, row_num))
            if updates:
                print(f"\n📅 บันทึกผลแจ้งลง Column V ({len(updates)} รายการ)...")
                batch_update_notified_delivered(sheet_id, updates, credentials_path, value=notify_result_value)
        else:
            from datetime import datetime
            now = datetime.now()
            date_str = f"{now.day}/{now.month}/{now.year}"
            updates = []
            for oid, tid in successful_sends:
                info = row_map.get((oid, tid))
                if info:
                    sn, row_num = info
                    updates.append((sn, row_num, date_str))
            if updates:
                print(f"\n📅 บันทึกวันที่ส่ง ({date_str}) ลง Column R ({len(updates)} รายการ)...")
                batch_update_send_dates(sheet_id, updates, credentials_path)


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    notify_delivered = "--notify-delivered" in args
    args = [a for a in args if a != "--notify-delivered"]
    notify_stock_out = "--notify-stock-out" in args
    args = [a for a in args if a != "--notify-stock-out"]
    notify_stock_available = "--notify-stock-available" in args
    args = [a for a in args if a != "--notify-stock-available"]
    notify_modes_count = int(notify_delivered) + int(notify_stock_out) + int(notify_stock_available)
    if notify_modes_count > 1:
        print("❌ เลือกได้เพียงโหมดแจ้งเดียว: --notify-delivered หรือ --notify-stock-out หรือ --notify-stock-available")
        sys.exit(1)
    carrier_cli = ""
    if "--carrier" in args:
        ci = args.index("--carrier")
        if ci + 1 < len(args) and not args[ci + 1].startswith("--"):
            carrier_cli = args[ci + 1]
            args = [a for j, a in enumerate(args) if j not in (ci, ci + 1)]
        else:
            args = [a for j, a in enumerate(args) if j != ci]

    bills_dir = DEFAULT_BILLS_DIR
    if "--bills-dir" in args:
        i = args.index("--bills-dir")
        if i + 1 < len(args):
            bills_dir = Path(args[i + 1])
        args = [a for a in args if a != "--bills-dir" and args.index(a) != i + 1]
    
    # User data directory (สำหรับเก็บ browser profile - ทำให้ session คงอยู่เหมือน browser ปกติ)
    user_data_dir = None
    if "--user-data-dir" in args:
        i = args.index("--user-data-dir")
        if i + 1 < len(args):
            user_data_dir = Path(args[i + 1])
        args = [a for a in args if a != "--user-data-dir" and args.index(a) != i + 1]
    else:
        user_data_dir = _resolve_facebook_user_data_dir()
    
    if "--csv" in args:
        i = args.index("--csv")
        if i + 1 < len(args):
            csv_path = args[i + 1]
            send_bill_from_csv(csv_path, bills_dir, user_data_dir, dry_run)
        else:
            print("❌ ต้องระบุ path ของ CSV หลัง --csv")
            sys.exit(1)
    elif "--sheet" in args:
        i = args.index("--sheet")
        sheet_id = None
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            sheet_id = args[i + 1]
        if not sheet_id:
            # โหลดจาก config ถ้ามี
            sheet_config_path = CONFIG_DIR / "sheet_config.json"
            if sheet_config_path.exists():
                try:
                    with open(sheet_config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    sheet_id = cfg.get("sheet_id") or cfg.get("sheet_ID")
                except Exception:
                    pass
        if not sheet_id:
            print("❌ ต้องระบุ Sheet ID หลัง --sheet หรือใส่ sheet_id ใน config/sheet_config.json")
            sys.exit(1)
        sheet_name = "Sheet1"
        sheet_names = None
        credentials_path = None
        if "--sheet-name" in args:
            j = args.index("--sheet-name")
            if j + 1 < len(args):
                sheet_name = args[j + 1]
        if "--credentials" in args:
            k = args.index("--credentials")
            if k + 1 < len(args):
                credentials_path = args[k + 1]
        sheet_config_path = CONFIG_DIR / "sheet_config.json"
        if sheet_config_path.exists():
            try:
                with open(sheet_config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                if not credentials_path:
                    cp = cfg.get("credentials_path")
                    if cp and not os.path.isabs(cp):
                        credentials_path = str(CONFIG_DIR.parent / cp)
                    else:
                        credentials_path = cp
                if cfg.get("sheet_names"):
                    sheet_names = cfg["sheet_names"]
                elif not sheet_name or sheet_name == "Sheet1":
                    sheet_name = cfg.get("sheet_name", "Sheet1")
            except Exception:
                pass
        send_bill_from_sheet(
            sheet_id,
            bills_dir,
            user_data_dir,
            dry_run,
            sheet_name=sheet_name,
            sheet_names=sheet_names,
            credentials_path=credentials_path,
            notify_delivered=notify_delivered,
            notify_stock_out=notify_stock_out,
            notify_stock_available=notify_stock_available,
        )
    elif len(args) >= 3:
        order_id, page_name, tracking_id = args[0], args[1], args[2]
        success = send_bill_single(
            order_id, page_name, tracking_id, bills_dir, user_data_dir, dry_run, carrier=carrier_cli
        )
        sys.exit(0 if success else 1)
    else:
        print("ใช้:")
        print("  python3 open_inbox_and_send.py <order_id> <page_name> <tracking_id> [--carrier ຮຸ່ງອາລຸນ] [--bills-dir ...] [--dry-run]")
        print("  python3 open_inbox_and_send.py --csv <path_to_csv> [--bills-dir ...] [--dry-run]")
        print("  python3 open_inbox_and_send.py --sheet [sheet_id] [--sheet-name Sheet1] [--credentials path] [--dry-run]")
        print("")
        print("  --carrier: ขนส่งสำหรับโหมด 3 args (เช่ນ ຮຸ່ງອາລຸນ → ลิงก์ halexpress.la; ค่าเริ่มต้น Anousith)")
        print("  --sheet: อ่านรายการจาก Google Sheet (ใส่ sheet_id หรือใช้จาก config/sheet_config.json)")
        print("  --notify-delivered: โหมดແຈ້ງຮອດແລ້ວ (คอลัมน์ A = 🏁ຮອດປາຍທາງແລ້ວ ຫຼື 💬ແຈ້ງຮອດແລ້ວ — ส่งข้อความแจ้งถึง บันทึก Column V)")
        print("  --notify-stock-out: โหมดແຈ້ງສິນຄ້າໝົດ (คอลัมน์ A = 🗑️ໝົດ หรือ ⏳ລໍສິນຄ້າ — ส่งข้อความแจ้งสินค้าหมด บันทึก Column V)")
        print("  --notify-stock-available: โหมดແຈ້ງມີສິນຄ້າ (คอลัมน์ A = 📢ແຈ້ງສິນຄ້າໝົດແລ້ວ — ส่งข้อความแจ้งมีสินค้า บันทึก Column V)")
        print("  --user-data-dir: โฟลเดอร์เก็บ browser profile (ค่าเริ่มต้น: browser_profile/)")
        sys.exit(1)

if __name__ == "__main__":
    main()
