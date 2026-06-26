"""JD 关键词与规则项匹配。

移植旧 `matchJdKeywords`、`matchJdRuleItems` 与岗位评分核心公式。函数只依赖输入文本
和岗位档案，可直接单测。
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from app.core.text import clean_text
from app.domain.scoring.jd_profiles import JdProfile, JdRule, get_jd_profile


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

    score = int(max(0, min(100, round(raw_score))))
    return {
        "profile": selected.name,
        "score": score,
        "level": get_jd_level(score),
        "must": must,
        "bonus": bonus,
        "risks": risks,
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
