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
  const exact = Array.from(document.querySelectorAll(
    ".side-panel-header__checkbox.km-checkbox, .side-panel-header__checkbox"
  )).filter((el) => visible(el) && text(el) === "未读");
  const controls = exact.length ? exact : Array.from(document.querySelectorAll(
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
  const exact = Array.from(document.querySelectorAll(
    ".side-panel-header__checkbox.km-checkbox, .side-panel-header__checkbox"
  )).filter((el) => visible(el) && text(el) === "未读");
  const candidates = (exact.length ? exact : Array.from(document.querySelectorAll(
    ".side-panel-header__checkbox, .km-checkbox, [role='checkbox'], " +
    "label, button, a, span, div, [role='button']"
  )).filter((el) => visible(el) && text(el).includes("未读")))
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
  const listCandidates = Array.from(document.querySelectorAll(
    ".im-session-list__virtual, .im-session-list, [class*='im-session-list']"
  )).filter(visible);
  const scrollRoot = listCandidates.find(
    (el) => el.scrollHeight > el.clientHeight + 4
  ) || listCandidates[0] || null;
  let rows = Array.from(document.querySelectorAll(".im-session-item__box")).filter(visible);
  if (!rows.length) {
    rows = Array.from(document.querySelectorAll(".im-session-item")).filter(visible);
  }
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
    const hasDot = badges.some((badge) => {
      const cls = String(badge.className || "");
      const value = text(badge).replace(/\s+/g, "");
      const dot = badge.querySelector(".km-badge__item, sup, [class*='dot']");
      return value !== "0" && (
        cls.includes("dot") ||
        (dot && visible(dot) && text(dot).replace(/\s+/g, "") !== "0")
      );
    });
    if (!badges.length) return { count: 0, hasUnreadBadge: false };
    const maxCount = counts.length ? Math.max(...counts) : 0;
    return {
      count: maxCount > 0 ? maxCount : (hasDot ? 1 : 0),
      hasUnreadBadge: maxCount > 0 || hasDot,
    };
  };
  const scrollTop = scrollRoot ? Number(scrollRoot.scrollTop || 0) : 0;
  const scrollHeight = scrollRoot ? Number(scrollRoot.scrollHeight || 0) : 0;
  const clientHeight = scrollRoot ? Number(scrollRoot.clientHeight || 0) : 0;
  const listText = text(scrollRoot);
  const emptyState = (
    /暂无(?:未读|消息|沟通|会话)|没有(?:未读|消息|沟通|会话)|无未读/
  ).test(listText);
  return {
    unreadActive,
    listFound: Boolean(scrollRoot),
    hasScrollableList: Boolean(scrollRoot && scrollHeight > clientHeight + 4),
    scrollTop,
    scrollHeight,
    clientHeight,
    atBottom: !scrollRoot || scrollHeight <= clientHeight + 4 ||
      scrollTop + clientHeight >= scrollHeight - 4,
    emptyState,
    rowCount: rows.length,
    rows: rows.map((row, index) => {
      const label = text(row);
      const lines = label.split(/\n+/).map((line) => line.trim()).filter(Boolean);
      const offset = /^\d+$/.test(lines[0] || "") ? 1 : 0;
      const nameNode = row.querySelector(".im-session-item__name-title");
      const parsedPosition = lines[offset + 1] || "";
      const positionNode = row.querySelector(".im-session-item-subtitle__suffix");
      const messageNode = row.querySelector(".im-session-item__msg");
      const avatarNode = row.querySelector(".km-image__inner, img");
      const badge = parseBadge(row);
      return {
        index,
        id: attr(row, "id") || attr(row, "data-id") || attr(row, "data-uid") || "",
        label,
        name: text(nameNode) || lines[offset] || "",
        position: text(positionNode) || parsedPosition,
        latestMessage: text(messageNode) || lines[offset + 2] || "",
        avatarKey: attr(avatarNode, "src") || "",
        unreadCount: badge.count,
        hasUnreadBadge: badge.hasUnreadBadge,
      };
    }),
  };
}
"""

RESET_UNREAD_LIST_SCROLL_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const candidates = Array.from(document.querySelectorAll(
    ".im-session-list__virtual, .im-session-list, [class*='im-session-list']"
  )).filter(visible);
  const root = candidates.find((el) => el.scrollHeight > el.clientHeight + 4) ||
    candidates[0] || null;
  if (!root) {
    return { changed: false, listFound: false, reason: "unread_list_not_found" };
  }
  const before = Number(root.scrollTop || 0);
  root.scrollTop = 0;
  root.dispatchEvent(new Event("scroll", { bubbles: true }));
  return {
    changed: before !== Number(root.scrollTop || 0),
    listFound: true,
    scrollTop: Number(root.scrollTop || 0),
    scrollHeight: Number(root.scrollHeight || 0),
    clientHeight: Number(root.clientHeight || 0),
    atBottom: root.scrollHeight <= root.clientHeight + 4,
  };
}
"""

SCROLL_UNREAD_LIST_JS = r"""
(options) => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const candidates = Array.from(document.querySelectorAll(
    ".im-session-list__virtual, .im-session-list, [class*='im-session-list']"
  )).filter(visible);
  const root = candidates.find((el) => el.scrollHeight > el.clientHeight + 4) ||
    candidates[0] || null;
  if (!root) {
    return { changed: false, listFound: false, reason: "unread_list_not_found" };
  }
  const ratio = Math.min(Math.max(Number(options && options.ratio) || 0.8, 0.5), 0.95);
  const before = Number(root.scrollTop || 0);
  const maxTop = Math.max(Number(root.scrollHeight || 0) - Number(root.clientHeight || 0), 0);
  const distance = Math.max(Math.floor(Number(root.clientHeight || 0) * ratio), 180);
  const target = Math.min(before + distance, maxTop);
  if (typeof root.scrollTo === "function") {
    root.scrollTo({ top: target, behavior: "auto" });
  } else {
    root.scrollTop = target;
  }
  root.dispatchEvent(new Event("scroll", { bubbles: true }));
  const after = Number(root.scrollTop || 0);
  return {
    changed: Math.abs(after - before) >= 1,
    listFound: true,
    before,
    scrollTop: after,
    scrollHeight: Number(root.scrollHeight || 0),
    clientHeight: Number(root.clientHeight || 0),
    atBottom: after + Number(root.clientHeight || 0) >= Number(root.scrollHeight || 0) - 4,
  };
}
"""

CLICK_SESSION_ROW_JS = r"""
(target) => {
  const wanted = target || {};
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) : "");
  let rows = Array.from(document.querySelectorAll(".im-session-item__box")).filter(visible);
  if (!rows.length) {
    rows = Array.from(document.querySelectorAll(".im-session-item")).filter(visible);
  }
  const normalized = (value) => String(value || "").replace(/\s+/g, "");
  const wantedId = normalized(wanted.id).replace(/^_+/, "");
  const wantedLabel = normalized(wanted.label);
  let row = null;
  let index = Number.isFinite(Number(wanted.index)) ? Number(wanted.index) : -1;
  if (wantedId) {
    row = rows.find((item) => normalized(attr(item, "id")).replace(/^_+/, "") === wantedId);
  }
  if (!row && wantedLabel) {
    row = rows.find((item) => normalized(text(item)) === wantedLabel) ||
      rows.find((item) => normalized(text(item)).includes(wantedLabel));
  }
  if (!row && index >= 0 && index < rows.length) {
    row = rows[index];
  }
  if (!row) {
    row = rows[0] || null;
    index = row ? rows.indexOf(row) : -1;
  }
  if (!row) return { opened: false, reason: "session_row_not_found" };
  row.scrollIntoView({ block: "center", inline: "nearest" });
  const rect = row.getBoundingClientRect();
  const x = rect.left + Math.min(Math.max(rect.width * 0.32, 64), Math.max(rect.width - 12, 1));
  const y = rect.top + rect.height / 2;
  const clickTarget = document.elementFromPoint(x, y) || row;
  for (const type of ["mouseover", "mousemove", "pointerdown", "mousedown", "mouseup", "click"]) {
    clickTarget.dispatchEvent(new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
    }));
  }
  return {
    opened: true,
    index: rows.indexOf(row),
    label: text(row),
    id: attr(row, "id") || attr(row, "data-id") || attr(row, "data-uid") || "",
    targetTag: clickTarget.tagName,
    targetClass: String(clickTarget.className || ""),
  };
}
"""

READ_CHAT_CONTEXT_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const firstText = (selectors, root = document) => {
    for (const selector of selectors) {
      const el = root.querySelector(selector);
      if (visible(el) && text(el)) return text(el);
    }
    return "";
  };
  const detail = document.querySelector("#im-session-detail, .im-session-detail") || document;
  const detailText = text(detail);
  const urlSessionId = (() => {
    try {
      return new URL(location.href).searchParams.get("sessionId") || "";
    } catch (_error) {
      return "";
    }
  })();
  const detailLines = detailText.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const nameFromDetail = detailLines.find((line) =>
    !line.includes("沟通职位") &&
    !line.includes("当前沟通") &&
    !line.includes("浏览过职位") &&
    !line.includes("星期") &&
    !line.includes("昨天") &&
    !line.includes("今天")
  ) || "";
  const detailPositionMatch = detailText.match(/沟通职位：\s*([^\n]+)/) ||
    detailText.match(/当前沟通(.+?)职位/);
  const selected = Array.from(document.querySelectorAll(
    ".im-session-item__box, .im-session-item.km-list__item"
  )).filter(visible).find((row) => {
    const classes = String(row.className || "").split(/\s+/).filter(Boolean);
    return classes.includes("active") || classes.includes("selected") ||
      classes.includes("current") || row.getAttribute("aria-selected") === "true";
  });
  const header = document.querySelector(
    ".im-chat-header, .im-chat__header, [class*='chat-header'], [class*='dialog-header']"
  );
  const selectedLabel = text(selected);
  const candidateName = nameFromDetail || firstText([
    ".im-chat-header__name",
    ".im-chat-title__name",
    "[class*='chat-header'] [class*='name']",
    "[class*='header'] [class*='name']",
    ".im-session-item--active .im-session-item__name-title",
  ], header || document) || firstText([
    ".im-session-item--active .im-session-item__name-title",
    ".im-session-item.active .im-session-item__name-title",
    ".im-session-item__box.active .im-session-item__name-title",
  ]) || selectedLabel.split(/\n/).filter(Boolean)[0] || "";
  const position = (detailPositionMatch ? detailPositionMatch[1].trim() : "") || firstText([
    ".im-chat-header__job",
    ".im-chat-header__position",
    "[class*='chat-header'] [class*='job']",
    "[class*='chat-header'] [class*='position']",
    ".im-session-item--active .im-session-item-subtitle__suffix",
  ], header || document) || firstText([
    ".im-session-item--active .im-session-item-subtitle__suffix",
    ".im-session-item.active .im-session-item-subtitle__suffix",
    ".im-session-item__box.active .im-session-item-subtitle__suffix",
  ]);
  const messageRoot = detail.querySelector(".im-timeline, .im-session-detail__main-inner") ||
    detail;
  let messageNodes = Array.from(messageRoot.querySelectorAll(".km-list__item.im-message"))
    .filter(visible);
  if (!messageNodes.length) {
    messageNodes = Array.from(messageRoot.querySelectorAll(".im-message")).filter(visible);
  }
  const messages = messageNodes.map((node) => {
    const raw = firstText([
      ".im-message__text",
      ".im-message__bubble-inner",
      ".im-message__custom--box",
    ], node) || text(node);
    const cls = String(node.className || "");
    const mine = cls.includes("mine") || cls.includes("--me") || cls.includes("myself") ||
      node.querySelector("[class*='mine'], [class*='bubble--me'], [class*='myself']");
    const system = cls.includes("system") || cls.includes("toast") ||
      node.querySelector("[class*='toast'], [class*='system']");
    return {
      sender: system ? "system" : (mine ? "me" : "other"),
      text: raw,
      rawText: raw,
      time: firstText(["time", "[class*='time']"], node),
    };
  }).filter((item) => item.text);
  const last = messages.length ? messages[messages.length - 1] : null;
  return {
    id: urlSessionId || (selected ? selected.getAttribute("id") || "" : ""),
    name: candidateName,
    position,
    label: selectedLabel,
    messages,
    latest_message: last ? last.text : "",
    unreadCount: 1,
  };
}
"""

ZHILIAN_RESUME_STATE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const detail = document.querySelector("#im-session-detail, .im-session-detail");
  if (!detail) {
    return {
      hasResumeAttachment: false,
      alreadyRequested: false,
      canRequestResume: false,
      summary: "",
      evidence: "detail_not_found",
      source: "zhilian_resume_dom",
    };
  }
  const messageRoot = detail.querySelector(".im-timeline, .im-session-detail__main-inner") ||
    detail;
  const senderRoot = detail.querySelector(".im-sender, .session-new-action");
  const messageText = text(messageRoot);
  const senderText = text(senderRoot);
  const messageNodes = Array.from(messageRoot.querySelectorAll(
    ".km-list__item.im-message, .im-message, [class*='message']"
  )).filter(visible);
  const nodeText = messageNodes.map((node) => text(node)).join("\n");
  const scopedText = [messageText, nodeText].join("\n");
  const hasFileName = /\.(pdf|docx?|wps|rtf)(\s|$|[?）)\]])/i.test(scopedText);
  const viewAttachmentNode = messageNodes.find((node) => text(node).includes("查看附件简历"));
  const visibleAttachmentAction = Array.from(
    detail.querySelectorAll("button, a, [role='button'], span, div")
  ).filter(visible).find((node) => text(node).includes("查看附件简历"));
  const attachmentCard = messageNodes.find((node) => {
    const value = text(node);
    const cls = String(node.className || "");
    if (value.includes("要附件简历") || value.includes("已要附件简历")) return false;
    return value.includes("查看附件简历") ||
      (value.includes("附件简历") && /resume|attach|file/i.test(cls));
  });
  const hasResumeAttachment = Boolean(
    hasFileName || viewAttachmentNode || visibleAttachmentAction || attachmentCard
  );
  const alreadyRequested = /已要附件简历|已向对方要附件简历|已请求附件简历/.test(scopedText);
  const canRequestResume = !hasResumeAttachment && !alreadyRequested &&
    (senderText.includes("要附件简历") || scopedText.includes("要附件简历"));
  let evidence = "";
  if (hasFileName) evidence = "file_name";
  else if (viewAttachmentNode) evidence = "view_attachment_resume";
  else if (visibleAttachmentAction) evidence = "view_attachment_action";
  else if (attachmentCard) evidence = "attachment_card";
  else if (alreadyRequested) evidence = "already_requested";
  else if (canRequestResume) evidence = "request_button";
  return {
    hasResumeAttachment,
    alreadyRequested,
    canRequestResume,
    summary: scopedText.slice(-500),
    evidence,
    source: "zhilian_resume_dom",
  };
}
"""
