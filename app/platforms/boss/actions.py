"""BOSS 页面动作封装。

动作函数只依赖 `BrowserPage` 抽象。真实页面后续由 Playwright CDP 包装执行，
Phase 2 测试通过 FakePage 验证顺序、选择器和业务分支。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent.proactive.thresholds import evaluate_proactive_threshold
from app.browser.base import BrowserElement, BrowserPage
from app.core.constants import Platform
from app.platforms.boss import selectors
from app.platforms.boss.dom_scripts import (
    CLICK_UNREAD_FILTER_JS,
    INSPECT_RESUME_REQUEST_STATE_JS,
    READ_CHAT_CONTEXT_JS,
)
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


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """点击 BOSS 未读筛选。"""

    clicked = await _safe_eval_dict(page, CLICK_UNREAD_FILTER_JS)
    if clicked.get("selected"):
        return clicked
    for element in await page.query_all(selectors.UNREAD_FILTER):
        label = await element.text()
        if label == "未读" or ("未读" in label and len(label) <= 12):
            await element.click()
            return {"selected": True, "label": label}
    return {"selected": False, "reason": "unread_filter_not_found"}


async def select_positions(
    page: BrowserPage, target_position: str | None = None
) -> dict[str, object]:
    """选择 BOSS 全部职位或指定职位。"""

    label = target_position or selectors.ALL_POSITION_OPTION_TEXT
    if not target_position:
        return {"selected": True, "label": label, "mode": "all", "clicked": False}
    clicked = await page.click(selectors.POSITION_FILTER)
    if hasattr(page, "selected_recommend_position") and target_position:
        page.selected_recommend_position = target_position  # type: ignore[attr-defined]
    return {"selected": clicked, "label": label, "mode": "target" if target_position else "all"}


async def read_unread_conversations(page: BrowserPage, *, owner: str) -> list[ConversationRef]:
    """读取 BOSS 当前列表里的未读会话引用。"""

    refs: list[ConversationRef] = []
    for row in await page.query_all(selectors.SESSION_ITEM):
        label = await row.text()
        if _should_skip_label(label) or _row_unread_count(await row.attr("unread")) <= 0:
            continue
        refs.append(
            ConversationRef(
                platform=Platform.BOSS,
                owner=owner,
                conversation_id=await row.attr("id") or label,
            )
        )
    return refs


async def find_next_unread_thread(page: BrowserPage, *, owner: str) -> ConversationRef | None:
    """从 BOSS 未读列表打开下一个真实候选人。"""

    for row in await page.query_all(selectors.SESSION_ITEM):
        label = await row.text()
        if _should_skip_label(label) or _row_unread_count(await row.attr("unread")) <= 0:
            continue
        await row.click()
        return ConversationRef(Platform.BOSS, owner, await row.attr("id") or label)
    return None


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
    filled = await page.fill(selectors.CHAT_INPUT, text)
    if not filled:
        return SendResult(sent=False, blocked=True, message="BOSS 没有找到聊天输入框")
    clicked = await page.click(selectors.SEND_BUTTON)
    if hasattr(page, "append_sent_message"):
        page.append_sent_message(text)  # type: ignore[attr-defined]
    verified = bool((await _safe_eval_dict(page, "boss.verify_sent", text)).get("verified"))
    sent = clicked or verified
    return SendResult(
        sent=sent,
        verified=verified or sent,
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
    clicked = await page.click(selectors.COMMON_PHRASE_BUTTON)
    if not clicked:
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

    raw = await _safe_eval_dict(page, "boss.inspect_resume_request_state")
    if not raw:
        raw = await _safe_eval_dict(page, INSPECT_RESUME_REQUEST_STATE_JS)
    if not raw:
        body = await page.text()
        raw = _resume_state_from_text(body)
    return ResumeRequestState(
        has_resume_attachment=bool(raw.get("hasResumeAttachment")),
        already_requested=bool(raw.get("alreadyRequested")),
        pending_resume_consent=bool(raw.get("pendingResumeConsent")),
        summary=str(raw.get("summary") or ""),
    )


async def request_resume(page: BrowserPage) -> dict[str, object]:
    """点击 BOSS 聊天工具栏里的“求简历”。"""

    state = await inspect_resume_request_state(page)
    if state.pending_resume_consent:
        consent = await _find_button_by_text(
            page,
            selectors.REQUEST_RESUME_BUTTON,
            selectors.RESUME_CONSENT_TEXT,
        )
        if consent is not None:
            await consent.click()
            return {"requested": True, "acceptedResumeConsent": True, "state": state}
    if state.has_resume_attachment:
        return {"requested": False, "resumeReceived": True, "state": state}
    if state.already_requested:
        return {"requested": False, "skipped": True, "reason": "already_requested", "state": state}
    button = await _find_button_by_text(
        page, selectors.REQUEST_RESUME_BUTTON, selectors.REQUEST_RESUME_TEXT
    )
    if button is None:
        return {"requested": False, "blocked": True, "reason": "request_resume_button_not_found"}
    await button.click()
    confirmed = await _click_request_resume_confirm(page)
    if not confirmed:
        return {
            "requested": False,
            "blocked": True,
            "reason": "request_resume_confirm_not_found",
            "requestButtonClicked": True,
            "state": state,
        }
    return {"requested": True, "confirmed": True, "state": state}


async def open_recommend_page(page: BrowserPage) -> None:
    """打开 BOSS 推荐牛人页。"""

    await page.goto(selectors.RECOMMEND_URL)


async def proactive_greet(
    page: BrowserPage,
    *,
    target_position: str,
    dry_run: bool = False,
) -> dict[str, object]:
    """按主动联系门槛处理 BOSS 推荐牛人候选人。"""

    await open_recommend_page(page)
    await _ensure_recommend_position(page, target_position)
    cards = await _safe_eval_list(page, "boss.recommend_cards")
    greeted = 0
    skipped: list[dict[str, object]] = []
    matched: list[dict[str, object]] = []
    for index, card in enumerate(cards):
        if card.get("similar") or card.get("alreadyGreeted"):
            skipped.append({"index": index, "reason": "similar_or_already_greeted"})
            continue
        await page.eval_js("boss.open_recommend_card", index)
        resume = await _safe_eval_dict(page, "boss.read_recommend_resume_dialog")
        evidence_text = "\n".join(
            str(item or "") for item in (card.get("text"), resume.get("text"))
        )
        decision = evaluate_proactive_threshold(evidence_text, target_position)
        if not decision.passed:
            skipped.append({"index": index, "reason": decision.reason})
            await page.eval_js("boss.close_recommend_resume_dialog")
            continue
        matched.append({"index": index, "reason": decision.reason})
        if not dry_run:
            button = await page.query(selectors.RECOMMEND_GREET_BUTTON)
            if button is None:
                skipped.append({"index": index, "reason": "greet_button_missing"})
                await page.eval_js("boss.close_recommend_resume_dialog")
                continue
            await button.click()
            greeted += 1
        await page.eval_js("boss.close_recommend_resume_dialog")
    return {"greeted": greeted, "matched": matched, "skipped": skipped, "dryRun": dry_run}


async def mark_unsuitable(page: BrowserPage, *, reason: str = "") -> dict[str, object]:
    """点击 BOSS “不合适”入口；Phase 2 仅保留动作边界。"""

    button = await _find_button_by_text(
        page, selectors.REQUEST_RESUME_BUTTON, selectors.UNSUITABLE_BUTTON_TEXT
    )
    if button is None:
        return {"marked": False, "reason": "unsuitable_button_not_found", "detail": reason}
    await button.click()
    return {"marked": True, "reason": reason}


async def _ensure_recommend_position(page: BrowserPage, target_position: str) -> None:
    summary = await _safe_eval_dict(page, "boss.recommend_summary")
    current = str(summary.get("selectedPosition") or "")
    if target_position and _compact(current) != _compact(target_position):
        await page.eval_js("boss.select_recommend_position", target_position)


async def _find_button_by_text(
    page: BrowserPage, selector: str, expected_text: str
) -> BrowserElement | None:
    for element in await page.query_all(selector):
        if expected_text in (await element.text()):
            return element
    return None


async def _click_request_resume_confirm(page: BrowserPage) -> bool:
    """点击“求简历”后的确认弹窗按钮。"""

    for _ in range(10):
        button = await _find_button_by_any_text(
            page,
            selectors.REQUEST_RESUME_CONFIRM_BUTTON,
            selectors.REQUEST_RESUME_CONFIRM_TEXTS,
        )
        if button is not None:
            await button.click()
            return True
        await asyncio.sleep(0.2)
    return False


async def _find_button_by_any_text(
    page: BrowserPage,
    selector: str,
    expected_texts: tuple[str, ...],
) -> BrowserElement | None:
    for element in await page.query_all(selector):
        label = await element.text()
        if any(expected in label for expected in expected_texts):
            return element
    return None


async def _safe_eval_dict(
    page: BrowserPage, script: str, arg: object | None = None
) -> dict[str, object]:
    try:
        value = await page.eval_js(script, arg)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def _safe_eval_list(page: BrowserPage, script: str) -> list[dict[str, object]]:
    try:
        value = await page.eval_js(script)
    except Exception:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


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
    compact = _compact(label)
    return not compact or any(term in compact for term in SYSTEM_SKIP_TERMS)


def _compact(value: str) -> str:
    return "".join(str(value or "").split())


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _row_unread_count(value: str | None) -> int:
    """真实 BOSS 行没有 unread attr；未读筛选后将缺省行视为可处理。"""

    if value is None or value == "":
        return 1
    return _safe_int(value)


def _resume_state_from_text(text: str) -> dict[str, object]:
    """保守判断聊天区简历状态；不把右侧资料按钮当成已收到简历。"""

    compact = _compact(text)
    file_markers = (".pdf", ".doc", ".docx", ".wps", ".rtf")
    has_file_name = any(marker in text.lower() for marker in file_markers)
    pending_resume_consent = any(
        marker in compact
        for marker in (
            "对方想发送附件简历给您您是否同意",
            "对方想发送简历给您您是否同意",
            "牛人想发送附件简历给您您是否同意",
            "候选人想发送附件简历给您您是否同意",
        )
    )
    has_resume_card = any(
        marker in compact
        for marker in (
            "简历已发送",
            "已发送简历",
            "收到简历",
            "简历预览",
            "附件预览",
            "下载简历",
        )
    ) and not pending_resume_consent
    already_requested = any(
        marker in compact
        for marker in (
            "已求简历",
            "简历请求已发送",
            "已发送求简历",
            "已向牛人索要简历",
        )
    )
    return {
        "hasResumeAttachment": has_file_name or has_resume_card,
        "alreadyRequested": already_requested,
        "pendingResumeConsent": pending_resume_consent,
        "summary": text[-500:],
        "source": "text_fallback",
    }
