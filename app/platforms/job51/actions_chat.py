"""51job 聊天页动作。

负责未读筛选、会话行跳过规则、上下文读取和消息发送。这里不做岗位业务判断，
共享 `ConversationRunner` 会根据统一规则推进答疑、筛选和求简历。
"""

from __future__ import annotations

import re
from typing import Any

from app.browser.base import BrowserPage
from app.browser.reliable_actions import (
    reliable_click,
    reliable_click_element,
    reliable_fill,
)
from app.core.constants import Platform
from app.platforms.job51 import selectors
from app.platforms.job51.actions_navigation import open_chat_page as navigate_chat_page
from app.platforms.job51.actions_unread import select_unread_filter as refresh_unread_filter
from app.platforms.job51.dom_scripts import (
    READ_CHAT_CONTEXT_JS,
    READ_UNREAD_ROWS_JS,
    VERIFY_SENT_JS,
)
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

    await navigate_chat_page(page)


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """刷新并切换 51job 未读筛选。"""

    return await refresh_unread_filter(page)


async def select_positions(
    page: BrowserPage, target_position: str | None = None
) -> dict[str, object]:
    """选择全部岗位或目标岗位。"""

    selector = selectors.POSITION_MENU if target_position else selectors.ALL_POSITION_MENU
    click = await reliable_click(page, selector, label="51job职位筛选")
    clicked = bool(click.get("ok"))
    return {
        "selected": clicked,
        "label": target_position or "全部岗位",
        "mode": "target" if target_position else "all",
    }


async def read_unread_conversations(page: BrowserPage, *, owner: str) -> list[ConversationRef]:
    """读取当前可处理的 51job 未读会话。"""

    refs: list[ConversationRef] = []
    for state in await read_unread_row_states(page):
        label = str(state.get("label") or "")
        if should_skip_thread_label(label):
            continue
        if _safe_int(state.get("unread_count")) <= 0:
            continue
        refs.append(
            ConversationRef(
                platform=Platform.JOB51,
                owner=owner,
                conversation_id=str(state.get("id") or label),
            )
        )
    return refs


async def read_unread_row_states(page: BrowserPage) -> list[dict[str, object]]:
    """读取 51job 当前列表中可处理的未读会话行状态。"""

    raw = await _safe_eval_dict(page, "job51.read_unread_rows")
    if not raw:
        raw = await _safe_eval_dict(page, READ_UNREAD_ROWS_JS)
    states = _normalize_unread_rows(raw.get("rows"))
    if states:
        return states

    fallback: list[dict[str, object]] = []
    for index, row in enumerate(await page.query_all(selectors.THREAD_ITEM)):
        unread_count = _safe_int(await row.attr("unread"))
        if unread_count <= 0:
            continue
        fallback.append(
            {
                "index": index,
                "id": await row.attr("id") or "",
                "label": await row.text(),
                "unread_count": unread_count,
            }
        )
    return fallback


async def find_next_thread(page: BrowserPage, *, owner: str) -> ConversationRef | None:
    """打开下一个未读且未回复过的 51job 会话。"""

    for state in await read_unread_row_states(page):
        label = str(state.get("label") or "")
        if should_skip_thread_label(label) or _safe_int(state.get("unread_count")) <= 0:
            continue
        row = await _find_thread_for_state(page, state)
        if row is None:
            continue
        expected = {
            "id": str(state.get("id") or label),
            "label": label,
            "name": await row.attr("name") or "",
            "position": await row.attr("position") or "",
        }
        click = await reliable_click_element(
            page,
            row,
            label="51job候选人会话",
            verify=lambda: _verify_chat_ready(page),
        )
        ready = bool(click.get("ok")) or await wait_chat_ready(page, timeout_ms=6500)
        opened = await verify_opened_candidate(page, expected, chat_ready=ready)
        if opened.get("opened"):
            return ConversationRef(Platform.JOB51, owner, str(expected["id"]))
    return None


async def click_thread_by_state(
    page: BrowserPage,
    state: dict[str, object],
) -> dict[str, object]:
    """Click a 51job conversation row with a JS fallback for virtual-list rows."""

    payload = {
        "id": str(state.get("id") or "").lstrip("_"),
        "label": str(state.get("label") or "").strip(),
        "index": _safe_int(state.get("index")),
    }
    result = await _safe_eval_dict(
        page,
        """
        (expected) => {
          const visible = (el) => {
            if (!el) return false;
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== "none" && style.visibility !== "hidden" &&
              rect.width > 0 && rect.height > 0;
          };
          const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
          const compact = (value) => String(value || "").replace(/\\s+/g, "");
          const rows = Array.from(document.querySelectorAll("#conversation-list .list-item"))
            .filter(visible);
          const target = rows.find((row) => {
            const id = String(row.id || row.getAttribute("data-id") ||
              row.getAttribute("data-uid") || "").replace(/^_/, "");
            return expected.id && id === expected.id;
          }) || rows.find((row) => expected.label && compact(text(row)) === compact(expected.label))
            || rows[Number(expected.index || 0)];
          if (!target) return { clicked: false, reason: "thread_row_not_found" };
          target.scrollIntoView({ block: "center", inline: "nearest" });
          const clickTarget = target.querySelector(".conversation-item") ||
            target.querySelector(".item-content") || target.querySelector(".info") || target;
          for (const type of ["mouseover", "mousemove", "mousedown", "mouseup", "click"]) {
            clickTarget.dispatchEvent(new MouseEvent(type, {
              bubbles: true,
              cancelable: true,
              view: window,
            }));
          }
          return { clicked: true, source: "dom_click", label: text(target) };
        }
        """,
        payload,
    )
    if result.get("clicked"):
        return result
    rows = await page.query_all(selectors.THREAD_ITEM)
    index = payload["index"]
    if isinstance(index, int) and 0 <= index < len(rows):
        try:
            await rows[index].click(timeout_ms=3000)
            return {"clicked": True, "source": "element_click", "index": index}
        except Exception as error:
            return {"clicked": False, "reason": "element_click_failed", "error": str(error)}
    return result or {"clicked": False, "reason": "thread_row_not_found"}


async def verify_opened_candidate(
    page: BrowserPage,
    expected: dict[str, object],
    *,
    chat_ready: bool = False,
) -> dict[str, object]:
    """校验虚拟列表点击后，右侧聊天区确实切到了目标候选人。"""

    raw = await _safe_eval_dict(page, "job51.opened_candidate_state", expected)
    if raw:
        return raw
    context = await _safe_eval_dict(page, "job51.read_chat_context")
    expected_name = str(expected.get("name") or "").strip()
    expected_position = str(expected.get("position") or "").strip()
    expected_label = str(expected.get("label") or "").strip()
    actual_name = str(context.get("name") or context.get("candidate_name") or "").strip()
    actual_position = str(context.get("position") or context.get("appliedPosition") or "").strip()
    actual_label = str(context.get("label") or "").strip()
    name_ok = bool(expected_name and actual_name and _text_matches(actual_name, expected_name))
    position_ok = bool(
        expected_position
        and actual_position
        and _position_matches(actual_position, expected_position)
    )
    label_ok = bool(expected_label and actual_label and _text_matches(actual_label, expected_label))
    opened = bool(chat_ready and (label_ok or name_ok or (actual_name and position_ok)))
    reason = "" if opened else "candidate_identity_mismatch"
    return {
        "opened": opened,
        "reason": reason,
        "chatReady": chat_ready,
        "expected": expected,
        "actual": {
            "name": actual_name,
            "position": actual_position,
            "label": actual_label,
        },
    }


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
    if not raw:
        raw = await _safe_eval_dict(page, READ_CHAT_CONTEXT_JS)
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
    fill = await reliable_fill(page, selectors.CHAT_INPUT, text, label="51job聊天输入框")
    if not fill.get("ok"):
        return SendResult(sent=False, blocked=True, message="51job 没有找到聊天输入框")
    click = await reliable_click(
        page,
        selectors.SEND_BUTTON,
        label="51job发送按钮",
        verify=lambda: _verify_recent_mine_message(page, text),
    )
    sent = bool(click.get("ok"))
    return SendResult(
        sent=sent,
        verified=sent,
        blocked=not sent,
        message="51job 已发送消息" if sent else "51job 发送按钮点击失败",
    )


async def dismiss_interruptions(page: BrowserPage) -> dict[str, object]:
    """关闭 AI 引导、微信提醒等遮挡层。"""

    closed = 0
    for selector in (selectors.AI_GUIDE_CLOSE, selectors.WECHAT_NOTIFY_CLOSE):
        element = await page.query(selector)
        if element is None:
            continue
        click = await reliable_click_element(page, element, label="51job关闭遮挡层")
        if click.get("ok"):
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


def _position_matches(actual: str, expected: str) -> bool:
    left = "".join(actual.split())
    right = "".join(expected.split())
    return bool(left and right and (left in right or right in left))


def _text_matches(actual: str, expected: str) -> bool:
    left = "".join(actual.split())
    right = "".join(expected.split())
    return bool(left and right and (left in right or right in left))


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _verify_chat_ready(page: BrowserPage) -> dict[str, object]:
    return {"verified": await wait_chat_ready(page, timeout_ms=6500)}


async def _find_thread_for_state(
    page: BrowserPage,
    state: dict[str, object],
) -> Any | None:
    row_id = str(state.get("id") or "").lstrip("_")
    label = str(state.get("label") or "").strip()
    rows = await page.query_all(selectors.THREAD_ITEM)
    if row_id:
        for row in rows:
            current_id = str(await row.attr("id") or "").lstrip("_")
            if current_id == row_id:
                return row
    if label:
        for row in rows:
            if (await row.text()).strip() == label:
                return row
    index = _safe_int(state.get("index"))
    if 0 <= index < len(rows):
        return rows[index]
    return None


async def _verify_recent_mine_message(
    page: BrowserPage,
    expected_text: str,
) -> dict[str, object]:
    raw = await _safe_eval_dict(page, "job51.verify_sent", expected_text)
    if raw.get("verified"):
        return {"verified": True, "source": "script"}
    raw = await _safe_eval_dict(page, VERIFY_SENT_JS, expected_text)
    if raw.get("verified"):
        return {"verified": True, "source": "dom_script"}
    messages = await page.query_all(selectors.MINE_MESSAGE)
    for element in reversed(messages):
        if expected_text in (await element.text()):
            return {"verified": True, "source": "dom"}
    return {"verified": False, "reason": "mine_message_not_found"}


def _normalize_unread_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    seen_labels: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        unread_count = _safe_int(item.get("unread_count") or item.get("unreadCount"))
        if unread_count <= 0:
            continue
        label = str(item.get("label") or "")
        compact_label = "".join(label.split())
        if compact_label in seen_labels:
            continue
        seen_labels.add(compact_label)
        rows.append(
            {
                "index": _safe_int(item.get("index")),
                "id": str(item.get("id") or ""),
                "label": label,
                "unread_count": unread_count,
            }
        )
    return rows
