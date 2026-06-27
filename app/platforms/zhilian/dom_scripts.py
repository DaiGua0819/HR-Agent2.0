"""智联真实页面只读 DOM 脚本。

脚本只用于未读筛选状态探测、点击未读页签和读取会话列表状态。岗位判断、消息
处理和副作用执行仍由共享 agent 与平台 action 层负责。
"""

from __future__ import annotations

UNREAD_FILTER_STATE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const controls = Array.from(document.querySelectorAll(
    ".side-panel-header__checkbox, .km-checkbox, [role='checkbox'], " +
    "label, button, a, span, div, [role='button']"
  )).filter((el) => visible(el) && text(el).includes("未读"));
  const active = controls.find((el) => {
    const cls = el.className ? String(el.className) : "";
    const aria = el.getAttribute && el.getAttribute("aria-checked");
    const input = el.querySelector && el.querySelector("input[type='checkbox']");
    return cls.includes("checked") || cls.includes("active") || aria === "true" ||
      Boolean(input && input.checked);
  });
  return {
    active: Boolean(active),
    label: active ? text(active) : "",
    candidates: controls.map((el) => text(el)).filter(Boolean).slice(0, 8),
  };
}
"""

CLICK_UNREAD_FILTER_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const candidates = Array.from(document.querySelectorAll(
    ".side-panel-header__checkbox, .km-checkbox, [role='checkbox'], " +
    "label, button, a, span, div, [role='button']"
  )).filter((el) => visible(el) && text(el).includes("未读"))
    .sort((a, b) => text(a).length - text(b).length);
  const target = candidates[0];
  if (!target) return { selected: false, reason: "unread_filter_not_found" };
  target.click();
  return { selected: true, label: text(target), source: "dom_text" };
}
"""

READ_UNREAD_ROWS_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) : "");
  const rows = Array.from(document.querySelectorAll(
    ".im-session-item__box, .im-session-item, " +
    ".im-session-list [class*='session'], [class*='session-item']"
  )).filter(visible);
  const unreadActive = Array.from(document.querySelectorAll(
    ".side-panel-header__checkbox, .km-checkbox, [role='checkbox'], " +
    "label, button, span, div, [role='button']"
  )).filter((el) => visible(el) && text(el).includes("未读")).some((el) => {
    const cls = el.className ? String(el.className) : "";
    const aria = el.getAttribute && el.getAttribute("aria-checked");
    const input = el.querySelector && el.querySelector("input[type='checkbox']");
    return cls.includes("checked") || cls.includes("active") || aria === "true" ||
      Boolean(input && input.checked);
  });
  const parseBadge = (row) => {
    const badges = Array.from(row.querySelectorAll(
      ".im-session-item__unread, .badge, [class*='unread'], [class*='badge']"
    )).filter(visible);
    const counts = badges.map((badge) => {
      const match = text(badge).match(/\d+/);
      return match ? Number.parseInt(match[0], 10) : 0;
    });
    return counts.length ? Math.max(...counts) : 0;
  };
  return {
    unreadActive,
    rows: rows.map((row, index) => {
      const label = text(row);
      const positionNode = row.querySelector(
        ".im-session-item-subtitle__suffix, [class*='subtitle'], [class*='position']"
      );
      const count = parseBadge(row);
      return {
        index,
        id: attr(row, "id") || attr(row, "data-id") || attr(row, "data-uid") || "",
        label,
        position: text(positionNode),
        unreadCount: count || (unreadActive ? 1 : 0),
      };
    }),
  };
}
"""
