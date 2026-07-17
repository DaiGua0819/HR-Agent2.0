from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from app.features.feishu_bot.lark_cli import LarkCliError
from app.features.feishu_bot.models import (
    BotActor,
    BotEvent,
    BotQueryPlan,
    BotQueryResult,
)
from app.features.feishu_bot.repository import FeishuBotRepository
from app.features.feishu_bot.service import FeishuRecruitmentBot


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
                "control:runtime",
            }
        ),
    )


def _event(
    *,
    event_id: str = "event-1",
    sender: str = "ou-member",
    chat_type: str = "p2p",
    content: str = "AI 产品经理有多少份简历？",
) -> BotEvent:
    return BotEvent(
        event_id=event_id,
        message_id=f"om-{event_id}",
        sender_open_id=sender,
        chat_id=f"oc-{chat_type}",
        chat_type=chat_type,
        message_type="text",
        content=content,
        create_time="1784179200000",
    )


class _AccessPolicy:
    def __init__(self, actors: dict[str, BotActor]) -> None:
        self.actors = actors

    def resolve(self, open_id: str) -> BotActor | None:
        return self.actors.get(open_id)


class _Planner:
    def __init__(self, plan: BotQueryPlan) -> None:
        self.plan_value = plan
        self.calls: list[dict[str, object]] = []

    async def plan(
        self,
        actor: BotActor,
        question: str,
        *,
        context: list[dict[str, object]],
        available_job_types: list[str],
    ) -> BotQueryPlan:
        self.calls.append(
            {
                "actor": actor,
                "question": question,
                "context": context,
                "available_job_types": available_job_types,
            }
        )
        return self.plan_value


class _Queries:
    def __init__(self, result: BotQueryResult) -> None:
        self.result = result
        self.calls: list[tuple[BotActor, BotQueryPlan]] = []

    def available_job_types(self, actor: BotActor) -> list[str]:
        return ["AI产品经理"] if not actor.is_admin else ["AI产品经理", "运营B"]

    async def execute(self, actor: BotActor, plan: BotQueryPlan) -> BotQueryResult:
        self.calls.append((actor, plan))
        return self.result


class _Replies:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, str]] = []

    async def reply(
        self,
        message_id: str,
        text: str,
        *,
        idempotency_key: str,
    ) -> str:
        self.calls.append(
            {
                "message_id": message_id,
                "text": text,
                "idempotency_key": idempotency_key,
            }
        )
        if self.failure is not None:
            raise self.failure
        return f"om-reply-{len(self.calls)}"


def _bot(
    tmp_path: Path,
    *,
    actors: dict[str, BotActor] | None = None,
    plan: BotQueryPlan | None = None,
    result: BotQueryResult | None = None,
    replies: _Replies | None = None,
    event_source_factory: object | None = None,
) -> tuple[FeishuRecruitmentBot, _Planner, _Queries, _Replies, FeishuBotRepository]:
    planner = _Planner(plan or BotQueryPlan(intent="resume_counts"))
    queries = _Queries(
        result
        or BotQueryResult(
            intent="resume_counts",
            data={
                "total": 3,
                "byJob": [{"jobType": "AI产品经理", "count": 3}],
            },
        )
    )
    reply_client = replies or _Replies()
    repository = FeishuBotRepository(tmp_path / "bot.sqlite")
    bot = FeishuRecruitmentBot(
        repository=repository,
        access_policy=_AccessPolicy(actors or {"ou-member": _member()}),
        planner=planner,
        queries=queries,
        replies=reply_client,
        event_source_factory=event_source_factory,
    )
    return bot, planner, queries, reply_client, repository


def test_duplicate_event_never_reaches_planner_query_or_second_reply(
    tmp_path: Path,
) -> None:
    bot, planner, queries, replies, repository = _bot(tmp_path)
    event = _event()

    first = asyncio.run(bot.handle_event(event))
    duplicate = asyncio.run(bot.handle_event(event))

    assert first == "completed"
    assert duplicate == "duplicate"
    assert len(planner.calls) == 1
    assert len(queries.calls) == 1
    assert len(replies.calls) == 1
    assert repository.get_event(event.event_id)["status"] == "completed"


def test_unknown_user_is_denied_before_codex_or_query(tmp_path: Path) -> None:
    bot, planner, queries, replies, repository = _bot(tmp_path, actors={})
    event = _event(sender="ou-unknown")

    status = asyncio.run(bot.handle_event(event))

    assert status == "denied"
    assert planner.calls == []
    assert queries.calls == []
    assert replies.calls[0]["text"] == "当前账号未获授权使用招聘查询机器人。"
    stored = repository.get_event(event.event_id)
    assert stored["status"] == "denied"
    assert stored["error"] == "unauthorized_open_id"


def test_group_chat_only_returns_generic_help(tmp_path: Path) -> None:
    bot, planner, queries, replies, repository = _bot(
        tmp_path,
        actors={"ou-admin": _admin()},
    )
    event = _event(sender="ou-admin", chat_type="group", content="今天处理多少人")

    status = asyncio.run(bot.handle_event(event))

    assert status == "completed"
    assert planner.calls == []
    assert queries.calls == []
    assert replies.calls[0]["text"] == (
        "为保护招聘数据，本机器人仅在授权用户的单聊中提供查询。"
    )
    assert repository.recent_turns(event.chat_id, event.sender_open_id) == []


def test_member_query_is_scoped_rendered_and_audited(tmp_path: Path) -> None:
    bot, planner, queries, replies, repository = _bot(tmp_path)
    event = _event()

    status = asyncio.run(bot.handle_event(event))

    assert status == "completed"
    assert planner.calls[0]["available_job_types"] == ["AI产品经理"]
    assert queries.calls[0][0].open_id == "ou-member"
    assert replies.calls == [
        {
            "message_id": "om-event-1",
            "text": "简历共 3 份\nAI产品经理：3 份",
            "idempotency_key": "feishu-bot:event-1",
        }
    ]
    turns = repository.recent_turns(event.chat_id, event.sender_open_id)
    assert len(turns) == 1
    assert turns[0]["actor_name"] == "菜花"
    assert turns[0]["intent"] == "resume_counts"


def test_service_strips_previous_query_results_before_calling_planner(
    tmp_path: Path,
) -> None:
    bot, planner, _queries, _replies, repository = _bot(tmp_path)
    previous = _event(event_id="previous", content="今天有多少份简历？")
    assert repository.claim_event(previous) is True
    repository.mark_processing(previous.event_id)
    repository.append_turn(
        event_id=previous.event_id,
        chat_id=previous.chat_id,
        sender_open_id=previous.sender_open_id,
        actor_name="测试成员",
        intent="resume_counts",
        question=previous.content,
        response="SENSITIVE_DB_RESULT_917",
    )
    repository.mark_completed(previous.event_id, response_message_id="om-previous")

    status = asyncio.run(
        bot.handle_event(_event(event_id="current", content="昨天呢？"))
    )

    assert status == "completed"
    context = planner.calls[0]["context"]
    assert isinstance(context, list)
    assert context == [
        {
            "intent": "resume_counts",
            "question": "今天有多少份简历？",
        }
    ]
    assert "SENSITIVE_DB_RESULT_917" not in str(context)


def test_long_event_id_uses_bounded_stable_reply_idempotency_key(tmp_path: Path) -> None:
    bot, _planner, _queries, replies, _repository = _bot(tmp_path)
    event = _event(event_id="event-" + "x" * 100)

    status = asyncio.run(bot.handle_event(event))

    assert status == "completed"
    key = replies.calls[0]["idempotency_key"]
    assert key.startswith("feishu-bot:")
    assert len(key) <= 50
    assert key != f"feishu-bot:{event.event_id}"


def test_admin_worker_query_uses_deterministic_renderer(tmp_path: Path) -> None:
    result = BotQueryResult(
        intent="worker_status",
        data={
            "items": [
                {
                    "owner": "宋峰峰",
                    "platform": "boss",
                    "status": "ready",
                    "agentReady": True,
                    "browserReady": True,
                    "agentBusy": False,
                    "browserBackend": "cloak",
                    "error": "",
                }
            ]
        },
    )
    bot, planner, queries, replies, _repository = _bot(
        tmp_path,
        actors={"ou-admin": _admin()},
        plan=BotQueryPlan(intent="worker_status"),
        result=result,
    )

    status = asyncio.run(
        bot.handle_event(
            _event(sender="ou-admin", content="看看 Worker 状态"),
        )
    )

    assert status == "completed"
    assert planner.calls[0]["available_job_types"] == ["AI产品经理", "运营B"]
    assert len(queries.calls) == 1
    assert replies.calls[0]["text"] == "Worker 状态\n宋峰峰｜boss｜就绪"


def test_help_result_uses_role_specific_deterministic_renderer(tmp_path: Path) -> None:
    bot, _planner, _queries, replies, _repository = _bot(
        tmp_path,
        actors={"ou-admin": _admin()},
        plan=BotQueryPlan(intent="help"),
        result=BotQueryResult(intent="help", data={}),
    )

    status = asyncio.run(
        bot.handle_event(_event(sender="ou-admin", content="帮助"))
    )

    assert status == "completed"
    assert "管理员还可查询 Worker 状态和最近异常" in replies.calls[0]["text"]
    assert "启动处理程序" in replies.calls[0]["text"]
    assert "暂停处理程序" in replies.calls[0]["text"]


def test_database_read_failure_returns_safe_message_and_is_audited(
    tmp_path: Path,
) -> None:
    class _BrokenQueries(_Queries):
        async def execute(
            self,
            actor: BotActor,
            plan: BotQueryPlan,
        ) -> BotQueryResult:
            del actor, plan
            raise sqlite3.OperationalError("database is locked")

    planner = _Planner(BotQueryPlan(intent="resume_counts"))
    queries = _BrokenQueries(BotQueryResult(intent="resume_counts", data={}))
    replies = _Replies()
    repository = FeishuBotRepository(tmp_path / "bot.sqlite")
    bot = FeishuRecruitmentBot(
        repository=repository,
        access_policy=_AccessPolicy({"ou-member": _member()}),
        planner=planner,
        queries=queries,
        replies=replies,
    )
    event = _event()

    status = asyncio.run(bot.handle_event(event))

    assert status == "failed"
    assert replies.calls[0]["text"] == "招聘数据暂不可用，请稍后再试。"
    stored = repository.get_event(event.event_id)
    assert stored["status"] == "failed"
    assert "database is locked" in stored["error"]


def test_reply_failure_is_audited_without_reprocessing(tmp_path: Path) -> None:
    replies = _Replies(
        failure=LarkCliError(
            "send failed",
            error_type="network",
            subtype="reply_failed",
        )
    )
    bot, planner, queries, _replies, repository = _bot(tmp_path, replies=replies)
    event = _event()

    status = asyncio.run(bot.handle_event(event))

    assert status == "reply_failed"
    assert len(planner.calls) == 1
    assert len(queries.calls) == 1
    stored = repository.get_event(event.event_id)
    assert stored["status"] == "reply_failed"
    assert "send failed" in stored["error"]
    assert repository.recent_turns(event.chat_id, event.sender_open_id) == []


def test_reply_failure_can_retry_the_same_event(tmp_path: Path) -> None:
    replies = _Replies(failure=RuntimeError("temporary reply failure"))
    bot, planner, queries, _replies, repository = _bot(tmp_path, replies=replies)
    event = _event()

    first = asyncio.run(bot.handle_event(event))
    replies.failure = None
    second = asyncio.run(bot.handle_event(event))

    assert first == "reply_failed"
    assert second == "completed"
    assert len(planner.calls) == 2
    assert len(queries.calls) == 2
    assert len(replies.calls) == 2
    assert repository.get_event(event.event_id)["status"] == "completed"


def test_serve_consumes_event_and_closes_source(tmp_path: Path) -> None:
    stop_event = asyncio.Event()

    class _Source:
        def __init__(self) -> None:
            self.closed = False

        async def events(self):
            yield _event()
            await stop_event.wait()

        async def close(self) -> None:
            self.closed = True

    source = _Source()
    replies = _Replies()
    original_reply = replies.reply

    async def reply_and_stop(
        message_id: str,
        text: str,
        *,
        idempotency_key: str,
    ) -> str:
        response = await original_reply(
            message_id,
            text,
            idempotency_key=idempotency_key,
        )
        stop_event.set()
        return response

    replies.reply = reply_and_stop  # type: ignore[method-assign]
    bot, _planner, _queries, _replies, _repository = _bot(
        tmp_path,
        replies=replies,
        event_source_factory=lambda: source,
    )

    asyncio.run(bot.serve(stop_event))

    assert len(replies.calls) == 1
    assert source.closed is True


def test_serve_stop_event_closes_idle_source_without_waiting_for_message(
    tmp_path: Path,
) -> None:
    stop_event = asyncio.Event()
    source_started = asyncio.Event()
    source_released = asyncio.Event()

    class _IdleSource:
        def __init__(self) -> None:
            self.closed = False

        async def events(self):
            source_started.set()
            await source_released.wait()
            if False:
                yield _event()

        async def close(self) -> None:
            self.closed = True
            source_released.set()

    source = _IdleSource()
    bot, _planner, _queries, _replies, _repository = _bot(
        tmp_path,
        event_source_factory=lambda: source,
    )

    async def scenario() -> None:
        serve_task = asyncio.create_task(bot.serve(stop_event))
        await asyncio.wait_for(source_started.wait(), timeout=1)
        stop_event.set()
        await asyncio.wait_for(serve_task, timeout=1)

    asyncio.run(scenario())

    assert source.closed is True


def test_serve_stops_immediately_for_missing_scope_startup_failure(
    tmp_path: Path,
) -> None:
    stop_event = asyncio.Event()
    sources: list[object] = []

    class _MissingScopeSource:
        def __init__(self) -> None:
            self.closed = False

        async def events(self):
            raise LarkCliError(
                "missing required scope",
                error_type="permission",
                subtype="missing_scope",
            )
            if False:
                yield _event()

        async def close(self) -> None:
            self.closed = True

    def source_factory() -> _MissingScopeSource:
        source = _MissingScopeSource()
        sources.append(source)
        return source

    bot, _planner, _queries, _replies, _repository = _bot(
        tmp_path,
        event_source_factory=source_factory,
    )

    async def scenario() -> None:
        with pytest.raises(LarkCliError, match="missing required scope"):
            await asyncio.wait_for(bot.serve(stop_event), timeout=0.25)

    asyncio.run(scenario())

    assert len(sources) == 1
    assert sources[0].closed is True
