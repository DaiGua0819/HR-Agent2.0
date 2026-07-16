from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.features.feishu_bot.codex_planner import (
    CodexPolicyViolation,
    CodexQueryPlanner,
    CodexRunResult,
    _codex_parent_environment,
    _resolve_command_prefix,
)
from app.features.feishu_bot.models import BotActor


def _member() -> BotActor:
    return BotActor(
        open_id="ou-member",
        display_name="菜花",
        role="member",
        job_types=("AI产品经理",),
        review_user_id="feishu:review-member",
        permissions=frozenset({"query:summary", "query:resumes", "query:reviews"}),
    )


def _admin() -> BotActor:
    return BotActor(
        open_id="ou-admin",
        display_name="王鑫力",
        role="admin",
        job_types=("*",),
        permissions=frozenset(
            {
                "query:summary",
                "query:resumes",
                "query:reviews",
                "query:workers",
                "query:errors",
                "query:all_jobs",
                "query:shared_queue",
            }
        ),
    )


def _agent_message(plan: dict[str, object]) -> str:
    return json.dumps(
        {
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "type": "agent_message",
                "text": json.dumps(plan, ensure_ascii=False),
            },
        },
        ensure_ascii=False,
    )


def test_codex_planner_uses_ephemeral_read_only_schema_constrained_process(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def runner(
        argv: list[str],
        *,
        stdin: str,
        cwd: Path,
        timeout_seconds: float,
        env: dict[str, str],
    ) -> CodexRunResult:
        calls.append(
            {
                "argv": argv,
                "stdin": stdin,
                "cwd": cwd,
                "timeout": timeout_seconds,
                "env": env,
            }
        )
        return CodexRunResult(
            returncode=0,
            stdout=_agent_message(
                {
                    "intent": "resume_counts",
                    "date": "",
                    "dateStart": "",
                    "dateEnd": "",
                    "jobTypes": ["AI Product Manager"],
                    "owner": "",
                    "platform": "",
                    "limit": 10,
                    "clarification": "",
                }
            ),
            stderr="",
            elapsed_seconds=0.2,
        )

    planner = CodexQueryPlanner(
        runtime_dir=tmp_path / "sandbox",
        runner=runner,
        now=lambda: datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )

    plan = asyncio.run(
        planner.plan(
            _member(),
            "AI 产品经理有多少份简历？",
            available_job_types=["AI产品经理"],
        )
    )

    assert plan.intent == "resume_counts"
    assert plan.job_types == ["AI产品经理"]
    assert len(calls) == 1
    argv = calls[0]["argv"]
    assert isinstance(argv, list)
    assert argv[:2] == ["codex", "exec"]
    assert "--ephemeral" in argv
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert "--skip-git-repo-check" in argv
    assert "--strict-config" in argv
    assert "--json" in argv
    assert "--output-schema" in argv
    assert 'default_permissions=":read-only"' in argv
    assert 'approval_policy="never"' in argv
    assert 'web_search="disabled"' in argv
    assert 'shell_environment_policy.inherit="none"' in argv
    assert "features.shell_tool=false" in argv
    assert "features.browser_use=false" in argv
    assert "features.browser_use_external=false" in argv
    assert "features.browser_use_full_cdp_access=false" in argv
    assert "features.computer_use=false" in argv
    assert "features.in_app_browser=false" in argv
    assert "features.apps=false" in argv
    assert "features.image_generation=false" in argv
    assert "features.multi_agent=false" in argv
    assert "features.goals=false" in argv
    assert "features.workspace_dependencies=false" in argv
    assert "features.tool_suggest=false" in argv
    assert "features.remote_plugin=false" in argv
    assert "features.shell_snapshot=false" in argv
    assert "features.personality=false" in argv
    assert "--sandbox" not in argv
    assert calls[0]["cwd"] == tmp_path / "sandbox"
    assert "完整简历" not in str(calls[0]["stdin"])
    assert "数据库" not in str(calls[0]["stdin"])


def test_codex_planner_api_key_mode_uses_isolated_provider_and_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("FEISHU_BOT_GATEWAY_KEY", "bot-only-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-project-key")

    async def runner(
        argv: list[str],
        *,
        stdin: str,
        cwd: Path,
        timeout_seconds: float,
        env: dict[str, str],
    ) -> CodexRunResult:
        calls.append({"argv": argv, "cwd": cwd, "env": env})
        return CodexRunResult(
            returncode=0,
            stdout=_agent_message(_help_plan()),
            stderr="",
            elapsed_seconds=0.1,
        )

    runtime_dir = tmp_path / "isolated-runtime"
    planner = CodexQueryPlanner(
        runtime_dir=runtime_dir,
        model="gpt-5.6-sol",
        provider_base_url="http://127.0.0.1:8097/v1",
        api_key_env="FEISHU_BOT_GATEWAY_KEY",
        runner=runner,
    )

    asyncio.run(planner.plan(_admin(), "帮助"))

    assert len(calls) == 1
    argv = calls[0]["argv"]
    env = calls[0]["env"]
    assert isinstance(argv, list)
    assert isinstance(env, dict)
    assert 'model_provider="feishu_bot_gateway"' in argv
    assert (
        'model_providers.feishu_bot_gateway.base_url="http://127.0.0.1:8097/v1"'
        in argv
    )
    assert (
        'model_providers.feishu_bot_gateway.env_key="CODEX_API_KEY"' in argv
    )
    assert "model_providers.feishu_bot_gateway.supports_websockets=false" in argv
    assert env["CODEX_API_KEY"] == "bot-only-secret"
    assert env["CODEX_HOME"] == str(runtime_dir / "codex-home")
    assert "FEISHU_BOT_GATEWAY_KEY" not in env
    assert "OPENAI_API_KEY" not in env
    assert (runtime_dir / "codex-home").is_dir()


@pytest.mark.parametrize(
    "item_type",
    ["command_execution", "file_change", "mcp_tool_call", "web_search"],
)
def test_codex_planner_rejects_any_tool_event(tmp_path: Path, item_type: str) -> None:
    async def runner(*_args: object, **_kwargs: object) -> CodexRunResult:
        tool_event = json.dumps(
            {
                "type": "item.started",
                "item": {"id": "item-tool", "type": item_type},
            }
        )
        return CodexRunResult(
            returncode=0,
            stdout=tool_event + "\n" + _agent_message(_help_plan()),
            stderr="",
            elapsed_seconds=0.1,
        )

    planner = CodexQueryPlanner(runtime_dir=tmp_path, runner=runner)

    with pytest.raises(CodexPolicyViolation, match=item_type):
        asyncio.run(planner.plan(_member(), "帮助"))


def test_codex_planner_rejects_tool_event_even_when_process_fails(tmp_path: Path) -> None:
    async def runner(*_args: object, **_kwargs: object) -> CodexRunResult:
        return CodexRunResult(
            returncode=1,
            stdout=json.dumps(
                {
                    "type": "item.started",
                    "item": {"id": "item-tool", "type": "command_execution"},
                }
            ),
            stderr="sandbox rejected command",
            elapsed_seconds=0.1,
        )

    planner = CodexQueryPlanner(runtime_dir=tmp_path, runner=runner)

    with pytest.raises(CodexPolicyViolation, match="command_execution"):
        asyncio.run(planner.plan(_member(), "help"))


def test_codex_plan_cannot_escalate_member_or_request_other_jobs(tmp_path: Path) -> None:
    plans = [
        {
            **_help_plan(),
            "intent": "worker_status",
        },
        {
            **_help_plan(),
            "intent": "resume_counts",
            "jobTypes": ["运营B"],
        },
    ]

    async def runner(*_args: object, **_kwargs: object) -> CodexRunResult:
        return CodexRunResult(
            returncode=0,
            stdout=_agent_message(plans.pop(0)),
            stderr="",
            elapsed_seconds=0.1,
        )

    planner = CodexQueryPlanner(runtime_dir=tmp_path, runner=runner)

    with pytest.raises(PermissionError, match="query:workers"):
        asyncio.run(planner.plan(_member(), "看看 Worker 状态"))
    with pytest.raises(PermissionError, match="job_scope_denied"):
        asyncio.run(planner.plan(_member(), "运营 B 有多少简历"))


def test_codex_unavailable_uses_safe_context_aware_fallback(tmp_path: Path) -> None:
    async def runner(*_args: object, **_kwargs: object) -> CodexRunResult:
        return CodexRunResult(
            returncode=1,
            stdout="",
            stderr="temporary unavailable",
            elapsed_seconds=0.1,
        )

    planner = CodexQueryPlanner(
        runtime_dir=tmp_path,
        runner=runner,
        now=lambda: datetime(2026, 7, 16, 2, 0, tzinfo=UTC),
    )

    plan = asyncio.run(
        planner.plan(
            _admin(),
            "昨天呢？",
            context=[
                {
                    "intent": "daily_summary",
                    "question": "今天处理了多少人",
                    "response": "今天处理 3 人",
                }
            ],
            available_job_types=["AI产品经理", "运营B"],
        )
    )

    assert plan.intent == "daily_summary"
    assert plan.date == "2026-07-15"


def test_windows_codex_launcher_resolves_node_without_shell() -> None:
    calls: list[str] = []

    def which(name: str) -> str | None:
        calls.append(name)
        return "C:/nvm/codex.cmd" if name == "codex.cmd" else None

    def exists(path: Path) -> bool:
        return str(path).replace("\\", "/") in {
            "C:/nvm/node.exe",
            "C:/nvm/node_modules/@openai/codex/bin/codex.js",
        }

    resolved = _resolve_command_prefix(
        "codex",
        platform_name="nt",
        which=which,
        exists=exists,
    )
    assert [Path(item).as_posix() for item in resolved] == [
        "C:/nvm/node.exe",
        "C:/nvm/node_modules/@openai/codex/bin/codex.js",
    ]
    assert calls == ["codex.cmd"]


def test_codex_parent_environment_drops_project_model_credentials() -> None:
    sanitized = _codex_parent_environment(
        {
            "PATH": "C:/bin",
            "HOME": "C:/Users/test",
            "OPENAI_API_KEY": "project-key",
            "OPENAI_BASE_URL": "https://provider.invalid/v1",
            "OPENAI_MODEL": "project-model",
            "CODEX_API_KEY": "codex-key",
            "CODEX_ACCESS_TOKEN": "codex-token",
        }
    )

    assert sanitized["PATH"] == "C:/bin"
    assert sanitized["HOME"] == "C:/Users/test"
    assert "OPENAI_API_KEY" not in sanitized
    assert "OPENAI_BASE_URL" not in sanitized
    assert "OPENAI_MODEL" not in sanitized
    assert "CODEX_API_KEY" not in sanitized
    assert "CODEX_ACCESS_TOKEN" not in sanitized


def test_codex_parent_environment_maps_only_explicit_bot_api_key(
    tmp_path: Path,
) -> None:
    sanitized = _codex_parent_environment(
        {
            "PATH": "C:/bin",
            "OPENAI_API_KEY": "project-key",
            "FEISHU_BOT_GATEWAY_KEY": "bot-key",
            "FEISHU_APP_SECRET": "feishu-secret",
            "AUTO_SYNC_SECRET": "sync-secret",
            "DATABASE_PASSWORD": "database-secret",
        },
        api_key_env="FEISHU_BOT_GATEWAY_KEY",
        codex_home=tmp_path / "codex-home",
    )

    assert sanitized["PATH"] == "C:/bin"
    assert sanitized["CODEX_API_KEY"] == "bot-key"
    assert sanitized["CODEX_HOME"] == str(tmp_path / "codex-home")
    assert "OPENAI_API_KEY" not in sanitized
    assert "FEISHU_BOT_GATEWAY_KEY" not in sanitized
    assert "FEISHU_APP_SECRET" not in sanitized
    assert "AUTO_SYNC_SECRET" not in sanitized
    assert "DATABASE_PASSWORD" not in sanitized


def test_codex_parent_environment_uses_minimal_system_allowlist() -> None:
    sanitized = _codex_parent_environment(
        {
            "PATH": "C:/bin",
            "SYSTEMROOT": "C:/Windows",
            "TEMP": "C:/Temp",
            "HOME": "C:/Users/test",
            "FEISHU_APP_SECRET": "feishu-secret",
            "AUTO_SYNC_SECRET": "sync-secret",
            "HR_AGENT_BROWSER_PROFILE": "browser-profile",
            "UNRELATED_TOKEN": "token",
        }
    )

    assert sanitized == {
        "PATH": "C:/bin",
        "SYSTEMROOT": "C:/Windows",
        "TEMP": "C:/Temp",
        "HOME": "C:/Users/test",
    }


def _help_plan() -> dict[str, object]:
    return {
        "intent": "help",
        "date": "",
        "dateStart": "",
        "dateEnd": "",
        "jobTypes": [],
        "owner": "",
        "platform": "",
        "limit": 10,
        "clarification": "",
    }
