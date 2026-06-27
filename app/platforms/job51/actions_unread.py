"""51job 未读筛选刷新动作。

51job 的“未读”是复选框语义。处理前必须先看当前是否已勾选：
已勾选时先取消、等待 1 秒、再勾选刷新；未勾选时只勾选一次。
"""

from __future__ import annotations

import asyncio

from app.browser.base import BrowserPage
from app.browser.reliable_actions import reliable_click
from app.platforms.job51 import selectors
from app.platforms.job51.dom_scripts import CLICK_UNREAD_FILTER_JS, UNREAD_FILTER_STATE_JS


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """刷新并切换 51job 未读筛选。"""

    before = await _unread_filter_state(page)
    actions: list[dict[str, object]] = []
    if before.get("active"):
        off_click = await _click_unread_filter_once(
            page,
            label="51job未读筛选取消刷新",
            expect_active=False,
        )
        actions.append({"step": "uncheck_for_refresh", "click": off_click})
    on_click = await _click_unread_filter_once(
        page,
        label="51job未读筛选勾选",
        expect_active=True,
    )
    actions.append({"step": "check_unread", "click": on_click})
    state = await _unread_filter_state(page)
    return {
        "selected": bool(state.get("active")),
        "refreshed": bool(before.get("active")),
        "selector": selectors.UNREAD_FILTER,
        "before": before,
        "state": state,
        "actions": actions,
    }


async def _click_unread_filter_once(
    page: BrowserPage,
    *,
    label: str,
    expect_active: bool,
) -> dict[str, object]:
    clicked = await _safe_eval_dict(page, CLICK_UNREAD_FILTER_JS)
    if clicked.get("selected"):
        await asyncio.sleep(1)
        state = await _unread_filter_state(page)
        return {
            "ok": bool(state.get("active")) == expect_active,
            "method": "dom_script",
            "state": state,
            **clicked,
        }
    verify = _verify_unread_active if expect_active else _verify_unread_inactive
    result = await reliable_click(
        page,
        selectors.UNREAD_FILTER,
        label=label,
        verify=lambda: verify(page),
    )
    await asyncio.sleep(1)
    return result


async def _verify_unread_active(page: BrowserPage) -> dict[str, object]:
    state = await _unread_filter_state(page)
    return {
        "verified": bool(state.get("active")),
        "reason": "" if state.get("active") else "unread_filter_not_active",
        "state": state,
    }


async def _verify_unread_inactive(page: BrowserPage) -> dict[str, object]:
    state = await _unread_filter_state(page)
    return {
        "verified": not bool(state.get("active")),
        "reason": "" if not state.get("active") else "unread_filter_still_active",
        "state": state,
    }


async def _unread_filter_state(page: BrowserPage) -> dict[str, object]:
    if bool(getattr(page, "unread_selected", False)):
        return {"active": True, "label": "未读", "source": "fake_page"}
    raw = await _safe_eval_dict(page, "job51.unread_filter_state")
    if not raw:
        raw = await _safe_eval_dict(page, UNREAD_FILTER_STATE_JS)
    return raw if raw else {"active": False, "reason": "unread_state_unknown"}


async def _safe_eval_dict(
    page: BrowserPage, script: str, arg: object | None = None
) -> dict[str, object]:
    try:
        value = await page.eval_js(script, arg)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
