# -*- coding: utf-8 -*-
"""Open Playwright Chromium with a persistent profile for first-time login."""
from __future__ import annotations

import threading
import time
from pathlib import Path

FACEBOOK_INBOX_URL = "https://business.facebook.com/latest/inbox/all/"
HAL_LOGIN_URL = "https://www.halexpress.la/login"


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


def open_persistent_login(user_data_dir: Path, start_url: str) -> None:
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

    playwright = sync_playwright().start()
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        except Exception:
            pass

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
