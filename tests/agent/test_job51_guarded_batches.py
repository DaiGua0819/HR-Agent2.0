from __future__ import annotations

from pathlib import Path

from scripts.run_job51_guarded_batches import (
    GuardedRunResult,
    build_job51_once_command,
    classify_abnormal_output,
    run_guarded_batches,
)


def test_job51_guarded_batches_runs_three_limit_one_per_owner() -> None:
    calls: list[list[str]] = []

    def runner(command: list[str], timeout: int) -> GuardedRunResult:
        calls.append(command)
        return GuardedRunResult(returncode=0, output="processed=1 skipped=0 failed=0 total=1")

    result = run_guarded_batches(
        owners=["owner-a", "owner-b"],
        per_owner=3,
        wait=0,
        live=False,
        timeout=30,
        runner=runner,
    )

    assert result["stopped"] is False
    assert len(calls) == 6
    assert [command[command.index("--owner") + 1] for command in calls] == [
        "owner-a",
        "owner-a",
        "owner-a",
        "owner-b",
        "owner-b",
        "owner-b",
    ]
    assert all(command[command.index("--limit") + 1] == "1" for command in calls)


def test_job51_guarded_batches_stops_on_identity_mismatch() -> None:
    calls = 0

    def runner(command: list[str], timeout: int) -> GuardedRunResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            return GuardedRunResult(returncode=0, output="candidate_identity_mismatch")
        return GuardedRunResult(returncode=0, output="processed=1 skipped=0 failed=0 total=1")

    result = run_guarded_batches(
        owners=["owner-a", "owner-b"],
        per_owner=3,
        wait=0,
        live=False,
        timeout=30,
        runner=runner,
    )

    assert result["stopped"] is True
    assert result["reason"] == "candidate_identity_mismatch"
    assert result["owner"] == "owner-a"
    assert result["round"] == 2
    assert calls == 2


def test_job51_guarded_batches_stops_on_failed_summary() -> None:
    def runner(command: list[str], timeout: int) -> GuardedRunResult:
        _ = command, timeout
        return GuardedRunResult(returncode=0, output="processed=0 skipped=0 failed=1 total=1")

    result = run_guarded_batches(
        owners=["owner-a"],
        per_owner=3,
        wait=0,
        live=False,
        timeout=30,
        runner=runner,
    )

    assert result["stopped"] is True
    assert result["reason"] == "failed_summary"
    assert result["owner"] == "owner-a"
    assert result["round"] == 1


def test_job51_guarded_command_adds_live_confirmation() -> None:
    command = build_job51_once_command(
        Path("scripts/run_job51_once.py"),
        owner="owner-a",
        wait=0,
        live=True,
    )

    assert "--live" in command
    assert "--confirm-live" in command
    assert command[command.index("--limit") + 1] == "1"


def test_job51_abnormal_output_classifies_download_mismatch_first() -> None:
    reason = classify_abnormal_output(
        "processed=0 skipped=0 failed=1 total=1\nresume_identity_mismatch"
    )

    assert reason == "resume_identity_mismatch"
