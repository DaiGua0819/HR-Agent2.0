"""真实浏览器 dry-run 读路径冒烟。

脚本强制 `DRY_RUN=true`，只读真实页面并记录意图，不发送消息、不求简历、不下载、
不打招呼。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from app.browser.manager import BrowserManager
from app.browser.read_once import dry_run_read_once
from app.core.constants import Platform
from app.settings import load_settings


def parse_args() -> argparse.Namespace:
    """解析 dry-run 读路径参数。"""

    parser = argparse.ArgumentParser(description="真实浏览器 dry-run 读取一个未读会话")
    parser.add_argument("--owner", required=True, help="负责人：和新红 / 宋峰峰")
    parser.add_argument("--platform", required=True, choices=[item.value for item in Platform])
    parser.add_argument(
        "--backend",
        default=os.getenv("HR_AGENT_BROWSER_BACKEND", "real"),
        choices=["real", "cdp", "real-per-platform", "cdp-per-platform"],
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    os.environ["DRY_RUN"] = "true"
    load_settings.cache_clear()
    settings = load_settings()
    worker = settings.worker_for_owner(args.owner)
    manager = BrowserManager(owner=args.owner, cdp_port=worker.cdp_port, backend=args.backend)
    return await dry_run_read_once(
        manager,
        owner=args.owner,
        platform=Platform(args.platform),
    )


def main() -> None:
    """脚本入口。"""

    payload = asyncio.run(_run(parse_args()))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
