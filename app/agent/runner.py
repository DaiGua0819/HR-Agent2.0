"""平台无关的单轮招聘对话执行器。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.agent.judgement import judge_candidate_reply
from app.agent.message_utils import append_sent, last_non_system, message_sent
from app.agent.persistence import ConversationPersistence
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
    is_operation_direct_resume_rule,
    is_silent_question,
    load_chat_rules,
    looks_like_question,
    rule_screening,
    select_position_rule,
    should_prioritize_screening,
)
from app.agent.screening import (
    analyze_position_screening,
    normalize_position_screening_questions,
    position_screening_question_matches_any,
    select_position_screening_question_text,
)
from app.agent.state import GraphState
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.artifacts import ResumeArtifactStore
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
        conversation_repository: ConversationRepository | None = None,
        artifact_store: ResumeArtifactStore | None = None,
    ) -> None:
        self.adapter = adapter
        self.rules = rules or load_chat_rules()
        self.llm = llm
        self.decision_sink = decision_sink or GLOBAL_DECISION_SINK
        self.persistence = ConversationPersistence(
            repository=conversation_repository,
            artifact_store=artifact_store,
            adapter=adapter,
        )

    async def run_current(self) -> GraphState:
        """读取当前会话并推进一轮。"""

        conversation = await self.adapter.read_chat_context()
        state = self._state_from_conversation(conversation)
        self.persistence.attach(state, conversation)
        return await self._process(state, conversation)

    async def _process(self, state: GraphState, conversation: Conversation) -> GraphState:
        if conversation.messages and not conversation.should_reply:
            return self._finish(state, "wait", "last_message_not_candidate")

        rule = select_position_rule(conversation.candidate.applied_position, self.rules)
        state["rules"] = self.rules
        if not rule:
            return self._finish(state, "skip", "unconfigured_position")
        state["position_rule"] = rule
        state["rule_source"] = rule.get("ruleSource", "")

        last = last_non_system(conversation)
        if not last or last.sender != MessageSender.CANDIDATE:
            return self._finish(state, "wait", "last_message_not_candidate")
        if _candidate_rejected_conversation(last.text):
            return self._finish(
                state,
                "skip",
                "candidate_rejected",
                evidence=last.text,
            )
        if self._needs_initial_ai_basic_phrase(conversation, rule):
            return await self._send_initial_ai_basic_phrase(state, conversation, rule)

        if is_direct_resume_rule(rule) and is_operation_direct_resume_rule(rule):
            return await self._handle_direct_resume(state, conversation, rule)

        if is_silent_question(
            last.text,
            self.rules,
            position=conversation.candidate.applied_position,
        ):
            return self._finish(
                state,
                "wait",
                "silent_question",
                evidence=last.text,
            )

        if is_direct_resume_rule(rule):
            return await self._handle_direct_resume(state, conversation, rule)

        if rule_screening(rule) and should_prioritize_screening(last.text, rule):
            return await self._handle_screening(state, conversation, rule, last.text)
        if self._should_handle_screening_before_knowledge(conversation, rule, last.text):
            return await self._handle_screening(state, conversation, rule, last.text)

        answer = self._knowledge_answer(last.text, conversation)
        if answer:
            screening = rule_screening(rule)
            if is_ai_basic_rule(conversation.candidate.applied_position, rule):
                phrase = initial_common_phrase(rule)
                judgement = await judge_candidate_reply(last.text, question=phrase, llm=self.llm)
                if judgement.status == "accept":
                    failed = await self._send_or_fail(
                        state,
                        answer,
                        action="answer_question",
                        failure_reason="knowledge_answer_send_failed",
                    )
                    if failed:
                        return failed
                    return await self._request_resume_after_basic_accept(
                        state,
                        knowledge_answer=answer,
                        judgement=asdict(judgement),
                    )
            if screening:
                analysis = await analyze_position_screening(
                    conversation.messages,
                    screening,
                    llm=self.llm,
                )
                if analysis.get("status") in {"not_asked", "accept"}:
                    failed = await self._send_or_fail(
                        state,
                        answer,
                        action="answer_question",
                        failure_reason="knowledge_answer_send_failed",
                    )
                    if failed:
                        return failed
                    return await self._handle_screening(
                        state,
                        conversation,
                        rule,
                        analysis=analysis,
                        knowledge_answer=answer,
                    )
            failed = await self._send_or_fail(
                state,
                answer,
                action="answer_question",
                failure_reason="knowledge_answer_send_failed",
            )
            if failed:
                return failed
            return self._finish(state, "answer_question", "knowledge_hit", reply=answer)

        if looks_like_question(last.text):
            if rule_screening(rule):
                return await self._handle_screening(state, conversation, rule, last.text)
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
        handled, request_state = await self._preflight_resume_request(
            state,
            knowledgeAnswer=knowledge_answer,
        )
        if handled:
            return handled
        position = conversation.candidate.applied_position
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
        if candidates and not any(message_sent(conversation, item) for item in candidates):
            prompt = prephrase_text(conversation.platform, position, rule)
            if prompt:
                failed = await self._send_or_fail(
                    state,
                    prompt,
                    action="request_resume",
                    failure_reason="direct_resume_prompt_send_failed",
                )
                if failed:
                    return failed
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
        if phrase and not message_sent(conversation, phrase):
            return await self._send_initial_ai_basic_phrase(state, conversation, rule)
        handled, _ = await self._preflight_resume_request(state)
        if handled:
            return handled
        judgement = await judge_candidate_reply(reply_text, question=phrase, llm=self.llm)
        if judgement.status == "accept":
            return await self._request_resume_after_basic_accept(
                state,
                judgement=asdict(judgement),
            )
        return self._finish(state, "wait", f"basic_{judgement.status}", judgement=asdict(judgement))

    async def _request_resume_after_basic_accept(
        self,
        state: GraphState,
        *,
        knowledge_answer: str = "",
        judgement: dict[str, Any] | None = None,
    ) -> GraphState:
        """AI 基础条件明确接受后，处理已有简历状态或继续求简历。"""

        judgement = judgement if isinstance(judgement, dict) else {}
        handled, _ = await self._preflight_resume_request(
            state,
            knowledgeAnswer=knowledge_answer,
            judgement=judgement,
        )
        if handled:
            return handled
        result = await self.adapter.request_resume()
        state["resume_requested"] = bool(result.get("requested") or result.get("resumeReceived"))
        return self._finish(
            state,
            "request_resume",
            "basic_accept",
            knowledgeAnswer=knowledge_answer,
            judgement=judgement,
            result=result,
        )

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
            result = await self.adapter.send_company_info(
                phrase=phrase,
                phrase_key="basic_conditions",
            )
        else:
            result = await self.adapter.send_message(phrase)
        if not self._send_result_ok(result):
            return self._finish(
                state,
                "send_failed",
                "basic_phrase_send_failed",
                reply=phrase,
                sendResult=asdict(result),
            )
        append_sent(state, phrase)
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
            failed = await self._send_or_fail(
                state,
                next_question,
                action="ask_screening",
                failure_reason="screening_question_send_failed",
            )
            if failed:
                return failed
            return self._finish(
                state,
                "ask_screening",
                "screening_question_sent",
                reply=next_question,
                screening=analysis,
            )
        if status == "accept":
            handled, _ = await self._preflight_resume_request(
                state,
                knowledgeAnswer=knowledge_answer,
                screening=analysis,
            )
            if handled:
                return handled
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

    async def _preflight_resume_request(
        self,
        state: GraphState,
        **extra: Any,
    ) -> tuple[GraphState | None, Any]:
        """Handle persisted and page-observed resume states before requesting."""

        if self.persistence.has_resume_downloaded():
            return (
                self._finish(
                    state,
                    "wait",
                    "resume_already_downloaded",
                    **extra,
                    result={"skipped": True, "reason": "persisted_resume_downloaded"},
                ),
                None,
            )
        request_state = await self.adapter.inspect_resume_request_state()
        if request_state.has_resume_attachment:
            result = await self.adapter.request_resume()
            if result.get("downloaded") and result.get("filePath"):
                return (
                    self._finish(
                        state,
                        "request_resume",
                        "resume_attachment_downloaded",
                        **extra,
                        result=result,
                    ),
                    request_state,
                )
            reason = (
                "resume_attachment_download_blocked"
                if result.get("blocked")
                else "resume_attachment_received"
            )
            return (
                self._finish(
                    state,
                    "wait",
                    reason,
                    **extra,
                    result=result or {"skipped": True, "reason": "resume_attachment_received"},
                ),
                request_state,
            )
        if request_state.pending_resume_consent:
            result = await self.adapter.request_resume()
            reason = (
                "resume_attachment_downloaded"
                if result.get("downloaded") and result.get("filePath")
                else "resume_consent_requested"
            )
            return (
                self._finish(
                    state,
                    "request_resume",
                    reason,
                    **extra,
                    result=result,
                ),
                request_state,
            )
        if self.persistence.has_resume_request_pending() or request_state.already_requested:
            return (
                self._finish(
                    state,
                    "wait",
                    "resume_already_requested",
                    **extra,
                    result={"skipped": True, "reason": "already_requested"},
                ),
                request_state,
            )
        return None, request_state

    async def _send_or_fail(
        self,
        state: GraphState,
        text: str,
        *,
        action: str,
        failure_reason: str,
    ) -> GraphState | None:
        result = await self.adapter.send_message(text)
        if self._send_result_ok(result):
            append_sent(state, text)
            return None
        return self._finish(
            state,
            "send_failed",
            failure_reason,
            attemptedAction=action,
            reply=text,
            sendResult=asdict(result),
        )

    def _send_result_ok(self, result: Any) -> bool:
        if bool(getattr(self.adapter, "dry_run", False)):
            return True
        return bool(getattr(result, "sent", False) and getattr(result, "verified", False))

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
            and not message_sent(conversation, phrase)
        )

    @staticmethod
    def _should_handle_screening_before_knowledge(
        conversation: Conversation,
        rule: dict[str, Any],
        text: str,
    ) -> bool:
        """短确认/拒绝语优先进入筛选进度，不走 FAQ。"""

        screening = rule_screening(rule)
        if not screening or not text.strip() or looks_like_question(text):
            return False
        questions = normalize_position_screening_questions(screening)
        if not questions:
            return False
        for message in conversation.messages:
            if message.sender != MessageSender.ME:
                continue
            if any(
                position_screening_question_matches_any(message.text, question)
                for question in questions
            ):
                return True
        return False

    @staticmethod
    def _should_escalate_direct_question(text: str) -> bool:
        if not looks_like_question(text):
            return False
        compact = "".join(text.lower().split())
        resume_intent_terms = (
            "发简历",
            "发送简历",
            "交换简历",
            "看看简历",
            "看简历",
            "查看简历",
            "投递简历",
            "传简历",
            "给简历",
            "简历发",
            "附件简历",
            "在线简历",
            "sendresume",
            "sendcv",
            "exchangeresume",
            "exchangecv",
        )
        if any(term in compact for term in resume_intent_terms):
            return False
        detail_terms = (
            "detail",
            "details",
            "requirement",
            "requirements",
            "scope",
            "salary",
            "location",
            "岗位",
            "职责",
            "要求",
            "薪资",
            "工资",
            "地点",
            "工作内容",
            "待遇",
            "加班",
            "住宿",
        )
        return any(term in compact for term in detail_terms)

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
        extra = _json_safe(extra)
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
        self.persistence.finish(state, action=action, reason=reason, extra=extra)
        return state

ZhilianConversationRunner = ConversationRunner


def _json_safe(value: Any) -> Any:
    """Return a response/log safe value without raw binary payloads."""

    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "bytes", "length": len(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _candidate_rejected_conversation(text: str) -> bool:
    """识别候选人明确结束沟通的短句，避免继续求简历。"""

    compact = "".join(str(text or "").lower().split())
    if not compact:
        return False
    reject_terms = (
        "职位不太合适",
        "岗位不太合适",
        "职位不合适",
        "岗位不合适",
        "不太匹配",
        "不匹配",
        "不考虑",
        "不太考虑",
        "暂不考虑",
        "不感兴趣",
        "不用了",
        "算了",
        "谢谢关注",
    )
    return any(term in compact for term in reject_terms)
