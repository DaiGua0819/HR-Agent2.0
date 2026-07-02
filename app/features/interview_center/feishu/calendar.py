"""Feishu calendar event normalization for the interview center."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.core.text import clean_text, clip_text

_INTERVIEW_KEYWORD_RE = re.compile(
    r"面试|初试|复试|终面|一面|二面|三面|面谈|面聊|约面|候选人|应聘|招聘|interview",
    re.IGNORECASE,
)
_JOB_KEYWORD_RE = re.compile(
    r"AI应用|HRBP|管培|应用技术|运营A|运营B|销售|人力资源|智能体|Agent|RAG",
    re.IGNORECASE,
)


def normalize_calendar_event(calendar_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Feishu calendar event into the old interview-center shape."""

    start_time = _event_time(raw.get("start_time") or raw.get("startTime") or raw.get("start"))
    end_time = _event_time(raw.get("end_time") or raw.get("endTime") or raw.get("end"))
    title = clean_text(raw.get("summary") or raw.get("title") or "未命名日程")
    description = clean_text(raw.get("description") or raw.get("note") or "")
    attendees = _normalize_attendees(raw)
    location = _location_text(raw.get("location"))
    normalized = {
        "calendarId": calendar_id,
        "feishuEventId": str(
            raw.get("feishuEventId")
            or raw.get("event_id")
            or raw.get("id")
            or raw.get("uid")
            or f"{calendar_id}:{title}:{start_time}"
        ),
        "title": title,
        "description": clip_text(description, max_length=5000),
        "location": location,
        "attendees": attendees,
        "meetingUrl": _meeting_url(raw),
        "startTime": start_time,
        "endTime": end_time,
        "rawEvent": dict(raw),
    }
    is_interview_like = is_interview_like_event({**raw, **normalized})
    normalized["isInterviewLike"] = is_interview_like
    normalized["status"] = "synced" if is_interview_like else "non_interview"
    return normalized


def is_interview_like_event(event: dict[str, Any]) -> bool:
    """Return whether a normalized or raw calendar event looks interview-related."""

    text = " ".join(
        clean_text(value)
        for value in [
            event.get("summary"),
            event.get("title"),
            event.get("description"),
            _location_text(event.get("location")),
            event.get("meetingUrl"),
            event.get("meeting_url"),
            *_normalize_attendees(event),
        ]
        if clean_text(value)
    )
    return bool(_INTERVIEW_KEYWORD_RE.search(text) or _JOB_KEYWORD_RE.search(text))


def _event_time(value: Any) -> int:
    if isinstance(value, dict):
        return _event_time(value.get("timestamp") or value.get("date") or value.get("datetime"))
    if value in (None, ""):
        return 0
    if isinstance(value, int | float):
        return _numeric_timestamp(value)
    text = clean_text(value)
    if not text:
        return 0
    try:
        return _numeric_timestamp(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return int(parsed.timestamp())


def _numeric_timestamp(value: int | float) -> int:
    number = int(value)
    if number > 10_000_000_000:
        return number // 1000
    return number


def _normalize_attendees(event: dict[str, Any]) -> list[str]:
    attendees = event.get("attendees")
    if not isinstance(attendees, list):
        return []
    result: list[str] = []
    for item in attendees:
        user = item.get("user") or item.get("attendee") or item if isinstance(item, dict) else item
        if isinstance(user, dict):
            text = clean_text(
                user.get("name")
                or user.get("display_name")
                or user.get("email")
                or user.get("open_id")
                or user.get("user_id")
            )
        else:
            text = clean_text(user)
        if text:
            result.append(text)
    return result[:20]


def _location_text(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("address") or "")
    return clean_text(value)


def _meeting_url(event: dict[str, Any]) -> str:
    vchat = event.get("vchat") if isinstance(event.get("vchat"), dict) else {}
    return clean_text(
        vchat.get("meeting_url")
        or event.get("video_meeting_url")
        or event.get("meeting_url")
        or event.get("online_meeting_url")
        or event.get("app_link")
        or event.get("meetingUrl")
        or ""
    )
