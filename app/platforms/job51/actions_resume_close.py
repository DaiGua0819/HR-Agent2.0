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
  const clickable = (el) => {
    let node = el;
    for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
      if (!visible(node)) continue;
      const tag = node.tagName ? node.tagName.toLowerCase() : "";
      const role = attr(node, "role");
      const cursor = getComputedStyle(node).cursor || "";
      if (tag === "button" || tag === "a" || role === "button" || cursor === "pointer") {
        return node;
      }
    }
    return el;
  };
  const rootText = text(document.body);
  const looksLikeResume = rootText.includes("在线简历") ||
    Boolean(document.querySelector("#sensor_imresume_download"));
  if (!looksLikeResume) {
    return { closed: false, reason: "not_online_resume_view" };
  }
  const nodes = Array.from(document.querySelectorAll(
    "#sensor_imresume_close, .resume-close, .imresume-close, .container-close, " +
    ".el-dialog__headerbtn, .el-icon-close, [title='关闭'], [aria-label='关闭'], " +
    "[aria-label='close'], button, a, [role='button'], i, svg, use, span, div"
  )).filter(visible).map((el) => {
    const target = clickable(el);
    const rect = target.getBoundingClientRect();
    const label = [
      text(target), attr(target, "id"), attr(target, "class"), attr(target, "title"),
      attr(target, "aria-label"), attr(el, "class"), attr(el, "xlink:href")
    ].join(" ");
    return { el: target, rect, label };
  }).filter((item, index, arr) => {
    return arr.findIndex((other) => other.el === item.el) === index;
  });
  const semantic = nodes.find((item) => {
    return /关闭|close|el-icon-close|container-close|imresume-close|resume-close/i
      .test(item.label);
  });
  const topRight = nodes.filter((item) => {
    const r = item.rect;
    return r.top >= 0 && r.top < 180 && r.right > window.innerWidth - 220 &&
      r.width >= 10 && r.width <= 90 && r.height >= 10 && r.height <= 90;
  }).sort((a, b) => b.rect.right - a.rect.right || a.rect.top - b.rect.top);
  const target = semantic ? semantic.el : (topRight[0] && topRight[0].el);
  if (!target) {
    return { closed: false, reason: "online_resume_close_not_found" };
  }
  const label = [
    text(target), attr(target, "id"), attr(target, "class"), attr(target, "title"),
    attr(target, "aria-label")
  ].join(" ").replace(/\s+/g, " ").trim();
  target.click();
  return { closed: true, label, source: semantic ? "semantic_close" : "top_right_close" };
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
    "[class*='guide']",
    "[class*='popover']"
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
      return { closed: true, source: "generic_blocker", label, blockerText: text(blocker).slice(0, 160) };
    }
  }
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  return { closed: false, reason: blockers.length ? "generic_close_control_not_found" : "generic_blocker_not_found" };
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
    preview = await close_resume_preview(page)
    actions.append({"name": "resume_preview", **preview})
    if preview.get("closed"):
        closed += 1
    export = await _close_export_dialog(page)
    actions.append({"name": "export_dialog", **export})
    if export.get("closed"):
        closed += 1
    generic = await _close_generic_blocker(page)
    actions.append({"name": "generic_blocker", **generic})
    if generic.get("closed"):
        closed += 1
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
    actions.append({"name": "escape", **escape})
    return {"closed": closed, "actions": actions}


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
        result = await page.eval_js("job51.close_export_dialog")
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
