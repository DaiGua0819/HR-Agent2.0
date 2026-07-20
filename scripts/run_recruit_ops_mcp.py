"""Serve the fixed recruitment operations MCP interface over stdio."""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.features.feishu_bot.runtime_control import (  # noqa: E402
    AgentManagerSubprocessClient,
)
from app.features.recruit_ops_mcp.server import (  # noqa: E402
    RecruitmentOpsMcpServer,
    RecruitmentOpsService,
)

_BLOCKED_MANAGER_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
}


class _StderrArgumentParser(argparse.ArgumentParser):
    def print_help(self, file: TextIO | None = None) -> None:
        super().print_help(file=file or sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = _StderrArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--topology", required=True, type=_existing_file)
    parser.add_argument("--max-contacts", type=_non_negative_int, default=0)
    parser.add_argument("--max-anomalies", type=_non_negative_int, default=0)
    parser.add_argument("--sleep", type=_non_negative_float, default=1.0)
    return parser


def build_service(args: argparse.Namespace) -> RecruitmentOpsService:
    manager = AgentManagerSubprocessClient(
        python_executable=sys.executable,
        manager_script=PROJECT_ROOT / "scripts" / "agent_manager.py",
        topology_path=args.topology,
        project_root=PROJECT_ROOT,
        max_contacts=args.max_contacts,
        max_anomalies=args.max_anomalies,
        sleep_seconds=args.sleep,
        blocked_env_names=_BLOCKED_MANAGER_ENV_NAMES,
    )
    return RecruitmentOpsService(manager)


def main(
    argv: Sequence[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    server = RecruitmentOpsMcpServer(build_service(args))
    asyncio.run(
        server.serve(
            input_stream=input_stream or sys.stdin,
            output_stream=output_stream or sys.stdout,
        )
    )
    return 0


def _existing_file(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError("topology must be an existing file")
    return path


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be a finite non-negative number")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
