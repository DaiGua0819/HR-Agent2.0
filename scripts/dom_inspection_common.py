"""Shared read-only DOM inspection helpers for recruiter platforms.

The scripts using this module only attach to CDP and read page structure. They
do not click business buttons, send messages, request/download resumes, or greet
candidates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

from app.browser.playwright_cdp import connect_cdp_browser
from app.core.constants import Platform
from app.platforms.job51 import selectors as job51_selectors
from app.platforms.zhilian import selectors as zhilian_selectors
from app.settings import PROJECT_ROOT

os.environ["DRY_RUN"] = "true"

DEFAULT_CDP = {
    Platform.JOB51: "http://127.0.0.1:9224",
    Platform.ZHILIAN: "http://127.0.0.1:9226",
}

URL_HINT = {
    Platform.JOB51: "51job.com",
    Platform.ZHILIAN: "zhaopin.com",
}

ENTRY_URL = {
    Platform.JOB51: "https://ehire.51job.com/",
    Platform.ZHILIAN: zhilian_selectors.CHAT_URL,
}


def build_parser(platform: Platform) -> argparse.ArgumentParser:
    """Build a platform-specific DOM inspection parser."""

    parser = argparse.ArgumentParser(description=f"Inspect {platform.value} DOM read-only")
    parser.add_argument("--cdp", default=DEFAULT_CDP[platform], help="CDP endpoint")
    parser.add_argument("--output-dir", default="data/diagnostics", help="Output directory")
    parser.add_argument("--wait", type=float, default=5.0, help="Seconds to wait before sampling")
    return parser


async def inspect_platform(platform: Platform, args: argparse.Namespace) -> None:
    """Attach to CDP, sample page DOM, and write json/txt diagnostics."""

    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    connection = await connect_cdp_browser(args.cdp)
    try:
        page = await connection.ensure_page(
            name=platform.value,
            url=ENTRY_URL[platform],
            url_hint=URL_HINT[platform],
        )
        await asyncio.sleep(max(args.wait, 0))
        payload = await page.eval_js(_INSPECT_JS, _selector_hints(platform))
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / f"{platform.value}_dom_{timestamp}.json"
        txt_path = out_dir / f"{platform.value}_dom_{timestamp}.txt"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        txt_path.write_text(_render_text(platform, payload), encoding="utf-8")
        print(f"DOM sample written: {json_path}")
        print(f"Text report written: {txt_path}")
        print(_render_text(platform, payload))
    finally:
        await connection.close()


def run(platform: Platform) -> None:
    """CLI entrypoint for thin platform wrappers."""

    parser = build_parser(platform)
    asyncio.run(inspect_platform(platform, parser.parse_args()))


def _selector_hints(platform: Platform) -> dict[str, str]:
    if platform == Platform.JOB51:
        return {
            "thread": job51_selectors.THREAD_ITEM,
            "message": job51_selectors.MESSAGE_ITEM,
            "input": job51_selectors.CHAT_INPUT,
            "requestResume": job51_selectors.REQUEST_RESUME_BUTTON,
        }
    return {
        "thread": zhilian_selectors.SESSION_ITEM,
        "message": zhilian_selectors.MESSAGE_ITEM,
        "input": zhilian_selectors.CHAT_INPUT,
        "requestResume": zhilian_selectors.REQUEST_RESUME_BUTTON,
    }


def _render_text(platform: Platform, payload: dict[str, Any]) -> str:
    lines = [
        f"===== {platform.value} DOM read-only sample =====",
        f"URL: {payload.get('url', '')}",
        f"Title: {payload.get('title', '')}",
        f"Body length: {payload.get('bodyLength', 0)}",
        "",
        "----- Body summary -----",
        str(payload.get("bodyText", ""))[:1200],
        "",
        "----- Selector hints -----",
    ]
    for item in payload.get("selectorHints") or []:
        lines.append(
            f"[{item.get('name')}] count={item.get('count')} selector={item.get('selector')}"
        )
        sample = str(item.get("sample") or "").replace("\n", " ")
        if sample:
            lines.append(f"    sample={sample[:180]}")
    for title, key, limit in (
        ("Visible controls", "controls", 70),
        ("Possible conversation/list nodes", "listCandidates", 60),
        ("Possible message nodes", "messageCandidates", 80),
        ("Possible input/toolbar nodes", "inputCandidates", 60),
        ("Frames", "frames", 30),
    ):
        lines.extend(["", f"----- {title} -----"])
        lines.extend(_format_items(payload.get(key) or [], limit))
    return "\n".join(lines)


def _format_items(items: list[dict[str, Any]], limit: int) -> list[str]:
    out: list[str] = []
    for index, item in enumerate(items[:limit], start=1):
        out.append(
            f"[{index}] tag={item.get('tag', '')} id={item.get('id', '')} "
            f"class={item.get('className', '')} selector={item.get('selector', '')}"
        )
        text = str(item.get("text") or item.get("url") or "").replace("\n", " ")
        if text:
            out.append(f"    text={text[:180]}")
    if len(items) > limit:
        out.append(f"... total={len(items)}, showing first {limit}")
    return out


_INSPECT_JS = r"""
(hints) => {
  const visible = (el) => {
    if (!el || !(el instanceof Element)) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== "hidden" &&
      style.display !== "none" &&
      rect.width > 0 &&
      rect.height > 0;
  };
  const textOf = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const css = (el) => {
    if (!el || !(el instanceof Element)) return "";
    if (el.id) return `#${CSS.escape(el.id)}`;
    const cls = Array.from(el.classList || []).slice(0, 4).map((v) => CSS.escape(v)).join(".");
    return cls ? `${el.tagName.toLowerCase()}.${cls}` : el.tagName.toLowerCase();
  };
  const item = (el) => {
    const rect = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || "",
      className: String(el.className || "").slice(0, 180),
      selector: css(el),
      role: el.getAttribute("role") || "",
      aria: el.getAttribute("aria-label") || "",
      placeholder: el.getAttribute("placeholder") || "",
      contenteditable: el.getAttribute("contenteditable") || "",
      text: textOf(el).replace(/\s+/g, " ").slice(0, 500),
      x: Math.round(rect.x),
      y: Math.round(rect.y),
      w: Math.round(rect.width),
      h: Math.round(rect.height),
    };
  };
  const all = Array.from(document.querySelectorAll("*")).filter(visible);
  const selectorHints = Object.entries(hints || {}).map(([name, selector]) => {
    const nodes = Array.from(document.querySelectorAll(selector || "")).filter(visible);
    return { name, selector, count: nodes.length, sample: nodes[0] ? textOf(nodes[0]) : "" };
  });
  const controls = all.filter((el) => {
    const tag = el.tagName.toLowerCase();
    return ["button", "a", "input", "textarea", "select"].includes(tag) ||
      el.getAttribute("role") === "button" ||
      el.getAttribute("contenteditable") === "true" ||
      el.tabIndex >= 0 ||
      /button|btn|tab|filter|send|input|textarea|editor/i.test(String(el.className || ""));
  }).map(item);
  const listCandidates = all.filter((el) => {
    const cls = String(el.className || "");
    const text = textOf(el);
    return /list|item|user|chat|friend|contact|session|conversation|card/i.test(cls) &&
      text.length >= 2 && text.length <= 500;
  }).map(item);
  const messageCandidates = all.filter((el) => {
    const cls = String(el.className || "");
    const text = textOf(el);
    return /message|bubble|text|chat|content|dialog/i.test(cls) &&
      text.length >= 1 && text.length <= 800;
  }).map(item);
  const inputCandidates = all.filter((el) => {
    const tag = el.tagName.toLowerCase();
    const cls = String(el.className || "");
    return tag === "textarea" || tag === "input" ||
      el.getAttribute("contenteditable") === "true" ||
      /input|editor|textarea|toolbar|send|reply|message/i.test(cls);
  }).map(item);
  const frames = Array.from(document.querySelectorAll("iframe,frame")).map((el) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || "",
    className: String(el.className || ""),
    selector: css(el),
    url: el.src || "",
    text: "",
  }));
  return {
    url: location.href,
    title: document.title,
    bodyLength: document.body ? document.body.innerText.length : 0,
    bodyText: document.body ? document.body.innerText.replace(/\s+/g, " ").slice(0, 4000) : "",
    selectorHints,
    controls,
    listCandidates,
    messageCandidates,
    inputCandidates,
    frames,
  };
}
"""
