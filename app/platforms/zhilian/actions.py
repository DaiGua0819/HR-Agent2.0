"""智联页面动作封装。

动作函数只接收 BrowserPage，不直接依赖 Playwright；真实页面通过 CDP 包装，
测试通过 FakePage 驱动同样的接口。
"""

from __future__ import annotations

import asyncio

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
from app.platforms.zhilian.dom_scripts import (
    CLICK_SESSION_ROW_JS,
    READ_CHAT_CONTEXT_JS,
    READ_UNREAD_ROWS_JS,
    UNREAD_FILTER_STATE_JS,
    ZHILIAN_RESUME_STATE_JS,
)
from app.platforms.zhilian.resume_files import save_zhilian_resume_bytes

SYSTEM_SKIP_TERMS = ("平台推荐", "系统提示", "广告", "职位助手", "智联小助手")


async def open_chat_page(page: BrowserPage) -> None:
    """打开智联聊天入口。"""

    await page.goto(selectors.CHAT_URL)


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """点击“未读”筛选。"""

    state = await _unread_filter_state(page)
    if state.get("active"):
        return {
            "selected": True,
            "label": str(state.get("label") or "未读"),
            "state": state,
            "click": {"skipped": True, "reason": "already_active"},
            "trustedClick": {},
            "fallbackRows": 0,
        }
    trusted = await _trusted_click_unread_filter(page)
    if trusted.get("attempted"):
        state = trusted.get("state", {})
        row_states = trusted.get("rows", [])
        selected = bool(trusted.get("ok")) and (bool(state.get("active")) or bool(row_states))
        return {
            "selected": selected,
            "label": str(trusted.get("label") or ""),
            "state": state,
            "click": trusted.get("click", {}),
            "trustedClick": trusted,
            "fallbackRows": len(row_states) if not state.get("active") else 0,
        }
    return {"selected": False, "reason": "unread_filter_not_found"}


async def select_positions(
    page: BrowserPage, target_position: str | None = None
) -> dict[str, object]:
    """选择全部职位或指定职位。"""

    label = target_position or selectors.ALL_POSITION_OPTION_TEXT
    if not target_position:
        return {"selected": True, "label": label, "mode": "all", "skippedClick": True}
    click = await reliable_click(page, selectors.POSITION_FILTER, label="智联职位筛选")
    clicked = bool(click.get("ok"))
    return {"selected": clicked, "label": label, "mode": "target"}


async def find_next_unread_thread(
    page: BrowserPage,
    *,
    owner: str,
    allowed_positions: list[str] | None = None,
    exclude_ids: set[str] | None = None,
) -> ConversationRef | None:
    """从顶部寻找下一个真实候选人的未读会话。"""

    allowed = [item.strip() for item in allowed_positions or [] if item.strip()]
    excluded = {str(item) for item in exclude_ids or set() if str(item)}
    for state in await read_unread_row_states(page):
        label = str(state.get("label") or "")
        if _should_skip_label(label):
            continue
        row_conversation_id = str(state.get("id") or label)
        if row_conversation_id in excluded:
            continue
        unread_count = _safe_int(state.get("unread_count"))
        if unread_count <= 0:
            continue
        position = str(state.get("position") or "").strip()
        if allowed and not any(_position_matches(position, item) for item in allowed):
            continue
        click = await _open_session_from_state(page, state)
        if not click.get("ok"):
            continue
        conversation = await read_chat_context(page, owner=owner)
        if not conversation.should_reply:
            continue
        conversation_id = str(conversation.id or state.get("id") or label)
        if conversation_id in excluded:
            continue
        return ConversationRef(Platform.ZHILIAN, owner, conversation_id)
    return None


async def read_unread_conversations(page: BrowserPage, *, owner: str) -> list[ConversationRef]:
    """读取当前智联未读会话引用。"""

    refs: list[ConversationRef] = []
    for state in await read_unread_row_states(page):
        label = str(state.get("label") or "")
        if _should_skip_label(label) or _safe_int(state.get("unread_count")) <= 0:
            continue
        refs.append(
            ConversationRef(
                platform=Platform.ZHILIAN,
                owner=owner,
                conversation_id=str(state.get("id") or label),
            )
        )
    return refs


async def read_unread_row_states(page: BrowserPage) -> list[dict[str, object]]:
    """读取智联当前列表中可处理的未读会话行状态。"""

    raw = await _safe_eval_dict(page, "zhilian.read_unread_rows")
    if not raw:
        raw = await _safe_eval_dict(page, READ_UNREAD_ROWS_JS)
    states = _normalize_unread_rows(raw.get("rows"))
    if states:
        return states

    fallback: list[dict[str, object]] = []
    for index, row in enumerate(await page.query_all(selectors.SESSION_ITEM)):
        unread_count = _safe_int(await row.attr("unread"))
        label = await row.text()
        if unread_count <= 0:
            continue
        if _should_skip_label(label):
            continue
        fallback.append(
            {
                "index": index,
                "id": await row.attr("id") or "",
                "label": label,
                "position": await row.attr("position") or "",
                "unread_count": unread_count,
            }
        )
    return fallback


async def read_chat_context(page: BrowserPage, *, owner: str) -> Conversation:
    """读取当前智联会话上下文。"""

    raw = await _safe_eval_dict(page, "zhilian.read_chat_context")
    if not _raw_context_has_content(raw):
        raw = await _safe_eval_dict(page, READ_CHAT_CONTEXT_JS)
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
    sent = bool(click.get("ok") and click.get("verified", True))
    return SendResult(
        sent=sent,
        verified=sent,
        blocked=not sent,
        details={"fill": fill, "trigger": click},
        message="智联已发送消息" if sent else "智联发送按钮点击失败",
    )


async def inspect_resume_request_state(page: BrowserPage) -> ResumeRequestState:
    """检查当前会话是否已有附件简历或已求过附件简历。"""

    raw = await _safe_eval_dict(page, "zhilian.inspect_resume_request_state")
    if not raw:
        raw = await _safe_eval_dict(page, ZHILIAN_RESUME_STATE_JS)
    if not raw:
        raw = _resume_state_from_text(await page.text())
    return ResumeRequestState(
        has_resume_attachment=bool(raw.get("hasResumeAttachment")),
        already_requested=bool(raw.get("alreadyRequested")),
        summary=str(raw.get("summary") or ""),
    )


async def request_resume(page: BrowserPage) -> dict[str, object]:
    """点击智联“要附件简历”。"""

    state = await inspect_resume_request_state(page)
    if state.has_resume_attachment:
        download = await _download_attachment_resume(page)
        return {"requested": False, "resumeReceived": True, "state": state, **download}
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
    )
    if not click.get("ok"):
        return {
            "requested": False,
            "blocked": True,
            "reason": "request_resume_click_failed",
            "state": state,
            "click": click,
        }
    await asyncio.sleep(1)
    after = await inspect_resume_request_state(page)
    if after.has_resume_attachment:
        download = await _download_attachment_resume(page)
        return {
            "requested": True,
            "resumeReceived": True,
            "confirmed": bool(after.already_requested),
            "verifyReason": "" if download.get("ok") else str(download.get("reason") or ""),
            "state": after,
            **download,
        }
    return {
        "requested": True,
        "confirmed": True,
        "verifyReason": "" if after.already_requested else "no_confirm_required",
        "state": after,
        "click": click,
    }


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
    try:
        pressed = await page.press(selectors.CHAT_INPUT, "Enter", timeout_ms=5000)
    except Exception as error:
        pressed = False
        press_error = str(error)
    else:
        press_error = ""
    if pressed:
        await asyncio.sleep(1)
        verified = await _verify_recent_mine_message(page, message)
        if verified.get("verified"):
            result = {
                "ok": True,
                "action": "press",
                "label": "智联输入框 Enter 发送",
                "verified": True,
                "verify": verified,
            }
            _record_reliable_action(page, result)
            return result
    button = await _find_button_by_text(page, "button, [role='button']", "发送")
    if button is not None:
        return await reliable_click_element(
            page,
            button,
        label="智联发送按钮",
        verify=lambda: _verify_recent_mine_message(page, message),
    )
    if press_error:
        return {"ok": False, "reason": "press_enter_failed", "error": press_error}
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


def _record_reliable_action(page: BrowserPage, result: dict[str, object]) -> None:
    actions = getattr(page, "reliable_actions", None)
    if isinstance(actions, list):
        actions.append(result)


async def _click_request_resume_confirm(page: BrowserPage) -> dict[str, object]:
    result = await _safe_eval_dict(page, "zhilian.click_visible_request_resume_confirm")
    if result:
        if result.get("clicked") or result.get("blocked"):
            return result
        if result.get("reason") == "confirm_button_not_visible":
            return {**result, "blocked": True}
    result = await _safe_eval_dict(page, _CLICK_VISIBLE_CONFIRM_JS)
    if result:
        if result.get("clicked") or result.get("blocked"):
            return result
        if result.get("reason") == "confirm_button_not_visible":
            return {**result, "blocked": True}
    legacy_clicked = await _legacy_click_request_resume_confirm(page)
    return {
        "clicked": bool(legacy_clicked),
        "reason": "" if legacy_clicked else "confirm_button_not_found",
        "source": "legacy_selector_fallback",
    }


async def _legacy_click_request_resume_confirm(page: BrowserPage) -> bool:
    result = await reliable_confirm(
        page,
        selectors.REQUEST_RESUME_CONFIRM_BUTTON,
        selectors.REQUEST_RESUME_CONFIRM_TEXTS,
        label="智联要附件简历确认",
    )
    return bool(result.get("ok"))


async def _download_attachment_resume(page: BrowserPage) -> dict[str, object]:
    context = await _safe_eval_dict(page, "zhilian.read_chat_context")
    if not context:
        context = await _safe_eval_dict(page, READ_CHAT_CONTEXT_JS)
    candidate_name = str(context.get("name") or context.get("candidate_name") or "")
    applied_position = str(context.get("position") or context.get("appliedPosition") or "")
    try:
        download = await page.click_and_download(
            _CLICK_VIEW_ATTACHMENT_RESUME_DOWNLOAD_JS,
            timeout_ms=30000,
        )
    except Exception as error:
        return {
            "ok": False,
            "downloaded": False,
            "blocked": True,
            "reason": "download_api_unavailable",
            "error": str(error),
            "sourceKind": "attachment",
        }
    content = download.get("bytes") if isinstance(download, dict) else None
    download_meta = _download_metadata(download)
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not isinstance(content, bytes):
        reason = (
            str(download.get("reason") or "attachment_download_missing")
            if isinstance(download, dict)
            else "attachment_download_missing"
        )
        return {
            "ok": False,
            "downloaded": False,
            "blocked": True,
            "reason": reason,
            "download": download_meta,
            "sourceKind": "attachment",
        }
    result = save_zhilian_resume_bytes(
        content,
        candidate_name=candidate_name,
        applied_position=applied_position,
        filename=str(download.get("filename") or ""),
    )
    return {**result, "sourceKind": "attachment", "download": download_meta}


def _download_metadata(download: object) -> dict[str, object]:
    if not isinstance(download, dict):
        return {}
    return {
        str(key): value
        for key, value in download.items()
        if key not in {"bytes", "bytesBase64"}
    }


async def _verify_chat_ready(page: BrowserPage) -> dict[str, object]:
    return {"verified": await page.wait_for(selectors.CHAT_READY, timeout_ms=6500)}


async def _find_session_for_state(
    page: BrowserPage,
    state: dict[str, object],
) -> BrowserElement | None:
    row_id = str(state.get("id") or "").lstrip("_")
    label = str(state.get("label") or "").strip()
    rows = await page.query_all(selectors.SESSION_ITEM)
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


async def _open_session_from_state(
    page: BrowserPage,
    state: dict[str, object],
) -> dict[str, object]:
    """用真实 DOM 内部点击打开智联会话，失败时回退到通用点击。"""

    target = {
        "id": str(state.get("id") or ""),
        "label": str(state.get("label") or ""),
        "index": _safe_int(state.get("index")),
    }
    result = await _safe_eval_dict(page, CLICK_SESSION_ROW_JS, target)
    if result.get("opened"):
        await asyncio.sleep(1)
        verified = await _verify_chat_ready(page)
        context = await _read_context_payload(page)
        identity_ok = _state_matches_context(state, context)
        if verified.get("verified") and identity_ok:
            return {"ok": True, "method": "dom_inner_click", "result": result}
    row = await _find_session_for_state(page, state)
    if row is None:
        return {
            "ok": False,
            "method": "dom_inner_click",
            "result": result,
            "reason": "session_row_not_found",
        }
    fallback = await reliable_click_element(
        page,
        row,
        label="智联候选人会话",
        verify=lambda: _verify_chat_ready(page),
    )
    if not fallback.get("ok"):
        return fallback
    context = await _read_context_payload(page)
    if _state_matches_context(state, context):
        return fallback
    return {
        **fallback,
        "ok": False,
        "reason": "candidate_identity_mismatch",
        "context": context,
    }


async def _verify_unread_active(page: BrowserPage) -> dict[str, object]:
    state = await _unread_filter_state(page)
    return {
        "verified": bool(state.get("active")),
        "reason": "" if state.get("active") else "unread_filter_not_active",
        "state": state,
    }


async def _unread_filter_state(page: BrowserPage) -> dict[str, object]:
    if bool(getattr(page, "unread_selected", False)):
        return {"active": True, "label": "未读", "source": "fake_page"}
    raw = await _safe_eval_dict(page, "zhilian.unread_filter_state")
    if not raw:
        raw = await _safe_eval_dict(page, UNREAD_FILTER_STATE_JS)
    return raw if raw else {"active": False, "reason": "unread_state_unknown"}


async def _trusted_click_unread_filter(page: BrowserPage) -> dict[str, object]:
    """Click the visible Zhilian unread checkbox through the BrowserElement path."""

    for element in await page.query_all(selectors.UNREAD_FILTER):
        label = " ".join((await element.text()).split())
        if not (label == "未读" or ("未读" in label and len(label) <= 8)):
            continue
        click = await reliable_click_element(page, element, label="智联未读筛选可信点击")
        await asyncio.sleep(1)
        state = await _unread_filter_state(page)
        rows = await read_unread_row_states(page)
        return {
            "attempted": True,
            "ok": bool(click.get("ok")),
            "label": label,
            "click": click,
            "state": state,
            "rows": rows,
        }
    return {"attempted": False, "reason": "unread_filter_not_found"}


async def _read_context_payload(page: BrowserPage) -> dict[str, object]:
    context = await _safe_eval_dict(page, "zhilian.read_chat_context")
    if context:
        return context
    return await _safe_eval_dict(page, READ_CHAT_CONTEXT_JS)


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
    result = await _safe_eval_dict(page, "zhilian.visible_request_resume_confirm_state")
    if result:
        return {
            "verified": bool(result.get("visible")),
            "reason": "" if result.get("visible") else str(result.get("reason") or ""),
            "source": result.get("source") or "script",
        }
    result = await _safe_eval_dict(page, _VISIBLE_CONFIRM_STATE_JS)
    if result:
        return {
            "verified": bool(result.get("visible")),
            "reason": "" if result.get("visible") else str(result.get("reason") or ""),
            "source": result.get("source") or "script",
        }
    for element in await page.query_all(selectors.REQUEST_RESUME_CONFIRM_BUTTON):
        label = await element.text()
        if any(text in label for text in selectors.REQUEST_RESUME_CONFIRM_TEXTS):
            return {"verified": True}
    return {"verified": False, "reason": "confirm_not_visible"}


async def _request_resume_progress_visible(page: BrowserPage) -> dict[str, object]:
    confirm = await _confirm_button_visible(page)
    if confirm.get("verified"):
        return {**confirm, "source": confirm.get("source") or "confirm_visible"}
    state = await inspect_resume_request_state(page)
    if state.has_resume_attachment:
        return {"verified": True, "source": "attachment_visible"}
    if state.already_requested:
        return {"verified": True, "source": "already_requested"}
    return {
        "verified": False,
        "reason": str(confirm.get("reason") or "request_resume_progress_not_visible"),
    }


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
        if message.text.strip():
            return message
    return None


def _raw_context_has_content(raw: dict[str, object]) -> bool:
    messages = raw.get("messages") if raw else None
    return bool(
        raw
        and (
            raw.get("name")
            or raw.get("candidate_name")
            or raw.get("position")
            or raw.get("appliedPosition")
            or (isinstance(messages, list) and messages)
        )
    )


def _resume_state_from_text(text: str) -> dict[str, object]:
    has_file_name = any(
        marker in text.lower() for marker in (".pdf", ".doc", ".docx", ".wps", ".rtf")
    )
    has_resume_attachment = selectors.ATTACHMENT_VIEW_TEXT in text or has_file_name
    already_requested = (
        "已要附件简历" in text
        or "已向对方要附件简历" in text
        or "已请求附件简历" in text
    )
    can_request = (
        not has_resume_attachment
        and not already_requested
        and selectors.REQUEST_RESUME_TEXT in text
    )
    evidence = ""
    if has_file_name:
        evidence = "file_name"
    elif selectors.ATTACHMENT_VIEW_TEXT in text:
        evidence = "view_attachment_resume"
    elif already_requested:
        evidence = "already_requested"
    elif can_request:
        evidence = "request_button"
    return {
        "hasResumeAttachment": has_resume_attachment,
        "alreadyRequested": already_requested,
        "canRequestResume": can_request,
        "summary": text[-240:],
        "evidence": evidence,
        "source": "text_fallback",
    }


def _state_matches_context(state: dict[str, object], context: dict[str, object]) -> bool:
    if not context:
        return False
    label = "".join(str(state.get("label") or "").split())
    expected_position = "".join(str(state.get("position") or "").split())
    name = "".join(str(context.get("name") or context.get("candidate_name") or "").split())
    position = "".join(str(context.get("position") or context.get("appliedPosition") or "").split())
    if name and label and name not in label:
        return False
    if name and name in label:
        return True
    if expected_position and position and (
        expected_position in position or position in expected_position
    ):
        return True
    return False


def _click_attempted(result: dict[str, object]) -> bool:
    attempts = result.get("attempts")
    if not isinstance(attempts, list):
        return False
    return any(isinstance(item, dict) and item.get("clicked") for item in attempts)


def _should_skip_label(label: str) -> bool:
    compact = "".join(str(label or "").split())
    return (
        not compact
        or _is_read_label(compact)
        or any(term in compact for term in SYSTEM_SKIP_TERMS)
    )


def _is_read_label(label: str) -> bool:
    compact = "".join(str(label or "").split())
    return "[已读]" in compact or "[送达]" in compact


def _position_matches(actual: str, expected: str) -> bool:
    left = "".join(actual.split())
    right = "".join(expected.split())
    return bool(left and right and (left in right or right in left))


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_unread_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        unread_count = _safe_int(item.get("unread_count") or item.get("unreadCount"))
        if unread_count <= 0 and item.get("hasUnreadBadge"):
            unread_count = 1
        label = str(item.get("label") or "")
        if unread_count <= 0:
            continue
        if _should_skip_label(label):
            continue
        rows.append(
            {
                "index": _safe_int(item.get("index")),
                "id": str(item.get("id") or ""),
                "label": label,
                "position": str(item.get("position") or ""),
                "unread_count": unread_count,
            }
        )
    return rows


_VISIBLE_CONFIRM_STATE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const dialogs = Array.from(document.querySelectorAll(
    ".km-modal--open, .km-dialog, .im-dialog, .el-dialog, .el-message-box, [role='dialog']"
  )).filter(visible);
  const confirmTexts = ["确定", "确认", "发送", "要附件简历"];
  for (const dialog of dialogs) {
    const buttons = Array.from(dialog.querySelectorAll(
      "button, .el-button, [role='button'], span, div"
    )).filter(visible);
    const button = buttons.find((item) => {
      const value = text(item).replace(/\s+/g, "");
      return confirmTexts.some((label) => value === label || value.includes(label));
    });
    if (button) {
      return { visible: true, label: text(button), source: "visible_dialog" };
    }
  }
  return { visible: false, reason: "confirm_button_not_visible" };
}
"""


_CLICK_VISIBLE_CONFIRM_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const dialogs = Array.from(document.querySelectorAll(
    ".km-modal--open, .km-dialog, .im-dialog, .el-dialog, .el-message-box, [role='dialog']"
  )).filter(visible);
  const confirmTexts = ["确定", "确认", "发送", "要附件简历"];
  for (const dialog of dialogs) {
    const buttons = Array.from(dialog.querySelectorAll(
      "button, .el-button, [role='button'], span, div"
    )).filter(visible);
    const button = buttons.find((item) => {
      const value = text(item).replace(/\s+/g, "");
      return confirmTexts.some((label) => value === label || value.includes(label));
    });
    if (button) {
      button.click();
      return { clicked: true, label: text(button), source: "visible_dialog" };
    }
  }
  return { clicked: false, blocked: true, reason: "confirm_button_not_visible" };
}
"""


_CLICK_VIEW_ATTACHMENT_RESUME_DOWNLOAD_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const clickTargetFor = (el) => {
    if (!el) return null;
    const selector = [
      "button",
      "a",
      "[role='button']",
      "[onclick]",
      ".file-card",
      ".attachment-card",
      ".message-file",
      ".im-file",
    ].join(", ");
    return el.closest(selector) || el;
  };
  const clickElement = (el) => {
    const target = clickTargetFor(el);
    if (!target) return { clicked: false, reason: "click_target_missing" };
    try {
      target.scrollIntoView({ block: "center", inline: "center" });
    } catch (error) {
      target.scrollIntoView();
    }
    const rect = target.getBoundingClientRect();
    const options = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: rect.left + Math.max(1, rect.width / 2),
      clientY: rect.top + Math.max(1, rect.height / 2),
    };
    target.dispatchEvent(new MouseEvent("mousedown", options));
    target.dispatchEvent(new MouseEvent("mouseup", options));
    if (typeof target.click === "function") {
      target.click();
    } else {
      target.dispatchEvent(new MouseEvent("click", options));
    }
    return {
      clicked: true,
      label: text(target) || text(el),
      source: "zhilian_view_attachment_resume_download",
    };
  };
  const detail = document.querySelector("#im-session-detail, .im-session-detail") || document;
  const candidates = Array.from(detail.querySelectorAll("button, a, [role='button'], span, div"))
    .filter(visible)
    .filter((item) => text(item).replace(/\s+/g, "").includes("查看附件简历"));
  const target = candidates.find((item) => {
    const value = text(item).replace(/\s+/g, "");
    return value === "查看附件简历";
  }) || candidates[candidates.length - 1];
  if (!target) {
    return { clicked: false, reason: "view_attachment_button_not_found" };
  }
  return clickElement(target);
}
"""
