"""
Shared Playwright navigation with automatic fallback:
networkidle (fast when it works) -> domcontentloaded + ready selector on timeout.
No .env flags required.
"""
from __future__ import annotations

ANOUSITH_PRIMARY_TIMEOUT_MS = 30_000
HAL_PRIMARY_TIMEOUT_MS = 45_000
FALLBACK_TIMEOUT_MS = 90_000
READY_WAIT_MS = 20_000

ANOUSITH_READY_SELECTOR = (
    "input[type=password], div:has-text('ແຊຣບິນ'), div:has-text('ເລກບິນ')"
)
HAL_LOGIN_READY_SELECTOR = (
    "input[type=password], button[type=submit], input[type=submit]"
)
HAL_LIST_READY_SELECTOR = "table tr, table td"


def _is_timeout(exc: BaseException) -> bool:
    return type(exc).__name__ == "TimeoutError" or "Timeout" in str(exc)


def _page_hint(url: str) -> str:
    idx = url.rfind("page=")
    return url[idx : idx + 12] if idx >= 0 else ""


async def _wait_ready_async(page, selector: str, timeout_ms: int = READY_WAIT_MS) -> None:
    try:
        await page.wait_for_selector(selector, timeout=timeout_ms)
    except Exception:
        await page.wait_for_timeout(3000)


def _wait_ready_sync(page, selector: str, timeout_ms: int = READY_WAIT_MS) -> None:
    try:
        page.wait_for_selector(selector, timeout=timeout_ms)
    except Exception:
        page.wait_for_timeout(3000)


async def _goto_with_fallback_async(
    page,
    url: str,
    *,
    primary_ms: int,
    fallback_ms: int,
    ready_selector: str,
    label: str,
) -> None:
    hint = _page_hint(url)
    try:
        await page.goto(url, wait_until="networkidle", timeout=primary_ms)
    except Exception as exc:
        if not _is_timeout(exc):
            raise
        print(
            f"   ℹ️ {label}: networkidle timeout → domcontentloaded "
            f"({hint or url[:60]})"
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=fallback_ms)
        await _wait_ready_async(page, ready_selector)


def _goto_with_fallback_sync(
    page,
    url: str,
    *,
    primary_ms: int,
    fallback_ms: int,
    ready_selector: str,
    label: str,
) -> None:
    hint = _page_hint(url)
    try:
        page.goto(url, wait_until="networkidle", timeout=primary_ms)
    except Exception as exc:
        if not _is_timeout(exc):
            raise
        print(
            f"   ℹ️ {label}: networkidle timeout → domcontentloaded "
            f"({hint or url[:60]})"
        )
        page.goto(url, wait_until="domcontentloaded", timeout=fallback_ms)
        _wait_ready_sync(page, ready_selector)


async def goto_anousith_bill_page(page, url: str) -> None:
    await _goto_with_fallback_async(
        page,
        url,
        primary_ms=ANOUSITH_PRIMARY_TIMEOUT_MS,
        fallback_ms=FALLBACK_TIMEOUT_MS,
        ready_selector=ANOUSITH_READY_SELECTOR,
        label="Anousith",
    )


def goto_anousith_bill_page_sync(page, url: str) -> None:
    _goto_with_fallback_sync(
        page,
        url,
        primary_ms=ANOUSITH_PRIMARY_TIMEOUT_MS,
        fallback_ms=FALLBACK_TIMEOUT_MS,
        ready_selector=ANOUSITH_READY_SELECTOR,
        label="Anousith",
    )


async def goto_hal_login_page(page, url: str) -> None:
    await _goto_with_fallback_async(
        page,
        url,
        primary_ms=HAL_PRIMARY_TIMEOUT_MS,
        fallback_ms=FALLBACK_TIMEOUT_MS,
        ready_selector=HAL_LOGIN_READY_SELECTOR,
        label="HAL login",
    )


async def goto_hal_list_page(page, url: str) -> None:
    await _goto_with_fallback_async(
        page,
        url,
        primary_ms=HAL_PRIMARY_TIMEOUT_MS,
        fallback_ms=FALLBACK_TIMEOUT_MS,
        ready_selector=HAL_LIST_READY_SELECTOR,
        label="HAL list",
    )


async def wait_hal_list_ready(page) -> None:
    """After pagination click: prefer networkidle, else ensure list table is present."""
    try:
        await page.wait_for_load_state("networkidle", timeout=HAL_PRIMARY_TIMEOUT_MS)
    except Exception as exc:
        if not _is_timeout(exc):
            return
        print("   ℹ️ HAL list: networkidle timeout → domcontentloaded")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=FALLBACK_TIMEOUT_MS)
        except Exception:
            pass
        await _wait_ready_async(page, HAL_LIST_READY_SELECTOR)
