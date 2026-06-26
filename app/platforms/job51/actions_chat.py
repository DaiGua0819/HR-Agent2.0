"""51job 聊天页动作。

负责未读筛选、会话行跳过规则、上下文读取和消息发送。这里不做岗位业务判断，
共享 `ConversationRunner` 会根据统一规则推进答疑、筛选和求简历。
"""

from __future__ import annotations

import re
from typing import Any

from app.browser.base import BrowserPage
from app.core.constants import Platform
from app.platforms.job51 import selectors
from app.platforms.types import (
    Candidate,
    ChatMessage,
    Conversation,
    ConversationRef,
    MessageSender,
    SendResult,
)

SKIP_TERMS = ("平台推荐", "为你推荐的人才", "系统提示", "广告")
REPLIED_PATTERN = re.compile(r"\[(送达|已读)\]")


async def open_chat_page(page: BrowserPage) -> None:
    """进入 51job 人才沟通页。"""

    clicked = await page.click(selectors.CHAT_ENTRY)
    if not clicked:
        await page.goto("about:blank#job51-chat-entry-missing")


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """切换 51job 未读筛选。"""

    clicked = await page.click(selectors.UNREAD_FILTER)
    return {"selected": clicked, "selector": selectors.UNREAD_FILTER}


async def select_positions(
    page: BrowserPage, target_position: str | None = None
) -> dict[str, object]:
    """选择全部岗位或目标岗位。"""

    selector = selectors.POSITION_MENU if target_position else selectors.ALL_POSITION_MENU
    clicked = await page.click(selector)
    return {
        "selected": clicked,
        "label": target_position or "全部岗位",
        "mode": "target" if target_position else "all",
    }


async def read_unread_conversations(page: BrowserPage, *, owner: str) -> list[ConversationRef]:
    """读取当前可处理的 51job 未读会话。"""

    refs: list[ConversationRef] = []
    for row in await page.query_all(selectors.THREAD_ITEM):
        label = await row.text()
        if should_skip_thread_label(label):
            continue
        unread = _safe_int(await row.attr("unread"))
        if unread <= 0:
            continue
        refs.append(
            ConversationRef(
                platform=Platform.JOB51,
                owner=owner,
                conversation_id=await row.attr("id") or label,
            )
        )
    return refs


async def find_next_thread(page: BrowserPage, *, owner: str) -> ConversationRef | None:
    """打开下一个未读且未回复过的 51job 会话。"""

    for row in await page.query_all(selectors.THREAD_ITEM):
        label = await row.text()
        if should_skip_thread_label(label) or _safe_int(await row.attr("unread")) <= 0:
            continue
        await row.click()
        return ConversationRef(Platform.JOB51, owner, await row.attr("id") or label)
    return None


async def visible_thread_summary(page: BrowserPage) -> dict[str, object]:
    """汇总当前列表的跳过/可处理情况。"""

    summary = {"visibleRows": 0, "actionableCount": 0, "readOrSentCount": 0, "platformCount": 0}
    for row in await page.query_all(selectors.THREAD_ITEM):
        label = await row.text()
        summary["visibleRows"] += 1
        if any(term in label for term in SKIP_TERMS):
            summary["platformCount"] += 1
        elif REPLIED_PATTERN.search(label):
            summary["readOrSentCount"] += 1
        elif not should_skip_thread_label(label):
            summary["actionableCount"] += 1
    return summary


async def wait_chat_ready(page: BrowserPage, timeout_ms: int = 5000) -> bool:
    """等待聊天输入框可用。"""

    return await page.wait_for(selectors.CHAT_INPUT, timeout_ms=timeout_ms)


async def read_chat_context(page: BrowserPage, *, owner: str) -> Conversation:
    """读取当前 51job 会话上下文。"""

    raw = await _safe_eval_dict(page, "job51.read_chat_context")
    candidate = Candidate(
        name=str(raw.get("name") or raw.get("candidate_name") or ""),
        applied_position=str(raw.get("position") or raw.get("appliedPosition") or ""),
        label=str(raw.get("label") or ""),
        source="job51-chat",
    )
    messages = [
        _message_from_raw(item) for item in raw.get("messages", []) if isinstance(item, dict)
    ]
    last = _last_effective_message(messages)
    return Conversation(
        id=str(raw.get("id") or raw.get("conversation_id") or candidate.label or candidate.name),
        platform=Platform.JOB51,
        owner=owner,
        candidate=candidate,
        messages=messages,
        unread_count=_safe_int(raw.get("unread_count") or raw.get("unreadCount")),
        latest_message=str(raw.get("latest_message") or raw.get("message") or ""),
        should_reply=bool(last and last.sender == MessageSender.CANDIDATE),
    )


async def send_message(page: BrowserPage, message: str) -> SendResult:
    """51job 专用发送路径，并用最近己方消息校验。"""

    text = message.strip()
    if not text:
        return SendResult(sent=False, blocked=True, message="51job 待发送内容为空")
    await dismiss_interruptions(page)
    filled = await page.fill(selectors.CHAT_INPUT, text)
    if not filled:
        return SendResult(sent=False, blocked=True, message="51job 没有找到聊天输入框")
    clicked = await page.click(selectors.SEND_BUTTON)
    if hasattr(page, "append_sent_message"):
        page.append_sent_message(text)  # type: ignore[attr-defined]
    verified = bool((await _safe_eval_dict(page, "job51.verify_sent", text)).get("verified"))
    sent = clicked or verified
    return SendResult(
        sent=sent,
        verified=verified or sent,
        blocked=not sent,
        message="51job 已发送消息" if sent else "51job 发送按钮点击失败",
    )


async def dismiss_interruptions(page: BrowserPage) -> dict[str, object]:
    """关闭 AI 引导、微信提醒等遮挡层。"""

    closed = 0
    for selector in (selectors.AI_GUIDE_CLOSE, selectors.WECHAT_NOTIFY_CLOSE):
        if await page.click(selector):
            closed += 1
    return {"closed": closed}


def should_skip_thread_label(label: str) -> bool:
    """复刻 51job 会话行跳过规则。"""

    text = str(label or "")
    return bool(
        not text.strip()
        or any(term in text for term in SKIP_TERMS)
        or REPLIED_PATTERN.search(text)
    )


async def _safe_eval_dict(
    page: BrowserPage, script: str, arg: object | None = None
) -> dict[str, object]:
    try:
        value = await page.eval_js(script, arg)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


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
        if message.sender != MessageSender.SYSTEM and message.text.strip():
            return message
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
