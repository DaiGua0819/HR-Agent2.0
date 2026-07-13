"""BOSS conversation row lookup and precise mouse click helpers."""

from __future__ import annotations

from app.browser.base import BrowserElement, BrowserPage
from app.browser.reliable_support import VerifyCallback, record_result, result_dict
from app.platforms.boss import selectors
from app.platforms.boss.interaction import boss_click_conversation_row

SAFE_ROW_TARGET_SELECTORS = (".geek-name", ".geek-info", ".geek-item-main")
STABLE_ROW_SELECTOR = ":is(.geek-item, .user-list-item, .user-item)"
ROW_CLICK_ATTEMPTS = 2


class _LocatorElement:
    def __init__(self, locator: object) -> None:
        self.locator = locator

    async def click(self, timeout_ms: int | None = None) -> None:
        kwargs = {"timeout": timeout_ms} if timeout_ms is not None else {}
        await self.locator.click(**kwargs)

    async def text(self) -> str:
        return str(await self.locator.inner_text())

    async def attr(self, name: str) -> str | None:
        return await self.locator.get_attribute(name)


async def find_row_for_state(
    page: BrowserPage,
    state: dict[str, object],
) -> BrowserElement | None:
    """Find a visible BOSS conversation row from a captured unread row state."""

    row_id = str(state.get("id") or "")
    row_id_norm = row_id.lstrip("_")
    label = str(state.get("label") or "").strip()
    expected_name = str(state.get("name") or "").strip()
    expected_position = str(state.get("position") or "").strip()

    if row_id_norm:
        stable = await _stable_row_for_id(page, row_id)
        if stable is not None:
            return stable
        rows = await page.query_all(selectors.SESSION_ITEM)
        for row in rows:
            current_ids = {
                str(await row.attr(name) or "").lstrip("_")
                for name in ("id", "data-id", "data-uid")
            }
            if row_id_norm in current_ids:
                return row
        return None
    rows = await page.query_all(selectors.SESSION_ITEM)
    if label:
        for row in rows:
            if (await row.text()).strip() == label:
                return row
    if expected_name:
        matches: list[BrowserElement] = []
        for row in rows:
            text = (await row.text()).strip()
            if expected_name in text and (not expected_position or expected_position in text):
                matches.append(row)
        if len(matches) == 1:
            return matches[0]
    return None


async def click_row_state(
    page: BrowserPage,
    state: dict[str, object],
    *,
    label: str = "BOSS候选人会话",
    verify: VerifyCallback | None = None,
) -> dict[str, object]:
    """Open a BOSS row and verify the target conversation became active."""

    row_attempts: list[dict[str, object]] = []
    last_result: dict[str, object] = {}
    for attempt in range(1, ROW_CLICK_ATTEMPTS + 1):
        row = await find_row_for_state(page, state)
        if row is None:
            last_result = result_dict(False, "click_element", label, reason="row_not_found")
            row_attempts.append({"attempt": attempt, "result": last_result})
            break
        target, target_source = await _safe_row_click_target(row)
        result = await boss_click_conversation_row(page, target, label=label, verify=verify)
        last_result = {**result, "targetSource": target_source}
        row_attempts.append(
            {"attempt": attempt, "targetSource": target_source, "result": last_result}
        )
        if result.get("ok"):
            return {**last_result, "rowAttempts": row_attempts}

    final = {
        **last_result,
        "ok": False,
        "reason": last_result.get("reason") or "row_click_not_verified",
        "rowAttempts": row_attempts,
    }
    record_result(page, final)
    return final


async def _safe_row_click_target(
    row: BrowserElement,
) -> tuple[BrowserElement | _LocatorElement, str]:
    locator = getattr(row, "locator", None)
    if locator is None or not hasattr(locator, "locator"):
        return row, "row"
    for selector in SAFE_ROW_TARGET_SELECTORS:
        try:
            child = locator.locator(selector).first
            if await child.count() > 0 and await child.is_visible():
                return _LocatorElement(child), selector
        except Exception:
            continue
    return row, "row"


async def _stable_row_for_id(page: BrowserPage, row_id: str) -> _LocatorElement | None:
    raw_page = getattr(page, "page", None)
    if raw_page is None or not hasattr(raw_page, "locator"):
        return None
    normalized = str(row_id or "").strip().lstrip("_")
    if not normalized:
        return None
    values = (f"_{normalized}", normalized)
    selectors_by_id = [
        f'{STABLE_ROW_SELECTOR}[{attribute}="{_css_attr_value(value)}"]'
        for attribute in ("id", "data-id", "data-uid")
        for value in values
    ]
    locator = raw_page.locator(", ".join(selectors_by_id)).first
    try:
        if await locator.count() > 0 and await locator.is_visible():
            return _LocatorElement(locator)
    except Exception:
        return None
    return None


def _css_attr_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
