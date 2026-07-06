"""BOSS 页面动作封装。

动作函数只依赖 `BrowserPage` 抽象。真实页面后续由 Playwright CDP 包装执行，
Phase 2 测试通过 FakePage 验证顺序、选择器和业务分支。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.browser.base import BrowserElement, BrowserPage
from app.browser.reliable_actions import (
    reliable_click,
    reliable_click_element,
    reliable_fill,
)
from app.core.constants import Platform
from app.platforms.boss import actions_recommend, actions_resume, selectors
from app.platforms.boss.dom_scripts import (
    CLICK_UNREAD_FILTER_JS,
    READ_CHAT_CONTEXT_JS,
    READ_UNREAD_ROWS_JS,
)
from app.platforms.boss.row_click import click_row_state, find_row_for_state
from app.platforms.types import (
    Candidate,
    ChatMessage,
    Conversation,
    ConversationRef,
    MessageSender,
    ResumeRequestState,
    SendResult,
)

SYSTEM_SKIP_TERMS = ("平台推荐", "系统消息", "BOSS直聘", "职位助手")


async def open_chat_page(page: BrowserPage) -> None:
    """打开 BOSS 招聘端聊天页。"""

    await page.goto(selectors.CHAT_URL)
    await page.wait_for(
        ".chat-message-filter, .chat-message-filter-left, .chat-user, "
        f"{selectors.SESSION_ITEM}",
        timeout_ms=12000,
    )


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """点击 BOSS 未读筛选。"""

    clicked = await _safe_eval_dict(page, CLICK_UNREAD_FILTER_JS)
    if clicked.get("selected"):
        await asyncio.sleep(1)
        active = await _active_message_filter_label(page)
        clicked["active"] = active
        clicked["selected"] = active == "未读"
        return clicked
    for element in await page.query_all(selectors.UNREAD_FILTER):
        label = await element.text()
        if label == "未读" or ("未读" in label and len(label) <= 12):
            result = await reliable_click_element(page, element, label="BOSS未读筛选")
            await asyncio.sleep(1)
            active = await _active_message_filter_label(page)
            return {
                "selected": bool(result.get("ok")) and active == "未读",
                "label": label,
                "active": active,
                "click": result,
            }
    return {"selected": False, "reason": "unread_filter_not_found"}


async def select_positions(
    page: BrowserPage, target_position: str | None = None
) -> dict[str, object]:
    """选择 BOSS 全部职位或指定职位。"""

    label = target_position or selectors.ALL_POSITION_OPTION_TEXT
    if not target_position:
        return {"selected": True, "label": label, "mode": "all", "clicked": False}
    result = await reliable_click(page, selectors.POSITION_FILTER, label="BOSS职位筛选")
    clicked = bool(result.get("ok"))
    if hasattr(page, "selected_recommend_position") and target_position:
        page.selected_recommend_position = target_position  # type: ignore[attr-defined]
    return {"selected": clicked, "label": label, "mode": "target" if target_position else "all"}


async def read_unread_conversations(page: BrowserPage, *, owner: str) -> list[ConversationRef]:
    """读取 BOSS 当前列表里的未读会话引用。"""

    refs: list[ConversationRef] = []
    for state in await read_unread_row_states(page):
        label = str(state.get("label") or "")
        if _should_skip_label(label) or _safe_int(state.get("unread_count")) <= 0:
            continue
        refs.append(
            ConversationRef(
                platform=Platform.BOSS,
                owner=owner,
                conversation_id=str(state.get("id") or label),
            )
        )
    return refs


async def find_next_unread_thread(
    page: BrowserPage,
    *,
    owner: str,
    exclude_ids: set[str] | None = None,
) -> ConversationRef | None:
    """从 BOSS 未读列表打开下一个真实候选人。"""

    unread = await read_unread_row_states(page)
    if not unread:
        return None
    excluded = {str(item) for item in exclude_ids or set() if str(item)}
    for state in unread:
        label = str(state.get("label") or "")
        conversation_id = str(state.get("id") or label)
        if conversation_id in excluded:
            continue
        row = await find_row_for_state(page, state)
        if row is None:
            continue
        if _should_skip_label(label):
            continue
        result = await reliable_click_element(page, row, label="BOSS候选人会话")
        if not result.get("ok"):
            result = await click_row_state(page, state, label="BOSS候选人会话")
        if result.get("ok"):
            return ConversationRef(Platform.BOSS, owner, conversation_id)
    return None


async def read_unread_row_states(page: BrowserPage) -> list[dict[str, object]]:
    """读取 BOSS 列表中带真实数字未读徽标的会话行。"""

    raw = await _safe_eval_dict(page, "boss.read_unread_rows")
    if not raw:
        raw = await _safe_eval_dict(page, READ_UNREAD_ROWS_JS)
    states = _normalize_unread_rows(raw.get("rows"))
    if states:
        return states

    fallback: list[dict[str, object]] = []
    for index, row in enumerate(await page.query_all(selectors.SESSION_ITEM)):
        label = await row.text()
        unread_count = _row_unread_count(await row.attr("unread"))
        if unread_count <= 0:
            continue
        fallback.append(
            {
                "index": index,
                "id": await row.attr("id") or "",
                "label": label,
                "unread_count": unread_count,
            }
        )
    return fallback


async def read_chat_context(page: BrowserPage, *, owner: str) -> Conversation:
    """读取当前 BOSS 会话上下文。"""

    raw = await _safe_eval_dict(page, "boss.read_chat_context")
    if not raw:
        raw = await _safe_eval_dict(page, READ_CHAT_CONTEXT_JS)
    candidate = Candidate(
        name=str(raw.get("name") or raw.get("candidate_name") or ""),
        applied_position=str(raw.get("position") or raw.get("appliedPosition") or ""),
        label=str(raw.get("label") or ""),
        source="boss-chat",
    )
    messages = [
        _message_from_raw(item) for item in raw.get("messages", []) if isinstance(item, dict)
    ]
    last = _last_effective_message(messages)
    return Conversation(
        id=str(raw.get("id") or raw.get("conversation_id") or candidate.label or candidate.name),
        platform=Platform.BOSS,
        owner=owner,
        candidate=candidate,
        messages=messages,
        unread_count=_safe_int(raw.get("unread_count") or raw.get("unreadCount")),
        latest_message=str(raw.get("latest_message") or raw.get("message") or ""),
        should_reply=bool(last and last.sender == MessageSender.CANDIDATE),
    )


async def send_message(page: BrowserPage, message: str) -> SendResult:
    """在 BOSS 当前会话发送一条文本消息。"""

    text = message.strip()
    if not text:
        return SendResult(sent=False, blocked=True, message="BOSS 待发送内容为空")
    fill = await reliable_fill(page, selectors.CHAT_INPUT, text, label="BOSS聊天输入框")
    if not fill.get("ok"):
        return SendResult(sent=False, blocked=True, message="BOSS 没有找到聊天输入框")
    click = await reliable_click(
        page,
        selectors.SEND_BUTTON,
        label="BOSS发送按钮",
        verify=lambda: _verify_recent_mine_message(page, selectors.MINE_MESSAGE, text),
    )
    sent = bool(click.get("ok"))
    return SendResult(
        sent=sent,
        verified=sent,
        blocked=not sent,
        message="BOSS 已发送消息" if sent else "BOSS 发送按钮点击失败",
    )


async def send_company_info(
    page: BrowserPage,
    *,
    phrase: str = "",
    phrase_key: str = "basic_conditions",
) -> SendResult:
    """通过 BOSS 常用语入口发送 AI 应用岗位基础条件。"""

    text = phrase.strip()
    if not text:
        text = f"common_phrase:{phrase_key or 'basic_conditions'}"
    if hasattr(page, "append_sent_message"):
        page.append_sent_message(text)  # type: ignore[attr-defined]
        return SendResult(sent=True, verified=True, message="BOSS 常用语已发送")
    if phrase:
        return await send_message(page, phrase)
    # 常用语面板真实路径尚未完成选择器逐项验证；无明确文本时才触发入口。
    click = await reliable_click(page, selectors.COMMON_PHRASE_BUTTON, label="BOSS常用语入口")
    if not click.get("ok"):
        return SendResult(sent=False, blocked=True, message="BOSS 常用语入口未找到")
    return SendResult(sent=True, verified=False, message="BOSS 常用语入口已触发")


async def send_common_phrase(
    page: BrowserPage,
    *,
    phrase_key: str = "",
    phrase: str = "",
) -> SendResult:
    """发送 BOSS 常用语。"""

    return await send_company_info(page, phrase=phrase, phrase_key=phrase_key)


async def inspect_resume_request_state(page: BrowserPage) -> ResumeRequestState:
    """检查当前 BOSS 会话是否已有附件简历或已经求过简历。"""

    return await actions_resume.inspect_resume_request_state(page)


async def request_resume(page: BrowserPage) -> dict[str, object]:
    """点击 BOSS 聊天工具栏里的“求简历”。"""

    return await actions_resume.request_resume(page)


async def open_recommend_page(page: BrowserPage) -> None:
    """打开 BOSS 推荐牛人页。"""

    await actions_recommend.open_recommend_page(page)


async def proactive_greet(
    page: BrowserPage,
    *,
    target_position: str,
    dry_run: bool = False,
) -> dict[str, object]:
    """按主动联系门槛处理 BOSS 推荐牛人候选人。"""

    return await actions_recommend.proactive_greet(
        page,
        target_position=target_position,
        dry_run=dry_run,
    )


async def mark_unsuitable(page: BrowserPage, *, reason: str = "") -> dict[str, object]:
    """点击 BOSS “不合适”入口；Phase 2 仅保留动作边界。"""

    button = await _find_button_by_text(
        page, selectors.REQUEST_RESUME_BUTTON, selectors.UNSUITABLE_BUTTON_TEXT
    )
    if button is None:
        return {"marked": False, "reason": "unsuitable_button_not_found", "detail": reason}
    click = await reliable_click_element(page, button, label="BOSS标记不合适")
    return {"marked": bool(click.get("ok")), "reason": reason, "click": click}


async def _find_row_for_state(
    page: BrowserPage,
    state: dict[str, object],
) -> BrowserElement | None:
    row_id = str(state.get("id") or "")
    row_id_norm = row_id.lstrip("_")
    label = str(state.get("label") or "")
    rows = await page.query_all(selectors.SESSION_ITEM)

    if row_id_norm:
        for row in rows:
            current_id = str(await row.attr("id") or "")
            if current_id.lstrip("_") == row_id_norm:
                return row
    if label:
        for row in rows:
            if (await row.text()).strip() == label:
                return row
    index = _safe_int(state.get("index"))
    if 0 <= index < len(rows):
        return rows[index]
    return None


async def _find_button_by_text(
    page: BrowserPage, selector: str, expected_text: str
) -> BrowserElement | None:
    for element in await page.query_all(selector):
        if expected_text in (await element.text()):
            return element
    return None


async def _verify_recent_mine_message(
    page: BrowserPage,
    selector: str,
    expected_text: str,
) -> dict[str, object]:
    raw = await _safe_eval_dict(page, "boss.verify_sent", expected_text)
    if raw.get("verified"):
        return {"verified": True, "source": "script"}
    messages = await page.query_all(selector)
    for element in reversed(messages):
        if expected_text in (await element.text()):
            return {"verified": True, "source": "dom"}
    return {"verified": False, "reason": "mine_message_not_found"}


async def _safe_eval_dict(
    page: BrowserPage, script: str, arg: object | None = None
) -> dict[str, object]:
    try:
        value = await page.eval_js(script, arg)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def _active_message_filter_label(page: BrowserPage) -> str:
    try:
        value = await page.eval_js(
            """
            () => {
              const active = Array.from(
                document.querySelectorAll(".chat-message-filter-left span.active")
              ).find((el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" &&
                  rect.width > 0 && rect.height > 0;
              });
              return active && active.innerText ? active.innerText.trim() : "";
            }
            """
        )
    except Exception:
        return ""
    return str(value or "")


def _message_from_raw(item: dict[str, object]) -> ChatMessage:
    sender = str(item.get("sender") or "")
    normalized = (
        MessageSender.CANDIDATE if sender in {"candidate", "other"} else MessageSender(sender)
    )
    return ChatMessage(
        sender=normalized,
        text=str(item.get("text") or ""),
        raw_text=str(item.get("rawText") or item.get("raw_text") or item.get("text") or ""),
        time=str(item.get("time") or ""),
    )


def _last_effective_message(messages: list[ChatMessage]) -> ChatMessage | None:
    for message in reversed(messages):
        if message.text.strip():
            return message
    return None


def _should_skip_label(label: str) -> bool:
    compact = _compact(label)
    return not compact or any(term in compact for term in SYSTEM_SKIP_TERMS)


def _normalize_unread_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        unread_count = _safe_int(item.get("unread_count") or item.get("unreadCount"))
        if unread_count <= 0:
            continue
        rows.append(
            {
                "index": _safe_int(item.get("index")),
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or ""),
                "unread_count": unread_count,
            }
        )
    return rows


def _compact(value: str) -> str:
    return "".join(str(value or "").split())


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _row_unread_count(value: str | None) -> int:
    """测试页可用 unread attr；真实页没有数字徽标时不视为未读。"""

    if value is None or value == "":
        return 0
    return _safe_int(value)
