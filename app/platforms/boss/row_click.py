"""BOSS conversation row click helpers.

The chat list can behave like a virtual scroll area on real BOSS pages.  This
module keeps row opening logic separate from business decisions: first try the
normal reliable click, then fall back to a DOM event click that re-finds the row
by id/label and verifies the chat pane changed.
"""

from __future__ import annotations

from typing import Any

from app.browser.base import BrowserElement, BrowserPage
from app.browser.reliable_support import VerifyCallback, record_result, result_dict
from app.platforms.boss import selectors
from app.platforms.boss.interaction import boss_click_element

DOM_CLICK_ROW_JS = r"""
payload => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const compact = (value) => String(value || "").replace(/\s+/g, "");
  const rowId = String(payload.id || "").replace(/^_/, "");
  const targetLabel = compact(payload.label || "");
  const rows = Array.from(document.querySelectorAll(payload.selector)).filter(visible);
  let target = null;
  if (rowId) {
    target = rows.find((row) => {
      const current = String(
        row.getAttribute("id") || row.getAttribute("data-id") || row.getAttribute("data-uid") || ""
      ).replace(/^_/, "");
      return current === rowId;
    });
  }
  if (!target && targetLabel) {
    target = rows.find((row) => compact(text(row)) === targetLabel);
  }
  if (!target && Number.isInteger(payload.index) && payload.index >= 0) {
    target = rows[payload.index] || null;
  }
  if (!target) {
    return { clicked: false, reason: "row_not_found", rowCount: rows.length };
  }
  const scrollParent = (() => {
    let node = target.parentElement;
    while (node && node !== document.body) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY || "") && node.scrollHeight > node.clientHeight) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  })();
  target.scrollIntoView({ block: "center", inline: "nearest" });
  if (scrollParent) {
    const parentRect = scrollParent.getBoundingClientRect();
    const rect = target.getBoundingClientRect();
    scrollParent.scrollTop +=
      rect.top - parentRect.top - (parentRect.height / 2) + (rect.height / 2);
    scrollParent.dispatchEvent(new Event("scroll", { bubbles: true }));
  }
  const rect = target.getBoundingClientRect();
  if (!rect.width || !rect.height) {
    return { clicked: false, reason: "row_not_visible_after_scroll", id: rowId };
  }
  const x = Math.max(1, Math.min(window.innerWidth - 1, rect.left + rect.width / 2));
  const y = Math.max(1, Math.min(window.innerHeight - 1, rect.top + rect.height / 2));
  const pointTarget = document.elementFromPoint(x, y);
  const clickTarget = pointTarget && target.contains(pointTarget) ? pointTarget : target;
  const init = {
    bubbles: true,
    cancelable: true,
    view: window,
    clientX: x,
    clientY: y,
    button: 0,
  };
  for (const name of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const EventClass = name.startsWith("pointer") ? PointerEvent : MouseEvent;
    clickTarget.dispatchEvent(new EventClass(name, {
      ...init,
      pointerId: 1,
      pointerType: "mouse",
      isPrimary: true,
    }));
  }
  if (typeof clickTarget.click === "function") clickTarget.click();
  return {
    clicked: true,
    reason: "dom_event_click",
    id: rowId,
    text: text(target).slice(0, 120),
    x: Math.round(x),
    y: Math.round(y),
  };
}
"""


async def find_row_for_state(
    page: BrowserPage,
    state: dict[str, object],
) -> BrowserElement | None:
    """Find a visible BOSS conversation row from a captured unread row state."""

    row_id = str(state.get("id") or "")
    row_id_norm = row_id.lstrip("_")
    label = str(state.get("label") or "")
    rows = await page.query_all(selectors.SESSION_ITEM)

    if row_id_norm:
        for row in rows:
            current_id = str(await row.attr("id") or await row.attr("data-id") or "")
            if current_id.lstrip("_") == row_id_norm:
                return row
    if label:
        for row in rows:
            if (await row.text()).strip() == label:
                return row
    index = _safe_int(state.get("index"))
    if 0 <= index < len(rows):
        return rows[index]
    return None


async def click_row_state(
    page: BrowserPage,
    state: dict[str, object],
    *,
    label: str = "BOSS候选人会话",
    verify: VerifyCallback | None = None,
) -> dict[str, object]:
    """Open a BOSS row and verify the target conversation became active."""

    row = await find_row_for_state(page, state)
    if row is None:
        result = result_dict(False, "click_element", label, reason="row_not_found")
        record_result(page, result)
        return result

    return await boss_click_element(page, row, label=label, verify=verify)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
