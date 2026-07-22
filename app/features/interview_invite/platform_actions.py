"""Platform-page actions for interview invite exchange workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.browser.base import BrowserPage
from app.core.constants import Platform
from app.platforms.types import SendResult

FOLLOWUP_MESSAGE = "加我微信沟通"


async def invite_to_interview(
    page: BrowserPage,
    *,
    platform: Platform,
    owner: str,
    payload: dict[str, Any],
    send_message: Callable[[str], Awaitable[SendResult]],
    dry_run: bool,
) -> dict[str, Any]:
    """Search target contact, locate WeChat exchange, and optionally execute it."""

    contact = dict(payload.get("platformContact") or {})
    display_name = str(contact.get("displayName") or "").strip()
    if not display_name:
        return _failed("missing_platform_display_name", dry_run=dry_run)
    search = await _search_contact(
        page,
        platform=platform,
        owner=owner,
        contact=contact,
    )
    if not search.get("found"):
        return _failed("search_result_not_found", dry_run=dry_run, search=search)
    if not search.get("verified", True):
        return _failed("multiple_candidates_unverified", dry_run=dry_run, search=search)
    exchange = await _eval_dict(
        page,
        _LOCATE_EXCHANGE_JS,
        {"platform": platform.value, "owner": owner, "contact": contact},
    )
    if not exchange.get("found"):
        return _failed(
            "wechat_exchange_button_not_found",
            dry_run=dry_run,
            search=search,
            exchange=exchange,
        )
    if dry_run:
        return {
            "accepted": True,
            "dryRun": True,
            "readyToExchange": True,
            "platform": platform.value,
            "search": search,
            "exchange": exchange,
        }
    clicked = await _eval_dict(
        page,
        _CLICK_EXCHANGE_JS,
        {"platform": platform.value, "owner": owner, "contact": contact},
    )
    if not clicked.get("verified"):
        return _failed(
            "wechat_exchange_verification_failed",
            dry_run=False,
            search=search,
            exchange=exchange,
            click=clicked,
        )
    sent = await send_message(FOLLOWUP_MESSAGE)
    if not sent.sent or not sent.verified:
        return _failed(
            "interview_followup_send_failed",
            dry_run=False,
            search=search,
            exchange=exchange,
            click=clicked,
            sendResult=_send_payload(sent),
        )
    return {
        "accepted": True,
        "dryRun": False,
        "readyToExchange": True,
        "exchanged": True,
        "platform": platform.value,
        "search": search,
        "exchange": exchange,
        "click": clicked,
        "sendResult": _send_payload(sent),
    }


async def _eval_dict(page: BrowserPage, script: str, arg: dict[str, Any]) -> dict[str, Any]:
    try:
        value = await page.eval_js(script, arg)
    except Exception as error:
        return {"ok": False, "error": str(error)}
    return value if isinstance(value, dict) else {"ok": False, "value": str(value)}


async def _search_contact(
    page: BrowserPage,
    *,
    platform: Platform,
    owner: str,
    contact: dict[str, Any],
) -> dict[str, Any]:
    arg = {"platform": platform.value, "owner": owner, "contact": contact}
    if platform is Platform.ZHILIAN:
        activation = await _eval_dict(page, _ACTIVATE_SEARCH_JS, arg)
        if activation.get("activated"):
            await asyncio.sleep(0.35)
    search = await _eval_dict(page, _SEARCH_CONTACT_JS, arg)
    for _attempt in range(3):
        if not search.get("searchSubmitted") and not search.get("conversationOpening"):
            break
        await asyncio.sleep(0.9 if search.get("searchSubmitted") else 0.7)
        search = await _eval_dict(page, _SEARCH_CONTACT_JS, arg)
    return search


def _send_payload(result: SendResult) -> dict[str, Any]:
    return {
        "sent": result.sent,
        "verified": result.verified,
        "blocked": result.blocked,
        "message": result.message,
        "details": result.details,
    }


def _failed(reason: str, *, dry_run: bool, **extra: Any) -> dict[str, Any]:
    return {"accepted": False, "dryRun": dry_run, "reason": reason, **extra}


_ACTIVATE_SEARCH_JS = r"""
({ platform }) => {
  const marker = "interview_invite.activate_search";
  if (platform !== "zhilian") {
    return { activated: false, platform, marker };
  }
  const visible = (node) => {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const activeInput = Array.from(document.querySelectorAll(
    "input[placeholder*='搜索聊天记录'], input[placeholder*='姓名/职位/公司']"
  )).find(visible);
  if (activeInput) {
    return { activated: false, searchInputVisible: true, platform, marker };
  }
  const activator = Array.from(document.querySelectorAll(
    ".side-panel-header__input-button, [class*='side-panel-header'][class*='input-button']"
  )).find(visible);
  if (!activator) {
    return { activated: false, reason: "search_activator_not_found", platform, marker };
  }
  activator.click();
  return { activated: true, platform, marker };
}
"""


_SEARCH_CONTACT_JS = r"""
({ platform, contact }) => {
  const marker = "interview_invite.search_contact";
  const text = (node) => (node?.innerText || node?.textContent || "").trim();
  const visible = (node) => {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const displayName = String(contact?.displayName || "").trim();
  const position = String(contact?.appliedPosition || "").trim();
  if (!displayName) {
    return {
      found: false,
      verified: false,
      reason: "missing_display_name",
      marker,
    };
  }
  const searchInputs = Array.from(document.querySelectorAll(
    [
      "input[placeholder*='搜索']",
      "input[placeholder*='姓名']",
      "input[type='search']",
      "textarea[placeholder*='搜索']",
    ].join(", ")
  )).filter(visible);
  const input = searchInputs[0] || null;
  if (input) {
    const currentValue = String(input.value || "").trim();
    if (currentValue !== displayName) {
      input.focus();
      input.value = displayName;
      input.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        inputType: "insertText",
        data: displayName,
      }));
      input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
      input.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter" }));
      return {
        found: false,
        verified: false,
        searchSubmitted: true,
        displayName,
        position,
        usedSearchInput: true,
        platform,
        marker,
      };
    }
  }
  const bodyText = text(document.body);
  const nameHit = bodyText.includes(displayName);
  const positionHit = !position || bodyText.includes(position);
  if (platform === "zhilian" && input && nameHit && positionHit) {
    const results = Array.from(document.querySelectorAll(
      ".im-search-result, .im-search-all-results__group-list > *, [class*='im-search-result']"
    )).filter((node) => {
      if (!visible(node)) return false;
      const value = text(node);
      return value.includes(displayName) && (!position || value.includes(position));
    });
    const leafResults = results.filter((node) => !results.some(
      (other) => other !== node && node.contains(other)
    ));
    if (leafResults.length === 1) {
      leafResults[0].click();
      return {
        found: true,
        verified: true,
        conversationOpening: true,
        displayName,
        position,
        usedSearchInput: true,
        platform,
        marker,
      };
    }
    if (leafResults.length > 1) {
      return {
        found: true,
        verified: false,
        reason: "multiple_candidates_unverified",
        resultCount: leafResults.length,
        displayName,
        position,
        usedSearchInput: true,
        platform,
        marker,
      };
    }
  }
  return {
    found: nameHit,
    verified: Boolean(nameHit && positionHit),
    displayName,
    position,
    usedSearchInput: Boolean(input),
    platform,
    marker,
  };
}
"""

_LOCATE_EXCHANGE_JS = r"""
({ platform }) => {
  const marker = "interview_invite.locate_wechat_exchange";
  const result = findWechatExchangeTarget();
  if (!result.target) {
    return {
      found: false,
      reason: "wechat_exchange_button_not_found",
      platform,
      marker,
      candidates: result.candidates,
    };
  }
  return {
    found: true,
    label: result.label,
    targetLabel: result.targetLabel,
    tag: result.target.tagName,
    className: String(result.target.className || ""),
    score: result.score,
    platform,
    marker,
  };

  function findWechatExchangeTarget() {
    const exact = "\u6362\u5fae\u4fe1";
    const stale = "\u5df2\u4ea4\u6362\u5fae\u4fe1";
    const keywords = [
      exact,
      "\u4ea4\u6362\u5fae\u4fe1",
      "\u5fae\u4fe1\u53f7",
      "\u590d\u5236\u5fae\u4fe1",
    ];
    const nodes = Array.from(document.querySelectorAll(
      "button,[role='button'],a,span,div"
    ));
    const candidates = nodes.filter(visible).map((node) => {
      const label = compactText(node);
      const attrs = [
        node.getAttribute("aria-label") || "",
        node.getAttribute("title") || "",
      ].join(" ");
      const target = clickTarget(node);
      const targetLabel = compactText(target);
      const rect = target.getBoundingClientRect();
      let score = 0;
      if (label === exact || targetLabel === exact) score += 1000;
      if (attrs.includes(exact)) score += 900;
      if (keywords.some((word) => label.includes(word) || attrs.includes(word))) {
        score += 120;
      }
      if (label.includes(stale) || targetLabel.includes(stale)) score -= 700;
      if (label.length > exact.length) score -= Math.min(label.length, 180);
      if (isInteractive(target)) score += 180;
      if (/exchange|wechat|wx|ask-for-wx|operate-icon|km-button/.test(
        String(target.className || "")
      )) {
        score += 150;
      }
      score -= Math.min(Math.round((rect.width * rect.height) / 1000), 80);
      return {
        node,
        target,
        label,
        targetLabel,
        score,
        tag: target.tagName,
        className: String(target.className || ""),
      };
    }).filter((item) => item.score > 0);
    candidates.sort((left, right) => right.score - left.score);
    const best = candidates[0] || {};
    return {
      ...best,
      candidates: candidates.slice(0, 5).map((item) => ({
        label: item.label,
        targetLabel: item.targetLabel,
        score: item.score,
        tag: item.tag,
        className: item.className,
      })),
    };
  }
  function compactText(node) {
    return (node?.innerText || node?.textContent || "").trim().replace(/\s+/g, " ");
  }
  function visible(node) {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 &&
      rect.height > 0 &&
      style.visibility !== "hidden" &&
      style.display !== "none";
  }
  function clickTarget(node) {
    return node.closest([
      "button",
      "a",
      "[role='button']",
      "[class*='exchange-wx']",
      "[class*='ask-for-wx']",
      "[class*='operate-icon-item']",
      "[class*='km-button']",
    ].join(",")) || node;
  }
  function isInteractive(node) {
    return Boolean(node?.matches("button,a,[role='button']"));
  }
}
"""

_CLICK_EXCHANGE_JS = r"""
({ platform }) => {
  const marker = "interview_invite.click_wechat_exchange";
  const result = findWechatExchangeTarget();
  const target = result.target || null;
  if (!target) {
    return {
      clicked: false,
      verified: false,
      reason: "wechat_exchange_button_not_found",
      platform,
      marker,
      candidates: result.candidates,
    };
  }
  target.click();
  const confirms = Array.from(document.querySelectorAll(
    "[role='dialog'] button,.modal button,[class*='dialog'] button,button"
  ))
    .filter(visible)
    .filter((node) => {
      const label = compactText(node);
      return [
        "\u786e\u5b9a",
        "\u786e\u8ba4",
        "\u53d1\u9001",
        "\u53d1\u8d77\u4ea4\u6362",
      ].some((word) => label.includes(word));
    });
  const confirm = confirms[0] || null;
  if (confirm) confirm.click();
  const bodyText = compactText(document.body);
  const verified = [
    "\u5df2\u4ea4\u6362",
    "\u4ea4\u6362\u5fae\u4fe1",
    "\u5fae\u4fe1\u53f7",
    "\u8bf7\u6c42\u5df2\u53d1\u9001",
    "\u5df2\u53d1\u9001",
  ].some((word) => bodyText.includes(word));
  return {
    clicked: true,
    confirmed: Boolean(confirm),
    verified,
    label: result.label,
    targetLabel: result.targetLabel,
    platform,
    marker,
  };

  function findWechatExchangeTarget() {
    const exact = "\u6362\u5fae\u4fe1";
    const stale = "\u5df2\u4ea4\u6362\u5fae\u4fe1";
    const keywords = [
      exact,
      "\u4ea4\u6362\u5fae\u4fe1",
      "\u5fae\u4fe1\u53f7",
      "\u590d\u5236\u5fae\u4fe1",
    ];
    const nodes = Array.from(document.querySelectorAll(
      "button,[role='button'],a,span,div"
    ));
    const candidates = nodes.filter(visible).map((node) => {
      const label = compactText(node);
      const attrs = [
        node.getAttribute("aria-label") || "",
        node.getAttribute("title") || "",
      ].join(" ");
      const target = clickTarget(node);
      const targetLabel = compactText(target);
      const rect = target.getBoundingClientRect();
      let score = 0;
      if (label === exact || targetLabel === exact) score += 1000;
      if (attrs.includes(exact)) score += 900;
      if (keywords.some((word) => label.includes(word) || attrs.includes(word))) {
        score += 120;
      }
      if (label.includes(stale) || targetLabel.includes(stale)) score -= 700;
      if (label.length > exact.length) score -= Math.min(label.length, 180);
      if (isInteractive(target)) score += 180;
      if (/exchange|wechat|wx|ask-for-wx|operate-icon|km-button/.test(
        String(target.className || "")
      )) {
        score += 150;
      }
      score -= Math.min(Math.round((rect.width * rect.height) / 1000), 80);
      return {
        node,
        target,
        label,
        targetLabel,
        score,
        tag: target.tagName,
        className: String(target.className || ""),
      };
    }).filter((item) => item.score > 0);
    candidates.sort((left, right) => right.score - left.score);
    const best = candidates[0] || {};
    return {
      ...best,
      candidates: candidates.slice(0, 5).map((item) => ({
        label: item.label,
        targetLabel: item.targetLabel,
        score: item.score,
        tag: item.tag,
        className: item.className,
      })),
    };
  }
  function compactText(node) {
    return (node?.innerText || node?.textContent || "").trim().replace(/\s+/g, " ");
  }
  function visible(node) {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 &&
      rect.height > 0 &&
      style.visibility !== "hidden" &&
      style.display !== "none";
  }
  function clickTarget(node) {
    return node.closest([
      "button",
      "a",
      "[role='button']",
      "[class*='exchange-wx']",
      "[class*='ask-for-wx']",
      "[class*='operate-icon-item']",
      "[class*='km-button']",
    ].join(",")) || node;
  }
  function isInteractive(node) {
    return Boolean(node?.matches("button,a,[role='button']"));
  }
}
"""
