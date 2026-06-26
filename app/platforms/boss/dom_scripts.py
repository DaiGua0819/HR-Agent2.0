"""BOSS 真实页面只读 DOM 脚本。

这些脚本集中放置，避免 actions.py 被页面 JS 细节撑大。脚本只读取页面或点击筛选
导航，不执行发送消息、求简历、下载、打招呼等真实业务副作用。
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
  const roots = Array.from(document.querySelectorAll(".chat-message-filter-left"));
  const candidates = roots.flatMap((root) => [root, ...Array.from(root.querySelectorAll("*"))])
    .filter((el) => visible(el) && text(el).includes("未读"))
    .sort((a, b) => text(a).length - text(b).length);
  const target = candidates[0];
  if (!target) return { selected: false, reason: "unread_filter_not_found" };
  target.click();
  return { selected: true, label: text(target), source: "dom_text" };
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
    id: attr(active, "data-id") || attr(active, "data-uid") || label || location.href,
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
  const pendingResumeConsent =
    /(?:对方|牛人|候选人).{0,12}(?:想|申请|请求).{0,12}(?:发送|发).{0,12}(?:附件)?简历.{0,12}(?:是否同意|同意)/.test(chatText);
  const hasResumeCard =
    !pendingResumeConsent &&
    /(?:已发送|发送|上传|收到|预览).{0,12}(?:简历|附件)|(?:简历|附件).{0,12}(?:已发送|预览|下载)/.test(chatText);
  const alreadyRequested =
    /(?:简历请求已发送|已求简历|已向.{0,8}(?:索要|请求).{0,8}简历|已发送求简历)/.test(chatText);
  return {
    hasResumeAttachment: Boolean(hasFileName || hasResumeCard),
    alreadyRequested: Boolean(alreadyRequested),
    pendingResumeConsent: Boolean(pendingResumeConsent),
    summary: chatText.slice(-500),
    source: "boss_chat_message_dom",
  };
}
"""
