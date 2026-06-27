"""智联页面动作封装。

动作函数只接收 BrowserPage，不直接依赖 Playwright；真实页面通过 CDP 包装，
测试通过 FakePage 驱动同样的接口。
"""

from __future__ import annotations

from app.browser.base import BrowserElement, BrowserPage
from app.browser.reliable_actions import (
    reliable_click,
    reliable_click_element,
    reliable_confirm,
    reliable_fill,
)
from app.core.constants import Platform
from app.platforms.types import (
    Candidate,
    ChatMessage,
    Conversation,
    ConversationRef,
    MessageSender,
    ResumeRequestState,
    SendResult,
)
from app.platforms.zhilian import selectors

SYSTEM_SKIP_TERMS = ("平台推荐", "系统提示", "广告", "职位助手", "智联小助手")


async def open_chat_page(page: BrowserPage) -> None:
    """打开智联聊天入口。"""

    await page.goto(selectors.CHAT_URL)


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """点击“未读”筛选。"""

    elements = await page.query_all(selectors.UNREAD_FILTER)
    for element in elements:
        label = await element.text()
        if label == "未读" or ("未读" in label and len(label) <= 8):
            click = await reliable_click_element(page, element, label="智联未读筛选")
            return {"selected": bool(click.get("ok")), "label": label, "click": click}
    return {"selected": False, "reason": "unread_filter_not_found"}


async def select_positions(
    page: BrowserPage, target_position: str | None = None
) -> dict[str, object]:
    """选择全部职位或指定职位。"""

    label = target_position or selectors.ALL_POSITION_OPTION_TEXT
    click = await reliable_click(page, selectors.POSITION_FILTER, label="智联职位筛选")
    clicked = bool(click.get("ok"))
    if label == selectors.ALL_POSITION_OPTION_TEXT:
        return {"selected": clicked, "label": label, "mode": "all"}
    return {"selected": clicked, "label": label, "mode": "target"}


async def find_next_unread_thread(
    page: BrowserPage,
    *,
    owner: str,
    allowed_positions: list[str] | None = None,
) -> ConversationRef | None:
    """从顶部寻找下一个真实候选人的未读会话。"""

    allowed = [item.strip() for item in allowed_positions or [] if item.strip()]
    rows = await page.query_all(selectors.SESSION_ITEM)
    for row in rows:
        label = await row.text()
        if _should_skip_label(label):
            continue
        unread_count = _safe_int(await row.attr("unread"))
        if unread_count <= 0:
            continue
        position = (await row.attr("position") or "").strip()
        if allowed and not any(_position_matches(position, item) for item in allowed):
            continue
        click = await reliable_click_element(
            page,
            row,
            label="智联候选人会话",
            verify=lambda: _verify_chat_ready(page),
        )
        if not click.get("ok"):
            continue
        conversation_id = await row.attr("id") or label
        return ConversationRef(Platform.ZHILIAN, owner, conversation_id)
    return None


async def read_chat_context(page: BrowserPage, *, owner: str) -> Conversation:
    """读取当前智联会话上下文。"""

    raw = await _safe_eval_dict(page, "zhilian.read_chat_context")
    candidate = Candidate(
        name=str(raw.get("name") or raw.get("candidate_name") or ""),
        applied_position=str(raw.get("position") or raw.get("appliedPosition") or ""),
        label=str(raw.get("label") or ""),
        source="zhilian-chat",
    )
    messages = [
        _message_from_raw(item) for item in raw.get("messages", []) if isinstance(item, dict)
    ]
    last = _last_effective_message(messages)
    return Conversation(
        id=str(raw.get("id") or raw.get("conversation_id") or candidate.label or candidate.name),
        platform=Platform.ZHILIAN,
        owner=owner,
        candidate=candidate,
        messages=messages,
        unread_count=_safe_int(raw.get("unread_count") or raw.get("unreadCount")),
        latest_message=str(raw.get("latest_message") or raw.get("message") or ""),
        should_reply=bool(last and last.sender == MessageSender.CANDIDATE),
    )


async def send_message(page: BrowserPage, message: str) -> SendResult:
    """填入智联 textarea，点击发送，并用最近己方消息校验。"""

    text = message.strip()
    if not text:
        return SendResult(sent=False, blocked=True, message="智联待发送内容为空")
    fill = await reliable_fill(page, selectors.CHAT_INPUT, text, label="智联聊天输入框")
    if not fill.get("ok"):
        return SendResult(sent=False, blocked=True, message="智联没有找到聊天输入框")
    click = await _click_send(page, text)
    sent = bool(click.get("ok"))
    return SendResult(
        sent=sent,
        verified=sent,
        blocked=not sent,
        message="智联已发送消息" if sent else "智联发送按钮点击失败",
    )


async def inspect_resume_request_state(page: BrowserPage) -> ResumeRequestState:
    """检查当前会话是否已有附件简历或已求过附件简历。"""

    raw = await _safe_eval_dict(page, "zhilian.inspect_resume_request_state")
    if not raw:
        body = await page.text()
        raw = {
            "hasResumeAttachment": selectors.ATTACHMENT_VIEW_TEXT in body or "附件简历" in body,
            "alreadyRequested": "已要附件简历" in body or "已向对方要附件简历" in body,
            "summary": body[-240:],
        }
    return ResumeRequestState(
        has_resume_attachment=bool(raw.get("hasResumeAttachment")),
        already_requested=bool(raw.get("alreadyRequested")),
        summary=str(raw.get("summary") or ""),
    )


async def request_resume(page: BrowserPage) -> dict[str, object]:
    """点击智联“要附件简历”。"""

    state = await inspect_resume_request_state(page)
    if state.has_resume_attachment:
        return {"requested": False, "resumeReceived": True, "state": state}
    if state.already_requested:
        return {"requested": False, "skipped": True, "reason": "already_requested", "state": state}
    button = await _find_button_by_text(
        page, selectors.REQUEST_RESUME_BUTTON, selectors.REQUEST_RESUME_TEXT
    )
    if button is None:
        return {"requested": False, "blocked": True, "reason": "request_resume_button_not_found"}
    click = await reliable_click_element(
        page,
        button,
        label="智联要附件简历",
        verify=lambda: _confirm_button_visible(page),
    )
    if not click.get("ok"):
        return {
            "requested": False,
            "blocked": True,
            "reason": "request_resume_click_not_verified",
            "state": state,
            "click": click,
        }
    confirmed = await _click_request_resume_confirm(page)
    return {"requested": True, "confirmed": confirmed, "state": state}


async def open_recommend_page(page: BrowserPage) -> None:
    """打开智联推荐人才页。"""

    await page.goto(selectors.RECOMMEND_URL)


async def proactive_greet(
    page: BrowserPage,
    *,
    target_position: str,
    dry_run: bool = False,
) -> dict[str, object]:
    """智联推荐人才打招呼入口。

    本阶段保留动作边界，完整主动联系门槛在后续平台实跑时继续补齐。
    """

    await open_recommend_page(page)
    if dry_run:
        return {"greeted": 0, "dryRun": True, "targetPosition": target_position}
    button = await _find_button_by_text(
        page,
        f"{selectors.RECOMMEND_MODAL} button, {selectors.RECOMMEND_MODAL} [role='button']",
        selectors.RECOMMEND_GREET_BUTTON_TEXT,
    )
    if button is None:
        return {"greeted": 0, "reason": "greet_button_missing", "targetPosition": target_position}
    click = await reliable_click_element(page, button, label="智联推荐打招呼")
    return {
        "greeted": 1 if click.get("ok") else 0,
        "targetPosition": target_position,
        "click": click,
    }


async def _click_send(page: BrowserPage, message: str) -> dict[str, object]:
    send_selectors = (
        ".im-sender button, .im-sender [role='button'], "
        "button[class*='send'], [class*='send'], [class*='submit']"
    )
    return await reliable_click(
        page,
        send_selectors,
        label="智联发送按钮",
        verify=lambda: _verify_recent_mine_message(page, message),
    )


async def _find_button_by_text(
    page: BrowserPage,
    selector: str,
    expected_text: str,
) -> BrowserElement | None:
    for element in await page.query_all(selector):
        if expected_text in (await element.text()):
            return element
    return None


async def _click_request_resume_confirm(page: BrowserPage) -> bool:
    result = await reliable_confirm(
        page,
        selectors.REQUEST_RESUME_CONFIRM_BUTTON,
        selectors.REQUEST_RESUME_CONFIRM_TEXTS,
        label="智联要附件简历确认",
    )
    return bool(result.get("ok"))


async def _verify_chat_ready(page: BrowserPage) -> dict[str, object]:
    return {"verified": await page.wait_for(selectors.CHAT_READY, timeout_ms=6500)}


async def _verify_recent_mine_message(
    page: BrowserPage,
    expected_text: str,
) -> dict[str, object]:
    raw = await _safe_eval_dict(page, "zhilian.verify_sent", expected_text)
    if raw.get("verified"):
        return {"verified": True, "source": "script"}
    messages = await page.query_all(selectors.MINE_MESSAGE)
    for element in reversed(messages):
        if expected_text in (await element.text()):
            return {"verified": True, "source": "dom"}
    return {"verified": False, "reason": "mine_message_not_found"}


async def _confirm_button_visible(page: BrowserPage) -> dict[str, object]:
    for element in await page.query_all(selectors.REQUEST_RESUME_CONFIRM_BUTTON):
        label = await element.text()
        if any(text in label for text in selectors.REQUEST_RESUME_CONFIRM_TEXTS):
            return {"verified": True}
    return {"verified": False, "reason": "confirm_not_visible"}


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


def _should_skip_label(label: str) -> bool:
    compact = "".join(str(label or "").split())
    return not compact or any(term in compact for term in SYSTEM_SKIP_TERMS)


def _position_matches(actual: str, expected: str) -> bool:
    left = "".join(actual.split())
    right = "".join(expected.split())
    return bool(left and right and (left in right or right in left))


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
