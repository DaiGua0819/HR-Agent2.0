"""Orchestration service for the standalone Feishu recruitment bot."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from hashlib import sha256
from typing import Any, Protocol

from app.features.feishu_bot.codex_planner import CodexPolicyViolation
from app.features.feishu_bot.lark_cli import LarkCliError
from app.features.feishu_bot.models import BotActor, BotEvent, BotQueryPlan, BotQueryResult
from app.features.feishu_bot.render import (
    DATA_UNAVAILABLE_TEXT,
    GROUP_HELP_TEXT,
    PERMISSION_DENIED_TEXT,
    POLICY_VIOLATION_TEXT,
    UNAUTHORIZED_TEXT,
    render_help,
    render_query_result,
)
from app.features.feishu_bot.runtime_control import (
    RuntimeControlRequest,
    parse_runtime_control_command,
)


class _Repository(Protocol):
    def claim_event(self, event: BotEvent) -> bool: ...

    def mark_processing(self, event_id: str) -> None: ...

    def mark_completed(self, event_id: str, *, response_message_id: str = "") -> None: ...

    def mark_failed(self, event_id: str, error: str, *, status: str = "failed") -> None: ...

    def append_turn(
        self,
        *,
        event_id: str,
        chat_id: str,
        sender_open_id: str,
        actor_name: str,
        intent: str,
        question: str,
        response: str,
    ) -> None: ...

    def recent_turns(
        self,
        chat_id: str,
        sender_open_id: str,
        *,
        limit: int = 6,
    ) -> list[dict[str, object]]: ...


class _AccessPolicy(Protocol):
    def resolve(self, open_id: str) -> BotActor | None: ...


class _Planner(Protocol):
    async def plan(
        self,
        actor: BotActor,
        question: str,
        *,
        context: list[dict[str, object]],
        available_job_types: list[str],
    ) -> BotQueryPlan: ...


class _Queries(Protocol):
    def available_job_types(self, actor: BotActor) -> list[str]: ...

    async def execute(self, actor: BotActor, plan: BotQueryPlan) -> BotQueryResult: ...


class _Replies(Protocol):
    async def reply(
        self,
        message_id: str,
        text: str,
        *,
        idempotency_key: str,
    ) -> str: ...


class _EventSource(Protocol):
    def events(self) -> Any: ...

    async def close(self) -> None: ...


class _RuntimeController(Protocol):
    async def execute(
        self,
        action: str,
        request: RuntimeControlRequest,
    ) -> dict[str, object]: ...


EventSourceFactory = Callable[[], _EventSource]


class FeishuRecruitmentBot:
    """Permission-gated queries plus fixed runtime controls outside Codex."""

    def __init__(
        self,
        *,
        repository: _Repository,
        access_policy: _AccessPolicy,
        planner: _Planner,
        queries: _Queries,
        replies: _Replies,
        runtime_controller: _RuntimeController | None = None,
        event_source_factory: EventSourceFactory | None = None,
        initial_reconnect_seconds: float = 1.0,
        max_reconnect_seconds: float = 30.0,
    ) -> None:
        self.repository = repository
        self.access_policy = access_policy
        self.planner = planner
        self.queries = queries
        self.replies = replies
        self.runtime_controller = runtime_controller
        self.event_source_factory = event_source_factory
        self.initial_reconnect_seconds = max(0.1, float(initial_reconnect_seconds))
        self.max_reconnect_seconds = max(
            self.initial_reconnect_seconds,
            float(max_reconnect_seconds),
        )
        self._active_source: _EventSource | None = None

    async def handle_event(self, event: BotEvent) -> str:
        event.validate_required()
        if not self.repository.claim_event(event):
            return "duplicate"
        self.repository.mark_processing(event.event_id)

        if event.chat_type != "p2p":
            return await self._reply_without_turn(event, GROUP_HELP_TEXT)

        actor = self.access_policy.resolve(event.sender_open_id)
        if actor is None:
            return await self._reply_denied(
                event,
                UNAUTHORIZED_TEXT,
                reason="unauthorized_open_id",
            )

        if event.message_type != "text" or not event.content.strip():
            return await self._reply_and_audit(
                event,
                actor,
                intent="help",
                response=render_help(actor),
            )

        control_action = parse_runtime_control_command(event.content)
        if control_action is not None:
            if not actor.can("control:runtime"):
                return await self._reply_denied(
                    event,
                    "当前账号无权启动或暂停招聘处理程序。",
                    reason="feishu_bot_permission_denied:control:runtime",
                )
            if self.runtime_controller is None:
                return await self._reply_failure_notice(
                    event,
                    DATA_UNAVAILABLE_TEXT,
                    error="runtime_controller_unavailable",
                    status="failed",
                )
            try:
                control_result = await self.runtime_controller.execute(
                    control_action,
                    RuntimeControlRequest(
                        event_id=event.event_id,
                        message_id=event.message_id,
                        actor_open_id=actor.open_id,
                        actor_name=actor.display_name,
                    ),
                )
            except (OSError, RuntimeError, ValueError) as exc:
                return await self._reply_failure_notice(
                    event,
                    DATA_UNAVAILABLE_TEXT,
                    error=str(exc),
                    status="failed",
                )
            return await self._reply_and_audit(
                event,
                actor,
                intent=f"runtime_{control_action}",
                response=str(control_result.get("message") or "运行控制请求已受理。"),
            )

        try:
            context = _planner_context(
                self.repository.recent_turns(
                    event.chat_id,
                    event.sender_open_id,
                    limit=6,
                )
            )
            available_jobs = self.queries.available_job_types(actor)
            plan = await self.planner.plan(
                actor,
                event.content,
                context=context,
                available_job_types=available_jobs,
            )
            result = await self.queries.execute(actor, plan)
            response = render_query_result(actor, result)
        except PermissionError as exc:
            return await self._reply_denied(
                event,
                PERMISSION_DENIED_TEXT,
                reason=str(exc),
            )
        except CodexPolicyViolation as exc:
            return await self._reply_failure_notice(
                event,
                POLICY_VIOLATION_TEXT,
                error=str(exc),
                status="policy_violation",
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            return await self._reply_failure_notice(
                event,
                DATA_UNAVAILABLE_TEXT,
                error=str(exc),
                status="failed",
            )

        return await self._reply_and_audit(
            event,
            actor,
            intent=result.intent,
            response=response,
        )

    async def serve(self, stop_event: asyncio.Event) -> None:
        if self.event_source_factory is None:
            raise RuntimeError("feishu_bot_event_source_factory_required")
        reconnect_seconds = self.initial_reconnect_seconds
        while not stop_event.is_set():
            source = self.event_source_factory()
            self._active_source = source
            connection_failed = False
            try:
                stopped = await self._consume_source(source, stop_event)
                if stopped:
                    return
                reconnect_seconds = self.initial_reconnect_seconds
            except LarkCliError as exc:
                if _fatal_connection_error(exc):
                    raise
                connection_failed = True
            finally:
                await source.close()
                self._active_source = None
            if stop_event.is_set():
                return
            if not connection_failed:
                connection_failed = True
            if connection_failed:
                stopped = await _wait_for_stop(stop_event, reconnect_seconds)
                if stopped:
                    return
                reconnect_seconds = min(
                    reconnect_seconds * 2,
                    self.max_reconnect_seconds,
                )

    async def _consume_source(
        self,
        source: _EventSource,
        stop_event: asyncio.Event,
    ) -> bool:
        iterator = source.events().__aiter__()
        try:
            while not stop_event.is_set():
                next_event = asyncio.create_task(anext(iterator))
                wait_for_stop = asyncio.create_task(stop_event.wait())
                done, _pending = await asyncio.wait(
                    {next_event, wait_for_stop},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if wait_for_stop in done:
                    await source.close()
                    next_event.cancel()
                    await _ignore_cancelled(next_event)
                    return True
                wait_for_stop.cancel()
                await _ignore_cancelled(wait_for_stop)
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    return False
                await self.handle_event(event)
            return True
        finally:
            close_iterator = getattr(iterator, "aclose", None)
            if close_iterator is not None:
                await close_iterator()

    async def close(self) -> None:
        source = self._active_source
        if source is not None:
            await source.close()

    async def _reply_without_turn(self, event: BotEvent, response: str) -> str:
        try:
            response_message_id = await self._reply(event, response)
        except Exception as exc:
            self.repository.mark_failed(
                event.event_id,
                str(exc),
                status="reply_failed",
            )
            return "reply_failed"
        self.repository.mark_completed(
            event.event_id,
            response_message_id=response_message_id,
        )
        return "completed"

    async def _reply_denied(
        self,
        event: BotEvent,
        response: str,
        *,
        reason: str,
    ) -> str:
        try:
            await self._reply(event, response)
        except Exception as exc:
            self.repository.mark_failed(
                event.event_id,
                f"{reason}; reply_error={exc}",
                status="reply_failed",
            )
            return "reply_failed"
        self.repository.mark_failed(event.event_id, reason, status="denied")
        return "denied"

    async def _reply_failure_notice(
        self,
        event: BotEvent,
        response: str,
        *,
        error: str,
        status: str,
    ) -> str:
        try:
            await self._reply(event, response)
        except Exception as reply_error:
            self.repository.mark_failed(
                event.event_id,
                f"{error}; reply_error={reply_error}",
                status="reply_failed",
            )
            return "reply_failed"
        self.repository.mark_failed(event.event_id, error, status=status)
        return status

    async def _reply_and_audit(
        self,
        event: BotEvent,
        actor: BotActor,
        *,
        intent: str,
        response: str,
    ) -> str:
        try:
            response_message_id = await self._reply(event, response)
        except Exception as exc:
            self.repository.mark_failed(
                event.event_id,
                str(exc),
                status="reply_failed",
            )
            return "reply_failed"
        self.repository.append_turn(
            event_id=event.event_id,
            chat_id=event.chat_id,
            sender_open_id=event.sender_open_id,
            actor_name=actor.display_name,
            intent=intent,
            question=event.content,
            response=response,
        )
        self.repository.mark_completed(
            event.event_id,
            response_message_id=response_message_id,
        )
        return "completed"

    async def _reply(self, event: BotEvent, response: str) -> str:
        return await self.replies.reply(
            event.message_id,
            response,
            idempotency_key=_reply_idempotency_key(event.event_id),
        )


def _fatal_connection_error(error: LarkCliError) -> bool:
    return error.error_type in {
        "auth",
        "authentication",
        "permission",
        "validation",
        "conflict",
        "already_connected",
    } or error.subtype in {
        "missing_scope",
        "already_connected",
        "connection_exists",
        "event_bus_already_connected",
        "subscription_already_exists",
    }


def _reply_idempotency_key(event_id: str) -> str:
    prefix = "feishu-bot:"
    key = f"{prefix}{event_id}"
    if len(key) <= 50:
        return key
    digest = sha256(event_id.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}{digest}"


def _planner_context(turns: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "intent": str(turn.get("intent") or ""),
            "question": str(turn.get("question") or ""),
        }
        for turn in turns
    ]


async def _wait_for_stop(stop_event: asyncio.Event, timeout: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=max(0.1, timeout))
    except TimeoutError:
        return False
    return True


async def _ignore_cancelled(task: asyncio.Task[Any]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass
