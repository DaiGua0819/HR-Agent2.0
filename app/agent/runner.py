"""平台无关的单轮招聘对话执行器。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.agent.judgement import judge_candidate_reply
from app.agent.policy import (
    prephrase_candidates,
    prephrase_text,
    should_use_company_info,
)
from app.agent.rules import (
    find_knowledge_answer,
    initial_common_phrase,
    is_ai_basic_rule,
    is_direct_resume_rule,
    load_chat_rules,
    looks_like_question,
    rule_screening,
    select_position_rule,
)
from app.agent.screening import (
    analyze_position_screening,
    select_position_screening_question_text,
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
        state["rule_source"] = rule.get("ruleSource", "")

        last = _last_non_system(conversation)
        if not last or last.sender != MessageSender.CANDIDATE:
            return self._finish(state, "wait", "last_message_not_candidate")

        if self._needs_initial_ai_basic_phrase(conversation, rule):
            return await self._send_initial_ai_basic_phrase(state, conversation, rule)

        answer = self._knowledge_answer(last.text, conversation)
        if answer:
            screening = rule_screening(rule)
            if is_direct_resume_rule(rule):
                await self._send_knowledge_answer(state, answer)
                return await self._handle_direct_resume(
                    state,
                    conversation,
                    rule,
                    knowledge_answer=answer,
                )
            if screening:
                analysis = await analyze_position_screening(
                    conversation.messages,
                    screening,
                    llm=self.llm,
                )
                if analysis.get("status") == "accept":
                    await self._send_knowledge_answer(state, answer)
                    return await self._handle_screening(
                        state,
                        conversation,
                        rule,
                        analysis=analysis,
                        knowledge_answer=answer,
                    )
            await self._send_knowledge_answer(state, answer)
            return self._finish(state, "answer_question", "knowledge_hit", reply=answer)

        if is_direct_resume_rule(rule):
            return await self._handle_direct_resume(state, conversation, rule)
        if looks_like_question(last.text):
            state["pending_question"] = last.text
            return self._finish(state, "escalate", "unknown_question", evidence=last.text)

        if is_ai_basic_rule(conversation.candidate.applied_position, rule):
            return await self._handle_ai_basic(state, conversation, rule, last.text)
        return await self._handle_screening(state, conversation, rule, last.text)

    async def _handle_direct_resume(
        self,
        state: GraphState,
        conversation: Conversation,
        rule: dict[str, Any],
        *,
        knowledge_answer: str = "",
    ) -> GraphState:
        request_state = await self.adapter.inspect_resume_request_state()
        position = conversation.candidate.applied_position
        if request_state.has_resume_attachment:
            return self._finish(
                state,
                "wait",
                "resume_attachment_received",
                knowledgeAnswer=knowledge_answer,
                result={"skipped": True, "reason": "resume_attachment_received"},
            )
        if request_state.already_requested:
            return self._finish(
                state,
                "wait",
                "resume_already_requested",
                knowledgeAnswer=knowledge_answer,
                result={"skipped": True, "reason": "already_requested"},
            )
        if request_state.pending_resume_consent:
            result = await self.adapter.request_resume()
            state["resume_requested"] = bool(
                result.get("requested") or result.get("resumeReceived")
            )
            return self._finish(
                state,
                "request_resume",
                "resume_consent_requested",
                knowledgeAnswer=knowledge_answer,
                result=result,
            )
        candidates = prephrase_candidates(conversation.platform, position, rule)
        if candidates and not any(_message_sent(conversation, item) for item in candidates):
            prompt = prephrase_text(conversation.platform, position, rule)
            if prompt:
                await self.adapter.send_message(prompt)
                _append_sent(state, prompt)
        result = await self.adapter.request_resume()
        state["resume_requested"] = bool(result.get("requested") or result.get("resumeReceived"))
        return self._finish(
            state,
            "request_resume",
            "direct_resume",
            knowledgeAnswer=knowledge_answer,
            result=result,
        )

    async def _handle_ai_basic(
        self,
        state: GraphState,
        conversation: Conversation,
        rule: dict[str, Any],
        reply_text: str,
    ) -> GraphState:
        phrase = initial_common_phrase(rule)
        if phrase and not _message_sent(conversation, phrase):
            return await self._send_initial_ai_basic_phrase(state, conversation, rule)
        request_state = await self.adapter.inspect_resume_request_state()
        if request_state.has_resume_attachment:
            return self._finish(
                state,
                "wait",
                "resume_attachment_received",
                result={"skipped": True, "reason": "resume_attachment_received"},
            )
        if request_state.already_requested:
            return self._finish(
                state,
                "wait",
                "resume_already_requested",
                result={"skipped": True, "reason": "already_requested"},
            )
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

    async def _send_initial_ai_basic_phrase(
        self,
        state: GraphState,
        conversation: Conversation,
        rule: dict[str, Any],
    ) -> GraphState:
        """AI 应用开发岗位首轮固定先发基础条件，再处理候选人问题。"""

        phrase = initial_common_phrase(rule)
        if not phrase:
            return self._finish(state, "wait", "basic_phrase_missing")
        position = conversation.candidate.applied_position
        if should_use_company_info(conversation.platform, position, rule):
            await self.adapter.send_company_info(phrase=phrase, phrase_key="basic_conditions")
        else:
            await self.adapter.send_message(phrase)
        _append_sent(state, phrase)
        return self._finish(state, "ask_basic_conditions", "basic_phrase_sent", reply=phrase)

    async def _handle_screening(
        self,
        state: GraphState,
        conversation: Conversation,
        rule: dict[str, Any],
        reply_text: str = "",
        *,
        analysis: dict[str, Any] | None = None,
        knowledge_answer: str = "",
    ) -> GraphState:
        screening = rule_screening(rule)
        if not screening:
            return self._finish(state, "wait", "no_screening_questions")
        analysis = analysis or await analyze_position_screening(
            conversation.messages,
            screening,
            llm=self.llm,
        )
        state["screening_analysis"] = analysis
        status = str(analysis.get("status") or "")
        if status == "not_configured":
            return self._finish(state, "wait", "no_screening_questions", screening=analysis)
        if status == "not_asked":
            question = (
                analysis.get("nextQuestion")
                if isinstance(analysis.get("nextQuestion"), dict)
                else {}
            )
            next_question = select_position_screening_question_text(question)
            if not next_question:
                return self._finish(state, "wait", "no_screening_question_text", screening=analysis)
            await self.adapter.send_message(next_question)
            _append_sent(state, next_question)
            return self._finish(
                state,
                "ask_screening",
                "screening_question_sent",
                reply=next_question,
                screening=analysis,
            )
        if status == "accept":
            result = await self.adapter.request_resume()
            state["resume_requested"] = bool(
                result.get("requested") or result.get("resumeReceived")
            )
            return self._finish(
                state,
                "request_resume",
                "screening_accept",
                knowledgeAnswer=knowledge_answer,
                screening=analysis,
                result=result,
            )
        if status == "reject":
            return self._finish(
                state,
                "skip",
                "screening_reject",
                screening=analysis,
            )
        if not analysis.get("latestAnswerText") and reply_text:
            judgement = await judge_candidate_reply(reply_text, llm=self.llm)
            analysis = {**analysis, "fallbackJudgement": asdict(judgement)}
        return self._finish(
            state,
            "wait",
            f"screening_{status or 'waiting'}",
            screening=analysis,
        )

    def _knowledge_answer(self, text: str, conversation: Conversation) -> str | None:
        return find_knowledge_answer(
            text,
            self.rules,
            position=conversation.candidate.applied_position,
        )

    @staticmethod
    def _needs_initial_ai_basic_phrase(
        conversation: Conversation,
        rule: dict[str, Any],
    ) -> bool:
        phrase = initial_common_phrase(rule)
        return bool(
            phrase
            and is_ai_basic_rule(conversation.candidate.applied_position, rule)
            and not _message_sent(conversation, phrase)
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
                "ruleSource": state.get("rule_source", ""),
                **extra,
            }
        )
        return state

    async def _send_knowledge_answer(self, state: GraphState, answer: str) -> None:
        await self.adapter.send_message(answer)
        _append_sent(state, answer)


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


def _append_sent(state: GraphState, message: str) -> None:
    sent = state.get("sent_messages")
    if not isinstance(sent, list):
        sent = []
    sent.append(message)
    state["sent_messages"] = sent


ZhilianConversationRunner = ConversationRunner
