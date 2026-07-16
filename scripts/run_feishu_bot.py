"""Operate the standalone Feishu Codex read-only recruitment bot."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.features.feishu_bot.runtime import FeishuBotRuntime, build_runtime  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="check configuration without consuming events")
    handle = commands.add_parser("handle-event", help="process one normalized event JSON")
    handle.add_argument("--event-json", default="")
    commands.add_parser("serve", help="run the standalone event listener")
    commands.add_parser("status", help="show bot-only process status")
    commands.add_parser("stop", help="request graceful bot shutdown")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime: FeishuBotRuntime | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    active_runtime = runtime or build_runtime()
    if args.command == "preflight":
        result = asyncio.run(active_runtime.preflight())
        _print_json(result)
        return 0 if result["ok"] else 1
    if args.command == "handle-event":
        raw = args.event_json or sys.stdin.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("feishu_bot_event_json_object_required")
        _print_json(asyncio.run(active_runtime.handle_event(payload)))
        return 0
    if args.command == "serve":
        asyncio.run(active_runtime.serve())
        return 0
    if args.command == "status":
        _print_json(active_runtime.status())
        return 0
    if args.command == "stop":
        _print_json(active_runtime.request_stop())
        return 0
    raise RuntimeError(f"unsupported_feishu_bot_command:{args.command}")


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
