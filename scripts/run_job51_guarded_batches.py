"""Run guarded 51job one-candidate batches and stop on identity anomalies."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ABNORMAL_REASONS = (
    "resume_identity_mismatch",
    "candidate_identity_mismatch",
    "stale_resume_overlay_not_closed",
)
FAILED_SUMMARY_PATTERN = re.compile(r"\bfailed=(\d+)\b")


@dataclass(frozen=True)
class GuardedRunResult:
    returncode: int
    output: str


Runner = Callable[[list[str], int], GuardedRunResult]


def build_job51_once_command(
    script_path: Path,
    *,
    owner: str,
    wait: float,
    live: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path),
        "--owner",
        owner,
        "--limit",
        "1",
        "--wait",
        str(wait),
    ]
    if live:
        command.extend(["--live", "--confirm-live"])
    return command


def classify_abnormal_output(output: str) -> str:
    for reason in ABNORMAL_REASONS:
        if reason in output:
            return reason
    if "Traceback (most recent call last)" in output:
        return "traceback"
    for match in FAILED_SUMMARY_PATTERN.finditer(output):
        if int(match.group(1)) > 0:
            return "failed_summary"
    return ""


def run_guarded_batches(
    *,
    owners: Sequence[str],
    per_owner: int,
    wait: float,
    live: bool,
    timeout: int,
    runner: Runner | None = None,
) -> dict[str, Any]:
    active_runner = runner or _subprocess_runner
    script_path = ROOT / "scripts" / "run_job51_once.py"
    runs: list[dict[str, Any]] = []

    for owner in owners:
        for round_index in range(1, max(1, per_owner) + 1):
            command = build_job51_once_command(
                script_path,
                owner=owner,
                wait=wait,
                live=live,
            )
            _print(f"[job51] owner={owner} round={round_index}/{per_owner} limit=1")
            result = active_runner(command, timeout)
            run_record = {
                "owner": owner,
                "round": round_index,
                "returncode": result.returncode,
                "output": result.output,
            }
            runs.append(run_record)
            if result.output:
                _print(result.output.rstrip())
            reason = classify_abnormal_output(result.output)
            if not reason and result.returncode != 0:
                reason = "nonzero_exit"
            if reason:
                _print(
                    f"[stop] job51 guarded batch stopped: "
                    f"owner={owner} round={round_index} reason={reason}"
                )
                return {
                    "stopped": True,
                    "reason": reason,
                    "owner": owner,
                    "round": round_index,
                    "runs": runs,
                }

    return {"stopped": False, "reason": "", "owner": "", "round": 0, "runs": runs}


def default_job51_owners() -> list[str]:
    from app.core.constants import Platform
    from app.settings import load_settings

    settings = load_settings()
    return [worker.owner for worker in settings.workers if Platform.JOB51 in worker.accounts]


def main() -> None:
    args = _parse_args()
    owners = list(args.owner) or default_job51_owners()
    if not owners:
        raise SystemExit("No 51job owners configured.")
    result = run_guarded_batches(
        owners=owners,
        per_owner=args.per_owner,
        wait=args.wait,
        live=bool(args.live),
        timeout=args.timeout,
    )
    raise SystemExit(2 if result["stopped"] else 0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 51job in guarded one-candidate batches; stop on anomalies."
    )
    parser.add_argument(
        "--owner",
        action="append",
        default=[],
        help="Owner name from config/accounts.yaml; repeat for multiple owners.",
    )
    parser.add_argument("--per-owner", type=int, default=3, help="One-candidate rounds per owner.")
    parser.add_argument("--wait", type=float, default=3.0, help="Seconds to wait after attach.")
    parser.add_argument("--timeout", type=int, default=180, help="Seconds per one-candidate run.")
    parser.add_argument("--live", action="store_true", help="Pass live mode to run_job51_once.py.")
    return parser.parse_args()


def _subprocess_runner(command: list[str], timeout: int) -> GuardedRunResult:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        output = "\n".join(part for part in (stdout, stderr, "process_timeout") if part)
        return GuardedRunResult(returncode=124, output=output)
    return GuardedRunResult(
        returncode=completed.returncode,
        output="\n".join(part for part in (completed.stdout, completed.stderr) if part),
    )


def _print(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":
    main()
