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
    ) -> CodexRunResult:
        calls.append(
            {
                "argv": argv,
                "stdin": stdin,
                "cwd": cwd,
                "timeout": timeout_seconds,
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
    assert "--skip-git-repo-check" in argv
    assert "--strict-config" in argv
    assert "--json" in argv
    assert "--output-schema" in argv
    assert 'default_permissions=":read-only"' in argv
    assert 'approval_policy="never"' in argv
    assert 'web_search="disabled"' in argv
    assert 'shell_environment_policy.inherit="none"' in argv
    assert "--sandbox" not in argv
    assert calls[0]["cwd"] == tmp_path / "sandbox"
    assert "完整简历" not in str(calls[0]["stdin"])
    assert "数据库" not in str(calls[0]["stdin"])


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
