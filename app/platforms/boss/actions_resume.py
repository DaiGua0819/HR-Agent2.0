"""BOSS 求简历动作。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.browser.base import BrowserElement, BrowserPage
from app.browser.reliable_actions import reliable_click_element, reliable_confirm
from app.platforms.boss import selectors
from app.platforms.boss.dom_scripts import INSPECT_RESUME_REQUEST_STATE_JS
from app.platforms.types import ResumeRequestState


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
            click = await reliable_click_element(page, consent, label="BOSS同意接收简历")
            return {
                "requested": bool(click.get("ok")),
                "acceptedResumeConsent": bool(click.get("ok")),
                "state": state,
                "click": click,
            }
    if state.has_resume_attachment:
        return {"requested": False, "resumeReceived": True, "state": state}
    if state.already_requested:
        return {"requested": False, "skipped": True, "reason": "already_requested", "state": state}
    if (await _confirm_prompt_visible(page)).get("verified"):
        confirmed = await _click_request_resume_confirm(page)
        after_confirm = await inspect_resume_request_state(page)
        return {
            "requested": bool(confirmed and after_confirm.already_requested),
            "confirmed": bool(confirmed),
            "state": after_confirm,
        }
    button = await _find_button_by_text(
        page, selectors.REQUEST_RESUME_BUTTON, selectors.REQUEST_RESUME_TEXT
    )
    if button is None:
        return {"requested": False, "blocked": True, "reason": "request_resume_button_not_found"}
    click = await reliable_click_element(
        page,
        button,
        label="BOSS求简历",
        verify=lambda: _request_resume_click_verified(page),
    )
    if not click.get("ok"):
        return {
            "requested": False,
            "blocked": True,
            "reason": "request_resume_click_not_verified",
            "state": state,
            "click": click,
        }
    after_click = await inspect_resume_request_state(page)
    if after_click.already_requested:
        return {"requested": True, "confirmed": False, "state": after_click, "click": click}
    confirm_visible = await _confirm_button_visible(page)
    if not confirm_visible.get("verified"):
        return {
            "requested": False,
            "blocked": True,
            "reason": "request_resume_confirm_not_found",
            "requestButtonClicked": True,
            "state": state,
        }
    confirmed = await _click_request_resume_confirm(page)
    after_confirm = await inspect_resume_request_state(page)
    return {
        "requested": bool(confirmed and after_confirm.already_requested),
        "confirmed": bool(confirmed),
        "state": after_confirm,
    }


async def _click_request_resume_confirm(page: BrowserPage) -> bool:
    result = await reliable_confirm(
        page,
        selectors.REQUEST_RESUME_CONFIRM_BUTTON,
        selectors.REQUEST_RESUME_CONFIRM_TEXTS,
        label="BOSS求简历确认",
    )
    if result.get("ok"):
        return True
    fallback = await _click_confirm_by_prompt_position(page)
    return bool(fallback.get("clicked"))


async def _confirm_button_visible(page: BrowserPage) -> dict[str, object]:
    button = await _find_button_by_any_text(
        page,
        selectors.REQUEST_RESUME_CONFIRM_BUTTON,
        selectors.REQUEST_RESUME_CONFIRM_TEXTS,
    )
    if button is not None:
        return {"verified": True, "source": "button"}
    return await _confirm_prompt_visible(page)


async def _request_resume_click_verified(page: BrowserPage) -> dict[str, object]:
    """求简历点击后，确认弹层或系统消息任一出现即算点击生效。"""

    state = await inspect_resume_request_state(page)
    if state.already_requested:
        return {"verified": True, "reason": "already_requested_after_click"}
    confirm = await _confirm_button_visible(page)
    if confirm.get("verified"):
        return {"verified": True, "reason": "confirm_visible_after_click"}
    return {"verified": False, "reason": "request_resume_not_ready"}


async def _confirm_prompt_visible(page: BrowserPage) -> dict[str, object]:
    body = await page.text()
    visible = "确定向牛人索取简历" in body and "取消" in body and "确定" in body
    return {"verified": visible, "source": "body_text" if visible else "none"}


async def _click_confirm_by_prompt_position(page: BrowserPage) -> dict[str, object]:
    result = await page.eval_js(_CLICK_CONFIRM_BY_PROMPT_POSITION_JS)
    await asyncio.sleep(1)
    return result if isinstance(result, dict) else {"clicked": False, "reason": "bad_result"}


async def _find_button_by_text(
    page: BrowserPage, selector: str, expected_text: str
) -> BrowserElement | None:
    matches: list[tuple[int, int, BrowserElement]] = []
    for element in await page.query_all(selector):
        label = " ".join((await element.text()).split())
        if expected_text not in label:
            continue
        priority = 0 if label == expected_text else 1
        matches.append((priority, len(label), element))
    if not matches:
        return None
    return sorted(matches, key=lambda item: (item[0], item[1]))[0][2]


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


def _resume_state_from_text(text: str) -> dict[str, object]:
    """保守判断聊天区简历状态；不把右侧资料按钮当成已收到简历。"""

    compact = _compact(text)
    has_file_name = any(marker in text.lower() for marker in (".pdf", ".doc", ".docx", ".wps"))
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
        for marker in ("简历已发送", "已发送简历", "收到简历", "简历预览", "下载简历")
    ) and not pending_resume_consent
    already_requested = any(
        marker in compact
        for marker in ("已求简历", "简历请求已发送", "已发送求简历", "已向牛人索要简历")
    )
    request_button_disabled = "求简历换电话换微信" in compact and "简历请求已发送" in compact
    return {
        "hasResumeAttachment": has_file_name or has_resume_card,
        "alreadyRequested": already_requested or request_button_disabled,
        "pendingResumeConsent": pending_resume_consent,
        "summary": text[-500:],
        "source": "text_fallback",
    }


_CLICK_CONFIRM_BY_PROMPT_POSITION_JS = r"""
() => {
  const prompt = "确定向牛人索取简历";
  const bodyText = document.body && document.body.innerText ? document.body.innerText : "";
  if (!bodyText.includes(prompt)) {
    return { clicked: false, reason: "confirm_prompt_not_visible" };
  }
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const request = Array.from(document.querySelectorAll(
    ".toolbar-box-right .operate-btn, .toolbar-box-right .operate-icon-item, " +
    ".conversation-operate .operate-btn, .conversation-operate .operate-icon-item"
  )).filter(visible).find((el) => text(el).includes("求简历"));
  if (!request) {
    return { clicked: false, reason: "request_button_anchor_not_found" };
  }
  const rect = request.getBoundingClientRect();
  const points = [
    [rect.left + rect.width + 43, rect.top - 46],
    [rect.left + rect.width + 63, rect.top - 46],
    [rect.left + rect.width + 43, rect.top - 62],
    [rect.left + rect.width + 70, rect.top - 72],
    [rect.left + rect.width + 100, rect.top - 72],
    [rect.left + rect.width + 70, rect.top - 48],
    [rect.left + rect.width + 100, rect.top - 48],
    [rect.left + rect.width + 70, rect.bottom + 72],
    [rect.left + rect.width + 100, rect.bottom + 72],
  ];
  const clickAt = (x, y) => {
    const target = document.elementFromPoint(x, y);
    if (!target) return null;
    for (const eventName of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      const EventClass = eventName.startsWith("pointer") ? PointerEvent : MouseEvent;
      target.dispatchEvent(new EventClass(eventName, {
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        button: 0,
        pointerId: 1,
        pointerType: "mouse",
        isPrimary: true,
      }));
    }
    return {
      tag: target.tagName.toLowerCase(),
      className: String(target.className || ""),
      text: text(target),
      x: Math.round(x),
      y: Math.round(y),
    };
  };
  for (const [x, y] of points) {
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) continue;
    const clicked = clickAt(x, y);
    if (clicked) return { clicked: true, source: "prompt_position", target: clicked };
  }
  return { clicked: false, reason: "confirm_point_not_found" };
}
"""


def _compact(value: Any) -> str:
    return "".join(str(value or "").split())
