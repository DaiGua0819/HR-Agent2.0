"""JD 关键词与规则项匹配。

移植旧 `matchJdKeywords`、`matchJdRuleItems` 与岗位评分核心公式。函数只依赖输入文本
和岗位档案，可直接单测。
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from app.core.text import clean_text
from app.domain.scoring.jd_profiles import JdHardGate, JdProfile, JdRule, get_jd_profile


def clean_jd_keyword(keyword: Any) -> str:
    """规整 JD 关键词。"""

    return clean_text(keyword).strip(" ,，;；")


def extract_resume_text(payload: dict[str, Any]) -> str:
    """从简历 payload 拼接可检索文本。"""

    parts: list[str] = []
    for value in payload.values():
        if isinstance(value, str | int | float):
            parts.append(str(value))
        elif isinstance(value, list | tuple):
            parts.extend(str(item) for item in value)
    return clean_text(" ".join(parts))


def match_jd_keywords(text: str, keywords: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """匹配关键词列表，返回命中、缺失和命中比例。"""

    haystack = clean_text(text).lower()
    normalized = [item for item in (clean_jd_keyword(keyword) for keyword in keywords) if item]
    matched = [keyword for keyword in normalized if keyword.lower() in haystack]
    missing = [keyword for keyword in normalized if keyword not in matched]
    ratio = len(matched) / len(normalized) if normalized else 1
    return {"matched": matched, "missing": missing, "ratio": ratio}


def match_jd_rule_items(text: str, rules: list[JdRule] | tuple[JdRule, ...]) -> dict[str, Any]:
    """匹配规则项；单个规则项命中任一关键词即通过。"""

    items: list[dict[str, Any]] = []
    for rule in rules:
        match = match_jd_keywords(text, rule.keywords)
        if match["matched"]:
            items.append(
                {
                    "label": rule.label,
                    "matched": match["matched"],
                    "keywords": list(rule.keywords),
                }
            )
    ratio = len(items) / len(rules) if rules else 1
    return {"items": items, "ratio": ratio, "count": len(items), "total": len(rules)}


def match_jd_hard_gates(
    text: str,
    gates: list[JdHardGate] | tuple[JdHardGate, ...],
) -> dict[str, Any]:
    """匹配分组硬门槛；每个证据组命中任一关键词才算命中该组。"""

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for gate in gates:
        groups: list[dict[str, Any]] = []
        for index, keywords in enumerate(gate.keyword_groups, start=1):
            match = match_jd_keywords(text, keywords)
            groups.append(
                {
                    "index": index,
                    "passed": bool(match["matched"]),
                    "matched": match["matched"],
                    "keywords": list(keywords),
                }
            )
        required_groups = gate.minimum_groups or len(groups)
        required_groups = min(len(groups), max(0, required_groups))
        matched_groups = sum(1 for group in groups if group["passed"])
        passed = matched_groups >= required_groups
        if not passed:
            missing.append(gate.label)
        items.append(
            {
                "label": gate.label,
                "passed": passed,
                "matchedGroups": matched_groups,
                "requiredGroups": required_groups,
                "groups": groups,
            }
        )
    return {
        "items": items,
        "passedCount": sum(1 for item in items if item["passed"]),
        "total": len(items),
        "missing": missing,
    }


def get_jd_level(score: int | float) -> str:
    """旧岗位分档：75/55/35 三档阈值。"""

    if score >= 75:
        return "A 优先"
    if score >= 55:
        return "B 复核"
    if score >= 35:
        return "C 暂缓"
    return "D 不优先"


def calculate_jd_match(
    text: str,
    job_type: str | None = None,
    *,
    profile: JdProfile | None = None,
) -> dict[str, Any]:
    """按旧 v5 公式计算岗位匹配分。"""

    selected = profile or get_jd_profile(job_type)
    must = match_jd_rule_items(text, selected.must_have)
    bonus = match_jd_rule_items(text, selected.bonus)
    risks = match_jd_rule_items(text, selected.risks)
    hard_gates = match_jd_hard_gates(text, selected.hard_gates)

    role_boost = 15 if _matches_role(job_type or "", selected) else 0
    focus_boost = 5 if bonus["items"] or must["items"] else 0
    risk_penalty = min(30, risks["count"] * 10)
    raw_score = must["ratio"] * 50 + bonus["ratio"] * 30 + role_boost + focus_boost - risk_penalty

    if must["count"] == 0:
        raw_score = min(raw_score, 45)
    elif 0 < must["ratio"] < 0.5:
        raw_score = min(raw_score, 68)
    if risks["count"] >= 2:
        raw_score = min(raw_score, 74)

    missing_gate_count = len(hard_gates["missing"])
    hard_gate_cap = 54 if missing_gate_count >= 2 else 74 if missing_gate_count == 1 else None
    if hard_gate_cap is not None:
        raw_score = min(raw_score, hard_gate_cap)

    score = int(max(0, min(100, round(raw_score))))
    return {
        "profile": selected.name,
        "score": score,
        "level": get_jd_level(score),
        "must": must,
        "bonus": bonus,
        "risks": risks,
        "hardGates": hard_gates,
        "missingHardGates": hard_gates["missing"],
        "hardGateCap": hard_gate_cap,
        "roleBoost": role_boost,
        "focusBoost": focus_boost,
        "riskPenalty": risk_penalty,
        "profileConfig": asdict(selected),
    }


def _matches_role(job_type: str, profile: JdProfile) -> bool:
    text = clean_text(job_type)
    return bool(text and (profile.name in text or any(alias in text for alias in profile.aliases)))


def split_keywords(value: Any) -> list[str]:
    """兼容前端/配置传入的逗号分隔关键词。"""

    if isinstance(value, list | tuple | set):
        raw = list(value)
    else:
        raw = re.split(r"[,，;；\n]+", clean_text(value))
    return [keyword for keyword in (clean_jd_keyword(item) for item in raw) if keyword]
