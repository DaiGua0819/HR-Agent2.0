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
      const name = text(row.querySelector(".username, .username-text"));
      const position = text(row.querySelector(".jobname"));
      const latestMessage = text(row.querySelector(".last-message, .msg, .message"));
      return {
        index,
        id: attr(row, "id") || attr(row, "data-id") || attr(row, "data-uid") || "",
        label,
        name,
        position,
        latestMessage,
        unreadCount: count || (unreadState ? 1 : 0),
      };
    }),
  };
}
"""

CLICK_THREAD_BY_IDENTITY_JS = r"""
(expected) => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) : "");
  const compact = (value) => String(value || "").replace(/\s+/g, "").toLowerCase();
  const contains = (actual, expectedValue) => {
    const left = compact(actual);
    const right = compact(expectedValue);
    return Boolean(left && right && (left.includes(right) || right.includes(left)));
  };
  const exact = (actual, expectedValue) => {
    const left = compact(actual);
    const right = compact(expectedValue);
    return Boolean(left && right && left === right);
  };
  const expectedName = String(expected && expected.name || "").trim();
  const expectedPosition = String(expected && expected.position || "").trim();
  const expectedLatest = String(
    expected && (expected.latest_message || expected.latestMessage) || ""
  ).trim();
  const expectedLabel = String(expected && expected.label || "").trim();
  const expectedId = String(expected && expected.id || "").replace(/^_/, "").trim();
  if (!expectedName && !expectedPosition && !expectedLabel && !expectedId) {
    return { clicked: false, reason: "thread_identity_fields_missing" };
  }
  const rows = Array.from(document.querySelectorAll(
    "#conversation-list .list-item, .conversation-list .list-item, " +
    "[class*='conversation'] [class*='list-item'], [class*='im'] [class*='list-item']"
  )).filter(visible);
  const scored = rows.map((row, index) => {
    const rowText = text(row);
    const rowId = String(attr(row, "id") || attr(row, "data-id") ||
      attr(row, "data-uid") || "").replace(/^_/, "");
    const rowName = text(row.querySelector(".username, .username-text"));
    const rowPosition = text(row.querySelector(".jobname, .job-name"));
    const rowLatest = text(row.querySelector(".last-message, .msg, .message"));
    const rowIdentityText = [rowText, rowName, rowPosition, rowLatest].join("\n");
    const positionMatched = Boolean(
      expectedPosition && contains(rowPosition || rowIdentityText, expectedPosition)
    );
    const positionConflict = Boolean(expectedPosition && !positionMatched);
    if (positionConflict) {
      return {
        row,
        index,
        score: -999,
        rejected: true,
        reason: "position_conflict",
        id: rowId,
        label: rowText,
        name: rowName,
        position: rowPosition,
        latestMessage: rowLatest,
      };
    }
    const latestMatched = Boolean(expectedLatest && contains(rowLatest || rowText, expectedLatest));
    let score = 0;
    if (expectedId && rowId && rowId === expectedId) score += 100;
    if (expectedLabel && exact(rowText, expectedLabel)) score += 45;
    else if (expectedLabel && contains(rowText, expectedLabel)) score += 18;
    if (expectedName && exact(rowName || rowText, expectedName)) score += 60;
    else if (expectedName && contains(rowName || rowText, expectedName)) score += 45;
    if (expectedPosition && exact(rowPosition || rowText, expectedPosition)) score += 45;
    else if (positionMatched) score += 35;
    if (latestMatched) score += 35;
    const missingName = expectedName && !contains(rowName || rowText, expectedName);
    if (missingName) score -= 80;
    return {
      row,
      index,
      score,
      latestMatched,
      id: rowId,
      label: rowText,
      name: rowName,
      position: rowPosition,
      latestMessage: rowLatest,
    };
  }).filter((item) => item.score > 0 && !item.rejected)
    .sort((a, b) => b.score - a.score || a.index - b.index);
  const target = scored[0];
  if (!target) {
    return { clicked: false, reason: "thread_identity_not_found", candidates: scored.length };
  }
  if (target.score < 55) {
    return {
      clicked: false,
      reason: "thread_identity_low_confidence",
      score: target.score,
      label: target.label,
    };
  }
  const second = scored[1];
  if (second && target.score - second.score < 20) {
    return {
      clicked: false,
      reason: "thread_identity_ambiguous",
      candidates: scored.slice(0, 3).map((item) => ({
        index: item.index,
        score: item.score,
        label: item.label,
      })),
    };
  }
  target.row.scrollIntoView({ block: "center", inline: "nearest" });
  const clickTarget = target.row.querySelector(".conversation-item") ||
    target.row.querySelector(".item-content") || target.row.querySelector(".info") || target.row;
  for (const type of ["mouseover", "mousemove", "mousedown", "mouseup", "click"]) {
    clickTarget.dispatchEvent(new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      view: window,
    }));
  }
  return {
    clicked: true,
    source: "identity_dom_click",
    index: target.index,
    score: target.score,
    label: target.label,
    name: target.name,
    position: target.position,
    latestMessage: target.latestMessage,
  };
}
"""

OPENED_CANDIDATE_STATE_JS = r"""
(expected) => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const clean = (value) => String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n")
    .trim();
  const compact = (value) => String(value || "").replace(/\s+/g, "");
  const genericPlaceNames = new Set([
    "\u5317\u4eac", "\u4e0a\u6d77", "\u5e7f\u5dde", "\u6df1\u5733",
    "\u676d\u5dde", "\u5357\u4eac", "\u82cf\u5dde", "\u6210\u90fd",
    "\u91cd\u5e86", "\u6b66\u6c49", "\u897f\u5b89", "\u5929\u6d25",
    "\u5b81\u6ce2", "\u65e0\u9521", "\u957f\u6c99", "\u90d1\u5dde",
    "\u9752\u5c9b", "\u53a6\u95e8", "\u5408\u80a5", "\u4f5b\u5c71"
  ]);
  const isGenericPlaceName = (value) => genericPlaceNames.has(compact(value));
  const ignoredHeaderNameLine = (line) => {
    const value = String(line || "").trim();
    const slim = compact(value);
    if (isGenericPlaceName(value)) return true;
    return !value || value === "|" || value === "｜" ||
      [
        "人才罗盘",
        "在线简历",
        "附件简历",
        "对方已投递",
        "对方撤回了一条消息",
        "暂未填写工作经历",
        "暂未填写教育经历",
        "已投",
        "已读",
        "拒绝",
        "同意",
        "查看更多",
        "求微信",
        "不匹配",
        "标已读",
        "批量回复",
        "可提升求职者",
        "设置",
        "添加",
        "留学",
        "双一流",
        "985",
        "211",
        "统招",
        "非统招",
        "海外院校",
        "全职",
        "兼职",
        "实习",
      ].includes(value) ||
      /^已邀请对方投递/.test(value) ||
      /^(沟通职位|求职意向)[:：]?/.test(value) ||
      /交换微信|涉嫌诈骗/.test(value) ||
      /活跃|在线|刚刚/.test(value) ||
      /^\d{1,2}:\d{2}$/.test(value) ||
      /^\d{2}-\d{2}\s+\d{1,2}:\d{2}$/.test(value) ||
      /^\d{4}\.\d{2}\s*-/.test(value) ||
      /^已选\s*\d+\s*人$/.test(value) ||
      /[|｜]/.test(value) ||
      slim.length > 24;
  };
  const readHeaderName = (parts) => {
    for (let index = 0; index < parts.length; index += 1) {
      const resumeCard = parts[index].match(/^(.{1,16})的简历$/);
      if (resumeCard && !ignoredHeaderNameLine(resumeCard[1])) {
        return resumeCard[1].trim();
      }
    }
    for (let index = 0; index < parts.length; index += 1) {
      const line = parts[index];
      if (/^(沟通职位|求职意向)[:：]?/.test(line)) break;
      if (ignoredHeaderNameLine(line)) continue;
      if (/^\d{4}\.\d{2}\s*-/.test(parts[index - 1] || "")) continue;
      if (/^[|｜]/.test(parts[index + 1] || "")) continue;
      const head = line.match(/^([^\s|｜]{1,16})\s+(?:男|女|\d+\s*岁|[|｜])/);
      if (head) return head[1].trim();
      if (/^[\u4e00-\u9fffA-Za-z·•]{1,12}(先生|女士|小姐|同学)?$/.test(line)) {
        return line;
      }
    }
    const activeIndex = parts.findIndex((line) => /活跃|在线|刚刚/.test(line));
    for (let index = activeIndex - 1; index >= 0; index -= 1) {
      if (!ignoredHeaderNameLine(parts[index])) return parts[index].trim();
    }
    return "";
  };
  const expectedName = String(expected && expected.name || "").trim();
  const expectedPosition = String(expected && expected.position || "").trim();
  const chatReady = Boolean(document.querySelector("#drop-area.input-textarea_self"));
  const rightViewportGate = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.left > window.innerWidth * 0.30 && rect.top < window.innerHeight * 0.70;
  };
  const directHeaderName = (() => {
    const selectors = [
      ".chat-user-info .name",
      ".chat-user-info [class*='name']",
      ".user-info .name",
      ".user-info [class*='name']",
      ".candidate-info .name",
      ".candidate-info [class*='name']",
      ".resume-base-info .name",
      ".resume-base-info [class*='name']",
      ".base-info .name",
      ".base-info [class*='name']",
      "[class*='candidate-name']",
      "[class*='user-name']"
    ];
    return Array.from(document.querySelectorAll(selectors.join(",")))
      .filter((el) => visible(el) && rightViewportGate(el))
      .map((el) => readHeaderName(clean(text(el)).split("\n")) || "")
      .map((value) => value.trim())
      .find((value) => value && !ignoredHeaderNameLine(value)) || "";
  })();
  const rightHeader = (() => {
    const viewportGate = (el) => {
      const rect = el.getBoundingClientRect();
      return rect.left > window.innerWidth * 0.30 && rect.top < window.innerHeight * 0.70;
    };
    const candidates = Array.from(document.querySelectorAll(
      ".im-chat-main, .chat-content, .chat-main, .chat-detail, .im-chat, " +
      ".resume-base-info, .base-info, .candidate-info, [class*='resume-detail'], " +
      "[class*='candidate-info'], [class*='chat-main'], [class*='chat-detail'], section"
    )).filter((el) => {
      if (!visible(el) || !viewportGate(el)) return false;
      const value = text(el);
      return value.includes("沟通职位") || value.includes("求职意向") ||
        (expectedName && compact(value).includes(compact(expectedName)));
    }).map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        el,
        value: clean(text(el)),
        top: rect.top,
        left: rect.left,
        area: rect.width * rect.height,
      };
    }).filter((item) => item.value);
    candidates.sort((a, b) => {
      const aActive = /活跃|在线|刚刚/.test(a.value);
      const bActive = /活跃|在线|刚刚/.test(b.value);
      const aScore = Number(a.value.includes("沟通职位")) * 10 +
        Number(expectedName && compact(a.value).includes(compact(expectedName))) * 50 +
        Number(aActive) * 20 -
        Math.min(a.area / 100000, 20);
      const bScore = Number(b.value.includes("沟通职位")) * 10 +
        Number(expectedName && compact(b.value).includes(compact(expectedName))) * 50 +
        Number(bActive) * 20 -
        Math.min(b.area / 100000, 20);
      return bScore - aScore || a.top - b.top || a.left - b.left;
    });
    return candidates[0] || null;
  })();
  const headerText = rightHeader ? rightHeader.value : "";
  const lines = headerText.split("\n").map((line) => line.trim()).filter(Boolean);
  const positionMatch = headerText.match(/沟通职位\s*[:：]\s*([^\n|｜]+)/);
  const actualPosition = clean(positionMatch ? positionMatch[1] : "");
  const actualName = (() => {
    if (directHeaderName) return directHeaderName;
    const parsed = readHeaderName(lines);
    if (parsed) return parsed;
    if (expectedName && compact(headerText).includes(compact(expectedName))) return expectedName;
    return "";
  })();
  const nameOk = Boolean(
    expectedName && actualName && compact(actualName) === compact(expectedName)
  );
  const nameConflict = Boolean(expectedName && actualName && !nameOk);
  const positionOk = Boolean(
    !nameConflict &&
    expectedPosition &&
    actualPosition &&
    (compact(actualPosition).includes(compact(expectedPosition)) ||
      compact(expectedPosition).includes(compact(actualPosition)))
  );
  const positionConflict = Boolean(
    expectedPosition && actualPosition &&
    !(compact(actualPosition).includes(compact(expectedPosition)) ||
      compact(expectedPosition).includes(compact(actualPosition)))
  );
  const opened = Boolean(chatReady && ((nameOk && !positionConflict) || positionOk));
  return {
    opened,
    reason: opened ? "" : "candidate_identity_mismatch",
    chatReady,
    source: "right_header",
    expected,
    actual: {
      name: actualName,
      position: actualPosition,
      label: headerText,
      source: "right_header",
      headerText,
    },
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
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) : "");
  const clean = (value) => String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !/^\d{1,2}:\d{2}$/.test(line))
    .filter((line) => !["快捷回复", "不匹配"].includes(line))
    .join("\n")
    .trim();
  const lines = (value) => clean(value).split("\n").map((line) => line.trim()).filter(Boolean);
  const compact = (value) => String(value || "").replace(/\s+/g, "");
  const ignoredHeaderNameLine = (line) => {
    const value = String(line || "").trim();
    const slim = compact(value);
    return !value || value === "|" || value === "｜" ||
      [
        "人才罗盘",
        "在线简历",
        "附件简历",
        "对方已投递",
        "对方撤回了一条消息",
        "暂未填写工作经历",
        "暂未填写教育经历",
        "已投",
        "已读",
        "拒绝",
        "同意",
        "查看更多",
        "求微信",
        "不匹配",
        "标已读",
        "批量回复",
        "可提升求职者",
        "设置",
        "添加",
        "留学",
        "双一流",
        "985",
        "211",
        "统招",
        "非统招",
        "海外院校",
        "全职",
        "兼职",
        "实习",
      ].includes(value) ||
      /^已邀请对方投递/.test(value) ||
      /^(沟通职位|求职意向)[:：]?/.test(value) ||
      /交换微信|涉嫌诈骗/.test(value) ||
      /活跃|在线|刚刚/.test(value) ||
      /^\d{1,2}:\d{2}$/.test(value) ||
      /^\d{2}-\d{2}\s+\d{1,2}:\d{2}$/.test(value) ||
      /^\d{4}\.\d{2}\s*-/.test(value) ||
      /^已选\s*\d+\s*人$/.test(value) ||
      /[|｜]/.test(value) ||
      slim.length > 24;
  };
  const readHeaderName = (parts) => {
    for (let index = 0; index < parts.length; index += 1) {
      const resumeCard = parts[index].match(/^(.{1,16})的简历$/);
      if (resumeCard && !ignoredHeaderNameLine(resumeCard[1])) {
        return resumeCard[1].trim();
      }
    }
    for (let index = 0; index < parts.length; index += 1) {
      const line = parts[index];
      if (/^(沟通职位|求职意向)[:：]?/.test(line)) break;
      if (ignoredHeaderNameLine(line)) continue;
      if (/^\d{4}\.\d{2}\s*-/.test(parts[index - 1] || "")) continue;
      if (/^[|｜]/.test(parts[index + 1] || "")) continue;
      const head = line.match(/^([^\s|｜]{1,16})\s+(?:男|女|\d+\s*岁|[|｜])/);
      if (head) return head[1].trim();
      if (/^[\u4e00-\u9fffA-Za-z·•]{1,12}(先生|女士|小姐|同学)?$/.test(line)) {
        return line;
      }
    }
    const activeIndex = parts.findIndex((line) => /活跃|在线|刚刚/.test(line));
    for (let index = activeIndex - 1; index >= 0; index -= 1) {
      if (!ignoredHeaderNameLine(parts[index])) return parts[index].trim();
    }
    return "";
  };
  const parseBatchPosition = (value) => {
    const match = String(value || "").match(/沟通职位[:：]\s*([^\n]+)/);
    return match ? clean(match[1]) : "";
  };
  const parseBatchName = (value) => {
    const parts = lines(value);
    const activeIndex = parts.findIndex((line) => /活跃|在线|刚刚/.test(line));
    if (activeIndex > 0) return parts[activeIndex - 1];
    return parts.find((line) => {
      return !/^沟通职位[:：]/.test(line) &&
        !/^求职意向[:：]/.test(line) &&
        !ignoredHeaderNameLine(line) &&
        !/^\d+\s*岁$/.test(line) &&
        !/\|/.test(line) &&
        !/[,，、]/.test(line) &&
        line.length <= 16;
    }) || "";
  };
  const readBatchItem = (item) => {
    const rawText = text(item);
    const messageNode = item.querySelector(".item-container-message");
    const rawMessage = text(messageNode) || lines(rawText).slice(-1)[0] || "";
    const itemName = text(item.querySelector(
      ".username, .username-text, .item-container-name, .candidate-name, [class*='user-name']"
    )) || parseBatchName(rawText);
    return {
      id: attr(item, "id") || attr(item, "data-id") || rawText,
      label: rawText,
      name: itemName,
      position: parseBatchPosition(rawText),
      message: clean(rawMessage),
      rawMessage,
    };
  };
  const rightHeader = (() => {
    const viewportGate = (el) => {
      const rect = el.getBoundingClientRect();
      return rect.left > window.innerWidth * 0.30 && rect.top < window.innerHeight * 0.70;
    };
    const candidates = Array.from(document.querySelectorAll(
      ".im-chat-main, .chat-content, .chat-main, .chat-detail, .im-chat, " +
      "[class*='chat'], [class*='resume'], [class*='candidate'], main, section, div"
    )).filter((el) => {
      if (!visible(el) || !viewportGate(el)) return false;
      const value = text(el);
      return value.includes("沟通职位") || value.includes("求职意向");
    }).map((el) => {
      const rect = el.getBoundingClientRect();
      return {
        el,
        value: clean(text(el)),
        top: rect.top,
        left: rect.left,
        area: rect.width * rect.height,
      };
    }).filter((item) => item.value);
    candidates.sort((a, b) => {
      const aActive = /活跃|在线|刚刚/.test(a.value);
      const bActive = /活跃|在线|刚刚/.test(b.value);
      const aScore = Number(a.value.includes("沟通职位")) * 10 +
        Number(aActive) * 20 -
        Math.min(a.area / 100000, 20);
      const bScore = Number(b.value.includes("沟通职位")) * 10 +
        Number(bActive) * 20 -
        Math.min(b.area / 100000, 20);
      return bScore - aScore || a.top - b.top || a.left - b.left;
    });
    return candidates[0] || null;
  })();
  const rightHeaderText = rightHeader ? rightHeader.value : "";
  const rightHeaderLines = lines(rightHeaderText);
  const rightHeaderPositionMatch = rightHeaderText.match(/沟通职位\s*[:：]\s*([^\n|｜]+)/);
  const rightHeaderPosition = clean(rightHeaderPositionMatch ? rightHeaderPositionMatch[1] : "");
  const rightHeaderName = (() => {
    return readHeaderName(rightHeaderLines);
  })();
  const rows = Array.from(
    document.querySelectorAll("#conversation-list .list-item")
  ).filter(visible);
  const selectedByClass = rows.find((row) => {
    const cls = String(row.className || "").toLowerCase();
    return /\b(selected|active|current|checked|highlight|is-active)\b/.test(cls) ||
      cls.includes("selected") || cls.includes("active") || cls.includes("highlight");
  });
  const selectedByBackground = rows.find((row) => {
    const color = getComputedStyle(row).backgroundColor;
    const match = color && color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
    if (!match) return false;
    const alpha = match[4] === undefined ? 1 : Number(match[4]);
    if (alpha <= 0) return false;
    const [r, g, b] = [Number(match[1]), Number(match[2]), Number(match[3])];
    return Math.abs(255 - r) + Math.abs(255 - g) + Math.abs(255 - b) > 18;
  });
  const selected = selectedByClass || selectedByBackground || null;
  const selectedText = text(selected);
  const selectedName = text(selected && selected.querySelector(".username, .username-text")) ||
    parseBatchName(selectedText) || "";
  const selectedPosition = text(selected && selected.querySelector(".jobname, .job-name"));
  const name = selectedName || rightHeaderName;
  const position = rightHeaderPosition || selectedPosition;
  const source = rightHeaderName || rightHeaderPosition
    ? "right_header"
    : (selected ? "left_selected_row" : "");
  const lastMessage = text(selected && selected.querySelector(".last-message")) ||
    selectedText.split("\n").slice(-2, -1)[0] || "";
  const unreadBadge = selected && selected.querySelector(".el-badge__content, [class*='badge']");
  const messageNodes = Array.from(document.querySelectorAll("div.im-message-item"));
  const messages = messageNodes.map((node) => {
    const cls = String(node.className || "");
    const mine = node.querySelector(".message-item.mine");
    const other = node.querySelector(".message-item.others");
    let sender = "system";
    if (mine || cls.includes("mine")) sender = "me";
    else if (other || cls.includes("others")) sender = "candidate";
    const rawText = text(node);
    return { sender, text: clean(rawText), rawText };
  }).filter((item) => item.text);
  const batchItems = Array.from(document.querySelectorAll(
    "section.batch-chat-panel .wrap-item, section.batch-chat-panel .batch-chat-item"
  )).filter(visible).map(readBatchItem).filter((item) => item.message);
  const batch = messages.length ? null : (
    batchItems.find((item) => name && compact(item.name) === compact(name)) ||
    batchItems.find((item) => name && compact(item.label).includes(compact(name))) ||
    batchItems[0] ||
    null
  );
  const effectiveMessages = messages.length ? messages : (
    batch ? [{ sender: "candidate", text: batch.message, rawText: batch.rawMessage }] : []
  );
  return {
    id: attr(selected, "id") || (batch && batch.id) || selectedText,
    label: rightHeaderText || selectedText || (batch && batch.label) || "",
    name: name || (batch && batch.name) || "",
    position: position || (batch && batch.position) || "",
    source,
    messages: effectiveMessages,
    latest_message: clean(lastMessage) || (batch && batch.message) || "",
    unread_count: Number.parseInt(text(unreadBadge) || "0", 10) || 0,
  };
}
"""

VERIFY_SENT_JS = r"""
(expected) => {
  const target = String(expected || "").replace(/\s+/g, "");
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const nodes = Array.from(document.querySelectorAll(
    "div.im-message-item, div.message-item.mine"
  ));
  const matched = nodes.some((node) => {
    const mine = node.className && String(node.className).includes("mine") ||
      Boolean(node.querySelector && node.querySelector(".message-item.mine"));
    return mine && target && text(node).replace(/\s+/g, "").includes(target);
  });
  return { verified: matched, source: "dom" };
}
"""

RESUME_PAYLOAD_JS = r"""
() => {
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const downloadLink = document.querySelector(
    ".annex-resume #sensor_Bchatinfo_xiazai a, .annex-resume .item-download a"
  );
  if (downloadLink) {
    return {
      href: downloadLink.href,
      filename: downloadLink.getAttribute("download") || "",
      source: "annex_download_link",
    };
  }
  const links = Array.from(document.querySelectorAll("div.im-message-item a[href], a[href]"));
  const resumeLink = links.find((link) => /简历|附件|pdf|doc/i.test(text(link) + " " + link.href));
  if (resumeLink) return { href: resumeLink.href, text: text(resumeLink) };
  const attachmentCard = Array.from(document.querySelectorAll(
    ".resume-element .info-content-item.file-item"
  )).find(visible);
  const onlineResumeButton = Array.from(document.querySelectorAll(
    "button, a, [role='button'], .el-button, .operate-item, .info-content-item, div, span"
  )).filter(visible).find((el) => {
    if (!text(el).includes("在线简历")) return false;
    return !el.closest(".im-message-item, .message-item");
  });
  const body = text(document.querySelector(".im-chat-main, .chat-content, body"));
  return {
    hasAttachmentCard: Boolean(attachmentCard),
    hasOnlineResumeButton: Boolean(onlineResumeButton),
    previewOnly: /在线简历|附件简历|对方向你发送了简历/.test(body),
    summary: body.slice(-240),
  };
}
"""

CLICK_ONLINE_RESUME_JS = r"""
() => {
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const candidates = Array.from(document.querySelectorAll(
    "button, a, [role='button'], .el-button, .operate-item, .info-content-item, div, span"
  )).filter((el) => {
    if (!visible(el) || !text(el).includes("在线简历")) return false;
    return !el.closest(".im-message-item, .message-item");
  }).map((el) => {
    const rect = el.getBoundingClientRect();
    return { el, label: text(el), top: rect.top, right: window.innerWidth - rect.right };
  }).sort((a, b) => {
    const exact = Number(a.label !== "在线简历") - Number(b.label !== "在线简历");
    if (exact !== 0) return exact;
    const top = a.top - b.top;
    return Math.abs(top) > 8 ? top : a.right - b.right;
  });
  const target = candidates[0] && candidates[0].el;
  if (!target) return { clicked: false, reason: "online_resume_button_not_found" };
  target.click();
  return { clicked: true, label: text(target), source: "top_right_online_resume" };
}
"""

CLICK_ONLINE_RESUME_SAVE_JS = r"""
async () => {
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
      const cursor = getComputedStyle(node).cursor || "";
      const role = attr(node, "role");
      if (tag === "button" || tag === "a" || role === "button" || cursor === "pointer") {
        return node;
      }
    }
    return el;
  };
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const clickConfirmIfNeeded = async () => {
    await sleep(1000);
    const dialogs = Array.from(document.querySelectorAll(
      ".el-dialog, .el-message-box, [role='dialog']"
    )).filter(visible);
    const dialog = dialogs.find((item) => text(item).includes("保存到本地"));
    if (!dialog) return { confirmed: false, reason: "save_dialog_not_found" };
    const pdf = Array.from(dialog.querySelectorAll("label, .el-radio, span, div"))
      .filter(visible)
      .find((item) => text(item).includes("Pdf"));
    if (pdf && !String(pdf.className || "").includes("is-checked")) {
      pdf.click();
    }
    const confirm = Array.from(dialog.querySelectorAll(
      "button, .el-button, [role='button'], span, div"
    )).filter(visible).find((item) => text(item).trim() === "确定");
    if (!confirm) return { confirmed: false, reason: "confirm_button_not_found" };
    confirm.click();
    return { confirmed: true, pdfSelected: Boolean(pdf) };
  };
  const direct = document.querySelector("#sensor_imresume_download");
  if (visible(direct)) {
    direct.click();
    const confirm = await clickConfirmIfNeeded();
    return {
      clicked: true,
      source: "job51_imresume_download",
      label: attr(direct, "title") || "保存",
      ...confirm,
    };
  }
  const nodes = Array.from(document.querySelectorAll(
    "button, a, [role='button'], i, svg, use, span, div"
  )).filter(visible).map((el) => {
    const target = clickable(el);
    const rect = target.getBoundingClientRect();
    const label = [
      text(target), attr(target, "title"), attr(target, "aria-label"),
      attr(target, "class"), attr(el, "class"), attr(el, "xlink:href"), attr(el, "href")
    ].join(" ");
    return { el: target, label, rect, text: text(target) };
  }).filter((item, index, arr) => {
    return arr.findIndex((other) => other.el === item.el) === index;
  });
  const semantic = nodes.find((item) => {
    return /下载|保存|存储|导出|download|save|export/i.test(item.label);
  });
  if (semantic) {
    semantic.el.click();
    const confirm = await clickConfirmIfNeeded();
    return {
      clicked: true,
      source: "semantic_save_icon",
      label: semantic.label.slice(0, 120),
      ...confirm,
    };
  }
  const topRight = nodes.filter((item) => {
    const r = item.rect;
    return r.top >= 0 && r.top < 180 && r.right > window.innerWidth - 280 &&
      r.width >= 12 && r.width <= 80 && r.height >= 12 && r.height <= 80;
  }).sort((a, b) => a.rect.left - b.rect.left);
  if (topRight.length >= 2) {
    const target = topRight[topRight.length - 2];
    target.el.click();
    const confirm = await clickConfirmIfNeeded();
    return {
      clicked: true,
      source: "top_right_second_from_right",
      count: topRight.length,
      label: target.label.slice(0, 120),
      ...confirm,
    };
  }
  return {
    clicked: false,
    reason: "online_resume_save_icon_not_found",
    candidates: nodes.slice(0, 20).map((item) => ({
      label: item.label.slice(0, 120),
      x: Math.round(item.rect.left),
      y: Math.round(item.rect.top),
      w: Math.round(item.rect.width),
      h: Math.round(item.rect.height),
    })),
  };
}
"""

ONLINE_RESUME_DOWNLOAD_PAYLOAD_JS = r"""
() => {
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const links = Array.from(document.querySelectorAll(
    ".annex-resume #sensor_Bchatinfo_xiazai a, .annex-resume .item-download a, " +
    "a[download], a[href^='blob:'], a[href*='download'], a[href*='resume']"
  )).filter(visible);
  const link = links.find((item) => {
    const label = text(item) + " " + (item.getAttribute("download") || "") + " " + item.href;
    return /下载|导出|简历|resume|pdf|doc/i.test(label);
  }) || links[0];
  if (!link) return { found: false };
  return {
    found: true,
    href: link.href,
    filename: link.getAttribute("download") || "",
    source: "online_resume_download_link",
  };
}
"""

ANNEX_DOWNLOAD_PAYLOAD_JS = r"""
() => {
  const link = document.querySelector(
    ".annex-resume #sensor_Bchatinfo_xiazai a, .annex-resume .item-download a"
  );
  if (!link) return { found: false };
  return {
    found: true,
    href: link.href,
    filename: link.getAttribute("download") || "",
  };
}
"""

CLICK_ATTACHMENT_RESUME_JS = r"""
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
    ".resume-element .info-content-item.file-item, " +
    ".resume-element [class*='file-item'], " +
    ".chat-user-operate .file-style.annex, .chat-new-header .file-style.annex, " +
    ".chat-user-operate [class*='annex'], .chat-new-header [class*='annex'], " +
    "[class*='attachment'] [class*='resume']"
  )).filter(visible);
  const matchesAttachment = (item) => /附件简历|简历|pdf|doc/i.test(text(item));
  const messageCandidates = candidates.filter((item) => {
    return item.closest(".resume-element, .im-message-item, .message-item");
  }).filter(matchesAttachment);
  const headerCandidates = candidates.filter((item) => {
    return item.closest(".chat-user-operate, .chat-new-header");
  }).filter(matchesAttachment);
  const target = messageCandidates[0] || headerCandidates[0] ||
    candidates.find(matchesAttachment) || candidates[0];
  if (!target) return { clicked: false, reason: "attachment_button_not_found" };
  target.scrollIntoView({ block: "center", inline: "nearest" });
  target.click();
  const source = target.closest(".chat-user-operate, .chat-new-header")
    ? "top_right_attachment"
    : "dom_attachment_card";
  return { clicked: true, label: text(target), source };
}
"""

FETCH_BLOB_BYTES_JS = r"""
async (href) => {
  const target = String(href || "").split("#")[0];
  if (!target || target.startsWith("javascript:") || target === "#") {
    return { ok: false, reason: "invalid_download_url", href };
  }
  const response = await fetch(target);
  if (!response.ok) {
    return { ok: false, reason: "fetch_failed", status: response.status };
  }
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return {
    ok: true,
    bytesBase64: btoa(binary),
    contentType: response.headers.get("content-type") || "",
    size: bytes.length,
  };
}
"""
