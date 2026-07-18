"""51job 简历预览关闭动作。

在线简历和附件简历是两套不同浮层；下载结束后必须关闭预览层回到聊天区，
否则下一轮会继续停留在同一份简历上，导致重复下载同一候选人。
"""

from __future__ import annotations

import asyncio

from app.browser.base import BrowserPage
from app.browser.reliable_actions import reliable_click_element
from app.platforms.job51 import selectors

CLOSE_ONLINE_RESUME_JS = r"""
() => {
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) || "" : "");
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const roots = Array.from(document.querySelectorAll("#IMResumePrint")).filter(visible);
  const sensor = Array.from(document.querySelectorAll("#sensor_imresume_download"))
    .find(visible);
  if (!roots.length && !sensor) {
    return { closed: false, reason: "not_online_resume_view" };
  }
  const root = roots[0] || null;
  const sensorScope = !root && sensor
    ? sensor.closest(".pop, .con, [class*='resume'], [class*='Resume']")
    : null;
  const closeSelector = [
    ".con-close",
    "#sensor_imresume_close",
    ".resume-close",
    ".imresume-close",
    ".container-close",
    ".el-dialog__headerbtn",
    ".el-icon-close",
    "[title='关闭']",
    "[aria-label='关闭']",
    "[aria-label='close']",
  ].join(", ");
  const controls = root
    ? Array.from(root.querySelectorAll(closeSelector))
    : (sensorScope ? Array.from(sensorScope.querySelectorAll(closeSelector)) : []);
  const target = controls.find(visible);
  if (!target) {
    return { closed: false, reason: "online_resume_close_not_found" };
  }
  const label = [
    text(target), attr(target, "id"), attr(target, "class"), attr(target, "title"),
    attr(target, "aria-label")
  ].join(" ").replace(/\s+/g, " ").trim();
  target.click();
  return { closed: true, label, source: "preview_explicit_close" };
}
"""


CLOSE_GENERIC_BLOCKERS_JS = r"""
() => {
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) || "" : "");
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const blockerSelectors = [
    "#driver-popover-item",
    ".el-dialog__wrapper",
    ".el-message-box__wrapper",
    ".wechat-notify",
    "[class*='guide']"
  ].join(",");
  const blockers = Array.from(document.querySelectorAll(blockerSelectors)).filter(visible);
  const safe = /关闭|取消|稍后|再说|知道了|我知道了|不感兴趣|跳过|close|cancel|later|skip/i;
  const risky = /确定|确认|保存|提交|发送|开启|启用|同意|求简历|下载|save|submit|send|confirm|ok/i;
  for (const blocker of blockers) {
    const controls = Array.from(blocker.querySelectorAll(
      ".el-dialog__headerbtn, .el-message-box__headerbtn, .el-icon-close, " +
      ".close, .close-btn, [class*='close'], [title], [aria-label], " +
      "button, .el-button, [role='button'], a, span, i, svg, div"
    )).filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const label = [
        text(el), attr(el, "class"), attr(el, "title"), attr(el, "aria-label"), attr(el, "id")
      ].join(" ").replace(/\s+/g, " ").trim();
      return { el, rect, label };
    });
    const semantic = controls.find((item) => safe.test(item.label) && !risky.test(item.label));
    const topRight = controls.filter((item) => {
      const r = item.rect;
      const b = blocker.getBoundingClientRect();
      return r.width >= 8 && r.width <= 80 && r.height >= 8 && r.height <= 80 &&
        r.top >= b.top && r.top <= b.top + 120 && r.right >= b.right - 160;
    }).sort((a, b) => b.rect.right - a.rect.right || a.rect.top - b.rect.top)[0];
    const target = semantic ? semantic.el : topRight && topRight.el;
    if (target) {
      const label = semantic ? semantic.label : topRight.label;
      target.click();
      return {
        closed: true,
        source: "generic_blocker",
        label,
        blockerText: text(blocker).slice(0, 160),
      };
    }
  }
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  return {
    closed: false,
    reason: blockers.length ? "generic_close_control_not_found" : "generic_blocker_not_found",
  };
}
"""


CLOSE_EXPORT_DIALOG_JS = r"""
() => {
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) || "" : "");
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const dialogs = Array.from(document.querySelectorAll(
    ".el-message-box__wrapper, .el-dialog__wrapper, [role='dialog']"
  )).filter(visible);
  const dialog = dialogs.find((item) => {
    const label = text(item);
    return label.includes("导出") &&
      (label.includes("导出成功") || label.includes("导出记录"));
  });
  if (!dialog) {
    return { closed: false, reason: "export_dialog_not_found" };
  }
  const controls = Array.from(dialog.querySelectorAll(
    "button, .el-message-box__headerbtn, [role='button'], [aria-label]"
  )).filter(visible);
  const acknowledged = controls.find((item) => text(item) === "我知道了");
  const headerClose = controls.find((item) => {
    const label = [text(item), attr(item, "aria-label"), attr(item, "class")].join(" ");
    return /关闭|close|el-message-box__headerbtn/i.test(label);
  });
  const target = acknowledged || headerClose;
  if (!target) {
    return { closed: false, reason: "export_dialog_close_control_not_found" };
  }
  const label = [text(target), attr(target, "aria-label"), attr(target, "class")]
    .join(" ").replace(/\s+/g, " ").trim();
  target.click();
  return { closed: true, source: "export_success_dialog", label };
}
"""


OVERLAY_STATE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const remaining = [];
  const anyVisible = (selector) => Array.from(document.querySelectorAll(selector)).some(visible);
  if (anyVisible("#IMResumePrint")) {
    remaining.push("online_resume_preview");
  }
  if (anyVisible(".annex-resume")) {
    remaining.push("annex_resume_preview");
  }
  if (anyVisible(".el-dialog, .el-dialog__wrapper, .el-message-box, " +
      ".el-message-box__wrapper, [role='dialog']")) {
    remaining.push("dialog");
  }
  return { remaining };
}
"""


async def close_resume_preview(page: BrowserPage) -> dict[str, object]:
    """关闭附件/在线简历预览层，动作后至少等待 1 秒。"""

    attachment = await _close_attachment_preview(page)
    if attachment.get("closed"):
        return attachment
    online = await _close_online_resume(page)
    if online.get("closed"):
        return online
    return online if online.get("reason") != "not_online_resume_view" else attachment


async def cleanup_resume_overlays(page: BrowserPage) -> dict[str, object]:
    """Close stale resume/export overlays before or after handling a candidate."""

    actions: list[dict[str, object]] = []
    closed = 0
    remaining: list[str] = []
    for attempt in range(1, 4):
        preview = await close_resume_preview(page)
        actions.append({"name": "resume_preview", "attempt": attempt, **preview})
        if preview.get("closed"):
            closed += 1
        export = await _close_export_dialog(page)
        actions.append({"name": "export_dialog", "attempt": attempt, **export})
        if export.get("closed"):
            closed += 1
        state = await _overlay_state(page)
        remaining = [
            str(item)
            for item in state.get("remaining", [])
            if str(item or "").strip()
        ]
        actions.append({"name": "overlay_state", "attempt": attempt, **state})
        if remaining and (preview.get("closed") or export.get("closed")):
            state = await _wait_overlay_transition(page)
            remaining = [
                str(item)
                for item in state.get("remaining", [])
                if str(item or "").strip()
            ]
            actions.append({"name": "overlay_transition", "attempt": attempt, **state})
        if not remaining:
            break
        generic = await _close_generic_blocker(page)
        actions.append({"name": "generic_blocker", "attempt": attempt, **generic})
        if generic.get("closed"):
            closed += 1
        state = await _overlay_state(page)
        remaining = [
            str(item)
            for item in state.get("remaining", [])
            if str(item or "").strip()
        ]
        actions.append({"name": "overlay_state", "attempt": attempt, **state})
        if not remaining:
            break
        try:
            pressed = await page.press("body", "Escape", timeout_ms=1000)
        except Exception as error:
            escape: dict[str, object] = {
                "closed": False,
                "reason": "escape_error",
                "error": str(error),
            }
        else:
            await asyncio.sleep(1)
            escape = {"closed": bool(pressed), "source": "escape"}
        actions.append({"name": "escape", "attempt": attempt, **escape})
        state = await _overlay_state(page)
        remaining = [
            str(item)
            for item in state.get("remaining", [])
            if str(item or "").strip()
        ]
        actions.append({"name": "overlay_state", "attempt": attempt, **state})
        if not remaining:
            break
    return {"closed": closed, "actions": actions, "remaining": remaining}


async def resume_overlay_state(page: BrowserPage) -> dict[str, object]:
    """Inspect visible resume/export overlays without performing any click."""

    return await _overlay_state(page)


async def _close_attachment_preview(page: BrowserPage) -> dict[str, object]:
    for element in await page.query_all(selectors.ANNEX_CLOSE):
        result = await reliable_click_element(page, element, label="51job关闭附件预览")
        await asyncio.sleep(1)
        return {"closed": bool(result.get("ok")), "source": "attachment_preview", **result}
    return {"closed": False, "reason": "attachment_close_not_found"}


async def _close_online_resume(page: BrowserPage) -> dict[str, object]:
    try:
        result = await page.eval_js(CLOSE_ONLINE_RESUME_JS)
    except Exception as error:
        return {"closed": False, "reason": "online_resume_close_error", "error": str(error)}
    await asyncio.sleep(1)
    return result if isinstance(result, dict) else {"closed": False, "reason": "bad_result"}


async def _close_export_dialog(page: BrowserPage) -> dict[str, object]:
    try:
        result = await page.eval_js(CLOSE_EXPORT_DIALOG_JS)
    except Exception as error:
        return {"closed": False, "reason": "export_close_error", "error": str(error)}
    await asyncio.sleep(1)
    return result if isinstance(result, dict) else {"closed": False, "reason": "bad_result"}


async def _close_generic_blocker(page: BrowserPage) -> dict[str, object]:
    try:
        result = await page.eval_js(CLOSE_GENERIC_BLOCKERS_JS)
    except Exception as error:
        return {"closed": False, "reason": "generic_close_error", "error": str(error)}
    await asyncio.sleep(1)
    return result if isinstance(result, dict) else {"closed": False, "reason": "bad_result"}


async def _overlay_state(page: BrowserPage) -> dict[str, object]:
    try:
        result = await page.eval_js(OVERLAY_STATE_JS)
    except Exception as error:
        return {"remaining": [], "error": str(error)}
    return result if isinstance(result, dict) else {"remaining": []}


async def _wait_overlay_transition(
    page: BrowserPage,
    *,
    timeout_ms: int = 800,
    interval_ms: int = 100,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + max(timeout_ms, 0) / 1000
    last = await _overlay_state(page)
    while last.get("remaining") and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(max(interval_ms, 0) / 1000)
        last = await _overlay_state(page)
    return last
