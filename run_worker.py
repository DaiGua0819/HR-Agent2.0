"""worker 启动入口。"""

from __future__ import annotations

import argparse
import os

import uvicorn
from app.core.logging import configure_logging
from app.settings import load_settings
from app.worker.main import build_worker_app


def parse_args() -> argparse.Namespace:
    """解析 worker 负责人和端口。"""

    parser = argparse.ArgumentParser(description="启动单负责人招聘 worker")
    parser.add_argument("--owner", required=True, help="负责人，如：和新红 / 宋峰峰")
    parser.add_argument("--port", type=int, required=True, help="worker 监听端口")
    return parser.parse_args()


def main() -> None:
    """启动 worker FastAPI。"""

    configure_logging()
    args = parse_args()
    settings = load_settings()
    worker = settings.worker_for_owner(args.owner)
    app = build_worker_app(
        owner=args.owner,
        port=args.port,
        cdp_port=worker.cdp_port,
        browser_backend=os.getenv("HR_AGENT_BROWSER_BACKEND", "fake"),
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, reload=False)


if __name__ == "__main__":
    main()
