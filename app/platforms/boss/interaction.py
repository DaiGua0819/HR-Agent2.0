"""BOSS-only precise mouse and incremental typing facade."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from app.browser.humanized_pointer import (
    HumanizedInteractionProfile,
    get_humanized_profile,
    humanized_click_element,
    humanized_click_rect,
    humanized_type_element,
)
from app.browser.reliable_actions import reliable_click, reliable_click_element, reliable_fill
from app.browser.reliable_support import is_fake
from app.platforms.boss import selectors
from app.settings import load_settings

VerifyCallback = Callable[[], Awaitable[bool | dict[str, object]]]
BOSS_THREAD_VERIFY_TIMEOUT_MS = 8000
BOSS_SEND_VERIFY_TIMEOUT_MS = 8000


async def boss_click_element(
    page: Any,
    element: Any,
    *,
    label: str,
    verify: VerifyCallback | None = None,
    profile: HumanizedInteractionProfile | None = None,
) -> dict[str, object]:
    profile = profile or _boss_profile()
    if is_fake(page):
        return await reliable_click_element(page, element, label=label, verify=verify)
    return await humanized_click_element(
        page,
        element,
        label=label,
        verify=verify,
        profile=profile,
    )


async def boss_click_conversation_row(
    page: Any,
    element: Any,
    *,
    label: str,
    verify: VerifyCallback | None = None,
) -> dict[str, object]:
    profile = replace(
        _boss_profile(),
        verify_timeout_ms=BOSS_THREAD_VERIFY_TIMEOUT_MS,
        max_click_attempts=1,
    )
    return await boss_click_element(
        page,
        element,
        label=label,
        verify=verify,
        profile=profile,
    )


async def boss_click_selector(
    page: Any,
    selector: str,
    *,
    label: str,
    verify: VerifyCallback | None = None,
    profile: HumanizedInteractionProfile | None = None,
) -> dict[str, object]:
    profile = profile or _boss_profile()
    if is_fake(page):
        return await reliable_click(page, selector, label=label, verify=verify)
    element = await page.query(selector)
    if element is None:
        return {"ok": False, "reason": "target_not_found", "label": label}
    return await boss_click_element(page, element, label=label, verify=verify, profile=profile)


async def boss_click_rect(
    page: Any,
    rect: dict[str, object],
    *,
    label: str,
    verify: VerifyCallback | None = None,
    profile: HumanizedInteractionProfile | None = None,
) -> dict[str, object]:
    profile = profile or _boss_profile()
    return await humanized_click_rect(
        page,
        rect,
        label=label,
        verify=verify,
        profile=profile,
    )


async def boss_type_and_send(
    page: Any,
    text: str,
    *,
    verify_sent: VerifyCallback,
    profile: HumanizedInteractionProfile | None = None,
    expected_conversation: VerifyCallback | None = None,
) -> dict[str, object]:
    """Atomically focus, type, verify, and click send for one BOSS message."""

    profile = profile or _boss_profile()
    lock = _interaction_lock(page)
    async with lock:
        if is_fake(page):
            fill = await reliable_fill(page, selectors.CHAT_INPUT, text, label="BOSS聊天输入框")
            if not fill.get("ok"):
                return fill
            return await reliable_click(
                page,
                selectors.SEND_BUTTON,
                label="BOSS发送按钮",
                verify=verify_sent,
            )

        input_element = await page.query(selectors.CHAT_INPUT)
        if input_element is None:
            return {"ok": False, "reason": "chat_input_not_found"}
        focus = await boss_click_element(
            page,
            input_element,
            label="BOSS聊天输入框聚焦",
            profile=profile,
        )
        if not focus.get("ok"):
            return {"ok": False, "reason": focus.get("reason") or "chat_input_focus_failed"}
        typed = await humanized_type_element(
            page,
            input_element,
            text,
            label="BOSS逐字输入",
            profile=profile,
        )
        if not typed.get("ok"):
            return typed
        if expected_conversation is not None:
            identity = await expected_conversation()
            if not bool(identity.get("verified") if isinstance(identity, dict) else identity):
                return {"ok": False, "reason": "conversation_changed_before_send"}
        send_element = await page.query(selectors.SEND_BUTTON)
        if send_element is None:
            return {"ok": False, "reason": "send_button_not_found"}
        return await boss_click_element(
            page,
            send_element,
            label="BOSS发送按钮",
            verify=verify_sent,
            profile=replace(
                profile,
                verify_timeout_ms=BOSS_SEND_VERIFY_TIMEOUT_MS,
                max_click_attempts=1,
            ),
        )


def _interaction_lock(page: Any) -> asyncio.Lock:
    lock = getattr(page, "_boss_interaction_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        page._boss_interaction_lock = lock
    return lock


def _boss_profile() -> HumanizedInteractionProfile:
    settings = load_settings()
    return get_humanized_profile(
        settings.boss_humanized_profile,
        enabled=settings.boss_humanized_interaction_enabled,
    )
