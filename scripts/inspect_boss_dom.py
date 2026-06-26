"""只读采样 BOSS 真实页面 DOM。

脚本只连接 CDP、读取页面结构并输出诊断文件；不点击业务按钮、不发送消息、不下载、
不打招呼。用于修复 BOSS 页面选择器漂移。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

from app.browser.playwright_cdp import connect_cdp_browser
from app.platforms.boss import selectors
from app.settings import PROJECT_ROOT

os.environ["DRY_RUN"] = "true"


def parse_args() -> argparse.Namespace:
    """解析 DOM 采样参数。"""

    parser = argparse.ArgumentParser(description="只读采样 BOSS 真实页面 DOM")
    parser.add_argument("--cdp", default="http://127.0.0.1:9333", help="BOSS CDP 地址")
    parser.add_argument("--output-dir", default="data/diagnostics", help="诊断输出目录")
    parser.add_argument("--wait", type=float, default=8.0, help="采样前等待秒数")
    return parser.parse_args()


async def main_async() -> None:
    """脚本异步入口。"""

    args = parse_args()
    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    connection = await connect_cdp_browser(args.cdp)
    try:
        page = await connection.ensure_page(
            name="boss",
            url=selectors.CHAT_URL,
            url_hint="zhipin.com",
        )
        if "zhipin.com/web/chat" not in page.url:
            await page.goto(selectors.CHAT_URL)
        await asyncio.sleep(max(args.wait, 0))
        payload = await page.eval_js(_INSPECT_JS)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / f"boss_dom_{timestamp}.json"
        txt_path = out_dir / f"boss_dom_{timestamp}.txt"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        txt_path.write_text(_render_text(payload), encoding="utf-8")
        print(f"DOM 采样完成: {json_path}")
        print(f"摘要报告: {txt_path}")
        print(_render_text(payload))
    finally:
        await connection.close()


def _render_text(payload: dict[str, Any]) -> str:
    """渲染人可读摘要。"""

    lines = [
        "===== BOSS DOM 只读采样 =====",
        f"URL: {payload.get('url', '')}",
        f"Title: {payload.get('title', '')}",
        f"Body length: {payload.get('bodyLength', 0)}",
        f"Frames: {len(payload.get('frames') or [])}",
        "",
        "----- Body 摘要 -----",
        str(payload.get("bodyText", ""))[:1200],
        "",
        "----- 可见控件 -----",
    ]
    lines.extend(_format_items(payload.get("controls") or [], 80))
    lines.extend(["", "----- 疑似会话/列表节点 -----"])
    lines.extend(_format_items(payload.get("listCandidates") or [], 60))
    lines.extend(["", "----- 疑似消息节点 -----"])
    lines.extend(_format_items(payload.get("messageCandidates") or [], 80))
    lines.extend(["", "----- 疑似输入/工具栏 -----"])
    lines.extend(_format_items(payload.get("inputCandidates") or [], 80))
    lines.extend(["", "----- iframe -----"])
    lines.extend(_format_items(payload.get("frames") or [], 30))
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
        out.append(f"... 共 {len(items)} 项，仅展示前 {limit} 项")
    return out


_INSPECT_JS = r"""
() => {
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
    return /list|item|user|chat|friend|contact|session|conversation|dialog|card/i.test(cls) &&
      text.length >= 2 &&
      text.length <= 500;
  }).map(item);
  const messageCandidates = all.filter((el) => {
    const cls = String(el.className || "");
    const text = textOf(el);
    return /message|bubble|text|chat|content|dialog/i.test(cls) &&
      text.length >= 1 &&
      text.length <= 800;
  }).map(item);
  const inputCandidates = all.filter((el) => {
    const tag = el.tagName.toLowerCase();
    const cls = String(el.className || "");
    return tag === "textarea" ||
      tag === "input" ||
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
    controls,
    listCandidates,
    messageCandidates,
    inputCandidates,
    frames,
  };
}
"""


def main() -> None:
    """脚本入口。"""

    asyncio.run(main_async())


if __name__ == "__main__":
    main()
