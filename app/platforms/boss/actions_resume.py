"""BOSS 求简历动作。"""

from __future__ import annotations

from typing import Any

from app.browser.base import BrowserElement, BrowserPage
from app.browser.reliable_support import is_fake
from app.platforms.boss import selectors
from app.platforms.boss.dom_scripts import INSPECT_RESUME_REQUEST_STATE_JS
from app.platforms.boss.interaction import (
    boss_click_element,
    boss_click_mutable_dialog_element,
    boss_click_rect,
)
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
    handled = await _handle_terminal_resume_state(page, state)
    if handled is not None:
        return handled
    if (await _confirm_prompt_visible(page)).get("verified"):
        return await _confirm_resume_request(page, state)
    click = await _click_request_resume_button(page)
    if not click.get("ok"):
        return {
            "ok": False,
            "outcome": "resume_request_button_failed",
            "requested": False,
            "blocked": True,
            "reason": "request_resume_click_not_verified",
            "beforeState": _resume_state_payload(state),
            "afterState": _resume_state_payload(await inspect_resume_request_state(page)),
            "click": click,
        }
    after_click = await inspect_resume_request_state(page)
    handled = await _handle_terminal_resume_state(
        page,
        after_click,
        before_state=state,
        click=click,
    )
    if handled is not None:
        return handled
    confirm_visible = await _confirm_button_visible(page)
    if not confirm_visible.get("verified"):
        return {
            "ok": False,
            "outcome": "resume_request_confirm_failed",
            "requested": False,
            "blocked": True,
            "reason": "request_resume_confirm_not_found",
            "requestButtonClicked": True,
            "beforeState": _resume_state_payload(state),
            "afterState": _resume_state_payload(after_click),
            "click": click,
        }
    return await _confirm_resume_request(page, state, request_click=click)


async def _click_request_resume_confirm(page: BrowserPage) -> dict[str, object]:
    return await _trusted_click_visible_request_resume_confirm(page)


async def _confirm_button_visible(page: BrowserPage) -> dict[str, object]:
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
    hard_state = await _safe_eval_dict(page, _BOSS_CONFIRM_PROMPT_VISIBLE_JS)
    if hard_state.get("verified"):
        return hard_state
    body = await page.text()
    visible = "确定向牛人索取简历" in body and "取消" in body and "确定" in body
    return {"verified": visible, "source": "body_text" if visible else "none"}


async def _click_resume_consent(page: BrowserPage) -> dict[str, object]:
    rect = await _safe_eval_dict(page, _BOSS_RESUME_CONSENT_RECT_JS)
    if rect.get("found"):
        result = await boss_click_rect(
            page,
            rect,
            label="BOSS同意接收简历",
            verify=lambda: _resume_consent_accepted(page),
        )
        if result.get("ok"):
            return {"clicked": True, "humanizedClick": result, "rect": rect}
    consent = await _find_button_by_text(
        page,
        selectors.REQUEST_RESUME_BUTTON,
        selectors.RESUME_CONSENT_TEXT,
    )
    if consent is None:
        return {
            "clicked": False,
            "reason": rect.get("reason") or "resume_consent_button_not_found",
            "rect": rect,
        }
    result = await boss_click_element(
        page,
        consent,
        label="BOSS同意接收简历",
        verify=lambda: _resume_consent_accepted(page),
    )
    return {"clicked": bool(result.get("ok")), "humanizedClick": result, "rect": rect}


async def _click_request_resume_button(page: BrowserPage) -> dict[str, object]:
    trusted_click = await _trusted_click_visible_request_resume_button(page)
    if trusted_click.get("ok"):
        return trusted_click
    button = await _find_button_by_text(
        page, selectors.REQUEST_RESUME_BUTTON, selectors.REQUEST_RESUME_TEXT
    )
    if button is None:
        return {
            "ok": False,
            "reason": trusted_click.get("reason") or "request_resume_button_not_found",
        }
    return await boss_click_element(
        page,
        button,
        label="BOSS求简历",
        verify=lambda: _request_resume_click_verified(page),
    )


async def _trusted_click_visible_request_resume_button(page: BrowserPage) -> dict[str, object]:
    rect = await _safe_eval_dict(page, _BOSS_REQUEST_RESUME_BUTTON_RECT_JS)
    return await boss_click_rect(
        page,
        rect,
        label="BOSS求简历",
        verify=lambda: _request_resume_click_verified(page),
    )


async def _trusted_click_visible_request_resume_confirm(page: BrowserPage) -> dict[str, object]:
    target = await _safe_eval_dict(page, _BOSS_REQUEST_RESUME_CONFIRM_TARGET_JS)
    selector = str(target.get("selector") or "")
    if selector:
        element = await page.query(selector)
        if element is not None:
            return await boss_click_mutable_dialog_element(
                page,
                element,
                label="BOSS求简历确认",
                verify=lambda: _resume_request_completed(page),
                pre_click_guard=lambda: _resume_confirm_pre_click_guard(page, selector),
            )
    if is_fake(page):
        rect = await _safe_eval_dict(page, _BOSS_REQUEST_RESUME_CONFIRM_RECT_JS)
        return await boss_click_rect(
            page,
            rect,
            label="BOSS求简历确认",
            verify=lambda: _resume_request_completed(page),
        )
    return {
        "ok": False,
        "reason": str(target.get("reason") or "request_resume_confirm_target_not_found"),
        "target": target,
    }


async def _resume_consent_accepted(page: BrowserPage) -> dict[str, object]:
    state = await inspect_resume_request_state(page)
    return {
        "verified": not state.pending_resume_consent,
        "reason": "" if not state.pending_resume_consent else "resume_consent_still_pending",
    }


async def _resume_request_completed(page: BrowserPage) -> dict[str, object]:
    state = await inspect_resume_request_state(page)
    verified = bool(
        state.already_requested or state.has_resume_attachment or state.pending_resume_consent
    )
    reason = "resume_request_not_completed"
    if state.already_requested:
        reason = "already_requested"
    elif state.pending_resume_consent:
        reason = "resume_consent_pending"
    elif state.has_resume_attachment:
        reason = "resume_attachment_received"
    return {
        "verified": verified,
        "reason": reason,
        "state": _resume_state_payload(state),
    }


async def _confirm_resume_request(
    page: BrowserPage,
    before_state: ResumeRequestState,
    *,
    request_click: dict[str, object] | None = None,
) -> dict[str, object]:
    before_confirm = await inspect_resume_request_state(page)
    handled = await _handle_terminal_resume_state(
        page,
        before_confirm,
        before_state=before_state,
        click=request_click,
    )
    if handled is not None:
        return handled
    confirm_click = await _click_request_resume_confirm(page)
    after_confirm = await inspect_resume_request_state(page)
    handled = await _handle_terminal_resume_state(
        page,
        after_confirm,
        before_state=before_state,
        click=confirm_click,
    )
    if handled is not None:
        handled["confirmed"] = bool(
            confirm_click.get("ok") and handled.get("outcome") == "request_confirmed"
        )
        if request_click is not None:
            handled["requestClick"] = request_click
        return handled
    reason = str(confirm_click.get("reason") or "resume_request_confirm_failed")
    outcome = (
        "resume_request_state_changed"
        if reason == "resume_request_state_changed"
        else "resume_request_confirm_failed"
    )
    return {
        "ok": False,
        "outcome": outcome,
        "requested": False,
        "confirmed": False,
        "blocked": True,
        "reason": outcome,
        "beforeState": _resume_state_payload(before_state),
        "afterState": _resume_state_payload(after_confirm),
        "click": confirm_click,
        "requestClick": request_click or {},
    }


async def _handle_terminal_resume_state(
    page: BrowserPage,
    state: ResumeRequestState,
    *,
    before_state: ResumeRequestState | None = None,
    click: dict[str, object] | None = None,
) -> dict[str, object] | None:
    before_state = before_state or state
    if state.pending_resume_consent:
        consent_click = await _click_resume_consent(page)
        after_consent = await inspect_resume_request_state(page)
        accepted = bool(consent_click.get("clicked") and not after_consent.pending_resume_consent)
        return {
            "ok": accepted,
            "outcome": "resume_consent_accepted" if accepted else "resume_consent_accept_failed",
            "requested": accepted,
            "acceptedResumeConsent": accepted,
            "consentHandled": accepted,
            "resumeReceived": bool(after_consent.has_resume_attachment),
            "reason": "" if accepted else "resume_consent_accept_failed",
            "beforeState": _resume_state_payload(before_state),
            "afterState": _resume_state_payload(after_consent),
            "click": consent_click,
            "stateChangeClick": click or {},
        }
    if state.has_resume_attachment:
        return {
            "ok": True,
            "outcome": "resume_attachment_received",
            "requested": False,
            "resumeReceived": True,
            "downloaded": False,
            "skipped": True,
            "reason": "boss_attachment_present_no_local_download",
            "beforeState": _resume_state_payload(before_state),
            "afterState": _resume_state_payload(state),
            "click": click or {},
        }
    if state.already_requested:
        return {
            "ok": True,
            "outcome": "request_confirmed",
            "requested": True,
            "alreadyRequested": True,
            "skipped": click is None,
            "reason": "already_requested" if click is None else "",
            "beforeState": _resume_state_payload(before_state),
            "afterState": _resume_state_payload(state),
            "click": click or {},
        }
    return None


async def _resume_confirm_pre_click_guard(
    page: BrowserPage,
    selector: str,
) -> dict[str, object]:
    state = await inspect_resume_request_state(page)
    if state.already_requested or state.has_resume_attachment or state.pending_resume_consent:
        return {
            "verified": False,
            "reason": "resume_request_state_changed",
            "state": _resume_state_payload(state),
        }
    target = await _safe_eval_dict(page, _BOSS_VALIDATE_REQUEST_RESUME_CONFIRM_TARGET_JS, selector)
    return {
        "verified": bool(target.get("verified")),
        "reason": str(target.get("reason") or ""),
        "target": target,
        "state": _resume_state_payload(state),
    }


def _resume_state_payload(state: ResumeRequestState) -> dict[str, object]:
    return {
        "hasResumeAttachment": state.has_resume_attachment,
        "alreadyRequested": state.already_requested,
        "pendingResumeConsent": state.pending_resume_consent,
        "summary": state.summary,
    }


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


_BOSS_RESUME_CONSENT_RECT_JS = r"""
() => {
  const marker = "boss_resume_consent_rect";
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, "");
  const containers = Array.from(document.querySelectorAll(
    ".message-item, .conversation-message, .chat-message-list, .custom-card, " +
    ".card-wrap, .card-wrapper, .dialog-wrap.active, body"
  )).filter((el) => visible(el) && text(el).includes("简历") && text(el).includes("是否同意"));
  const scoped = containers.length ? containers : [document.body];
  const candidates = [];
  for (const root of scoped) {
    candidates.push(...Array.from(root.querySelectorAll(
      "span.card-btn, a.btn, button, [role='button'], .btn"
    )));
  }
  const matches = candidates
    .filter((el) => visible(el) && text(el) === "同意")
    .sort((a, b) => {
      const priority = (el) => el.matches("span.card-btn") ? 0 : el.matches("a.btn") ? 1 : 2;
      return priority(a) - priority(b);
    });
  if (!matches.length) {
    return { found: false, reason: "resume_consent_button_not_found", source: marker };
  }
  const target = matches[0];
  const rect = target.getBoundingClientRect();
  return {
    found: true,
    source: marker,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    tag: target.tagName.toLowerCase(),
    className: String(target.className || ""),
    text: text(target),
  };
}
"""


_BOSS_REQUEST_RESUME_BUTTON_RECT_JS = r"""
() => {
  const marker = "boss_request_resume_button_rect";
  const requestText = "求简历";
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, "");
  const roots = Array.from(document.querySelectorAll(
    ".conversation-operate, .toolbar-box-right, .toolbar-box, .operate-box, .chat-op"
  )).filter(visible);
  const scoped = roots.length ? roots : [document.body];
  const candidates = [];
  for (const root of scoped) {
    candidates.push(...Array.from(root.querySelectorAll(
      ".operate-icon-item, .operate-btn, .btn-request-resume, button, [role='button']"
    )));
  }
  const matches = candidates
    .filter((el) => visible(el) && text(el).includes(requestText))
    .sort((a, b) => {
      const priority = (el) => {
        if (el.matches(".operate-icon-item")) return 0;
        if (el.matches(".operate-btn")) return 1;
        return 2;
      };
      return priority(a) - priority(b) || text(a).length - text(b).length;
    });
  if (!matches.length) {
    return { found: false, reason: "request_resume_button_not_found", source: marker };
  }
  const target = matches[0].closest(".operate-icon-item") || matches[0];
  const rect = target.getBoundingClientRect();
  return {
    found: true,
    source: marker,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    text: text(target),
  };
}
"""


_BOSS_CONFIRM_PROMPT_VISIBLE_JS = r"""
() => {
  const marker = "boss_confirm_prompt_visible";
  const prompt = "确定向牛人索取简历";
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, "");
  const containers = Array.from(document.querySelectorAll(
    ".exchange-tooltip, .boss-dialog__wrapper, .boss-dialog, .dialog-wrap.active, " +
    "[role='dialog'], .modal, [class*='dialog'], [class*='modal']"
  )).filter((el) => visible(el) && text(el).includes(prompt));
  if (containers.length) {
    return { verified: true, source: marker, text: text(containers[0]).slice(0, 80) };
  }
  const bodyText = document.body && document.body.innerText
    ? document.body.innerText.replace(/\s+/g, "")
    : "";
  const bodyVisible = bodyText.includes(prompt) &&
    bodyText.includes("取消") &&
    bodyText.includes("确定");
  return { verified: bodyVisible, source: bodyVisible ? `${marker}_body` : marker };
}
"""


_BOSS_REQUEST_RESUME_CONFIRM_TARGET_JS = r"""
() => {
  const marker = "boss_request_resume_confirm_target";
  const attribute = "data-recruit-agent-confirm-target";
  const prompt = "确定向牛人索取简历";
  const confirmTexts = new Set(["确定", "确认", "发送请求", "发起请求", "继续"]);
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, "");
  document.querySelectorAll(`[${attribute}]`).forEach((el) => el.removeAttribute(attribute));
  const containers = Array.from(document.querySelectorAll(
    ".exchange-tooltip, .boss-dialog__wrapper, .boss-dialog, .dialog-wrap.active, " +
    "[role='dialog'], .modal, [class*='dialog'], [class*='modal']"
  )).filter((el) => visible(el) && text(el).includes(prompt));
  if (!containers.length) {
    return { found: false, reason: "request_resume_confirm_prompt_not_visible", source: marker };
  }
  const candidates = [];
  for (const root of containers) {
    candidates.push(...Array.from(root.querySelectorAll(
      ".boss-btn-primary, .boss-btn, button, [role='button'], .btn, a, span"
    )));
  }
  const matches = candidates
    .filter((el) => visible(el) && confirmTexts.has(text(el)))
    .sort((a, b) => {
      const priority = (el) => el.matches(
        ".boss-btn-primary, .btn-primary, .confirm-btn, .sure-btn"
      ) ? 0 : 1;
      return priority(a) - priority(b);
    });
  if (!matches.length) {
    return { found: false, reason: "request_resume_confirm_not_found", source: marker };
  }
  const target = matches[0];
  target.setAttribute(attribute, "request-resume");
  const rect = target.getBoundingClientRect();
  return {
    found: true,
    source: marker,
    selector: `[${attribute}='request-resume']`,
    promptText: text(containers[0]).slice(0, 160),
    text: text(target),
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
  };
}
"""


_BOSS_VALIDATE_REQUEST_RESUME_CONFIRM_TARGET_JS = r"""
(selector) => {
  const marker = "boss_validate_request_resume_confirm_target";
  const prompt = "确定向牛人索取简历";
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, "");
  const target = document.querySelector(selector);
  if (!visible(target)) {
    return { verified: false, reason: "resume_request_state_changed", source: marker };
  }
  const dialog = target.closest(
    ".exchange-tooltip, .boss-dialog__wrapper, .boss-dialog, .dialog-wrap.active, " +
    "[role='dialog'], .modal, [class*='dialog'], [class*='modal']"
  );
  if (!visible(dialog) || !text(dialog).includes(prompt)) {
    return { verified: false, reason: "resume_request_state_changed", source: marker };
  }
  const rect = target.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  const hit = document.elementFromPoint(x, y);
  if (!hit || !(hit === target || target.contains(hit))) {
    return {
      verified: false,
      reason: "request_resume_confirm_target_obscured",
      source: marker,
      hitText: text(hit).slice(0, 80),
    };
  }
  return {
    verified: true,
    reason: "request_resume_confirm_target_current",
    source: marker,
    text: text(target),
    promptText: text(dialog).slice(0, 160),
  };
}
"""


_BOSS_REQUEST_RESUME_CONFIRM_RECT_JS = r"""
() => {
  const marker = "boss_request_resume_confirm_rect";
  const prompt = "确定向牛人索取简历吗";
  const confirmTexts = new Set(["确定", "确认", "发送请求", "发起请求", "继续"]);
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, "");
  const containers = Array.from(document.querySelectorAll(
    ".exchange-tooltip, .boss-dialog__wrapper, .boss-dialog, .dialog-wrap.active, " +
    "[role='dialog'], .modal, [class*='dialog'], [class*='modal']"
  )).filter((el) => visible(el) && text(el).includes(prompt));
  if (!containers.length) {
    return { found: false, reason: "request_resume_confirm_prompt_not_visible", source: marker };
  }
  const candidates = [];
  for (const root of containers) {
    candidates.push(...Array.from(root.querySelectorAll(
      ".boss-btn-primary, .boss-btn, button, [role='button'], .btn, a, span"
    )));
  }
  const matches = candidates
    .filter((el) => visible(el) && confirmTexts.has(text(el)))
    .sort((a, b) => {
      const priority = (el) => el.matches(
        ".boss-btn-primary, .btn-primary, .confirm-btn, .sure-btn"
      ) ? 0 : 1;
      return priority(a) - priority(b);
    });
  if (!matches.length) {
    return { found: false, reason: "request_resume_confirm_not_found", source: marker };
  }
  const rect = matches[0].getBoundingClientRect();
  return {
    found: true,
    source: marker,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    text: text(matches[0]),
  };
}
"""


def _compact(value: Any) -> str:
    return "".join(str(value or "").split())

