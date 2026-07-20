from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from scripts.run_codex_recruitment_schedule import (
    CommandResult,
    GlobalMutex,
    SchedulePaths,
    run_command,
    run_scheduled,
)

THREAD_ID = "019f8050-f5d6-71e3-a4d5-ebfa6c9db78a"


def _paths(tmp_path: Path) -> SchedulePaths:
    project_root = tmp_path / "project"
    scripts_dir = project_root / "scripts"
    scripts_dir.mkdir(parents=True)
    python_executable = tmp_path / "python.exe"
    codex_executable = tmp_path / "codex.exe"
    manager_script = scripts_dir / "agent_manager.py"
    topology_path = tmp_path / "topology.json"
    thread_id_path = tmp_path / "operations-thread-id.txt"
    for path in (python_executable, codex_executable, manager_script, topology_path):
        path.write_text("", encoding="utf-8")
    thread_id_path.write_text(THREAD_ID, encoding="ascii")
    return SchedulePaths(
        project_root=project_root,
        python_executable=python_executable,
        manager_script=manager_script,
        topology_path=topology_path,
        codex_executable=codex_executable,
        thread_id_path=thread_id_path,
        log_root=tmp_path / "logs",
    )


def _codex_jsonl(
    tools: list[str],
    *,
    inner_preflight_ok: bool,
    final_message: str = "summary",
    daily_report_date: str = "2026-07-21",
    extra_events: list[dict[str, object]] | None = None,
    status_overrides: dict[str, str] | None = None,
) -> str:
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": THREAD_ID},
        {"type": "turn.started"},
    ]
    events.extend(extra_events or [])
    for index, tool in enumerate(tools):
        arguments = {"date": daily_report_date} if tool == "daily_report" else {}
        payload: dict[str, object] = {"ok": True}
        status = "completed"
        if tool == "recruitment_preflight":
            payload = {"ok": inner_preflight_ok}
            status = "completed" if inner_preflight_ok else "failed"
        elif tool == "daily_report":
            payload = {"date": daily_report_date}
        status = (status_overrides or {}).get(tool, status)
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "id": f"tool-{index}",
                    "type": "mcp_tool_call",
                    "server": "recruit_ops",
                    "tool": tool,
                    "arguments": arguments,
                    "status": status,
                    "result": {"structured_content": payload},
                    "error": None if status in {"completed", "failed"} else "tool_failed",
                },
            }
        )
    events.append(
        {
            "type": "item.completed",
            "item": {
                "id": "final",
                "type": "agent_message",
                "text": final_message,
            },
        }
    )
    events.append({"type": "turn.completed", "usage": {}})
    return "\n".join(json.dumps(item) for item in events) + "\n"


def _summary(paths: SchedulePaths) -> dict[str, object]:
    files = list(paths.log_root.rglob("summary.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_blocked_preflight_resumes_thread_without_starting_processing(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    calls: list[dict[str, object]] = []

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        calls.append(
            {
                "argv": tuple(argv),
                "cwd": cwd,
                "input": input_text,
                "env": dict(env),
                "timeout": timeout_seconds,
            }
        )
        if len(calls) == 1:
            return CommandResult(
                2,
                json.dumps(
                    {
                        "ok": False,
                        "errors": [{"reason": "profile_missing"}],
                        "warnings": [],
                    }
                ),
                "",
            )
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=False,
                final_message="blocked summary",
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        environ={
            "OPENAI_API_KEY": "secret",
            "SAFE_VALUE": "kept",
            "FEISHU_BOT_RUNTIME_CONTROL_ENABLED": "true",
        },
    )

    assert result == 0
    assert len(calls) == 2
    assert calls[0]["argv"][-2:] == ("preflight", "--quick-check")
    assert "OPENAI_API_KEY" not in calls[0]["env"]
    assert "FEISHU_BOT_RUNTIME_CONTROL_ENABLED" not in calls[0]["env"]
    assert calls[0]["env"]["SAFE_VALUE"] == "kept"
    assert calls[0]["timeout"] == 120
    assert calls[1]["env"]["OPENAI_API_KEY"] == "secret"
    assert "SAFE_VALUE" not in calls[1]["env"]
    assert calls[1]["env"]["CODEX_HOME"] == r"C:\Users\Administrator\.codex"
    assert calls[1]["timeout"] == 9000
    assert "--disable" in calls[1]["argv"]
    assert "Do not call processing_start" in str(calls[1]["input"])
    assert _summary(paths) == {
        "status": "blocked_reported",
        "outerPreflightOk": False,
        "outerPreflightReasons": ["profile_missing"],
        "tools": [
            "recruitment_preflight",
            "processing_status",
            "data_health",
            "daily_report",
        ],
        "finalMessage": "blocked summary",
    }


def test_ready_preflight_requires_start_after_inner_preflight(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    calls: list[dict[str, object]] = []

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        calls.append({"argv": tuple(argv), "input": input_text})
        if len(calls) == 1:
            return CommandResult(0, '{"ok":true,"errors":[],"warnings":[]}', "")
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_start",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=True,
                final_message="completed summary",
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 11, 0, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 0
    assert "Only when that inner preflight returns ok=true" in str(calls[1]["input"])
    assert _summary(paths)["status"] == "completed"
    assert _summary(paths)["tools"][0:2] == [
        "recruitment_preflight",
        "processing_start",
    ]


def test_ready_outer_preflight_reports_later_inner_blocker(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    call_count = 0

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CommandResult(0, '{"ok":true,"errors":[]}', "")
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=False,
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 11, 30, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 0
    assert _summary(paths)["status"] == "blocked_reported"


def test_blocked_preflight_flags_any_processing_start_attempt(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    call_count = 0

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CommandResult(
                2,
                '{"ok":false,"errors":[{"reason":"cdp_not_ready"}]}',
                "",
            )
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_start",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=False,
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 13, 0, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 3
    assert _summary(paths)["status"] == "policy_violation"


def test_scheduler_rejects_non_mcp_command_event(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    call_count = 0

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CommandResult(2, '{"ok":false,"errors":[]}', "")
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=False,
                extra_events=[
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "command",
                            "type": "command_execution",
                            "command": "agent_manager.py start",
                            "status": "completed",
                        },
                    }
                ],
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 15, 0, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 3
    assert _summary(paths)["error"] == "forbidden_codex_item:command_execution"


def test_scheduler_rejects_fatal_codex_event(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    call_count = 0

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CommandResult(2, '{"ok":false,"errors":[]}', "")
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=False,
                extra_events=[{"type": "error", "message": "fatal"}],
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 15, 30, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 3
    assert _summary(paths)["error"] == "fatal_codex_event:error"


def test_scheduler_allows_non_json_cleanup_after_completed_turn(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    call_count = 0

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CommandResult(2, '{"ok":false,"errors":[]}', "")
        output = _codex_jsonl(
            [
                "recruitment_preflight",
                "processing_status",
                "data_health",
                "daily_report",
            ],
            inner_preflight_ok=False,
        )
        return CommandResult(0, output + "SUCCESS: cleanup child process\n", "")

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 16, 0, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 0
    assert _summary(paths)["status"] == "blocked_reported"


def test_scheduler_rejects_wrong_daily_report_date(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    call_count = 0

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CommandResult(0, '{"ok":true,"errors":[]}', "")
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_start",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=True,
                daily_report_date="2026-07-20",
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 17, 0, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 3
    assert _summary(paths)["error"] == "daily_report_arguments_invalid"


def test_scheduler_rejects_failed_report_tool(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    call_count = 0

    def runner(argv, *, cwd, input_text, env, timeout_seconds):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CommandResult(2, '{"ok":false,"errors":[]}', "")
        return CommandResult(
            0,
            _codex_jsonl(
                [
                    "recruitment_preflight",
                    "processing_status",
                    "data_health",
                    "daily_report",
                ],
                inner_preflight_ok=False,
                status_overrides={"data_health": "error"},
            ),
            "",
        )

    result = run_scheduled(
        paths,
        runner=runner,
        now=datetime(2026, 7, 21, 17, 0, tzinfo=UTC),
        environ={"OPENAI_API_KEY": "secret"},
    )

    assert result == 3
    assert _summary(paths)["error"] == "data_health_status_invalid"


def test_run_command_timeout_terminates_process_tree(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable,'-c',"
        + repr(child_code)
        + "],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
        "stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW); "
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid)); "
        "time.sleep(60)"
    )

    result = run_command(
        (sys.executable, "-c", parent_code),
        cwd=tmp_path,
        input_text=None,
        env=os.environ,
        timeout_seconds=1,
    )
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    try:
        deadline = time.monotonic() + 3
        while _process_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert result.returncode == 124
        assert _process_exists(child_pid) is False
    finally:
        if _process_exists(child_pid):
            subprocess.run(
                ["taskkill.exe", "/PID", str(child_pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )


def test_global_mutex_rejects_overlapping_run() -> None:
    name = rf"Local\Codex-Recruitment-Schedule-Test-{uuid.uuid4()}"
    acquired: list[bool] = []

    def attempt_overlap() -> None:
        with GlobalMutex(name) as second:
            acquired.append(second.acquired)

    with GlobalMutex(name) as first:
        assert first.acquired is True
        thread = threading.Thread(target=attempt_overlap)
        thread.start()
        thread.join(timeout=2)

    assert acquired == [False]


def _process_exists(process_id: int) -> bool:
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True
