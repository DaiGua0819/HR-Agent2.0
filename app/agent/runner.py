"""平台无关的单轮招聘对话执行器。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.agent.judgement import judge_candidate_reply
from app.agent.policy import prephrase_text, should_send_prephrase, should_use_company_info
from app.agent.rules import (
    find_knowledge_answer,
    initial_common_phrase,
    is_ai_basic_rule,
    is_direct_resume_rule,
    load_chat_rules,
    looks_like_question,
    screening_questions,
    select_position_rule,
)
from app.agent.state import GraphState
from app.evaluation.decision_log import GLOBAL_DECISION_SINK, InMemoryDecisionSink
from app.platforms.base import PlatformAdapter
from app.platforms.types import Conversation, MessageSender


async def run_once(state: GraphState) -> GraphState:
    """给定账号与会话上下文，运行 LangGraph 一轮。"""

    state["stage"] = state.get("stage") or "runner_passthrough"
    return state


class ConversationRunner:
    """用注入的任意平台 adapter 跑单个会话的一轮处理。"""

    def __init__(
        self,
        adapter: PlatformAdapter,
        *,
        rules: dict[str, Any] | None = None,
        llm: Any | None = None,
        decision_sink: InMemoryDecisionSink | None = None,
    ) -> None:
        self.adapter = adapter
        self.rules = rules or load_chat_rules()
        self.llm = llm
        self.decision_sink = decision_sink or GLOBAL_DECISION_SINK

    async def run_current(self) -> GraphState:
        """读取当前会话并推进一轮。"""

        conversation = await self.adapter.read_chat_context()
        state = self._state_from_conversation(conversation)
        return await self._process(state, conversation)

    async def _process(self, state: GraphState, conversation: Conversation) -> GraphState:
        rule = select_position_rule(conversation.candidate.applied_position, self.rules)
        state["rules"] = self.rules
        if not rule:
            return self._finish(state, "skip", "unconfigured_position")
        state["position_rule"] = rule

        last = _last_non_system(conversation)
        if not last or last.sender != MessageSender.CANDIDATE:
            return self._finish(state, "wait", "last_message_not_candidate")

        answer = self._knowledge_answer(last.text, conversation)
        if answer:
            await self.adapter.send_message(answer)
            state["sent_messages"] = [answer]
            return self._finish(state, "answer_question", "knowledge_hit", reply=answer)
        if looks_like_question(last.text):
            state["pending_question"] = last.text
            return self._finish(state, "escalate", "unknown_question", evidence=last.text)

        if is_direct_resume_rule(rule):
            return await self._handle_direct_resume(state, conversation, rule)
        if is_ai_basic_rule(conversation.candidate.applied_position, rule):
            return await self._handle_ai_basic(state, conversation, rule, last.text)
        return await self._handle_screening(state, conversation, rule, last.text)

    async def _handle_direct_resume(
        self,
        state: GraphState,
        conversation: Conversation,
        rule: dict[str, Any],
    ) -> GraphState:
        request_state = await self.adapter.inspect_resume_request_state()
        position = conversation.candidate.applied_position
        if (
            not request_state.has_resume_attachment
            and not request_state.already_requested
            and should_send_prephrase(conversation.platform, position, rule)
        ):
            prompt = prephrase_text(conversation.platform, position, rule)
            if prompt and not _message_sent(conversation, prompt):
                await self.adapter.send_message(prompt)
                state["sent_messages"] = [prompt]
        result = await self.adapter.request_resume()
        state["resume_requested"] = bool(result.get("requested") or result.get("resumeReceived"))
        return self._finish(state, "request_resume", "direct_resume", result=result)

    async def _handle_ai_basic(
        self,
        state: GraphState,
        conversation: Conversation,
        rule: dict[str, Any],
        reply_text: str,
    ) -> GraphState:
        phrase = initial_common_phrase(rule)
        if phrase and not _message_sent(conversation, phrase):
            position = conversation.candidate.applied_position
            if should_use_company_info(conversation.platform, position, rule):
                await self.adapter.send_company_info(phrase=phrase, phrase_key="basic_conditions")
            else:
                await self.adapter.send_message(phrase)
            state["sent_messages"] = [phrase]
            return self._finish(state, "ask_basic_conditions", "basic_phrase_sent", reply=phrase)
        judgement = await judge_candidate_reply(reply_text, question=phrase, llm=self.llm)
        if judgement.status == "accept":
            result = await self.adapter.request_resume()
            state["resume_requested"] = bool(
                result.get("requested") or result.get("resumeReceived")
            )
            return self._finish(
                state,
                "request_resume",
                "basic_accept",
                judgement=asdict(judgement),
                result=result,
            )
        return self._finish(state, "wait", f"basic_{judgement.status}", judgement=asdict(judgement))

    async def _handle_screening(
        self,
        state: GraphState,
        conversation: Conversation,
        rule: dict[str, Any],
        reply_text: str,
    ) -> GraphState:
        questions = screening_questions(rule)
        if not questions:
            return self._finish(state, "wait", "no_screening_questions")
        next_question = next(
            (item for item in questions if not _message_sent(conversation, item)), ""
        )
        if next_question:
            await self.adapter.send_message(next_question)
            state["sent_messages"] = [next_question]
            return self._finish(
                state, "ask_screening", "screening_question_sent", reply=next_question
            )
        judgement = await judge_candidate_reply(reply_text, question=questions[-1], llm=self.llm)
        if judgement.status == "accept":
            result = await self.adapter.request_resume()
            state["resume_requested"] = bool(
                result.get("requested") or result.get("resumeReceived")
            )
            return self._finish(
                state,
                "request_resume",
                "screening_accept",
                judgement=asdict(judgement),
                result=result,
            )
        if judgement.status == "reject":
            return self._finish(state, "skip", "screening_reject", judgement=asdict(judgement))
        return self._finish(
            state, "wait", f"screening_{judgement.status}", judgement=asdict(judgement)
        )

    def _knowledge_answer(self, text: str, conversation: Conversation) -> str | None:
        return find_knowledge_answer(
            text,
            self.rules,
            position=conversation.candidate.applied_position,
        )

    def _state_from_conversation(self, conversation: Conversation) -> GraphState:
        return {
            "owner": conversation.owner,
            "platform": conversation.platform.value,
            "conversation_id": conversation.id,
            "applied_position": conversation.candidate.applied_position,
            "candidate": {
                "name": conversation.candidate.name,
                "applied_position": conversation.candidate.applied_position,
                "label": conversation.candidate.label,
            },
            "messages": [
                {"sender": message.sender.value, "text": message.text, "raw_text": message.raw_text}
                for message in conversation.messages
            ],
        }

    def _finish(self, state: GraphState, action: str, reason: str, **extra: Any) -> GraphState:
        state["next_action"] = action
        state["stage"] = reason
        state["decision"] = {"action": action, "reason": reason, **extra}
        self.decision_sink.record(
            {
                "candidate": state.get("candidate"),
                "job": state.get("applied_position"),
                "action": action,
                "reason": reason,
                **extra,
            }
        )
        return state


def _last_non_system(conversation: Conversation):
    for message in reversed(conversation.messages):
        if message.sender != MessageSender.SYSTEM and message.text.strip():
            return message
    return None


def _message_sent(conversation: Conversation, text: str) -> bool:
    needle = "".join(text.split())
    return any(
        message.sender == MessageSender.ME and needle and needle in "".join(message.text.split())
        for message in conversation.messages
    )


ZhilianConversationRunner = ConversationRunner
