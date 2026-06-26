"""面试中心候选人匹配。

移植旧 `candidateMatcher.js` 的职责：用姓名、手机号、岗位等线索在候选人集合里打分排序。
这是纯逻辑模块，不读 DB、不调飞书。
"""

from __future__ import annotations

from typing import Any

from app.core.text import clean_text
from app.domain.resume.normalize import normalize_phone


def match_candidate(
    session: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """按姓名、电话、岗位等线索匹配候选人。"""

    pool = candidates or list(session.get("candidates", []))
    return match_candidates(session, pool)


def match_candidates(
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """返回按匹配分倒序排列的候选人。"""

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        score, reasons = score_candidate(query, candidate)
        if score <= 0:
            continue
        results.append({"candidate": candidate, "score": score, "reasons": reasons})
    return sorted(results, key=lambda item: item["score"], reverse=True)


def score_candidate(query: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, list[str]]:
    """计算候选人与查询会话的匹配分。"""

    score = 0
    reasons: list[str] = []
    query_phone = normalize_phone(query.get("phone") or query.get("phone_key"))
    candidate_phone = normalize_phone(candidate.get("phone") or candidate.get("phone_key"))
    if query_phone and candidate_phone and query_phone == candidate_phone:
        score += 80
        reasons.append("phone_exact")

    query_name = clean_text(query.get("name") or query.get("candidateName"))
    candidate_name = clean_text(candidate.get("name") or candidate.get("candidateName"))
    if query_name and candidate_name:
        if query_name == candidate_name:
            score += 40
            reasons.append("name_exact")
        elif query_name in candidate_name or candidate_name in query_name:
            score += 20
            reasons.append("name_partial")

    query_position = clean_text(query.get("position") or query.get("job_type"))
    candidate_position = clean_text(candidate.get("position") or candidate.get("job_type"))
    if query_position and candidate_position:
        if query_position == candidate_position:
            score += 25
            reasons.append("position_exact")
        elif query_position in candidate_position or candidate_position in query_position:
            score += 12
            reasons.append("position_partial")

    query_source = clean_text(query.get("source_platform"))
    candidate_source = clean_text(candidate.get("source_platform"))
    if query_source and candidate_source and query_source == candidate_source:
        score += 5
        reasons.append("source_platform")
    return min(100, score), reasons
