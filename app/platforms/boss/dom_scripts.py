"""BOSS 真实页面只读 DOM 脚本。

这些脚本集中放置，避免 actions.py 被页面 JS 细节撑大。脚本只读取页面，
不执行发送消息、求简历、下载、打招呼等真实业务副作用。
"""

from __future__ import annotations

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
  const activeFilter = () => {
    const active = Array.from(document.querySelectorAll(".chat-message-filter-left span.active"))
      .find((el) => visible(el));
    return text(active);
  };
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
    return target;
  };
  if (activeFilter() === "未读") {
    return { selected: true, label: "未读", source: "already_active" };
  }
  const candidates = Array.from(document.querySelectorAll(".chat-message-filter-left span"))
    .filter((el) => visible(el) && text(el) === "未读");
  const target = candidates[0];
  if (!target) return { selected: false, reason: "unread_filter_not_found" };
  const rect = target.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  const clicked = clickAt(x, y);
  return {
    selected: Boolean(clicked),
    label: "未读",
    source: "chat_message_filter_left_span",
    x: Math.round(x),
    y: Math.round(y),
    activeBefore: activeFilter(),
  };
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
  const visibleText = (node) => (node && node.innerText ? node.innerText.trim() : "");
  const attr = (node, name) => (node && node.getAttribute ? node.getAttribute(name) : "");
  const rows = Array.from(document.querySelectorAll(
    ".user-list .geek-item, .chat-user-list .user-list-item, " +
    ".chat-list .user-item, .user-list-item"
  )).filter(visible);
  const parseBadgeCount = (row) => {
    const badges = Array.from(row.querySelectorAll(
      ".badge-count, .badge, [class*='badge-count'], [class*='unread'], [class*='badge']"
    )).filter(visible);
    const counts = badges.map((badge) => {
      const text = visibleText(badge);
      const match = text.match(/\d+/);
      return match ? Number.parseInt(match[0], 10) : 0;
    });
    return counts.length ? Math.max(...counts) : 0;
  };
  return {
    rows: rows.map((row, index) => ({
      index,
      id: attr(row, "id") || attr(row, "data-id") || attr(row, "data-uid") || "",
      name: visibleText(row.querySelector(".geek-name, [class*='geek-name']")),
      position: visibleText(row.querySelector(".position-name, [class*='position-name']")),
      label: visibleText(row),
      unreadCount: parseBadgeCount(row),
    })),
  };
}
"""

READ_UNREAD_LIST_STATE_JS = r"""
() => {
  // boss_unread_list_state
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const visibleText = (node) => (node && node.innerText ? node.innerText.trim() : "");
  const parseCount = (node) => {
    const match = visibleText(node).match(/\d+/);
    return match ? Number.parseInt(match[0], 10) : 0;
  };
  const activeFilter = Array.from(
    document.querySelectorAll(".chat-message-filter-left span.active")
  ).find(visible);
  const rows = Array.from(document.querySelectorAll(
    ".user-list .geek-item, .chat-user-list .user-list-item, " +
    ".chat-list .user-item, .user-list-item"
  )).filter(visible);
  const badgeRowCount = rows.filter((row) => {
    const badges = Array.from(row.querySelectorAll(
      ".badge-count, [class*='badge-count'], [class*='unread-count']"
    )).filter(visible);
    return badges.some((badge) => parseCount(badge) > 0);
  }).length;
  const menuBadges = Array.from(document.querySelectorAll(
    ".menu-chat-badge, .menu-chat .badge, [class*='menu-chat-badge']"
  )).filter(visible);
  const menuUnreadCount = menuBadges.reduce(
    (maximum, badge) => Math.max(maximum, parseCount(badge)),
    0
  );
  const loading = Array.from(document.querySelectorAll(
    ".user-list .loading, .user-list [class*='loading'], " +
    ".chat-user-list [class*='loading'], .boss-loading, .ui-loading"
  )).some(visible);
  const listText = visibleText(
    document.querySelector(".user-list, .chat-user-list, .chat-list")
  );
  const emptyState = /暂无(?:未读|消息|沟通)|没有(?:未读|消息)|无未读/.test(listText);
  return {
    activeFilter: visibleText(activeFilter),
    rowCount: rows.length,
    badgeRowCount,
    menuUnreadCount,
    loading,
    emptyState,
    listText: listText.slice(0, 300),
  };
}
"""

READ_CHAT_CONTEXT_JS = r"""
() => {
  const visibleText = (node) => (node && node.innerText ? node.innerText.trim() : "");
  const attr = (node, name) => (node && node.getAttribute ? node.getAttribute(name) : "");
  const active =
    document.querySelector(".user-list .geek-item.selected") ||
    document.querySelector(".user-list .geek-item.active") ||
    document.querySelector(".chat-user-list .user-list-item.active") ||
    document.querySelector(".user-list-item.active") ||
    document.querySelector(".chat-list .user-item.active") ||
    document.querySelector(".user-list .geek-item") ||
    document.querySelector(".chat-user-list .user-list-item") ||
    document.querySelector(".user-list-item");
  const label = visibleText(active);
  const topText = visibleText(active && active.querySelector(".geek-item-top"));
  const nameNode =
    document.querySelector(".base-info-item.name-contet") ||
    document.querySelector(".chat-info .name") ||
    document.querySelector(".geek-name") ||
    document.querySelector(".chat-user-name") ||
    active;
  const jobNode =
    document.querySelector(".position-item .job-content") ||
    document.querySelector(".job-content") ||
    document.querySelector(".job-name") ||
    document.querySelector(".position-name") ||
    document.querySelector(".chat-info .job");
  const messageNodes = Array.from(
    document.querySelectorAll(
      ".conversation-message .message-item, .chat-message-list .message-item, " +
      ".message-item, .chat-message, .message-card, .item-myself, .message"
    )
  ).slice(-30);
  const messages = messageNodes
    .map((node) => {
      const className = String(node.className || "").toLowerCase();
      const textNode =
        node.querySelector(".text-content") ||
        node.querySelector(".message-card-top-title") ||
        node.querySelector(".text") ||
        node;
      const sender =
        node.querySelector(".item-system") || className.includes("system")
          ? "system"
          : node.querySelector(".item-myself") ||
        className.includes("mine") ||
        className.includes("myself") ||
        className.includes("self") ||
        className.includes("right")
          ? "me"
          : "other";
      return { sender, text: visibleText(textNode), rawText: visibleText(node) };
    })
    .filter((item) => item.text);
  const rawPosition = visibleText(jobNode).replace(/^沟通职位[:：]\s*/, "");
  return {
    id:
      attr(active, "id") ||
      attr(active, "data-id") ||
      attr(active, "data-uid") ||
      label ||
      location.href,
    name: visibleText(nameNode).split(/\n/)[0] || topText.split(/\s+/)[0] || "",
    position: rawPosition || topText.replace(/^\S+\s*/, "") || "",
    label: label || topText,
    messages,
    unread_count: 1,
    latest_message: messages.length ? messages[messages.length - 1].text : "",
  };
}
"""

INSPECT_RESUME_REQUEST_STATE_JS = r"""
() => {
  const visibleText = (node) => (node && node.innerText ? node.innerText.trim() : "");
  const messageRoot =
    document.querySelector(".conversation-message") ||
    document.querySelector(".chat-message-list");
  const messageText = visibleText(messageRoot);
  const messageItems = Array.from(
    document.querySelectorAll(
      ".conversation-message .message-item, .chat-message-list .message-item"
    )
  );
  const itemTexts = messageItems.map((node) => visibleText(node)).join("\n");
  const chatText = [messageText, itemTexts].join("\n");
  const hasFileName = /\.(pdf|doc|docx|wps|rtf)(\s|$|[?）)\]])/i.test(chatText);
  const consentPrompt =
    /(?:对方|牛人|候选人).{0,12}(?:想|申请|请求).{0,12}(?:发送|发).{0,12}(?:附件)?简历.{0,12}(?:是否同意|同意)/.test(chatText);
  const compactText = (node) => visibleText(node).replace(/\s+/g, "");
  const consentActionable = Array.from(
    document.querySelectorAll("span.card-btn, a.btn, button, [role='button'], .btn")
  ).some((node) => {
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    const enabled =
      !node.classList.contains("disabled") &&
      !node.hasAttribute("disabled") &&
      node.getAttribute("aria-disabled") !== "true" &&
      style.pointerEvents !== "none";
    return compactText(node) === "同意" && enabled &&
      style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  });
  const pendingResumeConsent = Boolean(consentPrompt && consentActionable);
  const hasResumeCard =
    !pendingResumeConsent &&
    /(?:已发送|发送|上传|收到|预览).{0,12}(?:简历|附件)|(?:简历|附件).{0,12}(?:已发送|预览|下载)/.test(chatText);
  const alreadyRequested =
    /(?:简历请求已发送|已求简历|已向.{0,8}(?:索要|请求).{0,8}简历|已发送求简历)/.test(chatText);
  return {
    hasResumeAttachment: Boolean(hasFileName || hasResumeCard),
    alreadyRequested: Boolean(alreadyRequested),
    pendingResumeConsent: Boolean(consentPrompt && consentActionable),
    summary: chatText.slice(-500),
    source: "boss_chat_message_dom",
  };
}
"""
