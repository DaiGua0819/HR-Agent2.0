"""招聘规则加载与岗位匹配。

规则资产仍以 `boss_chat_rules.json` 为准。本模块只做结构化读取与归一化：
先保留 `positionReplies` 的直求简历 / AI 基础条件等特殊配置，再补充
`companyKnowledgeBase.sections` 的岗位筛选与知识库 section，避免把岗位逻辑
写散到 runner 中。
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
    """按岗位名匹配 positionReplies 与 companyKnowledgeBase.sections。"""

    data = rules or load_chat_rules()
    position_match = _best_position_reply_match(position, data)
    section_match = _best_section_match(position, data)
    if position_match and section_match:
        rule = _normalize_position_reply_rule(position_match, position)
        section_rule = _normalize_section_rule(section_match, position)
        rule.setdefault("companyKnowledgeBase", section_rule.get("companyKnowledgeBase", {}))
        rule.setdefault("knowledgeSectionKey", section_rule.get("knowledgeSectionKey", ""))
        rule.setdefault("matchPositions", section_rule.get("matchPositions", []))
        if not rule.get("screening") and section_rule.get("screening"):
            rule["screening"] = section_rule["screening"]
        return rule
    if position_match:
        return _normalize_position_reply_rule(position_match, position)
    if section_match:
        return _normalize_section_rule(section_match, position)
    return None


def screening_questions(rule: dict[str, Any] | None) -> list[str]:
    """提取岗位筛选主问法，兼容旧 JSON 的多种字段形状。"""

    if not rule:
        return []
    values = rule.get("screeningQuestions") or rule.get("questions") or []
    if not values and isinstance(rule.get("screening"), dict):
        values = rule["screening"].get("questions") or []
    if isinstance(values, str):
        return [values]
    if isinstance(values, list):
        out: list[str] = []
        for item in values:
            if isinstance(item, dict):
                out.append(str(item.get("text") or item.get("question") or ""))
            else:
                out.append(str(item))
        return [item for item in out if item.strip()]
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


def rule_screening(rule: dict[str, Any] | None) -> dict[str, Any]:
    """返回岗位筛选配置。"""

    screening = (rule or {}).get("screening")
    if isinstance(screening, dict):
        return screening
    questions = screening_questions(rule)
    if questions:
        return {
            "mode": "ask_required_questions",
            "questions": [{"text": item, "required": True} for item in questions],
        }
    return {}


def should_prioritize_screening(text: str, rule: dict[str, Any] | None) -> bool:
    """部分岗位遇到泛问句时直接推进筛选，不先发通用 FAQ。"""

    if not text or not rule:
        return False
    patterns = _string_list(rule.get("screeningFirstQuestionPatterns"))
    kb = rule.get("companyKnowledgeBase") if isinstance(rule.get("companyKnowledgeBase"), dict) else {}
    patterns.extend(_string_list(kb.get("screeningFirstQuestionPatterns")))
    compact_text = _compact(text)
    for pattern in patterns:
        compact_pattern = _compact(pattern)
        if compact_pattern and compact_pattern in compact_text:
            return True
    return False


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
    scored: list[tuple[int, int, str]] = []
    compact_question = _compact(text)
    compact_position = _compact(position)
    for item in candidates:
        keys = [_compact(value) for value in item["keys"] if value]
        if not keys:
            continue
        position_bonus = 0
        if compact_position and any(
            compact_position in key or key in compact_position for key in keys
        ):
            position_bonus = 2
        question_match_len = 0
        for key in keys:
            if key and (key in compact_question or compact_question in key):
                question_match_len = max(question_match_len, len(key))
        prefix_bonus = int(any(key and key[:2] in compact_question for key in keys if len(key) >= 2))
        if question_match_len or prefix_bonus:
            score = 5 + prefix_bonus + position_bonus
            scored.append((question_match_len, score, item["answer"]))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[0][2]


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
            or value.get("questionPatterns")
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


def _best_position_reply_match(
    position: str,
    rules: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    position_rules = rules.get("positionReplies") or {}
    if not isinstance(position_rules, dict):
        return None
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for name, raw_rule in position_rules.items():
        if not isinstance(raw_rule, dict):
            continue
        names = [str(name)]
        names.extend(_string_list(raw_rule.get("aliases")))
        names.extend(_string_list(raw_rule.get("matchPositions")))
        for item in names:
            if item.strip():
                candidates.append((item, str(name), raw_rule))
    match = _best_named_match(position, candidates)
    return (match[1], match[2]) if match else None


def _best_section_match(
    position: str,
    rules: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    kb = (
        rules.get("companyKnowledgeBase")
        if isinstance(rules.get("companyKnowledgeBase"), dict)
        else {}
    )
    sections = kb.get("sections") if isinstance(kb.get("sections"), (dict, list)) else {}
    items: list[tuple[str, dict[str, Any]]] = []
    if isinstance(sections, dict):
        items = [(str(key), value) for key, value in sections.items() if isinstance(value, dict)]
    elif isinstance(sections, list):
        items = [
            (str(item.get("title") or item.get("name") or index), item)
            for index, item in enumerate(sections)
            if isinstance(item, dict)
        ]
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for key, section in items:
        names = [key, str(section.get("title") or ""), str(section.get("name") or "")]
        names.extend(_string_list(section.get("aliases")))
        names.extend(_string_list(section.get("matchPositions")))
        for item in names:
            if item.strip():
                candidates.append((item, key, section))
    match = _best_named_match(position, candidates)
    return (match[1], match[2]) if match else None


def _best_named_match(
    position: str,
    candidates: list[tuple[str, str, dict[str, Any]]],
) -> tuple[str, str, dict[str, Any]] | None:
    compact = _compact(position)
    if not compact:
        return None
    scored: list[tuple[int, int, str, str, dict[str, Any]]] = []
    for name, key, payload in candidates:
        candidate = _compact(name)
        if not candidate:
            continue
        if compact == candidate:
            score = 3
        elif candidate in compact:
            score = 2
        elif compact in candidate:
            score = 1
        else:
            continue
        scored.append((score, len(candidate), name, key, payload))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, name, key, payload = scored[0]
    return name, key, payload


def _normalize_position_reply_rule(
    match: tuple[str, dict[str, Any]],
    position: str,
) -> dict[str, Any]:
    key, raw_rule = match
    rule = dict(raw_rule)
    rule.setdefault("matchedPosition", position)
    rule.setdefault("ruleSource", "positionReplies")
    rule.setdefault("positionRuleKey", key)
    return rule


def _normalize_section_rule(
    match: tuple[str, dict[str, Any]],
    position: str,
) -> dict[str, Any]:
    key, section = match
    rule = dict(section)
    title = str(section.get("title") or section.get("name") or key)
    rule.setdefault("category", title)
    rule.setdefault("resumeJobType", title)
    rule.setdefault("matchedPosition", position)
    rule.setdefault("ruleSource", "companyKnowledgeBase.sections")
    rule.setdefault("knowledgeSectionKey", key)
    rule["companyKnowledgeBase"] = dict(section)
    return rule


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []
