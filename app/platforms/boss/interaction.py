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
from app.browser.reliable_support import is_fake, record_result
from app.platforms.boss import selectors
from app.settings import load_settings

VerifyCallback = Callable[[], Awaitable[bool | dict[str, object]]]
BOSS_THREAD_VERIFY_TIMEOUT_MS = 8000
BOSS_SEND_VERIFY_TIMEOUT_MS = 8000

_BOSS_SECURITY_WARNING_STATE_JS = """
() => {
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0
      && rect.height > 0
      && style.display !== "none"
      && style.visibility !== "hidden";
  };
  const dialogs = Array.from(document.querySelectorAll(
    '[role="dialog"], .boss-dialog__wrapper, .boss-dialog, .dialog-wrap.active, .modal'
  )).filter(visible);
  for (const dialog of dialogs) {
    const text = String(dialog.innerText || dialog.textContent || "").trim();
    if (text.includes("风险提示")
      && text.includes("第三方")
      && (text.includes("招聘辅助工具") || text.includes("封禁"))) {
      return {blocked: true, title: "风险提示", text: text.slice(0, 1200)};
    }
  }
  return {blocked: false, title: "", text: ""};
}
"""


async def boss_security_warning_state(page: Any) -> dict[str, object]:
    try:
        raw = await page.eval_js(_BOSS_SECURITY_WARNING_STATE_JS)
    except Exception:
        raw = {}
    if not isinstance(raw, dict) or not bool(raw.get("blocked")):
        return {"blocked": False, "title": "", "text": ""}
    return {
        "blocked": True,
        "title": str(raw.get("title") or "风险提示"),
        "text": str(raw.get("text") or "")[:1200],
    }


def _security_warning_result(
    page: Any,
    warning: dict[str, object],
    *,
    label: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "ok": False,
        "blocked": True,
        "verified": False,
        "label": label,
        "reason": "boss_security_warning",
        "warning": warning,
    }
    record_result(page, result)
    return result


async def boss_click_element(
    page: Any,
    element: Any,
    *,
    label: str,
    verify: VerifyCallback | None = None,
    pre_click_guard: VerifyCallback | None = None,
    profile: HumanizedInteractionProfile | None = None,
) -> dict[str, object]:
    warning = await boss_security_warning_state(page)
    if warning.get("blocked"):
        return _security_warning_result(page, warning, label=label)
    profile = profile or _boss_profile()
    if is_fake(page):
        return await reliable_click_element(page, element, label=label, verify=verify)

    async def guarded_pre_click() -> bool | dict[str, object]:
        current_warning = await boss_security_warning_state(page)
        if current_warning.get("blocked"):
            return {
                "verified": False,
                "reason": "boss_security_warning",
                "warning": current_warning,
            }
        if pre_click_guard is None:
            return {"verified": True}
        return await pre_click_guard()

    return await humanized_click_element(
        page,
        element,
        label=label,
        verify=verify,
        pre_click_guard=guarded_pre_click,
        profile=profile,
    )


async def boss_click_mutable_dialog_element(
    page: Any,
    element: Any,
    *,
    label: str,
    verify: VerifyCallback,
    pre_click_guard: VerifyCallback,
) -> dict[str, object]:
    """Click a dialog action once, with an immediate state guard before mouse down."""

    profile = replace(
        _boss_profile(),
        verify_timeout_ms=BOSS_SEND_VERIFY_TIMEOUT_MS,
        max_click_attempts=1,
    )
    return await boss_click_element(
        page,
        element,
        label=label,
        verify=verify,
        pre_click_guard=pre_click_guard,
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
    warning = await boss_security_warning_state(page)
    if warning.get("blocked"):
        return _security_warning_result(page, warning, label=label)
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
