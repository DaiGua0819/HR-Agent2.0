"""Standalone runtime and operational state for the Feishu read-only bot."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from app.control_plane.dispatcher import Dispatcher
from app.features.feishu_bot.access import FeishuBotAccessPolicy
from app.features.feishu_bot.codex_planner import (
    CodexQueryPlanner,
    _codex_parent_environment,
    _resolve_command_prefix,
)
from app.features.feishu_bot.lark_cli import (
    LarkEventSource,
    LarkReplyClient,
    _lark_parent_environment,
    _resolve_lark_cli_prefix,
)
from app.features.feishu_bot.models import BotEvent
from app.features.feishu_bot.queries import ReadOnlyRecruitmentQueries
from app.features.feishu_bot.repository import FeishuBotRepository, redact_sensitive_text
from app.features.feishu_bot.runtime_control import (
    AgentManagerSubprocessClient,
    RecruitmentRuntimeController,
    render_runtime_completion_report,
    runtime_report_idempotency_key,
)
from app.features.feishu_bot.service import FeishuRecruitmentBot
from app.settings import PROJECT_ROOT, AppSettings, load_settings

DEDICATED_LARK_PROFILE = "hr-agent-readonly-bot"
Probe = Callable[..., Awaitable[dict[str, object]]]
BotFactory = Callable[[], FeishuRecruitmentBot]
ProcessChecker = Callable[[int], bool]


@dataclass(frozen=True)
class FeishuBotRuntimePaths:
    runtime_dir: Path
    lock_path: Path
    state_path: Path
    stop_path: Path

    @classmethod
    def from_settings(cls, settings: AppSettings) -> FeishuBotRuntimePaths:
        runtime_dir = settings.resolved_feishu_bot_runtime_dir
        return cls(
            runtime_dir=runtime_dir,
            lock_path=runtime_dir / "feishu-bot.lock",
            state_path=runtime_dir / "state.json",
            stop_path=runtime_dir / "stop.request.json",
        )


class FeishuBotInstanceLock:
    """Cross-process lock scoped only to the standalone bot runtime."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle: Any | None = None

    def __enter__(self) -> FeishuBotInstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("feishu_bot_already_running") from exc
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if self._handle is None:
            return
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


class FeishuBotRuntime:
    """Own the bot process lifecycle without touching any existing service."""

    def __init__(
        self,
        *,
        settings: AppSettings,
        bot_factory: BotFactory | None = None,
        lark_probe: Probe | None = None,
        codex_probe: Probe | None = None,
        process_checker: ProcessChecker | None = None,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self.settings = settings
        self.paths = FeishuBotRuntimePaths.from_settings(settings)
        self.bot_factory = bot_factory or (lambda: _build_bot(settings))
        self.lark_probe = lark_probe or _probe_lark_profile
        self.codex_probe = codex_probe or _probe_codex_login
        self.process_checker = process_checker or _process_is_running
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))

    async def preflight(self) -> dict[str, object]:
        errors: list[str] = []
        checks: dict[str, object] = {
            "enabled": self.settings.feishu_bot_enabled,
            "profile": self.settings.feishu_bot_profile,
        }
        if not self.settings.feishu_bot_enabled:
            return {"ok": False, "errors": ["feishu_bot_disabled"], "checks": checks}
        if self.settings.feishu_bot_profile != DEDICATED_LARK_PROFILE:
            errors.append("dedicated_lark_profile_required")
        database_check = _check_read_only_database(self.settings.resolved_database_path)
        checks["database"] = database_check
        if not database_check["ok"]:
            errors.append(str(database_check["error"]))
        access_check = _check_access_config(
            self.settings.resolved_feishu_bot_access_config_path
        )
        checks["access"] = access_check
        if not access_check["ok"]:
            errors.append(str(access_check["error"]))
        if self.settings.feishu_bot_runtime_control_enabled:
            control_check = _check_runtime_control(self.settings)
            checks["runtimeControl"] = control_check
            errors.extend(str(item) for item in control_check["errors"])
        if errors:
            return {"ok": False, "errors": errors, "checks": checks}
        lark = await self.lark_probe(self.settings.feishu_bot_profile)
        configured_codex = _check_configured_codex_auth(self.settings, os.environ)
        codex = (
            configured_codex
            if configured_codex is not None
            else await self.codex_probe()
        )
        checks["lark"] = _safe_probe_result(lark)
        checks["codex"] = _safe_probe_result(codex)
        if not lark.get("ok"):
            errors.append(str(lark.get("error") or "lark_profile_unavailable"))
        if not codex.get("ok"):
            errors.append(str(codex.get("error") or "codex_login_unavailable"))
        return {"ok": not errors, "errors": errors, "checks": checks}

    def status(self) -> dict[str, object]:
        state = _read_json(self.paths.state_path)
        pid = _integer(state.get("pid"))
        running = pid > 0 and self.process_checker(pid)
        stored_status = str(state.get("status") or "")
        status = (
            "stale"
            if pid > 0 and not running and stored_status == "running"
            else stored_status or ("running" if running else "stopped")
        )
        return {
            "running": running,
            "pid": pid,
            "status": status,
            "profile": str(state.get("profile") or self.settings.feishu_bot_profile),
            "startedAt": str(state.get("startedAt") or ""),
            "stoppedAt": str(state.get("stoppedAt") or ""),
            "error": str(state.get("error") or ""),
            "stopRequested": self.paths.stop_path.is_file(),
        }

    def request_stop(self) -> dict[str, object]:
        current = self.status()
        self.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "action": "graceful_stop",
            "pid": current["pid"],
            "requestedAt": _now_iso(),
        }
        _write_json(self.paths.stop_path, payload)
        return {
            "requested": True,
            "pid": current["pid"],
            "running": current["running"],
            "stopPath": str(self.paths.stop_path),
        }

    async def handle_event(self, payload: dict[str, object]) -> dict[str, object]:
        preflight = await self.preflight()
        if not preflight["ok"]:
            raise RuntimeError(f"feishu_bot_preflight_failed:{preflight['errors']}")
        event = BotEvent.from_payload(payload)
        bot = self.bot_factory()
        try:
            status = await bot.handle_event(event)
        finally:
            await bot.close()
        return {"eventId": event.event_id, "status": status}

    async def serve(self) -> None:
        preflight = await self.preflight()
        if not preflight["ok"]:
            raise RuntimeError(f"feishu_bot_preflight_failed:{preflight['errors']}")
        self.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        with FeishuBotInstanceLock(self.paths.lock_path):
            self.paths.stop_path.unlink(missing_ok=True)
            stop_event = asyncio.Event()
            bot = self.bot_factory()
            watcher = asyncio.create_task(self._watch_stop_request(stop_event, bot))
            self._write_state(status="running", pid=os.getpid(), started_at=_now_iso())
            try:
                await bot.serve(stop_event)
            except Exception as exc:
                self._write_state(
                    status="failed",
                    pid=os.getpid(),
                    started_at=self.status().get("startedAt", ""),
                    stopped_at=_now_iso(),
                    error=redact_sensitive_text(exc),
                )
                raise
            finally:
                stop_event.set()
                await bot.close()
                watcher.cancel()
                try:
                    await watcher
                except asyncio.CancelledError:
                    pass
                current = self.status()
                if current["status"] != "failed":
                    self._write_state(
                        status="stopped",
                        pid=os.getpid(),
                        started_at=current.get("startedAt", ""),
                        stopped_at=_now_iso(),
                    )
                self.paths.stop_path.unlink(missing_ok=True)

    async def _watch_stop_request(
        self,
        stop_event: asyncio.Event,
        bot: FeishuRecruitmentBot,
    ) -> None:
        while not stop_event.is_set():
            if self.paths.stop_path.is_file():
                stop_event.set()
                await bot.close()
                return
            await asyncio.sleep(self.poll_interval_seconds)

    def _write_state(
        self,
        *,
        status: str,
        pid: int,
        started_at: object = "",
        stopped_at: object = "",
        error: object = "",
    ) -> None:
        _write_json(
            self.paths.state_path,
            {
                "pid": int(pid),
                "status": status,
                "profile": self.settings.feishu_bot_profile,
                "startedAt": str(started_at or ""),
                "stoppedAt": str(stopped_at or ""),
                "error": str(error or "")[:1000],
                "updatedAt": _now_iso(),
            },
        )


def build_runtime(settings: AppSettings | None = None) -> FeishuBotRuntime:
    return FeishuBotRuntime(settings=settings or load_settings())


def _build_bot(settings: AppSettings) -> FeishuRecruitmentBot:
    repository = FeishuBotRepository(
        settings.resolved_feishu_bot_runtime_dir / "feishu-bot.sqlite"
    )
    access_policy = FeishuBotAccessPolicy(settings.resolved_feishu_bot_access_config_path)
    dispatcher = Dispatcher()
    planner = CodexQueryPlanner(
        runtime_dir=settings.resolved_feishu_bot_codex_runtime_dir,
        model=settings.feishu_bot_codex_model,
        provider_base_url=settings.feishu_bot_codex_base_url,
        api_key_env=settings.feishu_bot_codex_api_key_env,
    )
    queries = ReadOnlyRecruitmentQueries(
        settings.resolved_database_path,
        manager_runs_dir=settings.resolved_feishu_bot_manager_runs_dir,
        worker_status_provider=dispatcher.worker_statuses,
    )
    replies = LarkReplyClient(
        profile=settings.feishu_bot_profile,
        cwd=settings.resolved_feishu_bot_runtime_dir,
    )
    runtime_controller = None
    if settings.feishu_bot_runtime_control_enabled:
        manager = AgentManagerSubprocessClient(
            python_executable=sys.executable,
            manager_script=settings.resolved_feishu_bot_agent_manager_path,
            topology_path=settings.resolved_feishu_bot_agent_manager_topology_path,
            project_root=PROJECT_ROOT,
            max_contacts=settings.feishu_bot_runtime_control_max_contacts,
            max_anomalies=settings.feishu_bot_runtime_control_max_anomalies,
            sleep_seconds=settings.feishu_bot_runtime_control_sleep_seconds,
            skip_targets=settings.parsed_feishu_bot_runtime_control_skip_targets,
            blocked_env_names={
                "OPENAI_API_KEY",
                "CODEX_API_KEY",
                settings.feishu_bot_codex_api_key_env,
            },
        )

        async def report_sink(request, report) -> None:
            await replies.reply(
                request.message_id,
                render_runtime_completion_report(report),
                idempotency_key=runtime_report_idempotency_key(
                    request.event_id,
                    report.run_id,
                ),
            )

        runtime_controller = RecruitmentRuntimeController(
            manager=manager,
            report_sink=report_sink,
            max_retries=settings.feishu_bot_runtime_control_max_retries,
            retry_delay_seconds=(
                settings.feishu_bot_runtime_control_retry_delay_seconds
            ),
        )
    return FeishuRecruitmentBot(
        repository=repository,
        access_policy=access_policy,
        planner=planner,
        queries=queries,
        replies=replies,
        runtime_controller=runtime_controller,
        event_source_factory=lambda: LarkEventSource(
            profile=settings.feishu_bot_profile,
            cwd=settings.resolved_feishu_bot_runtime_dir,
        ),
    )


async def _probe_lark_profile(profile: str) -> dict[str, object]:
    auth = await _run_probe(
        [
            *_resolve_lark_cli_prefix("lark-cli"),
            "--profile",
            profile,
            "auth",
            "status",
            "--json",
            "--verify",
        ],
        env=_lark_parent_environment(os.environ),
    )
    if not auth["ok"]:
        return {"ok": False, "error": "lark_profile_auth_failed", "detail": auth["detail"]}
    event_status = await _run_probe(
        [
            *_resolve_lark_cli_prefix("lark-cli"),
            "--profile",
            profile,
            "event",
            "status",
            "--current",
            "--json",
            "--fail-on-orphan",
        ],
        env=_lark_parent_environment(os.environ),
    )
    if not event_status["ok"]:
        return {
            "ok": False,
            "error": "lark_event_bus_unhealthy",
            "detail": event_status["detail"],
        }
    return {"ok": True, "profile": profile}


async def _probe_codex_login() -> dict[str, object]:
    result = await _run_probe(
        [*_resolve_command_prefix("codex"), "login", "status"],
        env=_codex_parent_environment(os.environ),
    )
    return (
        {"ok": True, "status": "logged_in"}
        if result["ok"]
        else {
            "ok": False,
            "error": "codex_login_unavailable",
            "detail": result["detail"],
        }
    )


def _check_configured_codex_auth(
    settings: AppSettings,
    environment: os._Environ[str] | dict[str, str],
) -> dict[str, object] | None:
    base_url = str(settings.feishu_bot_codex_base_url or "").strip()
    api_key_env = str(settings.feishu_bot_codex_api_key_env or "").strip()
    if not base_url and not api_key_env:
        return None
    if not api_key_env:
        return {"ok": False, "error": "codex_api_key_env_missing"}
    if not base_url:
        return {
            "ok": False,
            "error": "codex_provider_base_url_missing",
            "apiKeyEnv": api_key_env,
        }
    if not environment.get(api_key_env):
        return {
            "ok": False,
            "error": "codex_api_key_unavailable",
            "apiKeyEnv": api_key_env,
        }
    return {"ok": True, "auth": "api_key", "apiKeyEnv": api_key_env}


async def _run_probe(argv: list[str], *, env: dict[str, str]) -> dict[str, object]:
    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            env=env,
            shell=False,
        )

    try:
        completed = await asyncio.to_thread(run)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "detail": redact_sensitive_text(exc)[:1000]}
    detail = (completed.stderr or completed.stdout).strip()[-1000:]
    return {"ok": completed.returncode == 0, "detail": redact_sensitive_text(detail)}


def _check_read_only_database(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"ok": False, "error": "feishu_bot_database_missing"}
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        return {"ok": False, "error": "feishu_bot_database_unreadable"}
    return {"ok": True, "path": str(path)}


def _check_access_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"ok": False, "error": "feishu_bot_access_config_missing"}
    try:
        actors = FeishuBotAccessPolicy(path).actors()
    except (OSError, ValueError):
        return {"ok": False, "error": "feishu_bot_access_config_invalid"}
    if not actors:
        return {"ok": False, "error": "feishu_bot_access_list_empty"}
    return {"ok": True, "actorCount": len(actors)}


def _check_runtime_control(settings: AppSettings) -> dict[str, object]:
    errors: list[str] = []
    manager_path = settings.resolved_feishu_bot_agent_manager_path
    topology_path = settings.resolved_feishu_bot_agent_manager_topology_path
    if not manager_path.is_file():
        errors.append("feishu_bot_agent_manager_missing")
    if not topology_path.is_file():
        errors.append("feishu_bot_agent_manager_topology_missing")
    return {
        "ok": not errors,
        "errors": errors,
        "managerConfigured": manager_path.is_file(),
        "topologyConfigured": topology_path.is_file(),
    }


def _safe_probe_result(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item
        for key, item in value.items()
        if key
        in {
            "ok",
            "error",
            "status",
            "profile",
            "detail",
            "auth",
            "apiKeyEnv",
        }
    }


def _process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
