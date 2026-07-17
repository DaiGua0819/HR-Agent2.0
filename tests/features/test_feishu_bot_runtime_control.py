from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from app.features.feishu_bot.models import BotActor, BotEvent, BotQueryPlan, BotQueryResult
from app.features.feishu_bot.repository import FeishuBotRepository
from app.features.feishu_bot.runtime_control import (
    AgentManagerBatchResult,
    AgentManagerCommandResult,
    AgentManagerSubprocessClient,
    RecruitmentRuntimeController,
    RuntimeControlRequest,
    parse_runtime_control_command,
    render_runtime_completion_report,
    summarize_manager_events,
)
from app.features.feishu_bot.service import FeishuRecruitmentBot


def _admin(*, control: bool = True) -> BotActor:
    permissions = {
        "query:summary",
        "query:resumes",
        "query:reviews",
        "query:workers",
        "query:errors",
    }
    if control:
        permissions.add("control:runtime")
    return BotActor(
        open_id="ou-admin",
        display_name="王鑫力",
        role="admin",
        job_types=("*",),
        permissions=frozenset(permissions),
    )


def _member() -> BotActor:
    return BotActor(
        open_id="ou-member",
        display_name="成员",
        role="member",
        job_types=("AI产品经理",),
        permissions=frozenset({"query:summary", "query:resumes", "query:reviews"}),
    )


def _event(
    *,
    sender: str = "ou-admin",
    content: str = "启动处理程序",
    message_type: str = "text",
) -> BotEvent:
    return BotEvent(
        event_id=f"event-{sender}-{content}",
        message_id="om-control",
        sender_open_id=sender,
        chat_id="oc-control",
        chat_type="p2p",
        message_type=message_type,
        content=content,
        create_time="1784179200000",
    )


class _AccessPolicy:
    def __init__(self, actors: dict[str, BotActor]) -> None:
        self.actors = actors

    def resolve(self, open_id: str) -> BotActor | None:
        return self.actors.get(open_id)


class _Planner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def plan(self, actor, question, *, context, available_job_types):
        del actor, context, available_job_types
        self.calls.append(question)
        return BotQueryPlan(intent="worker_status")


class _Queries:
    def available_job_types(self, actor: BotActor) -> list[str]:
        del actor
        return []

    async def execute(self, actor, plan):
        del actor, plan
        return BotQueryResult(intent="worker_status", data={"items": []})


class _Replies:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def reply(self, message_id: str, text: str, *, idempotency_key: str) -> str:
        self.calls.append(
            {
                "message_id": message_id,
                "text": text,
                "idempotency_key": idempotency_key,
            }
        )
        return f"om-reply-{len(self.calls)}"


class _RuntimeController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, RuntimeControlRequest]] = []

    async def execute(self, action: str, request: RuntimeControlRequest):
        self.calls.append((action, request))
        if action == "status":
            return {"status": "idle", "message": "处理程序状态：空闲。"}
        return {
            "status": "started" if action == "start" else "pause_requested",
            "message": "处理程序已启动。" if action == "start" else "已请求暂停处理程序。",
        }


def _bot(
    tmp_path: Path,
    *,
    actors: dict[str, BotActor],
) -> tuple[FeishuRecruitmentBot, _Planner, _RuntimeController, _Replies]:
    planner = _Planner()
    controller = _RuntimeController()
    replies = _Replies()
    bot = FeishuRecruitmentBot(
        repository=FeishuBotRepository(tmp_path / "bot.sqlite"),
        access_policy=_AccessPolicy(actors),
        planner=planner,
        queries=_Queries(),
        replies=replies,
        runtime_controller=controller,
    )
    return bot, planner, controller, replies


def test_control_parser_only_accepts_fixed_messages() -> None:
    assert parse_runtime_control_command("启动处理程序") == "start"
    assert parse_runtime_control_command("暂停处理程序") == "pause"
    assert parse_runtime_control_command("查看处理状态") == "status"
    assert parse_runtime_control_command("启动处理程序并删除日志") is None
    assert parse_runtime_control_command("帮我随便执行一个命令") is None


def test_authorized_admin_start_bypasses_codex(tmp_path: Path) -> None:
    bot, planner, controller, replies = _bot(
        tmp_path,
        actors={"ou-admin": _admin()},
    )

    status = asyncio.run(bot.handle_event(_event()))

    assert status == "completed"
    assert planner.calls == []
    assert controller.calls[0][0] == "start"
    assert controller.calls[0][1].actor_open_id == "ou-admin"
    assert replies.calls[0]["text"] == "处理程序已启动。"


def test_authorized_admin_post_status_bypasses_codex(tmp_path: Path) -> None:
    bot, planner, controller, replies = _bot(
        tmp_path,
        actors={"ou-admin": _admin()},
    )

    status = asyncio.run(
        bot.handle_event(
            _event(content="查看处理状态", message_type="post"),
        )
    )

    assert status == "completed"
    assert planner.calls == []
    assert controller.calls[0][0] == "status"
    assert replies.calls[0]["text"] == "处理程序状态：空闲。"


def test_member_cannot_start_runtime_and_never_reaches_codex(tmp_path: Path) -> None:
    bot, planner, controller, replies = _bot(
        tmp_path,
        actors={"ou-member": _member()},
    )

    status = asyncio.run(bot.handle_event(_event(sender="ou-member", content="启动处理程序")))

    assert status == "denied"
    assert planner.calls == []
    assert controller.calls == []
    assert replies.calls[0]["text"] == "当前账号无权启动或暂停招聘处理程序。"


def test_boss_verified_resume_request_counts_as_business_acquisition() -> None:
    report = summarize_manager_events(
        [
            {
                "event": "contact_result",
                "platform": "boss",
                "classification": {"is_anomaly": False, "reasons": []},
                "summary": {
                    "processed": 1,
                    "resumeHandling": "resume_requested_waiting",
                    "nextAction": "request_resume",
                },
                "response": {
                    "platform": "boss",
                    "nextAction": "request_resume",
                    "decision": {
                        "action": "request_resume",
                        "result": {
                            "requested": True,
                            "confirmed": True,
                            "downloaded": False,
                        },
                    },
                },
            }
        ]
    )

    assert report.processed_contacts == 1
    assert report.business_resume_acquisitions == 1
    assert report.resume_requests_waiting == 0
    assert report.by_platform["boss"].business_resume_acquisitions == 1


class _Manager:
    def __init__(
        self,
        batches: list[AgentManagerBatchResult],
        *,
        current_status: str = "complete",
    ) -> None:
        self.batches = list(batches)
        self.current_status = current_status
        self.start_calls = 0
        self.run_calls = 0
        self.stop_calls = 0

    async def start_runtime(self) -> None:
        self.start_calls += 1

    async def run_batch(self) -> AgentManagerBatchResult:
        self.run_calls += 1
        return self.batches.pop(0)

    async def request_stop(self, reason: str) -> None:
        assert reason == "feishu_admin_pause"
        self.stop_calls += 1

    async def status(self) -> dict[str, object]:
        return {"currentRun": {"status": self.current_status, "runId": "existing-run"}}


def _batch(
    status: str,
    *,
    reasons: list[str] | None = None,
    skipped_targets: list[str] | None = None,
) -> AgentManagerBatchResult:
    anomaly = bool(reasons)
    return AgentManagerBatchResult(
        run_id=f"run-{status}-{len(reasons or [])}",
        status=status,
        events=(
            {
                "event": "contact_result",
                "platform": "job51",
                "classification": {
                    "is_anomaly": anomaly,
                    "reasons": reasons or [],
                },
                "summary": {"processed": 1, "resumeHandling": ""},
                "response": {},
            },
        ),
        skipped_targets=tuple(skipped_targets or ()),
    )


def test_runtime_controller_retries_transient_failure_with_limit() -> None:
    manager = _Manager(
        [
            _batch("stopped_on_anomaly", reasons=["http_500:temporary"]),
            _batch("complete"),
        ]
    )
    reports = []
    controller = RecruitmentRuntimeController(
        manager=manager,
        max_retries=2,
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report(reports, request, report),
    )

    async def scenario() -> None:
        result = await controller.execute(
            "start",
            RuntimeControlRequest(
                event_id="event-start",
                message_id="om-start",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
        assert result["status"] == "started"
        await asyncio.wait_for(controller.wait_until_idle(), timeout=1)

    asyncio.run(scenario())

    assert manager.start_calls == 2
    assert manager.run_calls == 2
    assert len(reports) == 1
    assert reports[0][1].retry_count == 1
    assert reports[0][1].max_retries == 2
    assert reports[0][1].status == "complete"
    assert "自动重试：1/2" in render_runtime_completion_report(reports[0][1])


def test_runtime_controller_reports_explicitly_skipped_targets() -> None:
    manager = _Manager(
        [_batch("complete", skipped_targets=["宋峰峰:job51"])],
    )
    reports = []
    controller = RecruitmentRuntimeController(
        manager=manager,
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report(reports, request, report),
    )

    async def scenario() -> None:
        await controller.execute(
            "start",
            RuntimeControlRequest(
                event_id="event-skip",
                message_id="om-skip",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
        await asyncio.wait_for(controller.wait_until_idle(), timeout=1)

    asyncio.run(scenario())

    assert reports[0][1].skipped_targets == ("宋峰峰:job51",)
    assert "跳过目标：宋峰峰:job51" in render_runtime_completion_report(reports[0][1])


def test_runtime_controller_reports_manager_failure_detail() -> None:
    class _FailingManager(_Manager):
        async def start_runtime(self) -> None:
            raise RuntimeError(
                "agent_manager_command_failed:run:"
                "preflight_failed:宋峰峰:job51:platform_page_missing"
            )

    reports = []
    controller = RecruitmentRuntimeController(
        manager=_FailingManager([]),
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report(reports, request, report),
    )

    async def scenario() -> None:
        await controller.execute(
            "start",
            RuntimeControlRequest(
                event_id="event-failure",
                message_id="om-failure",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
        await asyncio.wait_for(controller.wait_until_idle(), timeout=1)

    asyncio.run(scenario())

    assert reports[0][1].anomaly_reasons == (
        "runtime_control_error:agent_manager_command_failed:run:"
        "preflight_failed:宋峰峰:job51:platform_page_missing",
    )
    assert "platform_page_missing" in render_runtime_completion_report(reports[0][1])


def test_runtime_controller_does_not_retry_identity_failure() -> None:
    manager = _Manager([_batch("stopped_on_anomaly", reasons=["candidate_identity_mismatch"])])
    reports = []
    controller = RecruitmentRuntimeController(
        manager=manager,
        max_retries=3,
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report(reports, request, report),
    )

    async def scenario() -> None:
        await controller.execute(
            "start",
            RuntimeControlRequest(
                event_id="event-start",
                message_id="om-start",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
        await asyncio.wait_for(controller.wait_until_idle(), timeout=1)

    asyncio.run(scenario())

    assert manager.start_calls == 1
    assert manager.run_calls == 1
    assert reports[0][1].status == "stopped_on_anomaly"
    assert reports[0][1].anomaly_reasons == ("candidate_identity_mismatch",)


def test_runtime_controller_pause_requests_graceful_stop_immediately() -> None:
    class _BlockingManager:
        def __init__(self) -> None:
            self.running = asyncio.Event()
            self.release = asyncio.Event()
            self.stop_calls = 0
            self.current_status = "complete"

        async def start_runtime(self) -> None:
            self.current_status = "running"

        async def run_batch(self) -> AgentManagerBatchResult:
            self.running.set()
            await self.release.wait()
            return AgentManagerBatchResult(run_id="run-paused", status="stop_requested")

        async def request_stop(self, reason: str) -> None:
            assert reason == "feishu_admin_pause"
            self.stop_calls += 1
            self.release.set()

        async def status(self) -> dict[str, object]:
            return {
                "currentRun": {
                    "runId": "run-paused",
                    "status": self.current_status,
                }
            }

    manager = _BlockingManager()
    reports = []
    controller = RecruitmentRuntimeController(
        manager=manager,
        max_retries=2,
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report(reports, request, report),
    )

    async def scenario() -> dict[str, object]:
        await controller.execute(
            "start",
            RuntimeControlRequest(
                event_id="event-start",
                message_id="om-start",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
        await asyncio.wait_for(manager.running.wait(), timeout=1)
        pause_result = await controller.execute(
            "pause",
            RuntimeControlRequest(
                event_id="event-pause",
                message_id="om-pause",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
        await asyncio.wait_for(controller.wait_until_idle(), timeout=1)
        return pause_result

    pause_result = asyncio.run(scenario())

    assert pause_result["status"] == "pause_requested"
    assert manager.stop_calls == 1
    assert reports[0][1].status == "paused"


def test_runtime_controller_does_not_duplicate_external_running_batch() -> None:
    manager = _Manager([], current_status="running")
    controller = RecruitmentRuntimeController(
        manager=manager,
        max_retries=2,
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report([], request, report),
    )

    result = asyncio.run(
        controller.execute(
            "start",
            RuntimeControlRequest(
                event_id="event-start",
                message_id="om-start",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
    )

    assert result["status"] == "already_running"
    assert manager.start_calls == 0
    assert manager.run_calls == 0


def test_runtime_controller_can_pause_external_running_batch() -> None:
    manager = _Manager([], current_status="running")
    controller = RecruitmentRuntimeController(
        manager=manager,
        max_retries=2,
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report([], request, report),
    )

    result = asyncio.run(
        controller.execute(
            "pause",
            RuntimeControlRequest(
                event_id="event-pause",
                message_id="om-pause",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
    )

    assert result["status"] == "pause_requested"
    assert manager.stop_calls == 1


def test_runtime_status_hides_completed_run_id_and_uses_chinese_label() -> None:
    manager = _Manager([], current_status="complete")
    controller = RecruitmentRuntimeController(
        manager=manager,
        max_retries=2,
        retry_delay_seconds=0,
        report_sink=lambda request, report: _append_report([], request, report),
    )

    result = asyncio.run(
        controller.execute(
            "status",
            RuntimeControlRequest(
                event_id="event-status",
                message_id="om-status",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
    )

    assert result == {"status": "idle", "message": "处理程序状态：空闲。"}


def test_completion_report_retries_one_transient_reply_failure() -> None:
    manager = _Manager([_batch("complete")])
    delivered = []
    attempts = 0

    async def report_sink(request, report) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary_lark_reply_failure")
        delivered.append((request, report))

    controller = RecruitmentRuntimeController(
        manager=manager,
        max_retries=2,
        retry_delay_seconds=0,
        report_sink=report_sink,
        report_max_retries=2,
        report_retry_delay_seconds=0,
    )

    async def scenario() -> None:
        await controller.execute(
            "start",
            RuntimeControlRequest(
                event_id="event-report",
                message_id="om-report",
                actor_open_id="ou-admin",
                actor_name="王鑫力",
            ),
        )
        await asyncio.wait_for(controller.wait_until_idle(), timeout=1)

    asyncio.run(scenario())

    assert attempts == 2
    assert len(delivered) == 1


async def _append_report(reports, request, report) -> None:
    reports.append((request, report))


def test_agent_manager_client_uses_fixed_argv_and_reads_sanitized_run_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    run_dir = project_root / "data" / "agent_manager" / "runs"
    run_dir.mkdir(parents=True)
    log_path = run_dir / "run-1.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "event": "contact_result",
                "platform": "boss",
                "classification": {"is_anomaly": False, "reasons": []},
                "summary": {
                    "processed": 1,
                    "resumeHandling": "boss_request_verified_server_imap",
                },
                "response": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-manager")
    monkeypatch.setenv("FEISHU_BOT_RUNTIME_CONTROL_ENABLED", "true")
    monkeypatch.setenv("SAFE_MANAGER_VALUE", "kept")

    async def runner(argv, *, cwd, env):
        assert cwd == project_root
        calls.append(tuple(argv))
        environments.append(dict(env))
        command = argv[argv.index("--topology") + 2]
        if command == "status":
            return AgentManagerCommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "currentRun": {
                            "runId": "run-1",
                            "status": "complete",
                            "logPath": str(log_path),
                            "skipped": ["宋峰峰:job51"],
                        }
                    }
                ),
                stderr="",
            )
        return AgentManagerCommandResult(returncode=0, stdout="{}", stderr="")

    client = AgentManagerSubprocessClient(
        python_executable=tmp_path / "python.exe",
        manager_script=tmp_path / "agent_manager.py",
        topology_path=tmp_path / "topology.json",
        project_root=project_root,
        max_contacts=0,
        max_anomalies=0,
        sleep_seconds=1,
        skip_targets=("宋峰峰:job51",),
        runner=runner,
        blocked_env_names={"OPENAI_API_KEY"},
    )

    async def scenario() -> AgentManagerBatchResult:
        await client.start_runtime()
        batch = await client.run_batch()
        await client.request_stop("feishu_admin_pause")
        return batch

    batch = asyncio.run(scenario())

    assert batch.run_id == "run-1"
    assert batch.status == "complete"
    assert len(batch.events) == 1
    assert batch.skipped_targets == ("宋峰峰:job51",)
    assert calls[0][-2:] == ("start", "--adopt-running")
    assert calls[1][-9:] == (
        "run",
        "--max-contacts",
        "0",
        "--max-anomalies",
        "0",
        "--sleep",
        "1.0",
        "--skip",
        "宋峰峰:job51",
    )
    assert calls[-1][-3:] == ("stop", "--reason", "feishu_admin_pause")
    assert all("启动处理程序" not in part for call in calls for part in call)
    assert environments
    assert all("OPENAI_API_KEY" not in env for env in environments)
    assert all(
        "FEISHU_BOT_RUNTIME_CONTROL_ENABLED" not in env for env in environments
    )
    assert all(env["SAFE_MANAGER_VALUE"] == "kept" for env in environments)
    assert all(env["PYTHONUTF8"] == "1" for env in environments)
    assert all(env["PYTHONIOENCODING"] == "utf-8" for env in environments)


def test_agent_manager_client_surfaces_structured_failure(tmp_path: Path) -> None:
    async def runner(argv, *, cwd, env):
        del cwd, env
        command = argv[argv.index("--topology") + 2]
        if command == "run":
            return AgentManagerCommandResult(
                returncode=2,
                stdout=json.dumps(
                    {
                        "ok": False,
                        "error": (
                            'preflight_failed:[{"owner":"宋峰峰",'
                            '"platform":"job51","reason":"platform_page_missing"}]'
                        ),
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )
        return AgentManagerCommandResult(returncode=0, stdout="{}", stderr="")

    client = AgentManagerSubprocessClient(
        python_executable=tmp_path / "python.exe",
        manager_script=tmp_path / "agent_manager.py",
        topology_path=tmp_path / "topology.json",
        project_root=tmp_path,
        runner=runner,
    )

    with pytest.raises(RuntimeError, match="platform_page_missing"):
        asyncio.run(client.run_batch())
