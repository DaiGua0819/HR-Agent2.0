from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from app.features.feishu_bot.runtime import (
    DEDICATED_LARK_PROFILE,
    FeishuBotInstanceLock,
    FeishuBotRuntime,
)
from app.settings import AppSettings
from scripts.run_feishu_bot import build_parser


def _settings(tmp_path: Path, *, enabled: bool = True, profile: str = "") -> AppSettings:
    database = tmp_path / "resumes.sqlite"
    database.touch()
    access = tmp_path / "access.yaml"
    access.write_text("users: []\n", encoding="utf-8")
    return AppSettings(
        _env_file=None,
        DATABASE_PATH=database,
        FEISHU_BOT_ENABLED=enabled,
        FEISHU_BOT_PROFILE=profile or DEDICATED_LARK_PROFILE,
        FEISHU_BOT_ACCESS_CONFIG_PATH=access,
        FEISHU_BOT_RUNTIME_DIR=tmp_path / "runtime",
        FEISHU_BOT_CODEX_RUNTIME_DIR=tmp_path / "codex-runtime",
        FEISHU_BOT_MANAGER_RUNS_DIR=tmp_path / "manager-runs",
    )


def test_settings_default_to_disabled_dedicated_non_secret_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FEISHU_BOT_ENABLED", raising=False)
    monkeypatch.delenv("FEISHU_BOT_PROFILE", raising=False)

    settings = AppSettings(_env_file=None)

    assert settings.feishu_bot_enabled is False
    assert settings.feishu_bot_profile == "hr-agent-readonly-bot"
    assert "secret" not in settings.feishu_bot_profile.lower()
    dumped = settings.model_dump()
    assert "feishu_bot_app_secret" not in dumped
    assert "feishu_bot_app_id" not in dumped


def test_preflight_requires_explicit_enable_before_any_external_probe(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    async def lark_probe(_profile: str) -> dict[str, object]:
        calls.append("lark")
        return {"ok": True}

    async def codex_probe() -> dict[str, object]:
        calls.append("codex")
        return {"ok": True}

    runtime = FeishuBotRuntime(
        settings=_settings(tmp_path, enabled=False),
        lark_probe=lark_probe,
        codex_probe=codex_probe,
    )

    result = asyncio.run(runtime.preflight())

    assert result["ok"] is False
    assert result["errors"] == ["feishu_bot_disabled"]
    assert calls == []


def test_preflight_rejects_reusing_existing_day1_profile(tmp_path: Path) -> None:
    runtime = FeishuBotRuntime(
        settings=_settings(tmp_path, profile="day1"),
        lark_probe=lambda _profile: _async_result({"ok": True}),
        codex_probe=lambda: _async_result({"ok": True}),
    )

    result = asyncio.run(runtime.preflight())

    assert result["ok"] is False
    assert "dedicated_lark_profile_required" in result["errors"]


def test_preflight_runs_read_only_probes_after_local_checks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.resolved_feishu_bot_access_config_path.write_text(
        """
users:
  - openId: ou-member
    displayName: 菜花
    role: member
    jobTypes: [AI产品经理]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    async def lark_probe(profile: str) -> dict[str, object]:
        calls.append(f"lark:{profile}")
        return {"ok": True, "profile": profile, "secret": "must-not-return"}

    async def codex_probe() -> dict[str, object]:
        calls.append("codex")
        return {"ok": True, "status": "logged_in", "token": "must-not-return"}

    runtime = FeishuBotRuntime(
        settings=settings,
        lark_probe=lark_probe,
        codex_probe=codex_probe,
    )

    result = asyncio.run(runtime.preflight())

    assert result["ok"] is True
    assert result["errors"] == []
    assert calls == [f"lark:{DEDICATED_LARK_PROFILE}", "codex"]
    assert "secret" not in result["checks"]["lark"]
    assert "token" not in result["checks"]["codex"]


def test_bot_single_instance_lock_rejects_overlap(tmp_path: Path) -> None:
    lock_path = tmp_path / "feishu-bot.lock"

    with FeishuBotInstanceLock(lock_path):
        with pytest.raises(RuntimeError, match="feishu_bot_already_running"):
            with FeishuBotInstanceLock(lock_path):
                raise AssertionError("second bot unexpectedly acquired the lock")

    with FeishuBotInstanceLock(lock_path):
        assert lock_path.is_file()


def test_status_and_stop_only_use_bot_state_files(tmp_path: Path) -> None:
    runtime = FeishuBotRuntime(
        settings=_settings(tmp_path),
        process_checker=lambda pid: pid == 4321,
        lark_probe=lambda _profile: _async_result({"ok": True}),
        codex_probe=lambda: _async_result({"ok": True}),
    )
    runtime.paths.runtime_dir.mkdir(parents=True)
    runtime.paths.state_path.write_text(
        json.dumps(
            {
                "pid": 4321,
                "status": "running",
                "profile": DEDICATED_LARK_PROFILE,
                "startedAt": "2026-07-16T08:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    before = runtime.status()
    requested = runtime.request_stop()
    stop_payload = json.loads(runtime.paths.stop_path.read_text(encoding="utf-8"))

    assert before["running"] is True
    assert before["pid"] == 4321
    assert before["profile"] == DEDICATED_LARK_PROFILE
    assert requested["requested"] is True
    assert requested["pid"] == 4321
    assert stop_payload["pid"] == 4321
    assert stop_payload["action"] == "graceful_stop"
    assert runtime.status()["stopRequested"] is True


def test_status_marks_dead_pid_state_as_stale(tmp_path: Path) -> None:
    runtime = FeishuBotRuntime(
        settings=_settings(tmp_path),
        process_checker=lambda _pid: False,
        lark_probe=lambda _profile: _async_result({"ok": True}),
        codex_probe=lambda: _async_result({"ok": True}),
    )
    runtime.paths.runtime_dir.mkdir(parents=True)
    runtime.paths.state_path.write_text(
        json.dumps({"pid": 9999, "status": "running"}),
        encoding="utf-8",
    )

    status = runtime.status()

    assert status["running"] is False
    assert status["status"] == "stale"


def test_runtime_composition_exposes_existing_worker_status_provider(
    tmp_path: Path,
) -> None:
    runtime = FeishuBotRuntime(
        settings=_settings(tmp_path),
        lark_probe=lambda _profile: _async_result({"ok": True}),
        codex_probe=lambda: _async_result({"ok": True}),
    )

    bot = runtime.bot_factory()

    assert bot.queries.worker_status_provider is not None


def test_runtime_serve_obeys_stop_request_and_records_stopped_state(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.resolved_feishu_bot_access_config_path.write_text(
        """
users:
  - openId: ou-admin
    displayName: 管理员
    role: admin
    jobTypes: ['*']
""".strip()
        + "\n",
        encoding="utf-8",
    )
    started = asyncio.Event()

    class _Bot:
        def __init__(self) -> None:
            self.closed = False

        async def serve(self, stop_event: asyncio.Event) -> None:
            started.set()
            await stop_event.wait()

        async def close(self) -> None:
            self.closed = True

    bot = _Bot()
    runtime = FeishuBotRuntime(
        settings=settings,
        bot_factory=lambda: bot,  # type: ignore[arg-type]
        lark_probe=lambda _profile: _async_result({"ok": True}),
        codex_probe=lambda: _async_result({"ok": True}),
        poll_interval_seconds=0.01,
    )

    async def scenario() -> None:
        task = asyncio.create_task(runtime.serve())
        await asyncio.wait_for(started.wait(), timeout=1)
        runtime.request_stop()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())

    assert bot.closed is True
    assert runtime.paths.stop_path.exists() is False
    state = json.loads(runtime.paths.state_path.read_text(encoding="utf-8"))
    assert state["status"] == "stopped"


def test_operational_cli_and_manager_are_bot_only_and_hidden() -> None:
    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    manager = Path("scripts/manage_feishu_bot.ps1").read_text(encoding="utf-8")

    assert set(commands) == {"preflight", "handle-event", "serve", "status", "stop"}
    assert "Start-Process" in manager
    assert "-WindowStyle Hidden" in manager
    assert "run_feishu_bot.py" in manager
    assert "Stop-Process" not in manager
    assert "run_worker.py" not in manager
    assert "run_control_plane.py" not in manager
    assert "8080" not in manager
    assert "18080" not in manager


async def _async_result(value: dict[str, object]) -> dict[str, object]:
    return value
