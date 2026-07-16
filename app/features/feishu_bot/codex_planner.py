"""Use a tightly sandboxed Codex process to plan read-only bot queries."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from app.core.text import clean_text
from app.domain.resume.job_types import (
    any_job_type_matches,
    canonical_resume_job_type,
)
from app.features.feishu_bot.models import BotActor, BotQueryPlan

CodexRunner = Callable[..., Awaitable["CodexRunResult"]]
_TOOL_ITEM_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
}
_INTENT_PERMISSIONS = {
    "daily_summary": "query:summary",
    "resume_counts": "query:resumes",
    "recent_resumes": "query:resumes",
    "review_summary": "query:reviews",
    "worker_status": "query:workers",
    "recent_errors": "query:errors",
}
_DATE_RE = re.compile(r"\b(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?\b")
_CODEX_PARENT_ENV_DENY = {
    "CODEX_ACCESS_TOKEN",
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
}


class CodexPolicyViolation(RuntimeError):
    """Raised when Codex attempts a tool or emits an unauthorized plan."""


@dataclass(frozen=True)
class CodexRunResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class CodexQueryPlanner:
    """Convert a question to a validated query plan; never execute the query."""

    def __init__(
        self,
        *,
        runtime_dir: str | Path,
        codex_command: str = "codex",
        model: str = "",
        timeout_seconds: float = 45,
        schema_path: str | Path | None = None,
        runner: CodexRunner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.codex_command = codex_command
        self.model = clean_text(model)
        self.timeout_seconds = float(timeout_seconds)
        self.schema_path = (
            Path(schema_path)
            if schema_path is not None
            else Path(__file__).with_name("query_plan.schema.json")
        )
        self.runner = runner or _run_subprocess
        self.now = now or (lambda: datetime.now(UTC))

    async def plan(
        self,
        actor: BotActor,
        question: str,
        *,
        context: list[dict[str, object]] | None = None,
        available_job_types: list[str] | None = None,
    ) -> BotQueryPlan:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        available_jobs = _allowed_prompt_jobs(actor, available_job_types or [])
        prompt = _planner_prompt(
            actor,
            question,
            context=context or [],
            available_job_types=available_jobs,
            now=self.now(),
        )
        result = await self.runner(
            self._argv(),
            stdin=prompt,
            cwd=self.runtime_dir,
            timeout_seconds=self.timeout_seconds,
        )
        _raise_on_tool_events(result.stdout)
        if result.returncode != 0:
            return self.fallback_plan(
                actor,
                question,
                context=context or [],
                available_job_types=available_jobs,
            )
        try:
            raw_plan = _extract_plan(result.stdout)
            plan = BotQueryPlan.model_validate_json(raw_plan)
        except (ValueError, json.JSONDecodeError):
            return self.fallback_plan(
                actor,
                question,
                context=context or [],
                available_job_types=available_jobs,
            )
        return _validate_plan(actor, plan)

    def fallback_plan(
        self,
        actor: BotActor,
        question: str,
        *,
        context: list[dict[str, object]] | None = None,
        available_job_types: list[str] | None = None,
    ) -> BotQueryPlan:
        text = clean_text(question)
        jobs = _jobs_in_question(text, available_job_types or list(actor.job_types))
        date = _date_in_question(text, self.now())
        intent = _fallback_intent(text, context or [])
        plan = BotQueryPlan(
            intent=intent,
            date=date,
            jobTypes=jobs,
            limit=10,
            clarification="" if intent != "unsupported" else "请换一种方式描述查询需求",
        )
        return _validate_plan(actor, plan)

    def _argv(self) -> list[str]:
        argv = [
            self.codex_command,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--strict-config",
            "--json",
            "--output-schema",
            str(self.schema_path.resolve()),
            "-C",
            str(self.runtime_dir.resolve()),
            "-c",
            'default_permissions=":read-only"',
            "-c",
            'approval_policy="never"',
            "-c",
            'web_search="disabled"',
            "-c",
            'shell_environment_policy.inherit="none"',
            "-c",
            "shell_environment_policy.ignore_default_excludes=false",
            "-c",
            "features.shell_tool=false",
            "-c",
            "features.browser_use=false",
            "-c",
            "features.browser_use_external=false",
            "-c",
            "features.browser_use_full_cdp_access=false",
            "-c",
            "features.computer_use=false",
            "-c",
            "features.in_app_browser=false",
            "-c",
            "features.apps=false",
            "-c",
            "features.image_generation=false",
            "-c",
            "features.multi_agent=false",
            "-c",
            "features.goals=false",
            "-c",
            "features.workspace_dependencies=false",
            "-c",
            "features.tool_suggest=false",
            "-c",
            "features.hooks=false",
            "-c",
            "features.memories=false",
            "-c",
            "mcp_servers={}",
        ]
        if self.model:
            argv.extend(["--model", self.model])
        argv.append("-")
        return argv


async def _run_subprocess(
    argv: list[str],
    *,
    stdin: str,
    cwd: Path,
    timeout_seconds: float,
) -> CodexRunResult:
    started = time.monotonic()
    resolved_argv = [*_resolve_command_prefix(argv[0]), *argv[1:]]
    process = await asyncio.create_subprocess_exec(
        *resolved_argv,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_codex_parent_environment(os.environ),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin.encode("utf-8")),
            timeout=max(1.0, timeout_seconds),
        )
    except TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
        return CodexRunResult(
            returncode=124,
            stdout="",
            stderr="codex_query_plan_timeout",
            elapsed_seconds=time.monotonic() - started,
        )
    return CodexRunResult(
        returncode=int(process.returncode or 0),
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace")[-4000:],
        elapsed_seconds=time.monotonic() - started,
    )


def _resolve_command_prefix(
    command: str,
    *,
    platform_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[Path], bool] | None = None,
) -> list[str]:
    """Resolve npm's `node + codex.js` on Windows without invoking a shell."""

    active_platform = platform_name or os.name
    if active_platform != "nt" or Path(command).suffix:
        return [command]
    path_exists = exists or (lambda path: path.is_file())
    command_shim = which(f"{command}.cmd")
    if command_shim:
        root = Path(command_shim).parent
        node = root / "node.exe"
        script = root / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if path_exists(node) and path_exists(script):
            return [str(node), str(script)]
    executable = which(f"{command}.exe")
    if executable:
        return [executable]
    raise FileNotFoundError(f"feishu_bot_executable_not_found:{command}.exe")


def _codex_parent_environment(
    source: os._Environ[str] | dict[str, str],
) -> dict[str, str]:
    """Use saved Codex login rather than project/provider API credentials."""

    return {
        key: value
        for key, value in source.items()
        if key.upper() not in _CODEX_PARENT_ENV_DENY
    }


def _extract_plan(stdout: str) -> str:
    final_text = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = clean_text(item.get("type"))
        if item_type in _TOOL_ITEM_TYPES:
            raise CodexPolicyViolation(f"codex_policy_violation:{item_type}")
        if item_type == "agent_message":
            final_text = clean_text(item.get("text") or item.get("content"))
    if not final_text:
        raise ValueError("codex_query_plan_missing")
    if final_text.startswith("```"):
        final_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", final_text, flags=re.I)
    return final_text


def _raise_on_tool_events(stdout: str) -> None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        item_type = clean_text(item.get("type"))
        if item_type in _TOOL_ITEM_TYPES:
            raise CodexPolicyViolation(f"codex_policy_violation:{item_type}")


def _validate_plan(actor: BotActor, plan: BotQueryPlan) -> BotQueryPlan:
    permission = _INTENT_PERMISSIONS.get(plan.intent)
    if permission and not actor.can(permission):
        raise PermissionError(f"feishu_bot_permission_denied:{permission}")
    if not actor.is_admin and (clean_text(plan.owner) or clean_text(plan.platform)):
        raise PermissionError("feishu_bot_plan_scope_denied:owner_or_platform")
    jobs: list[str] = []
    for value in plan.job_types:
        job = canonical_resume_job_type(value)
        if not job:
            continue
        if "*" not in actor.job_types and not any_job_type_matches(job, actor.job_types):
            raise PermissionError(f"feishu_bot_job_scope_denied:{job}")
        if job not in jobs:
            jobs.append(job)
    return plan.model_copy(
        update={
            "job_types": jobs,
            "owner": clean_text(plan.owner),
            "platform": clean_text(plan.platform).lower(),
            "limit": max(1, min(int(plan.limit), 20)),
            "clarification": clean_text(plan.clarification)[:300],
        }
    )


def _planner_prompt(
    actor: BotActor,
    question: str,
    *,
    context: list[dict[str, object]],
    available_job_types: list[str],
    now: datetime,
) -> str:
    safe_context = [
        {
            "intent": clean_text(item.get("intent"))[:40],
            "question": clean_text(item.get("question"))[:300],
            "response": clean_text(item.get("response"))[:500],
        }
        for item in context[-4:]
    ]
    payload = {
        "currentTime": now.astimezone(_shanghai_timezone()).isoformat(),
        "role": actor.role,
        "allowedIntents": [
            intent
            for intent, permission in _INTENT_PERMISSIONS.items()
            if actor.can(permission)
        ]
        + ["help", "unsupported"],
        "allowedJobTypes": available_job_types,
        "recentContext": safe_context,
        "question": clean_text(question)[:1000],
    }
    return (
        "你是招聘只读查询规划器。禁止调用任何工具、命令、文件、网络或 MCP。"
        "只根据输入选择一个允许的 intent，并严格输出符合给定 JSON Schema 的对象。"
        "不要回答事实，不要补充人数，不要扩大岗位范围。相对日期按 currentTime 解析。\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _allowed_prompt_jobs(actor: BotActor, available: list[str]) -> list[str]:
    candidates = available if "*" in actor.job_types else list(actor.job_types)
    result: list[str] = []
    for value in candidates:
        job = canonical_resume_job_type(value)
        if job and job != "*" and job not in result:
            result.append(job)
    return result


def _jobs_in_question(question: str, available: list[str]) -> list[str]:
    compact_question = question.replace(" ", "").lower()
    result: list[str] = []
    for value in available:
        job = canonical_resume_job_type(value)
        compact_job = job.replace(" ", "").lower()
        if job and job != "*" and compact_job in compact_question and job not in result:
            result.append(job)
    return result


def _fallback_intent(question: str, context: list[dict[str, object]]) -> str:
    lowered = question.lower()
    if any(keyword in question for keyword in ("帮助", "能做什么", "怎么用")):
        return "help"
    if any(keyword in lowered for keyword in ("worker", "服务状态", "浏览器状态", "账号状态")):
        return "worker_status"
    if any(keyword in question for keyword in ("异常", "错误", "失败原因", "报错")):
        return "recent_errors"
    if any(keyword in question for keyword in ("待处理", "审阅", "合适", "不合适")):
        return "review_summary"
    if "简历" in question and any(keyword in question for keyword in ("最近", "名单", "哪些")):
        return "recent_resumes"
    if "简历" in question and any(
        keyword in question for keyword in ("多少", "数量", "几份", "下载")
    ):
        return "resume_counts"
    if any(keyword in question for keyword in ("处理", "日报", "多少人", "获取了多少")):
        return "daily_summary"
    if _is_relative_followup(question) and context:
        previous = clean_text(context[-1].get("intent"))
        if previous in _INTENT_PERMISSIONS:
            return previous
    return "unsupported"


def _date_in_question(question: str, now: datetime) -> str:
    local_now = now.astimezone(_shanghai_timezone())
    if "前天" in question:
        return (local_now - timedelta(days=2)).strftime("%Y-%m-%d")
    if "昨天" in question:
        return (local_now - timedelta(days=1)).strftime("%Y-%m-%d")
    if "今天" in question:
        return local_now.strftime("%Y-%m-%d")
    match = _DATE_RE.search(question)
    if match:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
        ).strftime("%Y-%m-%d")
    return ""


def _is_relative_followup(question: str) -> bool:
    stripped = question.strip("？?。!！ ")
    return stripped in {"昨天呢", "今天呢", "前天呢", "那昨天呢", "那今天呢"}


def _shanghai_timezone() -> timezone:
    return timezone(timedelta(hours=8), name="Asia/Shanghai")
