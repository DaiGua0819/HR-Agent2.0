"""51job 聊天页动作。

负责未读筛选、会话行跳过规则、上下文读取和消息发送。这里不做岗位业务判断，
共享 `ConversationRunner` 会根据统一规则推进答疑、筛选和求简历。
"""

from __future__ import annotations

import asyncio
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
    CLICK_THREAD_BY_IDENTITY_JS,
    OPENED_CANDIDATE_STATE_JS,
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
APP_DOWNLOAD_URL_PART = "app.51job.com/51job"
_TIME_LINE_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
_UNREAD_COUNT_PATTERN = re.compile(r"^\d+$")


async def open_chat_page(page: BrowserPage) -> None:
    """进入 51job 人才沟通页。"""

    await install_app_download_blocker(page)
    await navigate_chat_page(page)


async def select_unread_filter(page: BrowserPage) -> dict[str, object]:
    """刷新并切换 51job 未读筛选。"""

    await install_app_download_blocker(page)
    _clear_failed_open_keys(page)
    return await refresh_unread_filter(page)


async def select_positions(
    page: BrowserPage, target_position: str | None = None
) -> dict[str, object]:
    """选择全部岗位或目标岗位。"""

    await install_app_download_blocker(page)
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
                "name": await row.attr("name") or "",
                "position": await row.attr("position") or "",
                "unread_count": unread_count,
            }
        )
    return fallback


async def find_next_thread(
    page: BrowserPage,
    *,
    owner: str,
    exclude_ids: set[str] | None = None,
) -> ConversationRef | None:
    """打开下一个未读且未回复过的 51job 会话。"""

    excluded = {str(item) for item in exclude_ids or set() if str(item)}
    failed_open_keys = _failed_open_keys(page)
    for state in await read_unread_row_states(page):
        label = str(state.get("label") or "")
        conversation_id = str(state.get("id") or label)
        identity_key = _state_identity_key(state)
        if (
            conversation_id in excluded
            or identity_key in excluded
            or identity_key in failed_open_keys
        ):
            continue
        if should_skip_thread_label(label) or _safe_int(state.get("unread_count")) <= 0:
            continue
        row = await _find_thread_for_state(page, state, allow_index=False)
        if row is None:
            row = None
        expected = {
            "id": str(state.get("id") or label),
            "label": label,
            "name": str(
                state.get("name")
                or (await row.attr("name") if row is not None else "")
                or ""
            ),
            "position": str(
                state.get("position")
                or (await row.attr("position") if row is not None else "")
                or ""
            ),
            "latest_message": str(
                state.get("latest_message")
                or state.get("latestMessage")
                or state.get("message")
                or ""
            ),
        }
        click = await click_thread_by_state(page, state, expected=expected, row=row)
        ready = bool(click.get("ok") or click.get("clicked")) or await wait_chat_ready(
            page,
            timeout_ms=6500,
        )
        opened = await verify_opened_candidate(page, expected, chat_ready=ready)
        if opened.get("opened"):
            return ConversationRef(Platform.JOB51, owner, str(expected["id"]))
        failed_open_keys.add(identity_key)
    return None


async def click_thread_by_state(
    page: BrowserPage,
    state: dict[str, object],
    *,
    expected: dict[str, object] | None = None,
    row: Any | None = None,
) -> dict[str, object]:
    """Click a 51job conversation row with a JS fallback for virtual-list rows."""

    await install_app_download_blocker(page)
    if expected:
        identity_click = await _click_thread_by_identity(page, state, expected)
        if identity_click.get("clicked"):
            opened = await verify_opened_candidate(
                page,
                expected,
                chat_ready=await wait_chat_ready(page, timeout_ms=6500),
                timeout_ms=5000,
            )
            identity_click["ok"] = bool(opened.get("opened"))
            identity_click["verified"] = bool(opened.get("opened"))
            identity_click["verification"] = opened
            if not opened.get("opened"):
                identity_click["reason"] = opened.get("reason") or "candidate_identity_mismatch"
            return identity_click
        if identity_click.get("reason") == "thread_identity_ambiguous":
            return identity_click
        target_row = row or await _find_thread_for_state(page, state, allow_index=False)
        if target_row is not None:
            primary = await reliable_click_element(
                page,
                target_row,
                label="51job候选人会话",
                verify=lambda: _verify_opened_candidate_once(
                    page,
                    expected,
                    chat_ready=True,
                ),
            )
            if primary.get("ok"):
                return primary
    payload = {
        "id": str(state.get("id") or "").lstrip("_"),
        "label": str(state.get("label") or "").strip(),
        "index": _safe_int(state.get("index")),
        "allowIndexFallback": expected is None,
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
            || (expected.allowIndexFallback ? rows[Number(expected.index || 0)] : null);
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
    return result or {"clicked": False, "reason": "thread_row_dom_click_failed"}


async def _click_thread_by_identity(
    page: BrowserPage,
    state: dict[str, object],
    expected: dict[str, object],
) -> dict[str, object]:
    payload = {
        "id": str(expected.get("id") or state.get("id") or "").lstrip("_"),
        "label": str(expected.get("label") or state.get("label") or "").strip(),
        "name": str(expected.get("name") or state.get("name") or "").strip(),
        "position": str(expected.get("position") or state.get("position") or "").strip(),
        "latest_message": str(
            expected.get("latest_message")
            or expected.get("latestMessage")
            or state.get("latest_message")
            or state.get("latestMessage")
            or state.get("message")
            or ""
        ).strip(),
    }
    if not any(payload.get(key) for key in ("id", "label", "name", "position")):
        return {"clicked": False, "reason": "thread_identity_fields_missing"}
    result = await _safe_eval_dict(page, "job51.click_thread_by_identity", payload)
    if not result:
        result = await _safe_eval_dict(page, CLICK_THREAD_BY_IDENTITY_JS, payload)
    return result or {"clicked": False, "reason": "thread_identity_click_failed"}


async def install_app_download_blocker(page: BrowserPage) -> dict[str, object]:
    """Install guards that prevent 51job app-download tabs from lingering."""

    script_result = await _safe_eval_dict(
        page,
        """
        () => {
          const key = "__job51AppDownloadBlockerInstalled";
          const blockedPart = "app.51job.com/51job";
          const shouldBlock = (url) => String(url || "").includes(blockedPart);
          if (window[key]) return { installed: true, alreadyInstalled: true };
          window[key] = true;
          window.__job51BlockedAppDownloadUrls = window.__job51BlockedAppDownloadUrls || [];
          const originalOpen = window.open;
          window.open = function job51BlockedOpen(url, ...args) {
            if (shouldBlock(url)) {
              window.__job51BlockedAppDownloadUrls.push(String(url || ""));
              return null;
            }
            return originalOpen.call(window, url, ...args);
          };
          const preventBlockedNavigation = (event) => {
            const path = event.composedPath ? event.composedPath() : [];
            const link = path.find((node) => {
              return node && typeof node.href === "string" && shouldBlock(node.href);
            });
            if (!link) return;
            window.__job51BlockedAppDownloadUrls.push(link.href);
            event.preventDefault();
            event.stopImmediatePropagation();
          };
          document.addEventListener("click", preventBlockedNavigation, true);
          document.addEventListener("auxclick", preventBlockedNavigation, true);
          const originalAnchorClick = HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click = function job51BlockedAnchorClick(...args) {
            if (shouldBlock(this.href)) {
              window.__job51BlockedAppDownloadUrls.push(this.href);
              return undefined;
            }
            return originalAnchorClick.apply(this, args);
          };
          return { installed: true, source: "page_script" };
        }
        """,
    )
    context_result: dict[str, object] = {}
    installer = getattr(page, "install_url_popup_blocker", None)
    if callable(installer):
        try:
            context_result = await installer(APP_DOWNLOAD_URL_PART)
        except Exception as error:
            context_result = {"installed": False, "error": str(error)}
    return {
        "installed": bool(script_result.get("installed") or context_result.get("installed")),
        "script": script_result,
        "context": context_result,
    }


async def verify_opened_candidate(
    page: BrowserPage,
    expected: dict[str, object],
    *,
    chat_ready: bool = False,
    timeout_ms: int = 5000,
    interval_ms: int = 150,
) -> dict[str, object]:
    """校验虚拟列表点击后，右侧聊天区确实切到了目标候选人。"""

    deadline = asyncio.get_running_loop().time() + max(timeout_ms, 0) / 1000
    while True:
        result = await _verify_opened_candidate_once(page, expected, chat_ready=chat_ready)
        if result.get("opened") or asyncio.get_running_loop().time() >= deadline:
            return result
        await asyncio.sleep(max(interval_ms, 0) / 1000)


async def _verify_opened_candidate_once(
    page: BrowserPage,
    expected: dict[str, object],
    *,
    chat_ready: bool,
) -> dict[str, object]:
    raw = await _safe_eval_dict(page, "job51.opened_candidate_state", expected)
    if raw.get("opened"):
        return _ensure_actual_source(raw)
    right_header = await _safe_eval_dict(page, OPENED_CANDIDATE_STATE_JS, expected)
    if right_header.get("opened"):
        return _ensure_actual_source(right_header)
    if right_header.get("source") == "right_header":
        actual = right_header.get("actual") if isinstance(right_header.get("actual"), dict) else {}
        result = _opened_candidate_result(
            expected,
            actual_name=str(actual.get("name") or "").strip(),
            actual_position=str(actual.get("position") or "").strip(),
            actual_label=str(actual.get("label") or actual.get("headerText") or "").strip(),
            actual_source=str(actual.get("source") or "right_header").strip(),
            chat_ready=bool(chat_ready or right_header.get("chatReady")),
        )
        if (
            result.get("opened")
            or result["actual"]["name"]
            or result["actual"]["position"]
            or result["actual"]["label"]
        ):
            return result
    context = await _safe_eval_dict(page, "job51.read_chat_context")
    if not context:
        context = await _safe_eval_dict(page, READ_CHAT_CONTEXT_JS)
    actual_name = str(context.get("name") or context.get("candidate_name") or "").strip()
    actual_position = str(context.get("position") or context.get("appliedPosition") or "").strip()
    actual_label = str(context.get("label") or "").strip()
    actual_source = str(context.get("source") or "chat_context").strip()
    return _opened_candidate_result(
        expected,
        actual_name=actual_name,
        actual_position=actual_position,
        actual_label=actual_label,
        actual_source=actual_source,
        chat_ready=chat_ready,
    )


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
        if message.text.strip():
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


def _opened_candidate_result(
    expected: dict[str, object],
    *,
    actual_name: str,
    actual_position: str,
    actual_label: str,
    actual_source: str,
    chat_ready: bool,
) -> dict[str, object]:
    expected_name = str(expected.get("name") or "").strip()
    expected_position = str(expected.get("position") or "").strip()
    expected_label = str(expected.get("label") or "").strip()
    expected_name_from_label = _infer_name_from_label(expected_label)
    effective_expected_name = expected_name or expected_name_from_label
    name_ok = bool(
        effective_expected_name
        and actual_name
        and _text_matches(actual_name, effective_expected_name)
    )
    name_conflict = bool(effective_expected_name and actual_name and not name_ok)
    position_conflict = bool(
        expected_position
        and actual_position
        and not _position_matches(actual_position, expected_position)
    )
    position_ok = bool(
        not name_conflict
        and expected_position
        and actual_position
        and _position_matches(actual_position, expected_position)
    )
    label_ok = bool(expected_label and actual_label and _text_matches(actual_label, expected_label))
    opened = bool(
        chat_ready
        and (label_ok or (name_ok and not position_conflict) or (actual_name and position_ok))
    )
    return {
        "opened": opened,
        "reason": "" if opened else "candidate_identity_mismatch",
        "chatReady": chat_ready,
        "expected": expected,
        "actual": {
            "name": actual_name,
            "position": actual_position,
            "label": actual_label,
            "source": actual_source,
        },
    }


def _ensure_actual_source(payload: dict[str, object]) -> dict[str, object]:
    source = str(payload.get("source") or "").strip()
    actual = payload.get("actual")
    if source and isinstance(actual, dict) and not actual.get("source"):
        actual["source"] = source
    return payload


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _state_identity_key(state: dict[str, object]) -> str:
    name = _compact_identity_text(state.get("name"))
    position = _compact_identity_text(state.get("position") or state.get("jobName"))
    latest = _compact_identity_text(
        state.get("latest_message")
        or state.get("latestMessage")
        or state.get("message")
        or ""
    )
    row_id = _compact_identity_text(state.get("id"))
    label = _compact_identity_text(state.get("label"))
    if name or position or latest:
        return "|".join(("identity", name, position, latest))
    if row_id:
        return f"id|{row_id}"
    return f"label|{label}"


def _compact_identity_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _infer_name_from_label(label: str) -> str:
    for line in _identity_label_lines(label):
        if (
            _UNREAD_COUNT_PATTERN.match(line)
            or _TIME_LINE_PATTERN.match(line)
            or line in {"宸叉姇", "蹇嵎鍥炲", "涓嶅尮閰?", "已投", "快捷回复", "不匹配"}
            or line.startswith("[")
        ):
            continue
        if len(line) <= 16 and not any(term in line for term in ("您好", "职位", "岗位", "公司")):
            return line
    return ""


def _infer_latest_message_from_label(label: str) -> str:
    candidates = []
    for line in _identity_label_lines(label):
        if (
            _UNREAD_COUNT_PATTERN.match(line)
            or _TIME_LINE_PATTERN.match(line)
            or line in {"宸叉姇", "蹇嵎鍥炲", "涓嶅尮閰?", "已投", "快捷回复", "不匹配"}
            or line.startswith("[")
        ):
            continue
        candidates.append(line)
    return candidates[-1] if len(candidates) >= 2 else ""


def _identity_label_lines(label: str) -> list[str]:
    return [line.strip() for line in str(label or "").splitlines() if line.strip()]


def _failed_open_keys(page: BrowserPage) -> set[str]:
    keys = getattr(page, "_job51_failed_open_keys", None)
    if isinstance(keys, set):
        return keys
    keys = set()
    try:
        page._job51_failed_open_keys = keys
    except Exception:
        return keys
    return keys


def _clear_failed_open_keys(page: BrowserPage) -> None:
    try:
        page._job51_failed_open_keys = set()
    except Exception:
        return


async def _verify_chat_ready(page: BrowserPage) -> dict[str, object]:
    return {"verified": await wait_chat_ready(page, timeout_ms=6500)}


async def _find_thread_for_state(
    page: BrowserPage,
    state: dict[str, object],
    *,
    allow_index: bool = True,
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
    if allow_index:
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
        name = str(item.get("name") or item.get("candidateName") or "")
        latest_message = str(
            item.get("latest_message")
            or item.get("latestMessage")
            or item.get("message")
            or ""
        )
        if not name:
            name = _infer_name_from_label(label)
        if not latest_message:
            latest_message = _infer_latest_message_from_label(label)
        rows.append(
            {
                "index": _safe_int(item.get("index")),
                "id": str(item.get("id") or ""),
                "label": label,
                "name": name,
                "position": str(item.get("position") or item.get("jobName") or ""),
                "latest_message": latest_message,
                "unread_count": unread_count,
            }
        )
    return rows
