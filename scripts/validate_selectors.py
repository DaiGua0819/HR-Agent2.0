"""只读验证真实页面选择器。

示例：
  python scripts/validate_selectors.py --owner 和新红 --platform boss
  python scripts/validate_selectors.py --owner 宋峰峰 --platform zhilian --format json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from app.browser.manager import BrowserManager
from app.browser.selector_validation import (
    LoginDetection,
    SelectorResult,
    detect_login_page,
    validate_platform_selectors,
)
from app.core.constants import Platform
from app.settings import load_settings


def parse_args() -> argparse.Namespace:
    """解析选择器验证参数。"""

    parser = argparse.ArgumentParser(description="只读验证三平台真实页面选择器")
    parser.add_argument("--owner", required=True, help="负责人：和新红 / 宋峰峰")
    parser.add_argument("--platform", required=True, choices=[item.value for item in Platform])
    parser.add_argument(
        "--backend",
        default=os.getenv("HR_AGENT_BROWSER_BACKEND", "cloak"),
        choices=["cloak", "cloak-per-platform"],
        help="CloakBrowser 后端；默认按一人一浏览器三标签页连接",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--no-follow-safe-navigation",
        action="store_true",
        help="51job 不点击人才沟通/人才望远镜导航入口，仅检查当前页",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> tuple[LoginDetection, list[SelectorResult]]:
    settings = load_settings()
    worker = settings.worker_for_owner(args.owner)
    platform = Platform(args.platform)
    manager = BrowserManager(owner=args.owner, cdp_port=worker.cdp_port, backend=args.backend)
    await manager.start()
    page = manager.page_for(args.owner, platform)
    login = await detect_login_page(page, platform)
    if login.logged_out:
        return login, []
    results = await validate_platform_selectors(
        page,
        platform,
        follow_safe_navigation=not args.no_follow_safe_navigation,
    )
    return login, results


def _print_text(results: list[SelectorResult]) -> None:
    for item in results:
        sample = f" | sample={item.sample}" if item.sample else ""
        print(
            f"[{item.status}] {item.platform.value}/{item.section}/{item.name} "
            f"count={item.count} selector={item.selector} source={item.source}{sample}"
        )


def _print_login_skip(login: LoginDetection, *, as_json: bool) -> None:
    payload = {
        "platform": login.platform.value,
        "loggedIn": False,
        "message": "未登录,跳过选择器验证",
        "reason": login.reason,
        "url": login.url,
        "sample": login.sample,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "未登录,跳过选择器验证 "
            f"platform={login.platform.value} reason={login.reason} url={login.url}"
        )


def main() -> None:
    """脚本入口。"""

    args = parse_args()
    login, results = asyncio.run(_run(args))
    if login.logged_out:
        _print_login_skip(login, as_json=args.format == "json")
        return
    if args.format == "json":
        print(json.dumps([item.__dict__ for item in results], ensure_ascii=False, indent=2))
    else:
        _print_text(results)


if __name__ == "__main__":
    main()
