"""Run one guarded scheduled Codex recruitment-operations turn."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

BLOCKED_MANAGER_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "CODEX_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    }
)
CODEX_ENV_NAMES = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "OPENAI_API_KEY",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERDOMAIN",
        "USERNAME",
        "USERPROFILE",
        "WINDIR",
    }
)
CODEX_HOME = r"C:\Users\Administrator\.codex"
DISABLED_CODEX_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "in_app_browser",
    "multi_agent",
    "plugins",
    "remote_plugin",
    "shell_tool",
    "unified_exec",
    "workspace_dependencies",
)
ALLOWED_RECRUIT_TOOLS = frozenset(
    {
        "recruitment_preflight",
        "processing_start",
        "processing_status",
        "data_health",
        "daily_report",
    }
)
MANAGER_TIMEOUT_SECONDS = 120
CODEX_TIMEOUT_SECONDS = 9000
REQUIRED_REPORT_TOOLS = (
    "processing_status",
    "data_health",
    "daily_report",
)


@dataclass(frozen=True)
class SchedulePaths:
    project_root: Path
    python_executable: Path
    manager_script: Path
    topology_path: Path
    codex_executable: Path
    thread_id_path: Path
    log_root: Path


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CodexToolCall:
    tool: str
    arguments: dict[str, object]
    status: str
    result: dict[str, object] | None
    error: object


CommandRunner = Callable[..., CommandResult]


def production_paths() -> SchedulePaths:
    project_root = Path(r"C:\RecruitAgent2Preview\hr-agent")
    return SchedulePaths(
        project_root=project_root,
        python_executable=Path(r"C:\RecruitAgent2Preview\.venv\Scripts\python.exe"),
        manager_script=project_root / "scripts" / "agent_manager.py",
        topology_path=Path(
            r"C:\ProgramData\OpenAI\Codex\recruit-ops\topology.json"
        ),
        codex_executable=Path(
            r"C:\Users\Administrator\AppData\Roaming\npm\node_modules"
            r"\@openai\codex\node_modules\@openai\codex-win32-x64\vendor"
            r"\x86_64-pc-windows-msvc\codex\codex.exe"
        ),
        thread_id_path=Path(
            r"C:\ProgramData\OpenAI\Codex\recruit-ops\operations-thread-id.txt"
        ),
        log_root=Path(r"C:\ProgramData\OpenAI\Codex\recruit-ops\scheduled-runs"),
    )


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    input_text: str | None,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> CommandResult:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as error:
        return CommandResult(127, "", f"process_launch_failed:{type(error).__name__}")
    try:
        stdout, stderr = process.communicate(
            input=input_text,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        _terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        return CommandResult(
            returncode=124,
            stdout=stdout or _timeout_text(error.stdout),
            stderr=(
                (stderr or _timeout_text(error.stderr))
                + f"\ncommand_timeout_after_{timeout_seconds}_seconds"
            ).strip(),
        )
    return CommandResult(
        returncode=int(process.returncode or 0),
        stdout=stdout or "",
        stderr=stderr or "",
    )


def run_scheduled(
    paths: SchedulePaths,
    *,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    current = now or datetime.now().astimezone()
    date_text = current.date().isoformat()
    run_dir = paths.log_root / date_text / current.strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=True)

    missing = [
        str(path)
        for path in (
            paths.project_root,
            paths.python_executable,
            paths.manager_script,
            paths.topology_path,
            paths.codex_executable,
            paths.thread_id_path,
        )
        if not path.exists()
    ]
    if missing:
        _write_summary(
            run_dir,
            {"status": "configuration_error", "missingPaths": missing},
        )
        return 2

    source_environment = dict(environ if environ is not None else os.environ)
    manager_environment = {
        key: value
        for key, value in source_environment.items()
        if key.upper() not in BLOCKED_MANAGER_ENV_NAMES
        and not key.upper().startswith("FEISHU_BOT_")
    }
    manager_environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    preflight_result = runner(
        (
            str(paths.python_executable),
            str(paths.manager_script),
            "--topology",
            str(paths.topology_path),
            "preflight",
            "--quick-check",
        ),
        cwd=paths.project_root,
        input_text=None,
        env=manager_environment,
        timeout_seconds=MANAGER_TIMEOUT_SECONDS,
    )
    _write_text(run_dir / "preflight.stdout.json", preflight_result.stdout)
    _write_text(run_dir / "preflight.stderr.log", preflight_result.stderr)
    if preflight_result.returncode not in {0, 2}:
        _write_summary(
            run_dir,
            {
                "status": "preflight_command_failed",
                "returncode": preflight_result.returncode,
            },
        )
        return 2

    preflight = _json_object(preflight_result.stdout)
    if preflight is None or not isinstance(preflight.get("ok"), bool):
        _write_summary(run_dir, {"status": "preflight_invalid_json"})
        return 2
    preflight_ok = preflight["ok"] is True
    reasons = _preflight_reasons(preflight)

    thread_id = _thread_id(paths.thread_id_path)
    if thread_id is None:
        _write_summary(run_dir, {"status": "thread_id_invalid"})
        return 2
    prompt = _scheduled_prompt(
        preflight_ok=preflight_ok,
        reasons=reasons,
        date_text=date_text,
    )
    normalized_environment = {
        key.upper(): value for key, value in source_environment.items()
    }
    codex_environment = {
        key: normalized_environment[key]
        for key in CODEX_ENV_NAMES
        if key in normalized_environment
    }
    codex_environment["CODEX_HOME"] = CODEX_HOME
    codex_environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if not codex_environment.get("OPENAI_API_KEY"):
        _write_summary(run_dir, {"status": "api_key_missing"})
        return 2
    disabled_feature_arguments = tuple(
        argument
        for feature in DISABLED_CODEX_FEATURES
        for argument in ("--disable", feature)
    )
    codex_result = runner(
        (
            str(paths.codex_executable),
            "exec",
            "resume",
            "--json",
            "--skip-git-repo-check",
            "-c",
            'approval_policy="never"',
            "-c",
            'sandbox_mode="read-only"',
            *disabled_feature_arguments,
            thread_id,
            "-",
        ),
        cwd=paths.project_root,
        input_text=prompt,
        env=codex_environment,
        timeout_seconds=CODEX_TIMEOUT_SECONDS,
    )
    _write_text(run_dir / "codex.stdout.jsonl", codex_result.stdout)
    _write_text(run_dir / "codex.stderr.log", codex_result.stderr)
    if codex_result.returncode != 0:
        _write_summary(
            run_dir,
            {
                "status": "codex_failed",
                "outerPreflightOk": preflight_ok,
                "outerPreflightReasons": reasons,
                "returncode": codex_result.returncode,
            },
        )
        return 2

    calls, final_message, parse_error = _codex_result(codex_result.stdout)
    tools = [call.tool for call in calls]
    policy_error = parse_error or _tool_policy_error(
        calls,
        outer_preflight_ok=preflight_ok,
        date_text=date_text,
    )
    if policy_error or not final_message:
        _write_summary(
            run_dir,
            {
                "status": "policy_violation",
                "outerPreflightOk": preflight_ok,
                "outerPreflightReasons": reasons,
                "tools": tools,
                "finalMessage": final_message,
                "error": policy_error or "final_message_missing",
            },
        )
        return 3

    inner_preflight = _structured_content(calls[0].result) or {}
    processing_completed = (
        preflight_ok
        and inner_preflight.get("ok") is True
        and "processing_start" in tools
    )

    _write_summary(
        run_dir,
        {
            "status": "completed" if processing_completed else "blocked_reported",
            "outerPreflightOk": preflight_ok,
            "outerPreflightReasons": reasons,
            "tools": tools,
            "finalMessage": final_message,
        },
    )
    return 0


def _scheduled_prompt(
    *,
    preflight_ok: bool,
    reasons: Sequence[str],
    date_text: str,
) -> str:
    reason_text = ", ".join(reasons) or "none"
    if preflight_ok:
        action = (
            "Call recruitment_preflight first exactly once. Only when that inner "
            "preflight returns ok=true, call processing_start exactly once."
        )
    else:
        action = (
            "Call recruitment_preflight first exactly once. Do not call processing_start "
            "because the deterministic outer preflight is blocked."
        )
    return "\n".join(
        (
            "Run one scheduled recruitment-operations turn for the 18080 service.",
            f"The deterministic outer preflight ok value is {str(preflight_ok).lower()}.",
            f"Outer preflight reasons: {reason_text}.",
            action,
            "After that, call processing_status, data_health, and daily_report exactly once each.",
            f"Use {date_text} as the daily_report date.",
            "Never call processing_pause in a scheduled run.",
            "Do not use shell, browser, patch, edit, write, or unapproved MCP tools.",
            (
                "Finish with a concise status and report summary without secrets or "
                "browser-profile contents."
            ),
        )
    )


def _tool_policy_error(
    calls: Sequence[CodexToolCall],
    *,
    outer_preflight_ok: bool,
    date_text: str,
) -> str:
    tools = [call.tool for call in calls]
    if not calls or tools[0] != "recruitment_preflight":
        return "recruitment_preflight_must_be_first"
    if tools.count("recruitment_preflight") != 1:
        return "recruitment_preflight_count_invalid"
    if "processing_pause" in tools:
        return "scheduled_pause_forbidden"
    preflight_call = calls[0]
    if preflight_call.arguments:
        return "recruitment_preflight_arguments_invalid"
    preflight_payload = _structured_content(preflight_call.result)
    inner_preflight_ok = (
        preflight_payload.get("ok")
        if isinstance(preflight_payload, dict)
        else None
    )
    if not isinstance(inner_preflight_ok, bool):
        return "recruitment_preflight_result_invalid"
    expected_preflight_status = "completed" if inner_preflight_ok else "failed"
    if (
        preflight_call.status != expected_preflight_status
        or preflight_call.error is not None
    ):
        return "recruitment_preflight_status_invalid"
    if not outer_preflight_ok and "processing_start" in tools:
        return "processing_start_called_while_blocked"
    if not inner_preflight_ok and "processing_start" in tools:
        return "processing_start_called_after_failed_preflight"

    expected_tools = ["recruitment_preflight"]
    if outer_preflight_ok and inner_preflight_ok:
        expected_tools.append("processing_start")
    expected_tools.extend(REQUIRED_REPORT_TOOLS)
    if tools != expected_tools:
        return "tool_sequence_invalid"

    for call in calls[1:]:
        if call.tool == "daily_report":
            if call.arguments != {"date": date_text}:
                return "daily_report_arguments_invalid"
        elif call.arguments:
            return f"{call.tool}_arguments_invalid"
        if call.status != "completed" or call.error is not None:
            return f"{call.tool}_status_invalid"
        payload = _structured_content(call.result)
        if not isinstance(payload, dict):
            return f"{call.tool}_result_invalid"
        if call.tool == "processing_start" and payload.get("ok") is not True:
            return "processing_start_result_invalid"
        if call.tool == "daily_report" and payload.get("date") != date_text:
            return "daily_report_result_invalid"
    return ""


def _codex_result(raw: str) -> tuple[list[CodexToolCall], str, str]:
    calls: list[CodexToolCall] = []
    final_message = ""
    turn_completed = False
    for line in raw.splitlines():
        event = _json_object(line)
        if event is None:
            if turn_completed:
                continue
            return calls, final_message, "invalid_codex_jsonl"
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            return calls, final_message, "invalid_codex_event"
        if turn_completed:
            return calls, final_message, f"event_after_turn_completed:{event_type}"
        if event_type in {"error", "turn.failed"}:
            return calls, final_message, f"fatal_codex_event:{event_type}"
        if event_type == "turn.completed":
            turn_completed = True
            continue
        if event_type in {"thread.started", "turn.started"}:
            continue
        if event_type not in {"item.started", "item.completed"}:
            return calls, final_message, f"unknown_codex_event:{event_type}"
        item = event.get("item")
        if not isinstance(item, dict):
            return calls, final_message, "invalid_codex_item"
        item_type = item.get("type")
        if item_type == "mcp_tool_call":
            if item.get("server") != "recruit_ops":
                return calls, final_message, "unapproved_mcp_server"
            tool = item.get("tool")
            if not isinstance(tool, str) or tool not in ALLOWED_RECRUIT_TOOLS:
                return calls, final_message, "unapproved_recruit_ops_tool"
            if event_type != "item.completed":
                continue
            arguments = item.get("arguments")
            result = item.get("result")
            if not isinstance(arguments, dict):
                return calls, final_message, f"{tool}_arguments_invalid"
            calls.append(
                CodexToolCall(
                    tool=tool,
                    arguments=arguments,
                    status=str(item.get("status") or ""),
                    result=result if isinstance(result, dict) else None,
                    error=item.get("error"),
                )
            )
        elif item_type == "agent_message":
            if event_type != "item.completed":
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                final_message = " ".join(text.split())
        elif item_type != "reasoning":
            return calls, final_message, f"forbidden_codex_item:{item_type}"
    if not turn_completed:
        return calls, final_message, "turn_not_completed"
    return calls, final_message, ""


def _structured_content(result: Mapping[str, object] | None) -> dict[str, object] | None:
    if result is None:
        return None
    for key in ("structured_content", "structuredContent"):
        value = result.get(key)
        if isinstance(value, dict):
            return value
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return None
    first = content[0]
    if not isinstance(first, dict) or not isinstance(first.get("text"), str):
        return None
    return _json_object(first["text"])


def _preflight_reasons(payload: Mapping[str, object]) -> list[str]:
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return []
    reasons: list[str] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        reason = item.get("reason")
        if isinstance(reason, str) and reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _thread_id(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="ascii").strip()
        parsed = uuid.UUID(value)
    except (OSError, UnicodeError, ValueError):
        return None
    return str(parsed)


def _json_object(raw: str) -> dict[str, object] | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _timeout_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    if process.poll() is None:
        process.kill()


def _write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def _write_summary(path: Path, payload: Mapping[str, object]) -> None:
    (path / "summary.json").write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class GlobalMutex:
    WAIT_OBJECT_0 = 0
    WAIT_ABANDONED = 0x80
    WAIT_TIMEOUT = 0x102

    def __init__(self, name: str) -> None:
        self.name = name
        self.handle: int | None = None
        self.acquired = False

    def __enter__(self) -> GlobalMutex:
        if os.name != "nt":
            raise RuntimeError("scheduled recruitment mutex requires Windows")
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError()
        self.handle = int(handle)
        wait_result = kernel32.WaitForSingleObject(handle, 0)
        if wait_result in {self.WAIT_OBJECT_0, self.WAIT_ABANDONED}:
            self.acquired = True
        elif wait_result != self.WAIT_TIMEOUT:
            kernel32.CloseHandle(handle)
            self.handle = None
            raise ctypes.WinError()
        return self

    def __exit__(self, *_args: object) -> None:
        if self.handle is None:
            return
        kernel32 = ctypes.windll.kernel32
        if self.acquired:
            kernel32.ReleaseMutex(self.handle)
        kernel32.CloseHandle(self.handle)
        self.handle = None


def main() -> int:
    paths = production_paths()
    paths.log_root.mkdir(parents=True, exist_ok=True)
    with GlobalMutex(r"Global\OpenAI-Codex-RecruitOps-Scheduled") as mutex:
        if not mutex.acquired:
            overlap_log = paths.log_root / "overlap-skipped.log"
            with overlap_log.open("a", encoding="utf-8") as stream:
                stream.write(datetime.now().astimezone().isoformat() + "\n")
            return 0
        return run_scheduled(paths)


if __name__ == "__main__":
    raise SystemExit(main())
