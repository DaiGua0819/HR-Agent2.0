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


def match_calendar_event_candidates(
    event: dict[str, Any],
    resumes: list[Any],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Score resume records against a calendar event for auto binding."""

    event_text = _normalize_event_text(
        [
            event.get("title"),
            event.get("description"),
            event.get("location"),
            " ".join(event.get("attendees") or []),
            event.get("meetingUrl"),
        ]
    )
    results: list[dict[str, Any]] = []
    for resume in resumes:
        resume_id = _resume_value(resume, "id")
        if not resume_id:
            continue
        name = _resume_value(resume, "name", "candidateName", "parsed_name")
        phone = normalize_phone(_resume_value(resume, "phone", "phone_key"))
        job_type = _resume_value(resume, "job_type", "jobType", "applied_position", "position")
        score = 0
        reasons: list[str] = []
        exact_identity_match = False
        if _is_reliable_identity_name(name) and _normalize_event_text([name]) in event_text:
            score += 90
            exact_identity_match = True
            reasons.append("event_exact_candidate_name")
        if phone and phone in event_text:
            score += 45
            reasons.append("event_phone")
        if job_type and _normalize_event_text([job_type]) in event_text:
            score += 24
            reasons.append("event_job_type")
        if score <= 0:
            continue
        results.append(
            {
                "resumeId": resume_id,
                "name": name,
                "jobType": job_type,
                "score": min(100, score),
                "reasons": reasons,
                "exactIdentityMatch": exact_identity_match,
            }
        )
    return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]


def decide_calendar_auto_binding(
    matches: list[dict[str, Any]],
    *,
    min_score: int = 85,
    lead_score: int = 15,
) -> dict[str, Any]:
    """Decide whether a calendar event should auto-bind to one resume."""

    best = matches[0] if matches else None
    second = matches[1] if len(matches) > 1 else None
    if not best:
        return {
            "bind": False,
            "reason": "no_match",
            "status": "needs_match",
            "match": None,
            "lead": 0,
        }
    exact_matches = [item for item in matches if item.get("exactIdentityMatch")]
    if len(exact_matches) == 1:
        exact = exact_matches[0]
        closest_other = next(
            (item for item in matches if item["resumeId"] != exact["resumeId"]),
            None,
        )
        return {
            "bind": True,
            "reason": "unique_exact_identity",
            "status": "matched",
            "match": exact,
            "lead": exact["score"] - (closest_other["score"] if closest_other else 0),
        }
    if len(exact_matches) > 1:
        return {
            "bind": False,
            "reason": "duplicate_exact_identity",
            "status": "needs_confirmation",
            "match": exact_matches[0],
            "lead": exact_matches[0]["score"] - exact_matches[1]["score"],
        }
    lead = best["score"] - (second["score"] if second else 0)
    if best["score"] >= min_score and lead >= lead_score:
        return {
            "bind": True,
            "reason": "high_confidence",
            "status": "matched",
            "match": best,
            "lead": lead,
        }
    return {
        "bind": False,
        "reason": "low_confidence",
        "status": "needs_confirmation",
        "match": best,
        "lead": lead,
    }


def _normalize_event_text(values: list[Any]) -> str:
    return "".join(clean_text(value).lower() for value in values if clean_text(value))


def _is_reliable_identity_name(value: Any) -> bool:
    """Reject truncated names that are too weak for automatic calendar binding."""

    text = clean_text(value).replace(" ", "")
    if not text:
        return False
    chinese_characters = [character for character in text if "\u4e00" <= character <= "\u9fff"]
    if chinese_characters and len(chinese_characters) == len(text):
        return len(chinese_characters) >= 2
    alphanumeric = "".join(character for character in text if character.isalnum())
    return len(alphanumeric) >= 3


def _resume_value(resume: Any, *keys: str) -> str:
    payload = getattr(resume, "payload", None)
    if not isinstance(payload, dict):
        payload = resume if isinstance(resume, dict) else {}
    for key in keys:
        value = getattr(resume, key, None)
        if value not in (None, ""):
            return str(value)
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    if "name" in keys:
        candidate_name = getattr(resume, "candidate_name", None)
        if candidate_name:
            return str(candidate_name)
    return ""
