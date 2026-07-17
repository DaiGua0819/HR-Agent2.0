"""Deterministic recruitment runtime control outside the Codex planner."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol

from app.core.text import clean_text

RuntimeControlAction = Literal["start", "pause", "status"]

_CONTROL_COMMANDS: dict[str, RuntimeControlAction] = {
    "启动处理程序": "start",
    "暂停处理程序": "pause",
    "查看处理状态": "status",
}
_TRANSIENT_ANOMALY_PREFIXES = (
    "http_500:",
    "http_502:",
    "http_503:",
    "http_timeout:",
    "connection_refused:",
    "control_plane_unavailable",
    "worker_unavailable",
    "worker_busy",
    "cdp_unavailable",
    "target_closed",
)


@dataclass(frozen=True)
class RuntimeControlRequest:
    event_id: str
    message_id: str
    actor_open_id: str
    actor_name: str


@dataclass(frozen=True)
class AgentManagerBatchResult:
    run_id: str
    status: str
    events: tuple[dict[str, object], ...] = ()
    skipped_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentManagerCommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PlatformRuntimeSummary:
    processed_contacts: int = 0
    business_resume_acquisitions: int = 0
    resume_requests_waiting: int = 0
    anomalies: int = 0


@dataclass(frozen=True)
class RuntimeBatchSummary:
    processed_contacts: int
    business_resume_acquisitions: int
    resume_requests_waiting: int
    anomalies: int
    anomaly_reasons: tuple[str, ...]
    by_platform: dict[str, PlatformRuntimeSummary] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeCompletionReport:
    run_id: str
    status: str
    retry_count: int
    max_retries: int
    processed_contacts: int
    business_resume_acquisitions: int
    resume_requests_waiting: int
    anomalies: int
    anomaly_reasons: tuple[str, ...]
    by_platform: dict[str, PlatformRuntimeSummary] = field(default_factory=dict)
    skipped_targets: tuple[str, ...] = ()


class AgentManagerPort(Protocol):
    async def start_runtime(self) -> None: ...

    async def run_batch(self) -> AgentManagerBatchResult: ...

    async def request_stop(self, reason: str) -> None: ...

    async def status(self) -> dict[str, object]: ...


RuntimeReportSink = Callable[
    [RuntimeControlRequest, RuntimeCompletionReport], Awaitable[None]
]
class AgentManagerSubprocessClient:
    """Invoke only the allow-listed manager commands with fixed arguments."""

    def __init__(
        self,
        *,
        python_executable: str | Path,
        manager_script: str | Path,
        topology_path: str | Path,
        project_root: str | Path,
        max_contacts: int = 0,
        max_anomalies: int = 0,
        sleep_seconds: float = 1.0,
        skip_targets: Sequence[str] = (),
        runner: Callable[..., Awaitable[AgentManagerCommandResult]] | None = None,
        blocked_env_names: Sequence[str] = (),
    ) -> None:
        self.python_executable = Path(python_executable).resolve()
        self.manager_script = Path(manager_script).resolve()
        self.topology_path = Path(topology_path).resolve()
        self.project_root = Path(project_root).resolve()
        self.max_contacts = int(max_contacts)
        self.max_anomalies = max(0, int(max_anomalies))
        self.sleep_seconds = max(0.0, float(sleep_seconds))
        self.skip_targets = _validated_skip_targets(skip_targets)
        self.runner = runner or _run_manager_command
        self.blocked_env_names = {
            clean_text(item).upper() for item in blocked_env_names if clean_text(item)
        }

    async def start_runtime(self) -> None:
        await self._execute("start", "--adopt-running")

    async def run_batch(self) -> AgentManagerBatchResult:
        arguments = [
            "run",
            "--max-contacts",
            str(self.max_contacts),
            "--max-anomalies",
            str(self.max_anomalies),
            "--sleep",
            str(self.sleep_seconds),
        ]
        for target in self.skip_targets:
            arguments.extend(("--skip", target))
        result = await self._execute(
            *arguments,
            allowed_returncodes={0, 3},
        )
        del result
        status = await self.status()
        current = (
            status.get("currentRun")
            if isinstance(status.get("currentRun"), dict)
            else {}
        )
        log_path = Path(clean_text(current.get("logPath"))) if current.get("logPath") else None
        events = _read_manager_events(log_path, project_root=self.project_root)
        raw_skipped = current.get("skipped")
        skipped = raw_skipped if isinstance(raw_skipped, list) else []
        return AgentManagerBatchResult(
            run_id=clean_text(current.get("runId")),
            status=clean_text(current.get("status")) or "failed",
            events=tuple(events),
            skipped_targets=tuple(
                clean_text(item)
                for item in skipped
                if clean_text(item)
            ),
        )

    async def request_stop(self, reason: str) -> None:
        if reason != "feishu_admin_pause":
            raise ValueError("runtime_control_stop_reason_forbidden")
        await self._execute("stop", "--reason", reason)

    async def status(self) -> dict[str, object]:
        result = await self._execute("status", "--tail", "8")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("agent_manager_status_invalid_json") from exc
        if not isinstance(value, dict):
            raise RuntimeError("agent_manager_status_invalid_payload")
        return value

    async def _execute(
        self,
        *arguments: str,
        allowed_returncodes: set[int] | None = None,
    ) -> AgentManagerCommandResult:
        argv = [
            str(self.python_executable),
            str(self.manager_script),
            "--topology",
            str(self.topology_path),
            *arguments,
        ]
        result = await self.runner(
            argv,
            cwd=self.project_root,
            env=_manager_environment(os.environ, blocked=self.blocked_env_names),
        )
        allowed = allowed_returncodes or {0}
        if result.returncode not in allowed:
            raise RuntimeError(_manager_failure_reason(arguments[0], result))
        return result


def parse_runtime_control_command(value: object) -> RuntimeControlAction | None:
    """Recognize only exact, parameter-free control commands."""

    text = clean_text(value).rstrip("。！!")
    return _CONTROL_COMMANDS.get(text)


def render_runtime_completion_report(report: RuntimeCompletionReport) -> str:
    status_labels = {
        "complete": "处理完成",
        "paused": "处理已暂停",
        "stop_requested": "处理已暂停",
        "stopped_on_anomaly": "处理因异常停止",
        "failed": "处理启动失败",
    }
    lines = [
        status_labels.get(report.status, f"处理结束：{report.status}"),
        f"处理联系人：{report.processed_contacts} 人",
        f"业务简历获取：{report.business_resume_acquisitions} 份",
        f"待简历回复：{report.resume_requests_waiting} 人",
        f"异常：{report.anomalies} 人",
    ]
    for platform, summary in report.by_platform.items():
        lines.append(
            f"{platform}：处理 {summary.processed_contacts}，"
            f"简历 {summary.business_resume_acquisitions}，"
            f"待回复 {summary.resume_requests_waiting}，异常 {summary.anomalies}"
        )
    if report.retry_count:
        lines.append(f"自动重试：{report.retry_count}/{report.max_retries}")
    if report.anomaly_reasons:
        lines.append(f"停止原因：{'; '.join(report.anomaly_reasons[:3])}")
    if report.skipped_targets:
        lines.append(f"跳过目标：{', '.join(report.skipped_targets)}")
    return "\n".join(lines)


def runtime_report_idempotency_key(event_id: str, run_id: str) -> str:
    digest = sha256(f"{event_id}:{run_id}".encode()).hexdigest()[:28]
    return f"feishu-runtime-report:{digest}"


def summarize_manager_events(
    events: Sequence[dict[str, object]],
) -> RuntimeBatchSummary:
    """Summarize sanitized manager contact events using platform contracts."""

    counters: dict[str, dict[str, int]] = {}
    reasons: list[str] = []
    for event in _latest_contact_events(events):
        if clean_text(event.get("event")) != "contact_result":
            continue
        platform = clean_text(event.get("platform")).lower() or "unknown"
        row = counters.setdefault(
            platform,
            {"processed": 0, "acquired": 0, "waiting": 0, "anomalies": 0},
        )
        summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
        row["processed"] += max(0, _integer(summary.get("processed")))
        handling = _event_resume_handling(event)
        if handling in {"boss_request_verified_server_imap", "local_resume_downloaded"}:
            row["acquired"] += 1
        elif handling == "resume_requested_waiting":
            row["waiting"] += 1

        classification = (
            event.get("classification")
            if isinstance(event.get("classification"), dict)
            else {}
        )
        if classification.get("is_anomaly"):
            row["anomalies"] += 1
            raw_reasons = classification.get("reasons")
            if isinstance(raw_reasons, list):
                for item in raw_reasons:
                    reason = clean_text(item)
                    if reason and reason not in reasons:
                        reasons.append(reason)

    by_platform = {
        platform: PlatformRuntimeSummary(
            processed_contacts=row["processed"],
            business_resume_acquisitions=row["acquired"],
            resume_requests_waiting=row["waiting"],
            anomalies=row["anomalies"],
        )
        for platform, row in sorted(counters.items())
    }
    return RuntimeBatchSummary(
        processed_contacts=sum(item.processed_contacts for item in by_platform.values()),
        business_resume_acquisitions=sum(
            item.business_resume_acquisitions for item in by_platform.values()
        ),
        resume_requests_waiting=sum(
            item.resume_requests_waiting for item in by_platform.values()
        ),
        anomalies=sum(item.anomalies for item in by_platform.values()),
        anomaly_reasons=tuple(reasons),
        by_platform=by_platform,
    )


class RecruitmentRuntimeController:
    """Run fixed manager operations and report completion without involving Codex."""

    def __init__(
        self,
        *,
        manager: AgentManagerPort,
        report_sink: RuntimeReportSink,
        max_retries: int = 2,
        retry_delay_seconds: float = 3.0,
        report_max_retries: int = 2,
        report_retry_delay_seconds: float = 2.0,
    ) -> None:
        self.manager = manager
        self.report_sink = report_sink
        self.max_retries = max(0, int(max_retries))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self.report_max_retries = max(0, int(report_max_retries))
        self.report_retry_delay_seconds = max(
            0.0,
            float(report_retry_delay_seconds),
        )
        self._task: asyncio.Task[None] | None = None
        self._state = "idle"
        self._pause_requested = False
        self._last_report: RuntimeCompletionReport | None = None
        self._control_lock = asyncio.Lock()

    async def execute(
        self,
        action: RuntimeControlAction | str,
        request: RuntimeControlRequest,
    ) -> dict[str, object]:
        if action in {"start", "pause"}:
            async with self._control_lock:
                if action == "start":
                    return await self._start(request)
                return await self._pause()
        if action == "status":
            return await self._status()
        raise ValueError(f"unsupported_runtime_control_action:{action}")

    async def wait_until_idle(self) -> None:
        task = self._task
        if task is not None:
            await asyncio.shield(task)

    async def _start(self, request: RuntimeControlRequest) -> dict[str, object]:
        if self._task is not None and not self._task.done():
            return {"status": "already_running", "message": "处理程序已经在运行。"}
        manager_status = await self.manager.status()
        current = _current_run(manager_status)
        if clean_text(current.get("status")) in {"running", "stop_requested"}:
            self._state = clean_text(current.get("status"))
            return {"status": "already_running", "message": "处理程序已经在运行。"}
        self._pause_requested = False
        self._state = "starting"
        self._task = asyncio.create_task(self._run(request))
        return {"status": "started", "message": "处理程序已启动。"}

    async def _pause(self) -> dict[str, object]:
        if self._task is None or self._task.done():
            manager_status = await self.manager.status()
            current_status = clean_text(_current_run(manager_status).get("status"))
            if current_status not in {"running", "stop_requested"}:
                self._state = "paused"
                return {"status": "paused", "message": "处理程序当前已暂停。"}
            if current_status == "stop_requested":
                self._state = "pause_requested"
                return {
                    "status": "pause_requested",
                    "message": "处理程序已收到暂停请求。",
                }
        self._pause_requested = True
        self._state = "pause_requested"
        await self.manager.request_stop("feishu_admin_pause")
        return {
            "status": "pause_requested",
            "message": "已请求暂停处理程序，当前联系人完成后停止。",
        }

    async def _status(self) -> dict[str, object]:
        manager_status = await self.manager.status()
        current = _current_run(manager_status)
        run_id = clean_text(current.get("runId"))
        current_status = clean_text(current.get("status"))
        display_state = (
            current_status
            if current_status in {"running", "stop_requested"}
            else self._state
        )
        suffix = (
            f"，运行批次 {run_id}"
            if run_id and display_state in {"running", "stop_requested"}
            else ""
        )
        label = {
            "idle": "空闲",
            "starting": "启动中",
            "running": "运行中",
            "retrying": "自动重试中",
            "pause_requested": "正在暂停",
            "stop_requested": "正在暂停",
            "paused": "已暂停",
            "complete": "已完成",
            "stopped_on_anomaly": "异常停止",
            "failed": "启动失败",
            "report_failed": "汇报发送失败",
        }.get(display_state, display_state)
        return {
            "status": display_state,
            "message": f"处理程序状态：{label}{suffix}。",
        }

    async def _run(self, request: RuntimeControlRequest) -> None:
        retry_count = 0
        all_events: list[dict[str, object]] = []
        skipped_targets: list[str] = []
        last_batch = AgentManagerBatchResult(run_id="", status="failed")
        try:
            while True:
                self._state = "starting" if retry_count == 0 else "retrying"
                await self.manager.start_runtime()
                if self._pause_requested:
                    last_batch = AgentManagerBatchResult(run_id="", status="paused")
                    break
                self._state = "running"
                last_batch = await self.manager.run_batch()
                all_events.extend(last_batch.events)
                for target in last_batch.skipped_targets:
                    if target not in skipped_targets:
                        skipped_targets.append(target)
                summary = summarize_manager_events(last_batch.events)
                if (
                    last_batch.status == "stopped_on_anomaly"
                    and retry_count < self.max_retries
                    and _reasons_are_retryable(summary.anomaly_reasons)
                    and not self._pause_requested
                ):
                    retry_count += 1
                    if self.retry_delay_seconds:
                        await asyncio.sleep(self.retry_delay_seconds)
                    continue
                break
        except Exception as exc:
            failure_reason = clean_text(str(exc)) or type(exc).__name__
            last_batch = AgentManagerBatchResult(
                run_id=last_batch.run_id,
                status="failed",
                events=tuple(all_events),
            )
            all_events.append(
                {
                    "event": "contact_result",
                    "platform": "runtime",
                    "classification": {
                        "is_anomaly": True,
                        "reasons": [f"runtime_control_error:{failure_reason[:800]}"],
                    },
                    "summary": {"processed": 0},
                    "response": {},
                }
            )

        summary = summarize_manager_events(all_events)
        final_status = "paused" if self._pause_requested else last_batch.status
        report = RuntimeCompletionReport(
            run_id=last_batch.run_id,
            status=final_status,
            retry_count=retry_count,
            max_retries=self.max_retries,
            processed_contacts=summary.processed_contacts,
            business_resume_acquisitions=summary.business_resume_acquisitions,
            resume_requests_waiting=summary.resume_requests_waiting,
            anomalies=summary.anomalies,
            anomaly_reasons=summary.anomaly_reasons,
            by_platform=summary.by_platform,
            skipped_targets=tuple(skipped_targets),
        )
        self._last_report = report
        self._state = final_status
        await self._send_report(request, report)

    async def _send_report(
        self,
        request: RuntimeControlRequest,
        report: RuntimeCompletionReport,
    ) -> None:
        for attempt in range(self.report_max_retries + 1):
            try:
                await self.report_sink(request, report)
                return
            except Exception:
                if attempt >= self.report_max_retries:
                    self._state = "report_failed"
                    return
                if self.report_retry_delay_seconds:
                    await asyncio.sleep(self.report_retry_delay_seconds)


def _latest_contact_events(
    events: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    latest: dict[tuple[str, str, str], dict[str, object]] = {}
    unkeyed: list[dict[str, object]] = []
    for event in events:
        summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
        conversation_id = clean_text(summary.get("conversationId"))
        if not conversation_id:
            unkeyed.append(event)
            continue
        key = (
            clean_text(event.get("platform")).lower(),
            clean_text(event.get("owner")),
            conversation_id,
        )
        latest[key] = event
    return [*latest.values(), *unkeyed]


def _event_resume_handling(event: dict[str, object]) -> str:
    summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    platform = clean_text(event.get("platform") or response.get("platform")).lower()
    decision = (
        response.get("decision") if isinstance(response.get("decision"), dict) else {}
    )
    result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    next_action = clean_text(response.get("nextAction") or summary.get("nextAction"))
    action = clean_text(decision.get("action"))
    if platform == "boss":
        reason = clean_text(result.get("reason"))
        outcome = clean_text(result.get("outcome"))
        request_action = next_action == "request_resume" or action == "request_resume"
        verified_request = request_action and (
            bool(result.get("ok"))
            or bool(result.get("requested") and result.get("confirmed"))
        )
        if verified_request or reason == "boss_attachment_present_no_local_download" or outcome in {
            "request_confirmed",
            "resume_attachment_received",
            "resume_consent_accepted",
        }:
            return "boss_request_verified_server_imap"
    handling = clean_text(summary.get("resumeHandling"))
    if handling:
        return handling
    if bool(result.get("downloaded")):
        return "local_resume_downloaded"
    if (
        next_action == "request_resume" or action == "request_resume"
    ) and bool(result.get("requested") or result.get("confirmed")):
        return "resume_requested_waiting"
    return ""


def _reasons_are_retryable(reasons: Sequence[str]) -> bool:
    return bool(reasons) and all(
        any(reason.startswith(prefix) for prefix in _TRANSIENT_ANOMALY_PREFIXES)
        for reason in reasons
    )


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _validated_skip_targets(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        target = clean_text(value)
        owner, separator, platform = target.rpartition(":")
        if (
            separator != ":"
            or not owner
            or platform not in {"boss", "job51", "zhilian"}
            or owner.startswith("-")
        ):
            raise ValueError("invalid_runtime_control_skip_target")
        if target not in result:
            result.append(target)
    return tuple(result)


def _manager_failure_reason(
    command: str,
    result: AgentManagerCommandResult,
) -> str:
    detail = ""
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        detail = clean_text(payload.get("error"))
    if not detail:
        detail = clean_text(result.stderr)
    if not detail:
        detail = f"returncode_{result.returncode}"
    return f"agent_manager_command_failed:{command}:{detail[:800]}"


def _current_run(status: dict[str, object]) -> dict[str, object]:
    current = status.get("currentRun")
    return current if isinstance(current, dict) else {}


async def _run_manager_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> AgentManagerCommandResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return AgentManagerCommandResult(
        returncode=int(process.returncode or 0),
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


def _manager_environment(
    source: dict[str, str],
    *,
    blocked: set[str],
) -> dict[str, str]:
    environment = {
        key: value
        for key, value in source.items()
        if not key.upper().startswith("FEISHU_BOT_") and key.upper() not in blocked
    }
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _read_manager_events(
    log_path: Path | None,
    *,
    project_root: Path,
) -> list[dict[str, object]]:
    if log_path is None or not log_path.is_file():
        return []
    resolved = log_path.resolve()
    allowed_root = (project_root / "data" / "agent_manager" / "runs").resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise RuntimeError("agent_manager_log_path_outside_runtime") from exc
    events: list[dict[str, object]] = []
    for line in resolved.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events
