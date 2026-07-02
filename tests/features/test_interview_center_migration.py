from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from app.control_plane.main import create_app
from app.domain.resume.models import ResumeRecord
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.asset_sync import BitableAssetSync
from app.features.interview_center.feishu.bitable import (
    MockFeishuBitableClient,
    find_existing_bitable_record,
    pick_existing_bitable_fields,
)
from app.features.interview_center.feishu.calendar import normalize_calendar_event
from app.features.interview_center.feishu.routes import resolve_bitable_target
from app.features.interview_center.service import InterviewCenterService
from app.features.interview_center.store import InMemoryInterviewStore, SQLiteInterviewStore
from fastapi.testclient import TestClient


def test_bitable_route_resolution_uses_old_default_tables() -> None:
    ai = resolve_bitable_target({"resume": {"jobType": "AI应用开发实习生"}})
    hr = resolve_bitable_target({"resume": {"position": "HRBP"}})
    ops_b = resolve_bitable_target({"session": {"title": "B端社交媒体运营负责人面试"}})

    assert ai.table_id == "tblJTlyRbGdsbJmM"
    assert ai.table_name == "AI实习生"
    assert ai.route_matched is True
    assert ai.route_keyword == "AI应用开发实习生"
    assert hr.table_id == "tblbADJqkdRhRlxv"
    assert hr.table_name == "HR"
    assert ops_b.table_id == "tblXyHjYr0Ba1rhe"
    assert ops_b.table_name == "运营B表"


def test_bitable_record_matching_prefers_phone_over_name() -> None:
    records = [
        {"record_id": "name-record", "fields": {"姓名": "Alice"}},
        {
            "record_id": "phone-record",
            "fields": {"候选人联系电话": [{"text": "13800138000"}], "姓名": "Carol"},
        },
    ]

    match = find_existing_bitable_record(
        records,
        {"name": "Alice", "phone": "138 0013 8000"},
    )

    assert match.record["record_id"] == "phone-record"
    assert match.reason == "phone_match"


def test_bitable_record_matching_uses_single_exact_name_match() -> None:
    records = [
        {"record_id": "other", "fields": {"姓名": "Bob"}},
        {"record_id": "alice", "fields": {"候选人姓名": "Alice"}},
    ]

    match = find_existing_bitable_record(records, {"name": "Alice"})

    assert match.record["record_id"] == "alice"
    assert match.reason == "name_match"


def test_bitable_record_matching_skips_ambiguous_names() -> None:
    records = [
        {"record_id": "alice-1", "fields": {"姓名": "Alice"}},
        {"record_id": "alice-2", "fields": {"候选人姓名": "Alice"}},
    ]

    match = find_existing_bitable_record(records, {"name": "Alice"})

    assert match.record is None
    assert match.reason == "ambiguous_name_match"
    assert match.count == 2


def test_pick_existing_bitable_fields_filters_to_field_map() -> None:
    fields = {
        "姓名": "Alice",
        "候选人联系电话": "13800138000",
        "职位": "",
        "未知字段": "drop",
        "空值": None,
    }
    field_map = {
        "byName": {
            "姓名": {"field_name": "姓名"},
            "候选人联系电话": {"field_name": "候选人联系电话"},
            "职位": {"field_name": "职位"},
        }
    }

    assert pick_existing_bitable_fields(fields, field_map) == {
        "姓名": "Alice",
        "候选人联系电话": "13800138000",
    }


def test_normalize_calendar_event_detects_interview_like_event() -> None:
    normalized = normalize_calendar_event(
        "primary",
        {
            "event_id": "event-1",
            "summary": "Alice AI应用开发实习生一面",
            "description": "候选人电话 13800138000",
            "location": {"name": "线上会议"},
            "start_time": {"timestamp": "1783000000"},
            "end_time": {"timestamp": "1783003600"},
            "attendees": [
                {"user": {"name": "HR"}},
                {"attendee": {"email": "alice@example.com"}},
            ],
            "vchat": {"meeting_url": "https://meet.example/abc"},
        },
    )

    assert normalized["calendarId"] == "primary"
    assert normalized["feishuEventId"] == "event-1"
    assert normalized["title"] == "Alice AI应用开发实习生一面"
    assert normalized["location"] == "线上会议"
    assert normalized["attendees"] == ["HR", "alice@example.com"]
    assert normalized["meetingUrl"] == "https://meet.example/abc"
    assert normalized["startTime"] == 1_783_000_000
    assert normalized["endTime"] == 1_783_003_600
    assert normalized["isInterviewLike"] is True
    assert normalized["status"] == "synced"


def test_calendar_sync_upserts_matches_and_ignores_non_interviews() -> None:
    store = InMemoryInterviewStore()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        calendar_client=FakeCalendarClient(
            [
                {
                    "event_id": "event-1",
                    "summary": "Alice AI应用开发实习生面试",
                    "description": "候选人 13800138000",
                    "start_time": {"timestamp": "1783000000"},
                    "end_time": {"timestamp": "1783003600"},
                },
                {
                    "event_id": "event-2",
                    "summary": "部门周会",
                    "start_time": {"timestamp": "1783086400"},
                    "end_time": {"timestamp": "1783090000"},
                },
            ]
        ),
    )

    first = asyncio.run(service.sync_calendar(calendar_id="primary", auto_prepare=False))
    second = asyncio.run(service.sync_calendar(calendar_id="primary", auto_prepare=False))

    assert first["total"] == 2
    assert first["interviewLike"] == 1
    assert len(first["sessions"]) == 1
    assert first["sessions"][0]["resumeId"] == "resume-1"
    assert first["sessions"][0]["candidateName"] == "Alice"
    assert first["sessions"][0]["status"] == "matched"
    assert first["sessions"][0]["payload"]["isInterviewLike"] is True
    assert len(store.list()) == 2
    assert second["sessions"][0]["id"] == first["sessions"][0]["id"]


def test_interview_center_sync_api_routes_are_compatible() -> None:
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        calendar_client=FakeCalendarClient(
            [
                {
                    "event_id": "event-api",
                    "summary": "Alice 面试",
                    "description": "AI应用开发实习生",
                    "start_time": {"timestamp": "1783000000"},
                    "end_time": {"timestamp": "1783003600"},
                }
            ]
        ),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

        synced = client.post(
            "/api/interview-center/sync",
            json={"calendarId": "primary", "autoPrepare": False},
        )
        status = client.get("/api/interview-center/sync/status")

    assert synced.status_code == 200
    assert synced.json()["ok"] is True
    assert synced.json()["total"] == 1
    assert synced.json()["interviewLike"] == 1
    assert synced.json()["sessions"][0]["resumeId"] == "resume-1"
    assert synced.json()["logs"][0]["message"] == "manual calendar sync completed"
    assert status.status_code == 200
    assert status.json()["ok"] is True
    assert status.json()["running"] is False
    assert status.json()["lastResult"]["total"] == 1


def test_prepare_session_requires_bound_resume() -> None:
    store = InMemoryInterviewStore()
    session = store.create(resume_id="", candidate_name="", job_type="AI应用开发实习生")
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        llm=FakeLLM(),
        doc_client=FakeDocClient(),
    )

    with pytest.raises(ValueError, match="interview_session_resume_required"):
        asyncio.run(service.prepare_session(session.id))


def test_prepare_session_generates_question_set_and_feishu_doc() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
    )
    doc_client = FakeDocClient()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        llm=FakeLLM(),
        doc_client=doc_client,
    )

    result = asyncio.run(service.prepare_session(session.id))

    prepared = result["session"]
    assert prepared["status"] == "prepared"
    assert prepared["questions"][0]["question"] == "请介绍 Agent 项目"
    assert prepared["questionSet"]["questions"][0]["focus"] == "项目真实性"
    assert prepared["feishuDoc"]["documentId"] == "doc-1"
    assert prepared["feishuDoc"]["contentSynced"] is True
    assert doc_client.created[0]["title"] == "Alice-AI应用开发实习生-面试问题"
    assert "请介绍 Agent 项目" in doc_client.created[0]["text"]


def test_prepare_session_keeps_local_state_when_doc_creation_fails() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        llm=FakeLLM(),
        doc_client=FakeDocClient(error=RuntimeError("doc unavailable")),
    )

    result = asyncio.run(service.prepare_session(session.id))

    prepared = result["session"]
    assert prepared["status"] == "prepared_local"
    assert prepared["questionSet"]["questions"][0]["question"] == "请介绍 Agent 项目"
    assert prepared["feishuDoc"]["contentSynced"] is False
    assert prepared["feishuDoc"]["contentError"] == "doc unavailable"
    assert prepared["payload"]["prepareErrors"] == ["doc unavailable"]


def test_prepare_session_api_route_is_compatible() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        llm=FakeLLM(),
        doc_client=FakeDocClient(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.post(
            f"/api/interview-center/sessions/{session.id}/prepare",
            json={"force": False},
        )

    assert response.status_code == 200
    assert response.json()["session"]["status"] == "prepared"
    assert response.json()["session"]["feishuDoc"]["documentId"] == "doc-1"


def test_bitable_asset_sync_skips_existing_resume_attachment() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True},
    )
    table_id = "tblJTlyRbGdsbJmM"
    bitable = MockFeishuBitableClient(
        records={
            table_id: [
                {
                    "record_id": "rec-1",
                    "fields": {
                        "姓名": "Alice",
                        "候选人联系电话": "13800138000",
                        "简历": [{"file_token": "existing-token"}],
                    },
                }
            ]
        }
    )
    sync = BitableAssetSync(store=store, bitable=bitable)

    result = asyncio.run(
        sync.ensure_resume_image(
            session,
            _resume_payload(),
            resume_pdf_path="resume.pdf",
        )
    )

    assert result["skipped"] is True
    assert result["reason"] == "bitable_resume_field_already_has_attachment"
    assert result["recordId"] == "rec-1"
    assert not any(call["method"] == "upload_file" for call in bitable.calls)
    assert store.get(session.id).bitable_record_id == "rec-1"


def test_bitable_asset_sync_uploads_resume_image_and_creates_record() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True},
    )
    bitable = MockFeishuBitableClient()
    sync = BitableAssetSync(
        store=store,
        bitable=bitable,
        resume_image_renderer=lambda **_: "alice_resume.png",
    )

    result = asyncio.run(
        sync.ensure_resume_image(
            session,
            _resume_payload(),
            resume_pdf_path="resume.pdf",
        )
    )

    create_call = next(call for call in bitable.calls if call["method"] == "create_record")
    assert result["ok"] is True
    assert create_call["tableId"] == "tblJTlyRbGdsbJmM"
    assert create_call["fields"]["姓名"] == "Alice"
    assert create_call["fields"]["简历"] == [{"file_token": "mock-file-token:alice_resume.png"}]
    assert store.get(session.id).bitable_resume_image["field"] == "简历"


def test_bitable_asset_sync_guards_default_table_when_route_does_not_match() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="完全无关岗位",
        payload={"isInterviewLike": True},
    )
    bitable = MockFeishuBitableClient()
    sync = BitableAssetSync(store=store, bitable=bitable, default_table_id="default-table")

    result = asyncio.run(
        sync.ensure_resume_image(
            session,
            {**_resume_payload(), "jobType": "完全无关岗位", "job_type": "完全无关岗位"},
            resume_pdf_path="resume.pdf",
        )
    )

    assert result["skipped"] is True
    assert result["reason"] == "job_not_in_bitable_table"
    assert bitable.calls == []


def test_bitable_asset_sync_uses_second_interview_evaluation_field() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True},
    )
    session.interview_evaluation = {"round": "second", "summary": "建议复试通过"}
    store.save(session)
    bitable = MockFeishuBitableClient()
    sync = BitableAssetSync(store=store, bitable=bitable)

    result = asyncio.run(
        sync.ensure_evaluation_document(
            session,
            _resume_payload(),
            {
                "documentId": "doc-second",
                "url": "https://example.feishu.cn/docx/doc-second",
                "title": "复试评价",
            },
            second_round=True,
        )
    )

    create_call = next(call for call in bitable.calls if call["method"] == "create_record")
    assert result["ok"] is True
    assert "复试结果评价" in create_call["fields"]
    assert "技能评价" not in create_call["fields"]
    saved = store.get(session.id)
    assert saved.bitable_second_interview_evaluation_document["field"] == "复试结果评价"


def test_sqlite_store_upserts_calendar_event_by_feishu_event_id(tmp_path: Path) -> None:
    database = tmp_path / "interview.sqlite"
    store = SQLiteInterviewStore(database)

    first = store.upsert_from_calendar_event(
        {
            "feishuEventId": "event-1",
            "calendarId": "primary",
            "title": "Alice AI intern interview",
            "description": "first round",
            "startTime": 1_783_000_000,
            "endTime": 1_783_003_600,
            "isInterviewLike": True,
            "status": "synced",
        }
    )
    second = store.upsert_from_calendar_event(
        {
            "feishuEventId": "event-1",
            "calendarId": "primary",
            "title": "Alice AI intern interview updated",
            "description": "first round updated",
            "startTime": 1_783_000_100,
            "endTime": 1_783_003_700,
            "isInterviewLike": True,
            "status": "synced",
        }
    )

    assert second.id == first.id
    assert second.feishu_event_id == "event-1"
    assert second.calendar_id == "primary"
    assert second.start_time == 1_783_000_100
    assert second.end_time == 1_783_003_700
    assert second.payload["title"] == "Alice AI intern interview updated"
    assert len(store.list()) == 1


def test_sqlite_store_persists_feishu_oauth_token(tmp_path: Path) -> None:
    database = tmp_path / "interview.sqlite"
    store = SQLiteInterviewStore(database)

    store.save_token(
        {
            "accessToken": "user-access",
            "refreshToken": "refresh",
            "expiresAt": 1_783_100_000_000,
            "userInfo": {"open_id": "ou_1", "name": "HR"},
        }
    )

    restored = SQLiteInterviewStore(database).get_token()
    assert restored == {
        "accessToken": "user-access",
        "refreshToken": "refresh",
        "expiresAt": 1_783_100_000_000,
        "userInfo": {"open_id": "ou_1", "name": "HR"},
    }

    store.clear_token()
    assert SQLiteInterviewStore(database).get_token() is None


def test_sqlite_store_appends_and_lists_interview_logs(tmp_path: Path) -> None:
    database = tmp_path / "interview.sqlite"
    store = SQLiteInterviewStore(database)
    session = store.create(resume_id="resume-1", candidate_name="Alice", job_type="AI")

    store.append_log(session.id, "info", "calendar synced", {"total": 2})
    store.append_log(session.id, "warn", "bitable skipped", {"reason": "missing_config"})
    store.append_log("", "info", "global event", {})

    session_logs = store.list_logs(session.id, limit=10)
    assert [item["level"] for item in session_logs] == ["warn", "info"]
    assert session_logs[0]["message"] == "bitable skipped"
    assert session_logs[0]["payload"] == {"reason": "missing_config"}

    all_logs = store.list_logs("", limit=2)
    assert len(all_logs) == 2
    assert all_logs[0]["message"] == "global event"


class FakeCalendarClient:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.calls: list[dict[str, Any]] = []

    async def list_events(
        self,
        *,
        calendar_id: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "calendarId": calendar_id,
                "startTime": start_time,
                "endTime": end_time,
            }
        )
        return list(self.events)


class FakeDocClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.created: list[dict[str, Any]] = []

    async def create_document_from_text(self, title: str, text: str) -> dict[str, Any]:
        self.created.append({"title": title, "text": text})
        if self.error:
            raise self.error
        return {
            "documentId": "doc-1",
            "url": "https://example.feishu.cn/docx/doc-1",
            "title": title,
            "contentSynced": True,
        }


class FakeLLM:
    async def chat_completions(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        _ = messages, temperature
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            [
                                {
                                    "category": "项目",
                                    "question": "请介绍 Agent 项目",
                                    "focus": "项目真实性",
                                }
                            ],
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def _resume_record() -> ResumeRecord:
    return ResumeRecord(
        id="resume-1",
        payload={
            "name": "Alice",
            "phone": "13800138000",
            "job_type": "AI应用开发实习生",
            "rawText": "Alice 13800138000 Python LLM Agent",
        },
        phone_key="13800138000",
        job_type="AI应用开发实习生",
        match_score=90,
        updated_at="2026-01-01",
    )


def _resume_payload() -> dict[str, Any]:
    return {
        "id": "resume-1",
        "name": "Alice",
        "phone": "13800138000",
        "jobType": "AI应用开发实习生",
        "job_type": "AI应用开发实习生",
    }
