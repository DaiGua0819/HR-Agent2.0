"""Meeting/minutes source collection boundary for interview backfill."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.core.text import clean_text
from app.features.interview_center.feishu.client import (
    FEISHU_BASE_URL,
    FeishuUserTokenProvider,
)
from app.features.interview_center.store import InterviewSession


class MeetingSourceClientProtocol(Protocol):
    """Collect text sources that can be used for interview evaluation backfill."""

    async def collect_sources(self, session: InterviewSession) -> dict[str, Any]:
        """Return collected text and public source metadata."""


class EmptyMeetingSourceClient:
    """Safe default until the real Feishu VC/minutes client is wired."""

    async def collect_sources(self, session: InterviewSession) -> dict[str, Any]:
        return {
            "text": "",
            "source": {
                "source": "empty",
                "sessionId": session.id,
                "errors": ["meeting_source_client_not_configured"],
            },
        }


@dataclass
class FeishuMeetingSourceClient:
    """Collect interview backfill text from Feishu docs, meetings, and minutes."""

    token_provider: FeishuUserTokenProvider
    base_url: str = FEISHU_BASE_URL
    transport: httpx.AsyncBaseTransport | None = None
    skip_without_token: bool = True

    async def collect_sources(self, session: InterviewSession) -> dict[str, Any]:
        user_token = await self.token_provider.user_access_token()
        if not user_token:
            if not self.skip_without_token:
                raise ValueError("feishu_user_token_required")
            return _empty_source("feishu_user_token_required")

        document_texts: list[str] = []
        sources: list[dict[str, Any]] = []
        errors: list[str] = []
        linked_doc_ids: list[str] = []
        discovered_minute_tokens: list[str] = []
        discovered_meeting_note_ids: list[str] = []
        meeting_ids: list[str] = []

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30,
            transport=self.transport,
        ) as client:
            doc_id = clean_text(session.feishu_doc.get("documentId") or "")
            if doc_id:
                await self._collect_interview_doc(
                    client,
                    user_token,
                    doc_id,
                    session,
                    document_texts,
                    sources,
                    errors,
                )

            source_text = _session_source_text(session)
            _append_unique(linked_doc_ids, _extract_document_tokens(source_text))
            linked_doc_ids[:] = [token for token in linked_doc_ids if token != doc_id]
            for token in linked_doc_ids[:3]:
                await self._collect_doc_text(
                    client,
                    user_token,
                    token,
                    "linked_doc",
                    document_texts,
                    sources,
                    errors,
                    url=f"https://feishu.cn/docx/{token}",
                )

            _append_unique(discovered_minute_tokens, _extract_minute_tokens(source_text))
            _append_unique(meeting_ids, _extract_meeting_ids(source_text))

            relation = await self._resolve_calendar_relations(
                client,
                user_token,
                session,
            )
            _append_unique(meeting_ids, relation["meetingIds"])
            _append_unique(sources, relation["sources"])
            _append_unique(errors, relation["errors"])
            relation_doc_tokens = [
                token for token in relation["meetingNoteDocTokens"] if token != doc_id
            ]
            _append_unique(linked_doc_ids, relation_doc_tokens)
            for token in relation_doc_tokens[:3]:
                await self._collect_doc_text(
                    client,
                    user_token,
                    token,
                    "meeting_note_doc",
                    document_texts,
                    sources,
                    errors,
                    url=f"https://feishu.cn/docx/{token}",
                )

            if not meeting_ids:
                meeting_search = await self._search_meetings(client, user_token, session)
                _append_unique(meeting_ids, meeting_search["meetingIds"])
                _append_unique(sources, meeting_search["sources"])
                _append_unique(errors, meeting_search["errors"])

            for meeting_id in meeting_ids[:5]:
                detail = await self._read_meeting_detail(client, user_token, meeting_id)
                if detail["source"]:
                    sources.append(detail["source"])
                if detail["noteId"]:
                    _append_unique(discovered_meeting_note_ids, [detail["noteId"]])

            discovered_note_doc_ids: list[str] = []
            for note_id in discovered_meeting_note_ids[:5]:
                note = await self._read_meeting_note_doc_tokens(client, user_token, note_id)
                if note["source"]:
                    sources.append(note["source"])
                _append_unique(discovered_note_doc_ids, note["docTokens"])

            for token in [
                item for item in discovered_note_doc_ids if item and item != doc_id
            ][:8]:
                _append_unique(linked_doc_ids, [token])
                await self._collect_doc_text(
                    client,
                    user_token,
                    token,
                    "meeting_note_doc",
                    document_texts,
                    sources,
                    errors,
                    url=f"https://feishu.cn/docx/{token}",
                )

            for meeting_id in meeting_ids[:5]:
                recording = await self._read_meeting_recording(
                    client,
                    user_token,
                    meeting_id,
                )
                if recording["source"]:
                    sources.append(recording["source"])
                if recording["token"]:
                    _append_unique(discovered_minute_tokens, [recording["token"]])

            if not discovered_minute_tokens:
                minutes_search = await self._search_minutes(client, user_token, session)
                _append_unique(discovered_minute_tokens, minutes_search["minuteTokens"])
                _append_unique(sources, minutes_search["sources"])
                _append_unique(errors, minutes_search["errors"])

            for token in discovered_minute_tokens[:5]:
                try:
                    text = await self._read_minutes_transcript(client, user_token, token)
                    if text:
                        document_texts.append(text)
                        sources.append(
                            {
                                "type": "minutes_transcript",
                                "id": token,
                                "length": len(text),
                                "url": f"https://feishu.cn/minutes/{token}",
                            }
                        )
                except Exception as exc:
                    errors.append(f"read_minutes_transcript_failed({token}): {exc}")

        text = "\n\n".join(item for item in document_texts if item)
        source = {
            "source": "feishu_meeting",
            "types": _unique([str(item.get("type") or "") for item in sources]),
            "rawTextLength": len(text),
            "linkedDocIds": linked_doc_ids,
            "minuteTokens": discovered_minute_tokens,
            "meetingNoteIds": discovered_meeting_note_ids,
            "sources": sources,
            "errors": errors,
        }
        return {
            "text": text,
            "source": source,
            "linkedDocIds": linked_doc_ids,
            "minuteTokens": discovered_minute_tokens,
            "sources": sources,
            "errors": errors,
        }

    async def _collect_interview_doc(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        doc_id: str,
        session: InterviewSession,
        document_texts: list[str],
        sources: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        try:
            text = await self._read_document_text(client, user_token, doc_id)
            doc_text = _meaningful_doc_text(
                text,
                clean_text(session.feishu_doc.get("localText") or ""),
            )
            if doc_text:
                document_texts.append(doc_text)
                sources.append(
                    {
                        "type": "interview_doc",
                        "id": doc_id,
                        "length": len(doc_text),
                        "url": session.feishu_doc.get("url") or "",
                    }
                )
            elif text:
                sources.append(
                    {
                        "type": "interview_doc",
                        "id": doc_id,
                        "length": 0,
                        "url": session.feishu_doc.get("url") or "",
                    }
                )
        except Exception as exc:
            errors.append(f"read_interview_doc_failed({doc_id}): {exc}")

    async def _collect_doc_text(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        doc_id: str,
        source_type: str,
        document_texts: list[str],
        sources: list[dict[str, Any]],
        errors: list[str],
        *,
        url: str = "",
    ) -> None:
        try:
            text = await self._read_document_text(client, user_token, doc_id)
            if text:
                document_texts.append(text)
                sources.append(
                    {
                        "type": source_type,
                        "id": doc_id,
                        "length": len(text),
                        "url": url,
                    }
                )
        except Exception as exc:
            errors.append(f"read_doc_failed({doc_id}): {exc}")

    async def _read_document_text(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        document_id: str,
    ) -> str:
        payload = await _request_json(
            client,
            "GET",
            f"/docx/v1/documents/{document_id}/blocks",
            user_token,
        )
        blocks = payload.get("data", {}).get("items") or payload.get("data", {}).get("blocks") or []
        lines: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            elements = block.get("text", {}).get("elements") or []
            text = "".join(
                clean_text(element.get("text_run", {}).get("content") or "")
                for element in elements
                if isinstance(element, dict)
            )
            if text:
                lines.append(text)
        return clean_text("\n".join(lines))

    async def _resolve_calendar_relations(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        session: InterviewSession,
    ) -> dict[str, Any]:
        event_id = clean_text(session.feishu_event_id)
        if not event_id:
            return {"meetingIds": [], "meetingNoteDocTokens": [], "sources": [], "errors": []}
        raw_event = _raw_event(session)
        calendar_ids = _unique(
            [
                session.calendar_id or "primary",
                "primary",
                clean_text(raw_event.get("organizer_calendar_id") or ""),
            ]
        )
        meeting_ids: list[str] = []
        meeting_note_doc_tokens: list[str] = []
        sources: list[dict[str, Any]] = []
        errors: list[str] = []
        for calendar_id in calendar_ids:
            try:
                payload = await _request_json(
                    client,
                    "POST",
                    f"/calendar/v4/calendars/{calendar_id}/events/mget_instance_relation_info",
                    user_token,
                    json={
                        "instance_ids": [event_id],
                        "need_meeting_instance_ids": True,
                        "need_meeting_notes": True,
                    },
                )
                infos = (
                    payload.get("data", {}).get("instance_relation_infos")
                    or payload.get("data", {}).get("items")
                    or []
                )
                for info in infos:
                    _append_unique(
                        meeting_ids,
                        [
                            *_string_ids(info.get("meeting_instance_ids")),
                            *_string_ids(info.get("meeting_ids")),
                            *_string_ids(info.get("meeting_instance_id")),
                            *_string_ids(info.get("meeting_id")),
                        ],
                    )
                    _append_unique(
                        meeting_note_doc_tokens,
                        [
                            *_string_ids(info.get("meeting_notes")),
                            *_string_ids(info.get("note_doc_tokens")),
                            *_string_ids(info.get("note_doc_token")),
                            *_string_ids(info.get("verbatim_doc_token")),
                        ],
                    )
                sources.append(
                    {
                        "type": "calendar_relation",
                        "id": event_id,
                        "length": len(meeting_ids) + len(meeting_note_doc_tokens),
                        "url": clean_text(raw_event.get("app_link") or ""),
                    }
                )
                if meeting_ids or meeting_note_doc_tokens:
                    break
            except Exception as exc:
                errors.append(f"calendar_relation_failed({calendar_id}): {exc}")
        return {
            "meetingIds": meeting_ids,
            "meetingNoteDocTokens": meeting_note_doc_tokens,
            "sources": sources,
            "errors": errors,
        }

    async def _read_meeting_detail(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        meeting_id: str,
    ) -> dict[str, Any]:
        try:
            payload = await _request_json(
                client,
                "GET",
                f"/vc/v1/meetings/{meeting_id}",
                user_token,
                params={"with_participants": "false", "query_mode": "0"},
            )
            meeting = payload.get("data", {}).get("meeting") or payload.get("meeting") or {}
            note_id = clean_text(meeting.get("note_id") or meeting.get("noteId") or "")
            return {
                "noteId": note_id,
                "source": {
                    "type": "meeting_detail",
                    "id": clean_text(meeting.get("id") or meeting_id),
                    "length": 1 if note_id else 0,
                    "url": clean_text(meeting.get("url") or ""),
                },
            }
        except Exception:
            return {"noteId": "", "source": None}

    async def _read_meeting_note_doc_tokens(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        note_id: str,
    ) -> dict[str, Any]:
        try:
            payload = await _request_json(
                client,
                "GET",
                f"/vc/v1/notes/{note_id}",
                user_token,
            )
            note = payload.get("data", {}).get("note") or payload.get("note") or {}
            doc_tokens = _extract_note_artifact_doc_tokens(note)
            return {
                "docTokens": doc_tokens,
                "source": {
                    "type": "meeting_note",
                    "id": note_id,
                    "length": len(doc_tokens),
                    "url": "",
                },
            }
        except Exception:
            return {"docTokens": [], "source": None}

    async def _read_meeting_recording(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        meeting_id: str,
    ) -> dict[str, Any]:
        try:
            payload = await _request_json(
                client,
                "GET",
                f"/vc/v1/meetings/{meeting_id}/recording",
                user_token,
            )
            recording = (
                payload.get("data", {}).get("recording")
                or payload.get("recording")
                or {}
            )
            recording_url = clean_text(
                recording.get("url") or recording.get("recording_url") or ""
            )
            token = _extract_minute_token_from_url(recording_url)
            return {
                "token": token,
                "source": {
                    "type": "meeting_recording",
                    "id": meeting_id,
                    "length": 1 if token else 0,
                    "url": recording_url,
                },
            }
        except Exception:
            return {"token": "", "source": None}

    async def _search_meetings(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        session: InterviewSession,
    ) -> dict[str, Any]:
        query = clean_text(session.candidate_name or session.payload.get("title") or "")[:50]
        if not query and not session.start_time and not session.end_time:
            return {"meetingIds": [], "sources": [], "errors": []}
        try:
            payload = await _request_json(
                client,
                "POST",
                "/vc/v1/meetings/search",
                user_token,
                params={"page_size": "10"},
                json=_meeting_search_body(session, query),
            )
            meeting_ids: list[str] = []
            for item in payload.get("data", {}).get("items") or payload.get("items") or []:
                _append_unique(
                    meeting_ids,
                    _string_ids(
                        item.get("id")
                        or item.get("meeting_id")
                        or item.get("meeting_instance_id")
                    ),
                )
            return {
                "meetingIds": meeting_ids,
                "sources": [
                    {
                        "type": "meeting_search",
                        "id": query or str(session.start_time or ""),
                        "length": len(meeting_ids),
                        "url": "",
                    }
                ],
                "errors": [],
            }
        except Exception as exc:
            return {"meetingIds": [], "sources": [], "errors": [f"meeting_search_failed: {exc}"]}

    async def _search_minutes(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        session: InterviewSession,
    ) -> dict[str, Any]:
        query = clean_text(session.candidate_name or session.payload.get("title") or "")[:50]
        if not query and not session.start_time and not session.end_time:
            return {"minuteTokens": [], "sources": [], "errors": []}
        try:
            payload = await _request_json(
                client,
                "POST",
                "/minutes/v1/minutes/search",
                user_token,
                params={"page_size": "10"},
                json=_minutes_search_body(session, query),
            )
            minute_tokens: list[str] = []
            for item in payload.get("data", {}).get("items") or payload.get("items") or []:
                _append_unique(
                    minute_tokens,
                    _string_ids(
                        item.get("token") or item.get("minute_token") or item.get("minuteToken")
                    ),
                )
            return {
                "minuteTokens": minute_tokens,
                "sources": [
                    {
                        "type": "minutes_search",
                        "id": query or str(session.start_time or ""),
                        "length": len(minute_tokens),
                        "url": "",
                    }
                ],
                "errors": [],
            }
        except Exception as exc:
            return {"minuteTokens": [], "sources": [], "errors": [f"minutes_search_failed: {exc}"]}

    async def _read_minutes_transcript(
        self,
        client: httpx.AsyncClient,
        user_token: str,
        minute_token: str,
    ) -> str:
        response = await client.get(
            f"/minutes/v1/minutes/{minute_token}/transcript",
            headers={"Authorization": f"Bearer {user_token}"},
            params={
                "need_speaker": "true",
                "need_timestamp": "true",
                "file_format": "txt",
            },
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        raw_text = response.text
        if "application/json" in content_type or raw_text.lstrip().startswith("{"):
            payload = response.json()
            _validate_feishu_payload(payload, "read_minutes_transcript_failed")
            return _transcript_payload_to_text(payload)
        return clean_text(raw_text)


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    user_token: str,
    **kwargs: Any,
) -> dict[str, Any]:
    response = await client.request(
        method,
        url,
        headers={"Authorization": f"Bearer {user_token}"},
        **kwargs,
    )
    response.raise_for_status()
    payload = response.json()
    _validate_feishu_payload(payload, f"feishu_{method.lower()}_failed")
    return dict(payload)


def _validate_feishu_payload(payload: dict[str, Any], error: str) -> None:
    if int(payload.get("code") or 0) != 0:
        raise ValueError(str(payload.get("msg") or error))


def _empty_source(error: str) -> dict[str, Any]:
    return {
        "text": "",
        "source": {
            "source": "feishu_meeting",
            "types": [],
            "rawTextLength": 0,
            "linkedDocIds": [],
            "minuteTokens": [],
            "meetingNoteIds": [],
            "sources": [],
            "errors": [error],
        },
        "linkedDocIds": [],
        "minuteTokens": [],
        "sources": [],
        "errors": [error],
    }


def _session_source_text(session: InterviewSession) -> str:
    payload = session.payload or {}
    raw_event = _raw_event(session)
    values = [
        payload.get("description"),
        payload.get("meetingUrl"),
        payload.get("meeting_url"),
        json.dumps(raw_event, ensure_ascii=False) if raw_event else "",
    ]
    return "\n".join(clean_text(value) for value in values if clean_text(value))


def _raw_event(session: InterviewSession) -> dict[str, Any]:
    raw_event = session.payload.get("rawEvent") if isinstance(session.payload, dict) else {}
    return dict(raw_event) if isinstance(raw_event, dict) else {}


def _extract_document_tokens(text: str) -> list[str]:
    return _extract_tokens(
        text,
        [
            r"/docx/([A-Za-z0-9]+)",
            r"/docs/([A-Za-z0-9]+)",
            r"/wiki/([A-Za-z0-9]+)",
            r"document_id=([A-Za-z0-9]+)",
        ],
    )


def _extract_minute_tokens(text: str) -> list[str]:
    return _extract_tokens(
        text,
        [
            r"/minutes/([A-Za-z0-9_-]+)",
            r"/minute/([A-Za-z0-9_-]+)",
            r"minute_token=([A-Za-z0-9_-]+)",
            r'"minute_token"\s*:\s*"([^"]+)"',
            r'"minuteToken"\s*:\s*"([^"]+)"',
            r'"minutes_token"\s*:\s*"([^"]+)"',
        ],
    )


def _extract_meeting_ids(text: str) -> list[str]:
    return _extract_tokens(
        text,
        [
            r"vc\.feishu\.cn/j/([0-9]+)",
            r"meetings/([0-9]+)",
            r'"meeting_id"\s*:\s*"([^"]+)"',
            r'"meetingId"\s*:\s*"([^"]+)"',
        ],
    )


def _extract_tokens(text: str, patterns: list[str]) -> list[str]:
    tokens: list[str] = []
    raw = str(text or "")
    for pattern in patterns:
        for match in re.finditer(pattern, raw):
            if match.group(1):
                _append_unique(tokens, [match.group(1)])
    return tokens


def _extract_minute_token_from_url(url: str) -> str:
    tokens = _extract_minute_tokens(url)
    return tokens[0] if tokens else ""


def _extract_note_artifact_doc_tokens(note: dict[str, Any]) -> list[str]:
    verbatim: list[str] = []
    main: list[str] = []
    other: list[str] = []
    for artifact in note.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        doc_token = clean_text(artifact.get("doc_token") or artifact.get("docToken") or "")
        if not doc_token:
            continue
        artifact_type = int(artifact.get("artifact_type") or artifact.get("artifactType") or 0)
        if artifact_type == 2:
            verbatim.append(doc_token)
        elif artifact_type == 1:
            main.append(doc_token)
        else:
            other.append(doc_token)
    references = [
        clean_text(item.get("doc_token") or item.get("docToken") or "")
        for item in note.get("references") or []
        if isinstance(item, dict)
    ]
    return _unique([*verbatim, *main, *other, *references])


def _transcript_payload_to_text(payload: dict[str, Any]) -> str:
    data = payload.get("data") or payload
    direct = data.get("content") or data.get("text") or data.get("transcript")
    direct = direct or data.get("raw_content")
    if isinstance(direct, str) and clean_text(direct):
        return clean_text(direct)
    items = (
        data.get("items")
        or data.get("sentences")
        or data.get("segments")
        or data.get("transcripts")
        or data.get("paragraphs")
        or []
    )
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            lines.append(clean_text(item))
            continue
        if not isinstance(item, dict):
            continue
        speaker = (
            item.get("speaker", {}).get("name")
            if isinstance(item.get("speaker"), dict)
            else ""
        )
        speaker = speaker or item.get("speaker_name") or item.get("user_name") or item.get("name")
        timestamp = item.get("start_time") or item.get("startTime") or item.get("time")
        text = item.get("text") or item.get("content") or item.get("sentence")
        line = " ".join(
            clean_text(part)
            for part in [
                f"[{timestamp}]" if timestamp else "",
                f"{speaker}:" if speaker else "",
                text or "",
            ]
            if clean_text(part)
        )
        if line:
            lines.append(line)
    return clean_text("\n".join(lines))


def _meaningful_doc_text(text: str, baseline: str = "") -> str:
    value = clean_text(text)
    base = clean_text(baseline)
    if not value:
        return ""
    if base and value == base:
        return ""
    return value


def _meeting_search_body(session: InterviewSession, query: str) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if query:
        body["query"] = query
    start = _rfc3339(int(session.start_time or 0) - 60 * 60)
    end = _rfc3339(int(session.end_time or session.start_time or 0) + 2 * 60 * 60)
    if start or end:
        body["meeting_filter"] = {
            "start_time": {
                **({"start_time": start} if start else {}),
                **({"end_time": end} if end else {}),
            }
        }
    return body


def _minutes_search_body(session: InterviewSession, query: str) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if query:
        body["query"] = query
    start = _rfc3339(int(session.start_time or 0) - 60 * 60)
    end = _rfc3339(int(session.end_time or session.start_time or 0) + 2 * 60 * 60)
    if start or end:
        body["filter"] = {
            "create_time": {
                **({"start_time": start} if start else {}),
                **({"end_time": end} if end else {}),
            }
        }
    return body


def _rfc3339(seconds: int) -> str:
    if seconds <= 0:
        return ""
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")


def _string_ids(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    single = clean_text(value)
    return [single] if single else []


def _append_unique(target: list[Any], items: list[Any]) -> None:
    for item in items:
        if item and item not in target:
            target.append(item)


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    _append_unique(result, [item for item in items if item])
    return result
