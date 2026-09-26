# -*- coding: utf-8 -*-
"""Open Playwright Chromium with a persistent profile for first-time login."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional, Tuple

FACEBOOK_INBOX_URL = "https://business.facebook.com/latest/inbox/all/"
HAL_LOGIN_URL = "https://www.halexpress.la/login"
WHATSAPP_WEB_URL = "https://web.whatsapp.com/"

_DEFAULT_W = 1400
_DEFAULT_H = 900


def _alive_pages(context) -> bool:
    """Return True if the context still has at least one responsive page.

    On Windows persistent profiles, closing the Chromium window often leaves
    page objects with is_closed() == False even though the target is gone.
    """
    try:
        pages = context.pages
    except Exception:
        return False
    if not pages:
        return False
    for page in pages:
        if page.is_closed():
            continue
        try:
            page.evaluate("() => true", timeout=1500)
            return True
        except Exception:
            continue
    return False


def _join_timeout(fn, timeout_sec: float) -> None:
    worker = threading.Thread(target=fn, daemon=True)
    worker.start()
    worker.join(timeout_sec)


def move_browser_window(
    page,
    position: Tuple[int, int],
    *,
    width: int = _DEFAULT_W,
    height: int = _DEFAULT_H,
) -> None:
    """Force Chrome window bounds via CDP (overrides restored profile position)."""
    try:
        x, y = int(position[0]), int(position[1])
    except (TypeError, ValueError, IndexError):
        return
    try:
        session = page.context.new_cdp_session(page)
        info = session.send("Browser.getWindowForTarget")
        window_id = info.get("windowId")
        if window_id is None:
            return
        session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window_id,
                "bounds": {
                    "left": x,
                    "top": y,
                    "width": int(width),
                    "height": int(height),
                    "windowState": "normal",
                },
            },
        )
    except Exception:
        pass


def open_persistent_login(
    user_data_dir: Path,
    start_url: str,
    window_position: Optional[Tuple[int, int]] = None,
) -> None:
    """Launch Chromium with user_data_dir, open start_url, wait until user closes it.

    Must not be called on the Tk UI thread — context.close() can hang on Windows.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "ต้องติดตั้ง Playwright ก่อน: pip install playwright && playwright install chromium"
        ) from e

    profile = Path(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)
    url = (start_url or "").strip() or "about:blank"

    launch_args: list[str] = [f"--window-size={_DEFAULT_W},{_DEFAULT_H}"]
    if window_position is not None:
        x, y = window_position
        launch_args.append(f"--window-position={int(x)},{int(y)}")

    playwright = sync_playwright().start()
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            viewport={"width": _DEFAULT_W, "height": _DEFAULT_H},
            args=launch_args,
        )
        page = context.pages[0] if context.pages else context.new_page()
        if window_position is not None:
            move_browser_window(page, window_position)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        except Exception:
            pass
        if window_position is not None:
            # Profile restore can re-apply after first navigation.
            move_browser_window(page, window_position)

        while _alive_pages(context):
            try:
                browser = context.browser
                if browser is not None and not browser.is_connected():
                    break
            except Exception:
                break
            time.sleep(0.3)
    finally:

        def _stop() -> None:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            try:
                playwright.stop()
            except Exception:
                pass

        # Never block forever: Windows persistent-context teardown can hang.
        _join_timeout(_stop, 8.0)
