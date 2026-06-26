"""招聘规则加载与匹配。

智联复用 `boss_chat_rules.json`。这里做结构化读取，不修改规则资产本身。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.settings import PROJECT_ROOT

RULES_PATH = PROJECT_ROOT / "config" / "chat_rules" / "boss_chat_rules.json"
OPERATION_RESUME_TYPES = {"运营A", "运营B"}


@lru_cache(maxsize=1)
def load_chat_rules(path: str | Path | None = None) -> dict[str, Any]:
    """读取知识库与岗位规则。"""

    target = Path(path) if path else RULES_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def select_position_rule(
    position: str, rules: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """按岗位名匹配 positionReplies。"""

    data = rules or load_chat_rules()
    position_rules = data.get("positionReplies") or {}
    if position in position_rules:
        return dict(position_rules[position])
    compact = _compact(position)
    for name, rule in position_rules.items():
        rule_name = _compact(name)
        if compact and rule_name and (compact in rule_name or rule_name in compact):
            return dict(rule)
    return None


def screening_questions(rule: dict[str, Any] | None) -> list[str]:
    """提取岗位筛选问题，兼容旧 JSON 的多种字段形状。"""

    if not rule:
        return []
    values = rule.get("screeningQuestions") or rule.get("questions") or []
    if not values and isinstance(rule.get("screening"), dict):
        values = rule["screening"].get("questions") or []
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        return [str(item.get("question") if isinstance(item, dict) else item) for item in values]
    return []


def is_ai_basic_rule(position: str, rule: dict[str, Any] | None) -> bool:
    """判断是否走 AI 应用开发基础条件流。"""

    category = str((rule or {}).get("category") or "")
    return category == "ai_app_intern" or "AI应用开发" in position


def is_direct_resume_rule(rule: dict[str, Any] | None) -> bool:
    """判断是否直求简历。"""

    return bool(rule and rule.get("directResume"))


def should_skip_prompt_before_resume(rule: dict[str, Any] | None) -> bool:
    """运营 A/B 在智联不发送前置话术，直接要附件简历。"""

    resume_type = str((rule or {}).get("resumeJobType") or "")
    category = str((rule or {}).get("category") or "")
    return resume_type in OPERATION_RESUME_TYPES or category == "operation_direct_resume"


def resume_request_prompt(rule: dict[str, Any] | None) -> str:
    """返回直求简历岗位的话术。"""

    return str((rule or {}).get("resumeRequestPrompt") or "").strip()


def initial_common_phrase(rule: dict[str, Any] | None) -> str:
    """返回 AI 应用开发基础条件常用语。"""

    return str((rule or {}).get("initialCommonPhrase") or "").strip()


def find_knowledge_answer(
    question: str,
    rules: dict[str, Any] | None = None,
    *,
    position: str = "",
) -> str | None:
    """从 companyKnowledgeBase 中查找简短答案。"""

    text = question.strip()
    if not text:
        return None
    kb = (rules or load_chat_rules()).get("companyKnowledgeBase") or {}
    candidates = _collect_answer_candidates(kb)
    scored: list[tuple[int, str]] = []
    compact_question = _compact(text)
    compact_position = _compact(position)
    for item in candidates:
        keys = [_compact(value) for value in item["keys"] if value]
        if not keys:
            continue
        score = 0
        if compact_position and any(
            compact_position in key or key in compact_position for key in keys
        ):
            score += 2
        if any(key and (key in compact_question or compact_question in key) for key in keys):
            score += 5
        if any(key and key[:2] in compact_question for key in keys if len(key) >= 2):
            score += 1
        if score > 0:
            scored.append((score, item["answer"]))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def looks_like_question(text: str) -> bool:
    """识别候选人是否在提问。"""

    value = text.strip()
    return bool(
        value and ("?" in value or "？" in value or any(k in value for k in QUESTION_TERMS))
    )


QUESTION_TERMS = ("吗", "么", "什么", "多少", "哪里", "在哪", "薪资", "工资", "加班", "双休")


def _collect_answer_candidates(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        answer = value.get("answer") or value.get("template") or value.get("reply")
        keys = (
            value.get("keywords")
            or value.get("match")
            or value.get("question")
            or value.get("title")
        )
        if answer and keys:
            key_list = keys if isinstance(keys, list) else [str(keys)]
            out.append({"keys": key_list, "answer": str(answer)})
        for key, child in value.items():
            child_items = _collect_answer_candidates(child)
            for item in child_items:
                item["keys"].append(str(key))
            out.extend(child_items)
    elif isinstance(value, list):
        for child in value:
            out.extend(_collect_answer_candidates(child))
    return out


def _compact(value: str) -> str:
    return "".join(str(value or "").split()).lower()
