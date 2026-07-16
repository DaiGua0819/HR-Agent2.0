"""Operate the standalone Feishu Codex read-only recruitment bot."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.features.feishu_bot.runtime import FeishuBotRuntime, build_runtime  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start", help="launch the standalone listener in the background")
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
    if args.command == "start":
        preflight = asyncio.run(active_runtime.preflight())
        if not preflight["ok"]:
            _print_json(preflight)
            return 1
        _print_json(launch_detached_bot(active_runtime))
        return 0
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


def launch_detached_bot(
    runtime: FeishuBotRuntime,
    *,
    python_executable: str = sys.executable,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 15,
    platform_name: str | None = None,
) -> dict[str, object]:
    current = runtime.status()
    if current["running"]:
        return {
            "started": False,
            "alreadyRunning": True,
            "launcherPid": 0,
            "pid": int(current["pid"] or 0),
            "status": current["status"],
        }

    runtime.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = runtime.paths.runtime_dir / "bot.out.log"
    stderr_path = runtime.paths.runtime_dir / "bot.err.log"
    active_platform = platform_name or os.name
    creationflags = 0
    if active_platform == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
            | subprocess.DETACHED_PROCESS
        )

    with stdout_path.open("ab") as stdout_handle, stderr_path.open("ab") as stderr_handle:
        process = popen_factory(
            [python_executable, str(Path(__file__).resolve()), "serve"],
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            close_fds=True,
            shell=False,
            creationflags=creationflags,
            start_new_session=active_platform != "nt",
        )

    previous_pid = int(current.get("pid") or 0)
    previous_started_at = str(current.get("startedAt") or "")
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        status = runtime.status()
        if status["running"] and (
            int(status["pid"] or 0) != previous_pid
            or str(status.get("startedAt") or "") != previous_started_at
        ):
            return {
                "started": True,
                "alreadyRunning": False,
                "launcherPid": int(process.pid),
                "pid": int(status["pid"] or 0),
                "status": status["status"],
            }
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(f"feishu_bot_start_failed:{returncode}")
        sleep(0.1)
    raise RuntimeError("feishu_bot_start_timeout")


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
