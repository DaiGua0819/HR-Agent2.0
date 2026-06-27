"""可靠动作层内部工具。

本模块只服务 `reliable_actions.py`，负责验证、节流、记录和页面只读探测。
它不包含平台业务规则，也不读取 dry-run。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.browser.base import BrowserPage
from app.browser.interaction_profile import InteractionProfile

VerifyCallback = Callable[[], Awaitable[bool | dict[str, object]]]


async def wait_verified(
    page: BrowserPage,
    verify: VerifyCallback | None,
    timeout_ms: int,
) -> dict[str, object]:
    """等待调用方的动作后验证成功。"""

    if verify is None:
        return {"verified": True}
    if is_fake(page):
        return await verify_once(verify)
    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    last = {"verified": False, "reason": "verify_timeout"}
    while time.monotonic() <= deadline:
        last = await verify_once(verify)
        if last["verified"]:
            return last
        await asyncio.sleep(0.15)
    return last


async def verify_once(verify: VerifyCallback | None) -> dict[str, object]:
    """执行一次验证回调并规整结果。"""

    if verify is None:
        return {"verified": False, "reason": "verify_not_configured"}
    try:
        value = await verify()
    except Exception as error:
        return {"verified": False, "reason": "verify_error", "error": str(error)}
    if isinstance(value, dict):
        verified = bool(value.get("verified", value.get("ok", False)))
        return {"verified": verified, **value}
    return {"verified": bool(value)}


async def verify_filled(page: BrowserPage, selector: str, text: str) -> bool:
    """校验输入框当前值与期望文本一致。"""

    value = await safe_eval(
        page,
        """
        payload => {
          const el = document.querySelector(payload.selector);
          if (!el) return null;
          return ("value" in el) ? el.value : (el.textContent || "");
        }
        """,
        {"selector": selector},
    )
    if value is None:
        value = await page.text(selector)
    return str(value or "") == text


async def scroll_position(page: BrowserPage, selector: str) -> int:
    """读取页面或容器当前滚动位置。"""

    value = await safe_eval(
        page,
        """
        selector => {
          const el = selector ? document.querySelector(selector) : null;
          const target = el || document.scrollingElement || document.documentElement;
          return Math.round(target.scrollTop || window.scrollY || 0);
        }
        """,
        selector,
    )
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def safe_eval(page: BrowserPage, script: str, arg: object | None = None) -> Any:
    """执行只读 JS，失败时返回 None。"""

    try:
        return await page.eval_js(script, arg)
    except Exception:
        return None


async def sleep_ms(page: BrowserPage, milliseconds: int, profile: InteractionProfile) -> None:
    """按配置休眠；FakePage 下永远不休眠。"""

    if not profile.enabled or milliseconds <= 0 or is_fake(page):
        return
    await asyncio.sleep(milliseconds / 1000)


def record_result(page: BrowserPage, result: dict[str, object]) -> None:
    """把动作结果追加到页面记录。"""

    if hasattr(page, "reliable_actions"):
        page.reliable_actions.append(dict(result))  # type: ignore[attr-defined]


def result_dict(ok: bool, action: str, label: str, **extra: object) -> dict[str, object]:
    """生成统一动作返回结构。"""

    return {
        "ok": ok,
        "action": action,
        "label": label,
        "method": f"reliable_{action}",
        **extra,
    }


def last_reason(attempts: list[dict[str, object]], fallback: str) -> str:
    """提取最后一次失败原因。"""

    if not attempts:
        return fallback
    return str(attempts[-1].get("reason") or fallback)


def is_fake(page: BrowserPage) -> bool:
    """识别 FakePage，避免测试里真实休眠。"""

    return bool(getattr(page, "is_fake", False))


SCROLL_JS = """
payload => {
  const el = payload.selector ? document.querySelector(payload.selector) : null;
  const target = el || document.scrollingElement || document.documentElement;
  if (!target) return { scrolled: false };
  if (target === document.documentElement || target === document.scrollingElement) {
    window.scrollBy(0, payload.amount);
  } else {
    target.scrollTop = (target.scrollTop || 0) + payload.amount;
    target.dispatchEvent(new Event("scroll", { bubbles: true }));
  }
  return { scrolled: true, amount: payload.amount };
}
"""
