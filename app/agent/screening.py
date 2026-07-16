"""岗位筛选问题分析。

本模块复刻旧 BOSS 未读处理里的岗位筛选核心语义：每个问题的 `text`
和 `variants` 是同一筛选条件的不同问法；历史命中任一问法都视为已问。
runner 只消费本模块给出的状态，不直接理解具体岗位问题。
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from app.agent.judgement import JudgementResult, judge_candidate_reply
from app.platforms.types import ChatMessage, MessageSender

Chooser = Callable[[list[str]], str]
QUESTION_MODES = {"ask_required_questions", "ask_any_required_question"}


async def analyze_position_screening(
    messages: list[ChatMessage] | list[dict[str, Any]],
    screening: dict[str, Any],
    *,
    llm: Any | None = None,
) -> dict[str, Any]:
    """分析岗位筛选进度，返回 not_asked/waiting/unclear/accept/reject。"""

    questions = normalize_position_screening_questions(screening)
    mode = str(screening.get("mode") or "ask_required_questions").strip()
    if mode not in QUESTION_MODES:
        mode = "ask_required_questions"
    if not questions:
        return {"status": "not_configured", "reason": "position_screening_questions_missing"}

    normalized_messages = [_normalize_message(item) for item in messages]
    progress = []
    for question in questions:
        progress.append(
            await _question_progress(question, questions, normalized_messages, llm=llm)
        )
    return _decide_screening_status(mode, questions, progress)


def normalize_position_screening_questions(screening: dict[str, Any]) -> list[dict[str, Any]]:
    """归一化 screening.questions，保留同题 variants。"""

    raw_questions = screening.get("questions") if isinstance(screening, dict) else []
    if not isinstance(raw_questions, list):
        raw_questions = []
    questions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_questions):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("question") or "").strip()
            question_id = str(item.get("id") or "").strip()
            required = bool(item.get("required", True))
            variants = normalize_screening_question_variants(text, item.get("variants"))
            selected = item.get("selectedVariantIndex", item.get("variantIndex"))
        else:
            text = str(item or "").strip()
            question_id = ""
            required = True
            variants = normalize_screening_question_variants(text, [])
            selected = None
        if not text:
            continue
        question = {
            "id": question_id or _stable_question_id(text, index),
            "text": text,
            "variants": variants,
            "required": required,
            "index": index,
        }
        if selected is not None:
            try:
                question["selectedVariantIndex"] = int(selected)
            except (TypeError, ValueError):
                pass
        questions.append(question)
    return questions


def normalize_screening_question_variants(text: str, raw_variants: Any) -> list[str]:
    """把主问法与 variants 合并去重，主问法永远排第一。"""

    values = [text]
    if isinstance(raw_variants, list):
        values.extend(str(item or "") for item in raw_variants)
    elif isinstance(raw_variants, str):
        values.append(raw_variants)
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        cleaned = re.sub(r"\s+", " ", str(item or "").strip())
        key = _compact(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def screening_question_variant_texts(question: dict[str, Any]) -> list[str]:
    """返回某个筛选问题所有等价问法。"""

    variants = question.get("variants") if isinstance(question.get("variants"), list) else []
    if variants:
        return [str(item) for item in variants if str(item or "").strip()]
    text = str(question.get("text") or "").strip()
    return [text] if text else []


def select_position_screening_question_text(
    question: dict[str, Any],
    *,
    chooser: Chooser | None = None,
) -> str:
    """选择要发出的问法；测试可注入 chooser 保持确定性。"""

    variants = screening_question_variant_texts(question)
    if not variants:
        return ""
    selected = question.get("selectedVariantIndex")
    if isinstance(selected, int) and 0 <= selected < len(variants):
        return variants[selected]
    if chooser:
        return chooser(variants)
    return random.choice(variants)


def position_screening_question_matches_any(message_text: str, question: dict[str, Any]) -> bool:
    """判断消息是否命中某个问题的主问法或任意 variant。"""

    variants = screening_question_variant_texts(question)
    if any(
        _question_text_matches(message_text, item)
        for item in variants
    ):
        return True
    return any(_semantic_question_matches(message_text, item) for item in variants)


async def _question_progress(
    question: dict[str, Any],
    all_questions: list[dict[str, Any]],
    messages: list[dict[str, str]],
    *,
    llm: Any | None,
) -> dict[str, Any]:
    asked_index = -1
    asked_message: dict[str, str] = {}
    for index, item in enumerate(messages):
        if item["sender"] != MessageSender.ME.value:
            continue
        if position_screening_question_matches_any(item["text"], question):
            asked_index = index
            asked_message = item

    answer_messages: list[dict[str, str]] = []
    if asked_index >= 0:
        for item in messages[asked_index + 1 :]:
            if item["sender"] == MessageSender.ME.value and any(
                position_screening_question_matches_any(item["text"], other)
                for other in all_questions
            ):
                break
            if item["sender"] == MessageSender.CANDIDATE.value and item["text"].strip():
                answer_messages.append(item)

    answer_text = " ".join(item["text"] for item in answer_messages).strip()
    judgement = await _classify_answer(question, answer_text, llm=llm)
    if asked_index < 0:
        status = "not_asked"
    elif not answer_messages:
        status = "waiting"
    else:
        status = judgement.status
    return {
        "question": question,
        "asked": asked_index >= 0,
        "askedMessage": asked_message,
        "answerMessages": answer_messages,
        "answerText": answer_text,
        "judgement": asdict(judgement),
        "status": status,
    }


def _decide_screening_status(
    mode: str,
    questions: list[dict[str, Any]],
    progress: list[dict[str, Any]],
) -> dict[str, Any]:
    required_progress = [item for item in progress if item["question"].get("required", True)]
    rejected = next((item for item in required_progress if item["status"] == "reject"), None)
    accepted = [item for item in required_progress if item["status"] == "accept"]
    unasked = next((item for item in required_progress if item["status"] == "not_asked"), None)
    waiting = next(
        (item for item in required_progress if item["status"] in {"waiting", "unclear"}),
        None,
    )

    if mode == "ask_any_required_question":
        if accepted:
            return _analysis("accept", mode, questions, progress, "any_required_question_accept")
        if unasked:
            return _analysis(
                "not_asked",
                mode,
                questions,
                progress,
                "ask_next_required_question",
                next_question=unasked["question"],
            )
        if waiting:
            return _analysis(
                waiting["status"],
                mode,
                questions,
                progress,
                "waiting_candidate_reply",
            )
        if rejected:
            return _analysis("reject", mode, questions, progress, "all_required_questions_reject")
        return _analysis("unclear", mode, questions, progress, "screening_unclear")

    if rejected:
        return _analysis("reject", mode, questions, progress, "required_question_reject")
    if waiting:
        return _analysis(waiting["status"], mode, questions, progress, "waiting_candidate_reply")
    if unasked:
        return _analysis(
            "not_asked",
            mode,
            questions,
            progress,
            "ask_next_required_question",
            next_question=unasked["question"],
        )
    if len(accepted) == len(required_progress):
        return _analysis("accept", mode, questions, progress, "all_required_questions_accept")
    return _analysis("unclear", mode, questions, progress, "screening_unclear")


def _analysis(
    status: str,
    mode: str,
    questions: list[dict[str, Any]],
    progress: list[dict[str, Any]],
    reason: str,
    *,
    next_question: dict[str, Any] | None = None,
) -> dict[str, Any]:
    latest = next((item for item in reversed(progress) if item.get("answerText")), {})
    return {
        "status": status,
        "reason": reason,
        "mode": mode,
        "questions": questions,
        "progress": progress,
        "nextQuestion": next_question or {},
        "latestAnswerText": latest.get("answerText", ""),
    }


async def _classify_answer(
    question: dict[str, Any],
    answer_text: str,
    *,
    llm: Any | None,
) -> JudgementResult:
    text = answer_text.strip()
    if not text:
        return JudgementResult(status="waiting", evidence="", source="screening_rule")
    rule_status = _rule_classify(str(question.get("text") or ""), text)
    if rule_status:
        return JudgementResult(status=rule_status, evidence=text, source="screening_rule")
    return await judge_candidate_reply(text, question=str(question.get("text") or ""), llm=llm)


def _rule_classify(question_text: str, answer_text: str) -> str:
    compact = _compact(answer_text)
    question_compact = _compact(question_text)
    if not compact:
        return "waiting"
    if any(term in compact for term in ("没问题", "没有问题")):
        return "accept"
    if any(
        term in compact
        for term in (
            "不接受",
            "不能接受",
            "接受不了",
            "无法接受",
            "没法接受",
            "不太能接受",
            "不怎么能接受",
            "不愿意接受",
            "不可以",
            "不行",
            "不考虑",
        )
    ):
        return "reject"
    if any(term in compact for term in ("可以接受", "能接受")):
        return "accept"
    if any(term in question_compact for term in ("证", "经历", "熟悉", "了解", "接触", "做过")):
        if re.search(r"(没有|没|无|不是|不了解|不熟悉|没接触|没做过)", compact):
            return "reject"
        if re.search(r"(有|做过|接触过|了解|熟悉|会|持有|考了|拿到)", compact):
            return "accept"
    if re.search(r"(不能|不可以|不接受|不行|不考虑|不愿意|暂时不|拒绝)", compact):
        return "reject"
    if re.search(r"(可以|接受|能|愿意|没问题|符合|是的|对)", compact):
        return "accept"
    return ""


def _normalize_message(item: ChatMessage | dict[str, Any]) -> dict[str, str]:
    if isinstance(item, ChatMessage):
        sender = item.sender.value
        text = item.text
    else:
        sender = str(item.get("sender") or "")
        text = str(item.get("text") or "")
    return {"sender": sender, "text": text}


def _question_text_matches(message_text: str, question_text: str) -> bool:
    message = _compact(message_text)
    question = _compact(question_text)
    return bool(message and question and (question in message or message in question))


def _semantic_question_matches(message_text: str, question_text: str) -> bool:
    message = _compact(message_text)
    question = _compact(question_text)
    if not message or not question:
        return False
    if "出差" in message and "出差" in question:
        accept_terms = ("接受", "可以", "能", "是否")
        question_terms = (*accept_terms, "需要")
        return any(term in message for term in accept_terms) and any(
            term in question for term in question_terms
        )
    return False


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _stable_question_id(text: str, index: int) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"q_{index}_{digest}"
