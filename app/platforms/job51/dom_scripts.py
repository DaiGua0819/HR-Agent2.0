"""51job 真实页面只读 DOM 脚本。

这里集中放置页面结构探测脚本，动作层只调用结果，不把真实 DOM 细节散落到业务
流程里。脚本只用于切换未读筛选和读取当前列表状态，不执行发送、求简历、下载等
业务副作用。
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
    "label.el-checkbox.btn.unread-checkbox, .unread-checkbox, " +
    "label, button, [role='button'], span, div"
  )).filter((el) => visible(el) && text(el).includes("未读"));
  const active = controls.find((el) => {
    const cls = el.className ? String(el.className) : "";
    const input = el.querySelector && el.querySelector("input[type='checkbox']");
    return cls.includes("is-checked") || cls.includes("active") ||
      cls.includes("checked") || Boolean(input && input.checked);
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
    "label.el-checkbox.btn.unread-checkbox, .unread-checkbox, " +
    "label, button, [role='button'], span, div"
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
    "#conversation-list .list-item, .conversation-list .list-item, " +
    "[class*='conversation'] [class*='list-item'], [class*='im'] [class*='list-item']"
  )).filter(visible);
  const unreadState = (() => {
    const state = Array.from(document.querySelectorAll(
      "label.el-checkbox.btn.unread-checkbox, .unread-checkbox, label, button, span, div"
    )).filter((el) => visible(el) && text(el).includes("未读")).find((el) => {
      const cls = el.className ? String(el.className) : "";
      const input = el.querySelector && el.querySelector("input[type='checkbox']");
      return cls.includes("is-checked") || cls.includes("active") ||
        cls.includes("checked") || Boolean(input && input.checked);
    });
    return Boolean(state);
  })();
  const parseBadge = (row) => {
    const badges = Array.from(row.querySelectorAll(
      ".el-badge__content, .badge, [class*='badge'], [class*='unread']"
    )).filter(visible);
    const counts = badges.map((badge) => {
      const match = text(badge).match(/\d+/);
      return match ? Number.parseInt(match[0], 10) : 0;
    });
    return counts.length ? Math.max(...counts) : 0;
  };
  return {
    unreadActive: unreadState,
    rows: rows.map((row, index) => {
      const label = text(row);
      const count = parseBadge(row);
      return {
        index,
        id: attr(row, "id") || attr(row, "data-id") || attr(row, "data-uid") || "",
        label,
        unreadCount: count || (unreadState ? 1 : 0),
      };
    }),
  };
}
"""
