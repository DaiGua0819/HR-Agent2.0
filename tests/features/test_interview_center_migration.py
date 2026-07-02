from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.control_plane.main import create_app
from app.domain.resume.models import ResumeRecord
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.asset_sync import BitableAssetSync
from app.features.interview_center.calendar_sync import FeishuCalendarClient
from app.features.interview_center.feishu.bitable import (
    FeishuBitableClient,
    MockFeishuBitableClient,
    find_existing_bitable_record,
    pick_existing_bitable_fields,
)
from app.features.interview_center.feishu.calendar import normalize_calendar_event
from app.features.interview_center.feishu.client import FeishuStoredUserTokenProvider
from app.features.interview_center.feishu.docx import FeishuInterviewDocClient
from app.features.interview_center.feishu.meeting import FeishuMeetingSourceClient
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


def test_feishu_bitable_client_filters_fields_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "app-token")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer tenant-token"
        path = request.url.path
        if path == "/open-apis/bitable/v1/apps/app-token/tables/table-1/fields":
            if request.url.params.get("page_token") == "next":
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "items": [{"field_name": "简历"}],
                            "has_more": False,
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [{"field_name": "姓名"}],
                        "has_more": True,
                        "page_token": "next",
                    },
                },
            )
        if path == "/open-apis/bitable/v1/apps/app-token/tables/table-1/records":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload == {
                "fields": {"姓名": "Alice", "简历": [{"file_token": "file-1"}]}
            }
            assert request.url.params["user_id_type"] == "open_id"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"record": {"record_id": "rec-1", "fields": payload["fields"]}},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = FeishuBitableClient(
        token_provider=FakeTenantTokenProvider(),
        transport=httpx.MockTransport(handler),
        dry_run=False,
    )

    record = asyncio.run(
        client.create_record(
            "table-1",
            {
                "姓名": "Alice",
                "简历": [{"file_token": "file-1"}],
                "不存在字段": "drop",
            },
        )
    )

    assert record["record_id"] == "rec-1"
    assert [request.url.path for request in requests].count(
        "/open-apis/bitable/v1/apps/app-token/tables/table-1/fields"
    ) == 2


def test_feishu_bitable_client_uploads_file_with_drive_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "app-token")
    image_path = tmp_path / "summary.png"
    image_path.write_bytes(b"png-bytes")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer tenant-token"
        assert request.url.path == "/open-apis/drive/v1/medias/upload_all"
        body = request.content
        assert b'name="parent_node"' in body
        assert b"app-token" in body
        assert b'name="parent_type"' in body
        assert b"bitable_image" in body
        assert b"summary.png" in body
        return httpx.Response(
            200,
            json={"code": 0, "data": {"file_token": "uploaded-token"}},
        )

    client = FeishuBitableClient(
        token_provider=FakeTenantTokenProvider(),
        transport=httpx.MockTransport(handler),
        dry_run=False,
    )

    token = asyncio.run(client.upload_file(image_path))

    assert token == "uploaded-token"
    assert len(requests) == 1


def test_interview_center_service_uses_real_bitable_client_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "app-id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "app-secret")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "app-token")

    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
    )

    assert isinstance(service.bitable, FeishuBitableClient)


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


def test_calendar_sync_auto_prepare_generates_docs_for_matched_sessions() -> None:
    store = InMemoryInterviewStore()
    doc_client = FakeDocClient()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        calendar_client=FakeCalendarClient(
            [
                {
                    "event_id": "event-auto-prepare",
                    "summary": "Alice interview",
                    "description": "phone 13800138000",
                    "start_time": {"timestamp": "1783000000"},
                    "end_time": {"timestamp": "1783003600"},
                }
            ]
        ),
        llm=FakeLLM(),
        doc_client=doc_client,
    )

    result = asyncio.run(
        service.sync_calendar(
            calendar_id="primary",
            auto_prepare=True,
            auto_prepare_limit=1,
        )
    )

    assert result["prepared"] == 1
    assert result["prepareErrors"] == []
    assert result["sessions"][0]["status"] == "prepared"
    assert result["sessions"][0]["questionSet"]["questions"][0]["question"] == "请介绍 Agent 项目"
    assert result["sessions"][0]["feishuDoc"]["documentId"] == "doc-1"
    assert len(doc_client.created) == 1
    assert service.calendar_sync_status()["lastResult"]["prepared"] == 1


def test_calendar_sync_syncs_bound_resume_image_to_bitable() -> None:
    store = InMemoryInterviewStore()
    asset_sync = FakeAssetSync()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory(
            [
                _resume_record(
                    {
                        "pdfPath": "alice.pdf",
                    }
                )
            ]
        ),
        store=store,
        calendar_client=FakeCalendarClient(
            [
                {
                    "event_id": "event-bitable-resume",
                    "summary": "Alice interview",
                    "description": "phone 13800138000",
                    "start_time": {"timestamp": "1783000000"},
                    "end_time": {"timestamp": "1783003600"},
                }
            ]
        ),
        asset_sync=asset_sync,
    )

    result = asyncio.run(service.sync_calendar(calendar_id="primary", auto_prepare=False))

    assert result["bitableResumeResults"] == [
        {
            "sessionId": result["sessions"][0]["id"],
            "ok": True,
            "recordId": "resume-image-record",
        }
    ]
    assert asset_sync.calls == ["resume_image"]
    assert asset_sync.resume_image_calls[0]["resumePdfPath"] == "alice.pdf"
    status = service.calendar_sync_status()["lastResult"]
    assert status["bitableResumeSynced"] == 1
    assert status["bitableResumeSkipped"] == 0
    assert status["bitableResumeErrors"] == 0


def test_list_sessions_includes_old_interview_flow_payload() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Alice 二面面试"},
    )
    session.start_time = 4_000_000_000
    session.end_time = 4_000_003_600
    session.status = "matched"
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
    )

    [listed] = service.list_sessions()

    assert listed["interviewFlow"] == {
        "groupKey": "waiting",
        "groupLabel": "等待面试",
        "roundKey": "second",
        "roundLabel": "二面",
        "stageText": "",
        "source": "calendar",
        "recordId": "",
        "error": "",
    }


def test_sessions_api_prefers_bitable_interview_flow_stage() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Alice 初面"},
    )
    session.bitable_table_id = "table-stage"
    session.bitable_record_id = "rec-stage"
    session.start_time = 4_000_000_000
    session.end_time = 4_000_003_600
    session.status = "matched"
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        bitable=MockFeishuBitableClient(
            records={
                "table-stage": [
                    {
                        "record_id": "rec-stage",
                        "fields": {"面试阶段": "二面通过"},
                    }
                ]
            }
        ),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        response = client.get(
            "/api/interview-center/sessions",
            params={"startTime": 0, "endTime": 0},
        )

    flow = response.json()["sessions"][0]["interviewFlow"]
    assert flow["source"] == "bitable"
    assert flow["stageText"] == "二面通过"
    assert flow["recordId"] == "rec-stage"
    assert flow["groupKey"] == "completed"
    assert flow["roundKey"] == "second"


def test_sessions_api_uses_old_default_time_window() -> None:
    now = 2_000_000_000
    day_seconds = 86_400
    store = InMemoryInterviewStore()
    upcoming = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Alice 初面"},
    )
    upcoming.start_time = now + 3_600
    upcoming.end_time = now + 7_200
    store.save(upcoming)
    stale = store.create(
        resume_id="resume-old",
        candidate_name="Old",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Old 面试"},
    )
    stale.start_time = now - 2 * day_seconds
    stale.end_time = stale.start_time + 3_600
    store.save(stale)
    far_future = store.create(
        resume_id="resume-future",
        candidate_name="Future",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Future 面试"},
    )
    far_future.start_time = now + 15 * day_seconds
    far_future.end_time = far_future.start_time + 3_600
    store.save(far_future)
    non_interview = store.create(
        resume_id="resume-meeting",
        candidate_name="Meeting",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": False, "title": "项目例会"},
    )
    non_interview.start_time = now + 3_600
    non_interview.end_time = now + 7_200
    store.save(non_interview)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        now=lambda: now,
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        default_response = client.get("/api/interview-center/sessions")
        unbounded_response = client.get(
            "/api/interview-center/sessions",
            params={"startTime": 0, "endTime": 0},
        )

    default_ids = {item["id"] for item in default_response.json()["sessions"]}
    unbounded_ids = {item["id"] for item in unbounded_response.json()["sessions"]}
    assert default_response.status_code == 200
    assert default_ids == {upcoming.id}
    assert stale.id in unbounded_ids
    assert far_future.id in unbounded_ids
    assert non_interview.id not in unbounded_ids


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


def test_interview_center_sync_api_defaults_to_auto_prepare_without_body() -> None:
    doc_client = FakeDocClient()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        calendar_client=FakeCalendarClient(
            [
                {
                    "event_id": "event-api-auto-prepare",
                    "summary": "Alice 面试",
                    "description": "phone 13800138000",
                    "start_time": {"timestamp": "1783000000"},
                    "end_time": {"timestamp": "1783003600"},
                }
            ]
        ),
        llm=FakeLLM(),
        doc_client=doc_client,
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        synced = client.post("/api/interview-center/sync")

    assert synced.status_code == 200
    assert synced.json()["ok"] is True
    assert synced.json()["prepared"] == 1
    assert synced.json()["sessions"][0]["status"] == "prepared"
    assert synced.json()["sessions"][0]["feishuDoc"]["documentId"] == "doc-1"
    assert len(doc_client.created) == 1


def test_interview_center_sync_uses_old_js_body_defaults() -> None:
    doc_client = FakeDocClient()
    calendar_client = FakeCalendarClient(
        [
            {
                "event_id": "event-sync-js-defaults",
                "summary": "Alice 面试",
                "description": "phone 13800138000",
                "start_time": {"timestamp": "1783000000"},
                "end_time": {"timestamp": "1783003600"},
            }
        ]
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        calendar_client=calendar_client,
        llm=FakeLLM(),
        doc_client=doc_client,
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        synced = client.post(
            "/api/interview-center/sync",
            json={"calendarId": "", "autoPrepare": "false", "autoPrepareLimit": 0},
        )

    assert synced.status_code == 200
    assert synced.json()["ok"] is True
    assert synced.json()["prepared"] == 1
    assert calendar_client.calls[0]["calendarId"] == "primary"
    assert len(doc_client.created) == 1


def test_old_action_routes_treat_malformed_json_body_as_empty_like_old_node() -> None:
    doc_client = FakeDocClient()
    sync_service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        calendar_client=FakeCalendarClient(
            [
                {
                    "event_id": "event-malformed-sync",
                    "summary": "Alice 面试",
                    "description": "phone 13800138000",
                    "start_time": {"timestamp": "1783000000"},
                    "end_time": {"timestamp": "1783003600"},
                }
            ]
        ),
        llm=FakeLLM(),
        doc_client=doc_client,
    )
    sync_app = create_app()
    sync_app.state.interview_center_service = sync_service

    prepare_store = InMemoryInterviewStore()
    prepare_session = _backfill_session(prepare_store)
    prepare_service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=prepare_store,
        llm=FakeLLM(),
        doc_client=FakeDocClient(),
    )
    prepare_app = create_app()
    prepare_app.state.interview_center_service = prepare_service

    backfill_store = InMemoryInterviewStore()
    backfill_session = _backfill_session(backfill_store)
    backfill_service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=backfill_store,
        meeting_client=FakeMeetingClient(text="候选人项目扎实，建议通过"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: backfill_session.end_time + 601,
    )
    backfill_app = create_app()
    backfill_app.state.interview_center_service = backfill_service

    review_store = InMemoryInterviewStore()
    review_session_record = _backfill_session(review_store)
    review_session_record.status = "needs_review"
    review_session_record.interview_evaluation = {
        "summary": "候选人项目扎实",
        "humanReviewRequired": True,
    }
    review_store.save(review_session_record)
    review_service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=review_store,
        asset_sync=FakeAssetSync(),
    )
    review_app = create_app()
    review_app.state.interview_center_service = review_service
    malformed_body = "{"
    headers = {"content-type": "application/json"}

    with TestClient(sync_app) as client:
        synced = client.post(
            "/api/interview-center/sync",
            content=malformed_body,
            headers=headers,
        )
    with TestClient(prepare_app) as client:
        prepared = client.post(
            f"/api/interview-center/sessions/{prepare_session.id}/prepare",
            content=malformed_body,
            headers=headers,
        )
    with TestClient(backfill_app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{backfill_session.id}/backfill",
            content=malformed_body,
            headers=headers,
        )
    with TestClient(review_app) as client:
        reviewed = client.post(
            f"/api/interview-center/sessions/{review_session_record.id}/review",
            content=malformed_body,
            headers=headers,
        )

    assert synced.status_code == 200
    assert synced.json()["ok"] is True
    assert synced.json()["prepared"] == 1
    assert prepared.status_code == 200
    assert prepared.json()["session"]["status"] in {"prepared", "prepared_local"}
    assert backfilled.status_code == 200
    assert backfilled.json()["session"]["status"] == "needs_review"
    assert reviewed.status_code == 200
    assert reviewed.json()["session"]["status"] == "completed"
    assert reviewed.json()["session"]["interviewEvaluation"]["review"]["decision"] == "passed"


def test_prepare_api_uses_old_js_boolean_force_semantics() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.question_set = {
        "questions": [{"question": "old question", "focus": "old"}],
        "jobType": session.job_type,
    }
    session.questions = list(session.question_set["questions"])
    session.feishu_doc = {
        "documentId": "old-doc",
        "url": "https://example.feishu.cn/docx/old-doc",
        "contentSynced": True,
    }
    store.save(session)
    doc_client = FakeDocClient()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        llm=FakeLLM(),
        doc_client=doc_client,
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        prepared = client.post(
            f"/api/interview-center/sessions/{session.id}/prepare",
            json={"force": "false"},
        )

    assert prepared.status_code == 200
    assert prepared.json()["session"]["feishuDoc"]["documentId"] == "doc-1"
    assert len(doc_client.created) == 1


def test_backfill_api_uses_old_js_boolean_force_semantics() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.interview_evaluation = {
        "summary": "old evaluation",
        "humanReviewRequired": True,
    }
    store.save(session)
    meeting_client = FakeMeetingClient(text="候选人项目扎实，建议通过")
    evaluation_generator = FakeEvaluationGenerator()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=meeting_client,
        evaluation_generator=evaluation_generator,
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 601,
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={"force": "false"},
        )

    assert backfilled.status_code == 200
    assert backfilled.json()["session"]["status"] == "needs_review"
    assert backfilled.json()["session"]["interviewEvaluation"]["summary"] == "候选人项目扎实"
    assert meeting_client.calls == 1
    assert evaluation_generator.calls == 1


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
    assert response.json()["ok"] is True
    assert response.json()["session"]["status"] == "prepared"
    assert response.json()["session"]["feishuDoc"]["documentId"] == "doc-1"
    assert isinstance(response.json()["logs"], list)


def test_bind_session_persists_manual_resume_binding() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="",
        candidate_name="",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Alice 一面"},
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
    )

    result = asyncio.run(service.bind_session(session.id, resume_id="resume-1"))

    bound = result["session"]
    assert bound["resumeId"] == "resume-1"
    assert bound["status"] == "matched"
    assert bound["resume"]["name"] == "Alice"
    assert bound["resume"]["jobType"] == "AI应用开发实习生"
    assert bound["matchedResume"] == {
        "id": "resume-1",
        "name": "Alice",
        "jobType": "AI应用开发实习生",
    }
    assert bound["matchMode"] == "manual"
    assert bound["manualBoundAt"]
    assert store.list_logs(session.id, limit=1)[0]["message"] == "已人工绑定候选人"


def test_bind_and_sessions_api_routes_are_compatible() -> None:
    store = InMemoryInterviewStore()
    interview_session = store.create(
        resume_id="",
        candidate_name="",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Alice 面试"},
    )
    ignored_session = store.create(
        resume_id="",
        candidate_name="Bob",
        job_type="运营",
        payload={"isInterviewLike": False, "title": "Bob 周会"},
    )
    ignored_session.start_time = interview_session.start_time + 1
    store.save(ignored_session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        bound = client.post(
            f"/api/interview-center/sessions/{interview_session.id}/bind",
            json={"resumeId": "resume-1", "prepare": False},
        )
        listed = client.get("/api/interview-center/sessions")

    assert bound.status_code == 200
    assert bound.json()["ok"] is True
    assert bound.json()["session"]["resumeId"] == "resume-1"
    assert bound.json()["session"]["matchedResume"]["name"] == "Alice"
    assert bound.json()["logs"][0]["message"] == "已人工绑定候选人"
    assert listed.status_code == 200
    assert listed.json()["ok"] is True
    assert [item["id"] for item in listed.json()["sessions"]] == [interview_session.id]
    assert listed.json()["items"] == listed.json()["sessions"]
    assert listed.json()["status"]["connected"] is False
    assert listed.json()["logs"][0]["message"] == "已人工绑定候选人"


def test_bind_api_accepts_empty_body_like_old_node() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="",
        candidate_name="",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": "Alice 面试"},
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        response = client.post(f"/api/interview-center/sessions/{session.id}/bind")
        unknown_session = client.post("/api/interview-center/sessions/missing-session/bind")

    assert response.status_code == 404
    assert response.json() == {"ok": False, "error": "候选人简历不存在"}
    assert unknown_session.status_code == 404
    assert unknown_session.json() == {"ok": False, "error": "候选人简历不存在"}


def test_unknown_interview_center_route_uses_old_error_payload() -> None:
    app = create_app()

    with TestClient(app) as client:
        unknown = client.get("/api/interview-center/unknown")
        unknown_action = client.post("/api/interview-center/sessions/session-1/unknown")

    assert unknown.status_code == 404
    assert unknown.json() == {"ok": False, "error": "未知面试中心接口"}
    assert unknown_action.status_code == 404
    assert unknown_action.json() == {"ok": False, "error": "未知面试中心接口"}


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


def test_backfill_blocks_until_ten_minutes_after_interview_end() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True},
    )
    session.end_time = 1_783_003_600
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="面试记录"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )

    with pytest.raises(ValueError, match="backfill_not_available"):
        asyncio.run(service.backfill_session(session.id))


def test_backfill_allows_old_one_off_early_override_token() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.payload = {
        **session.payload,
        "earlyBackfillOverride": {
            "allowed": True,
            "token": "override-secret",
            "expiresAt": "2099-01-01T00:00:00Z",
            "reason": "manual emergency",
        },
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="提前回灌授权测试"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )

    result = asyncio.run(
        service.backfill_session(
            session.id,
            force=True,
            early_override=True,
            early_override_token="override-secret",
        )
    )

    override = result["session"]["earlyBackfillOverride"]
    assert result["session"]["status"] == "needs_review"
    assert override["allowed"] is True
    assert override["usedAt"]
    assert override["availableAt"] == session.end_time + 600
    assert override["reason"] == "manual emergency"


def test_backfill_old_early_override_failure_records_failed_at() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.payload = {
        **session.payload,
        "earlyBackfillOverride": {
            "allowed": True,
            "token": "override-secret",
            "expiresAt": "2099-01-01T00:00:00Z",
            "reason": "manual emergency",
        },
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="提前读取面试记录"),
        evaluation_generator=FailingEvaluationGenerator(ValueError("llm_json_parse_failed")),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )

    result = asyncio.run(
        service.backfill_session(
            session.id,
            force=True,
            early_override=True,
            early_override_token="override-secret",
            early_override_reason="operator failed reason",
        )
    )

    override = result["session"]["earlyBackfillOverride"]
    assert result["session"]["status"] == "backfill_failed"
    assert result["session"]["lastBackfillError"] == "llm_json_parse_failed"
    assert override["allowed"] is True
    assert override["failedAt"]
    assert "usedAt" not in override
    assert override["availableAt"] == session.end_time + 600
    assert override["reason"] == "operator failed reason"


def test_list_sessions_clears_premature_backfill_from_session_and_resume() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.status = "needs_review"
    session.feishu_doc = {"documentId": "doc-1", "contentSynced": True}
    session.interview_evaluation = {
        "sessionId": session.id,
        "summary": "premature evaluation",
        "source": {"source": "fake_meeting"},
    }
    session.backfill_source = {"source": "fake_meeting"}
    session.rule_suggestion_ids = ["rule-1"]
    session.last_backfill_error = "old error"
    store.save(session)
    repository = ResumeRepository.in_memory(
        [_resume_record({"interviewEvaluation": dict(session.interview_evaluation)})]
    )
    service = InterviewCenterService(
        repository=repository,
        store=store,
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )

    [listed] = service.list_sessions()

    assert listed["status"] == "prepared"
    assert listed["interviewEvaluation"] == {}
    assert listed["backfillSource"] == {}
    assert listed["ruleSuggestionIds"] == []
    assert listed["lastBackfillError"] == ""
    stale = listed["staleInterviewEvaluation"]
    assert stale["reason"] == "interview_not_finished"
    assert stale["source"] == "sessions_response"
    assert stale["evaluation"]["summary"] == "premature evaluation"
    assert listed["staleInterviewEvaluationHistory"][0] == stale
    saved = store.get(session.id)
    assert saved.interview_evaluation == {}
    assert saved.backfill_source == {}
    assert saved.rule_suggestion_ids == []
    saved_resume = repository.get("resume-1")
    assert "interviewEvaluation" not in saved_resume.payload
    assert (
        saved_resume.payload["staleInterviewEvaluation"]["evaluation"]["summary"]
        == "premature evaluation"
    )


def test_backfill_fails_when_sources_are_empty() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text=""),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 601,
    )

    result = asyncio.run(service.backfill_session(session.id, force=True))

    assert result["session"]["status"] == "backfill_failed"
    assert result["session"]["lastBackfillError"] == "no_valid_interview_record"
    assert result["session"]["backfillSource"]["source"] == "fake_meeting"


def test_backfill_marks_session_failed_when_evaluation_generation_errors_like_old_node() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    repository = ResumeRepository.in_memory([_resume_record()])
    service = InterviewCenterService(
        repository=repository,
        store=store,
        meeting_client=FakeMeetingClient(text="候选人项目扎实，建议通过"),
        evaluation_generator=FailingEvaluationGenerator(ValueError("llm_json_parse_failed")),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 601,
    )

    result = asyncio.run(service.backfill_session(session.id, force=True))

    assert result["session"]["status"] == "backfill_failed"
    assert result["session"]["lastBackfillError"] == "llm_json_parse_failed"
    assert result["session"]["backfillAttempts"] == 1
    assert "interviewEvaluation" not in repository.get("resume-1").payload
    logs = store.list_logs(session.id, limit=10)
    assert logs[0]["level"] == "error"
    assert logs[0]["message"] == "llm_json_parse_failed"


def test_backfill_persists_evaluation_updates_resume_and_calls_assets() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    repository = ResumeRepository.in_memory([_resume_record()])
    asset_sync = FakeAssetSync()
    service = InterviewCenterService(
        repository=repository,
        store=store,
        meeting_client=FakeMeetingClient(text="候选人项目扎实，建议通过"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=asset_sync,
        now=lambda: session.end_time + 601,
    )

    result = asyncio.run(service.backfill_session(session.id, force=True))

    assert result["session"]["status"] == "needs_review"
    assert result["session"]["interviewEvaluation"]["summary"] == "候选人项目扎实"
    assert result["session"]["interviewEvaluation"]["humanReviewRequired"] is True
    assert repository.get("resume-1").payload["interviewEvaluation"]["sessionId"] == session.id
    assert asset_sync.calls == ["interview_record_image", "evaluation_document"]


def test_backfill_keeps_evaluation_when_asset_sync_fails() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    repository = ResumeRepository.in_memory([_resume_record()])
    service = InterviewCenterService(
        repository=repository,
        store=store,
        meeting_client=FakeMeetingClient(text="候选人项目扎实，建议通过"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FailingAssetSync(),
        now=lambda: session.end_time + 601,
    )

    result = asyncio.run(service.backfill_session(session.id, force=True))

    assert result["session"]["status"] == "needs_review"
    assert result["session"]["interviewEvaluation"]["summary"] == "候选人项目扎实"
    assert result["session"]["lastBackfillError"] == ""
    assert repository.get("resume-1").payload["interviewEvaluation"]["sessionId"] == session.id
    logs = store.list_logs(session.id, limit=10)
    assert any(
        item["level"] == "warn" and item["message"] == "asset_sync_failed"
        for item in logs
    )


def test_backfill_syncs_missing_evaluation_document_without_force_like_old_node() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.status = "needs_review"
    session.interview_evaluation = {
        "summary": "已有面评",
        "humanReviewRequired": True,
        "sessionId": session.id,
    }
    session.feishu_doc = {
        "documentId": "doc-existing",
        "url": "https://example.feishu.cn/docx/doc-existing",
        "title": "Alice 面试题",
    }
    store.save(session)
    repository = ResumeRepository.in_memory(
        [_resume_record({"interviewEvaluation": dict(session.interview_evaluation)})]
    )
    meeting_client = FakeMeetingClient(text="新的会议记录不应被读取")
    evaluation_generator = FakeEvaluationGenerator()
    asset_sync = FakeAssetSync()
    service = InterviewCenterService(
        repository=repository,
        store=store,
        meeting_client=meeting_client,
        evaluation_generator=evaluation_generator,
        asset_sync=asset_sync,
        now=lambda: session.end_time + 601,
    )

    result = asyncio.run(service.backfill_session(session.id, force=False))

    assert result["session"]["interviewEvaluation"]["summary"] == "已有面评"
    assert result["session"]["status"] == "needs_review"
    assert repository.get("resume-1").payload["interviewEvaluation"]["summary"] == "已有面评"
    assert meeting_client.calls == 0
    assert evaluation_generator.calls == 0
    assert asset_sync.calls == ["evaluation_document"]
    assert result["session"]["bitableSkillEvaluationDocument"]["field"] == "技能评价"
    assert (
        result["session"]["bitableSkillEvaluationDocument"]["documentId"]
        == "evaluation:" + session.id
    )
    assert result["session"]["bitableSkillEvaluationDocument"]["url"] == session.feishu_doc["url"]


def test_backfill_existing_evaluation_uses_session_round_for_second_document() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.status = "needs_review"
    session.payload = {
        **session.payload,
        "title": "Alice 二面面试",
        "description": "复试安排",
    }
    session.interview_evaluation = {
        "summary": "已有二面面评",
        "humanReviewRequired": True,
        "sessionId": session.id,
    }
    session.feishu_doc = {
        "documentId": "doc-second",
        "url": "https://example.feishu.cn/docx/doc-second",
        "title": "Alice 二面题",
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="新的会议记录不应被读取"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 601,
    )

    result = asyncio.run(service.backfill_session(session.id, force=False))

    assert result["session"]["interviewEvaluation"]["summary"] == "已有二面面评"
    assert result["session"]["bitableSkillEvaluationDocument"] == {}
    second_document = result["session"]["bitableSecondInterviewEvaluationDocument"]
    assert second_document["field"] == "复试结果评价"
    assert second_document["documentId"] == "evaluation:" + session.id
    assert second_document["url"] == session.feishu_doc["url"]


def test_review_session_updates_session_and_resume_evaluation() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.status = "needs_review"
    session.interview_evaluation = {
        "summary": "候选人项目扎实",
        "humanReviewRequired": True,
    }
    store.save(session)
    repository = ResumeRepository.in_memory([_resume_record()])
    service = InterviewCenterService(
        repository=repository,
        store=store,
        asset_sync=FakeAssetSync(),
    )

    result = asyncio.run(
        service.review_session(session.id, decision="need_followup", note="补充系统设计追问")
    )

    assert result["session"]["status"] == "needs_review"
    assert result["session"]["interviewEvaluation"]["humanReviewRequired"] is True
    assert result["session"]["interviewEvaluation"]["review"]["decision"] == "need_followup"
    assert result["session"]["humanReview"]["confirmed"] is True
    saved_resume = repository.get("resume-1")
    assert saved_resume.payload["interviewEvaluation"]["review"]["note"] == "补充系统设计追问"
    assert store.list_logs(session.id, limit=1)[0]["message"] == "interview review completed"


def test_backfill_api_routes_are_compatible() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="候选人项目扎实，建议通过"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 601,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={"force": True},
        )
        source = client.get(f"/api/interview-center/sessions/{session.id}/backfill-source")
        status = client.get("/api/interview-center/backfill/status")

    assert backfilled.status_code == 200
    assert backfilled.json()["ok"] is True
    assert backfilled.json()["session"]["status"] == "needs_review"
    assert source.status_code == 200
    assert source.json()["source"]["source"] == "fake_meeting"
    assert status.status_code == 200
    assert status.json()["lastResult"]["sessionId"] == session.id


def test_backfill_api_accepts_empty_body_like_old_node() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="候选人项目扎实，建议通过"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 601,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        backfilled = client.post(f"/api/interview-center/sessions/{session.id}/backfill")

    assert backfilled.status_code == 200
    assert backfilled.json()["ok"] is True
    assert backfilled.json()["session"]["status"] == "needs_review"
    assert backfilled.json()["session"]["interviewEvaluation"]["summary"] == "候选人项目扎实"


def test_backfill_api_rejects_invalid_old_early_override_with_403() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    original_status = session.status
    session.payload = {
        **session.payload,
        "earlyBackfillOverride": {
            "allowed": True,
            "token": "override-secret",
            "expiresAt": "2099-01-01T00:00:00Z",
        },
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="不应读取"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={
                "force": True,
                "earlyOverride": True,
                "earlyOverrideToken": "wrong-token",
            },
        )

    assert backfilled.status_code == 403
    assert backfilled.json() == {
        "ok": False,
        "error": "提前回灌未授权或授权已使用，已停止避免误读会议纪要",
    }
    assert store.get(session.id).status == original_status


def test_backfill_api_requires_force_for_old_early_override_token() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    original_status = session.status
    session.payload = {
        **session.payload,
        "earlyBackfillOverride": {
            "allowed": True,
            "token": "override-secret",
            "expiresAt": "2099-01-01T00:00:00Z",
        },
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="不应读取"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={
                "earlyOverride": True,
                "earlyOverrideToken": "override-secret",
            },
        )

    assert backfilled.status_code == 409
    assert backfilled.json()["ok"] is False
    assert backfilled.json()["error"] == "面试结束后 10 分钟才可读取纪要"
    assert backfilled.json()["availableAt"] == session.end_time + 600
    assert backfilled.json()["endTime"] == session.end_time
    assert store.get(session.id).status == original_status


def test_backfill_api_persists_old_early_override_reason_from_body() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.payload = {
        **session.payload,
        "earlyBackfillOverride": {
            "allowed": True,
            "token": "override-secret",
            "expiresAt": "2099-01-01T00:00:00Z",
            "reason": "stored reason",
        },
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="提前读取面试记录"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={
                "force": True,
                "earlyOverride": True,
                "earlyOverrideToken": "override-secret",
                "earlyOverrideReason": "manual operator reason",
            },
        )

    assert backfilled.status_code == 200
    override = backfilled.json()["session"]["earlyBackfillOverride"]
    assert override["reason"] == "manual operator reason"
    assert override["usedAt"]


def test_backfill_api_uses_old_js_string_semantics_for_early_override_reason() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.payload = {
        **session.payload,
        "earlyBackfillOverride": {
            "allowed": True,
            "token": "override-secret",
            "expiresAt": "2099-01-01T00:00:00Z",
            "reason": "stored reason",
        },
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="early override meeting notes"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={
                "force": True,
                "earlyOverride": True,
                "earlyOverrideToken": "override-secret",
                "earlyOverrideReason": {"source": "manual"},
            },
        )

    assert backfilled.status_code == 200
    override = backfilled.json()["session"]["earlyBackfillOverride"]
    assert override["reason"] == "[object Object]"
    assert override["usedAt"]


def test_backfill_api_clips_early_override_reason_like_old_node_clip_text() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.payload = {
        **session.payload,
        "earlyBackfillOverride": {
            "allowed": True,
            "token": "override-secret",
            "expiresAt": "2099-01-01T00:00:00Z",
            "reason": "stored reason",
        },
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="early override meeting notes"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 599,
    )
    app = create_app()
    app.state.interview_center_service = service
    reason = f"  {'r' * 301}  "
    with TestClient(app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={
                "force": True,
                "earlyOverride": True,
                "earlyOverrideToken": "override-secret",
                "earlyOverrideReason": reason,
            },
        )

    assert backfilled.status_code == 200
    override = backfilled.json()["session"]["earlyBackfillOverride"]
    assert override["reason"] == ("r" * 300) + "..."


def test_old_interview_center_errors_use_error_payload_for_frontend() -> None:
    store = InMemoryInterviewStore()
    session = store.create(
        resume_id="",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"title": "Alice 面试"},
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        asset_sync=FakeAssetSync(),
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        missing = client.get("/api/interview-center/sessions/missing-session")
        unbound = client.post(f"/api/interview-center/sessions/{session.id}/prepare")

    assert missing.status_code == 404
    assert missing.json() == {
        "ok": False,
        "error": "面试日程不存在",
    }
    assert unbound.status_code == 409
    assert unbound.json() == {
        "ok": False,
        "error": "该日程尚未绑定候选人",
    }


def test_backfill_source_payload_is_normalized_like_old_node() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient(text="候选人项目扎实，建议通过"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: session.end_time + 601,
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        backfilled = client.post(
            f"/api/interview-center/sessions/{session.id}/backfill",
            json={"force": True},
        )
        source_response = client.get(
            f"/api/interview-center/sessions/{session.id}/backfill-source"
        )

    expected_defaults = {
        "source": "fake_meeting",
        "types": [],
        "rawTextLength": 0,
        "linkedDocIds": [],
        "minuteTokens": [],
        "sources": [],
        "errors": [],
    }
    assert backfilled.status_code == 200
    for key, value in expected_defaults.items():
        assert backfilled.json()["session"]["backfillSource"][key] == value
    assert source_response.status_code == 200
    for key, value in expected_defaults.items():
        assert source_response.json()["source"][key] == value


def test_backfill_source_falls_back_to_evaluation_source_like_old_node() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.backfill_source = {}
    session.interview_evaluation = {
        "summary": "stored evaluation",
        "source": {
            "source": "evaluation_source",
            "types": ("doc",),
            "rawTextLength": "123",
            "linkedDocIds": ("doc-1",),
            "minuteTokens": ("minute-1",),
            "sources": [
                {
                    "type": "doc",
                    "id": "doc-1",
                    "url": "https://example.test/doc",
                    "length": "123",
                }
            ],
            "errors": ("source warning",),
        },
    }
    session.last_backfill_error = "source warning"
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        asset_sync=FakeAssetSync(),
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        response = client.get(f"/api/interview-center/sessions/{session.id}/backfill-source")

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["source"]["source"] == "evaluation_source"
    assert payload["source"]["types"] == ["doc"]
    assert payload["source"]["rawTextLength"] == 123
    assert payload["source"]["linkedDocIds"] == ["doc-1"]
    assert payload["source"]["minuteTokens"] == ["minute-1"]
    assert payload["source"]["sources"] == [
        {"type": "doc", "id": "doc-1", "url": "https://example.test/doc", "length": 123}
    ]
    assert payload["source"]["errors"] == ["source warning"]
    assert payload["lastBackfillError"] == "source warning"


def test_auto_calendar_tick_skips_when_feishu_is_not_connected() -> None:
    calendar_client = FakeCalendarClient(
        [
            {
                "event_id": "event-auto",
                "summary": "Alice 面试",
                "start_time": {"timestamp": "1783000000"},
            }
        ]
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        calendar_client=calendar_client,
    )

    status = asyncio.run(service.run_auto_calendar_sync_tick())

    assert status["enabled"] is True
    assert status["running"] is False
    assert status["intervalMs"] >= 60_000
    assert status["lastError"] == "飞书未授权，跳过自动日历同步"
    assert calendar_client.calls == []


def test_auto_calendar_tick_runs_full_service_sync_when_connected() -> None:
    store = InMemoryInterviewStore()
    store.save_token({"accessToken": "user-access", "expiresAt": 999_999_999_999})
    asset_sync = FakeAssetSync()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record({"pdfPath": "alice.pdf"})]),
        store=store,
        calendar_client=FakeCalendarClient(
            [
                {
                    "event_id": "event-auto-connected",
                    "summary": "Alice interview",
                    "description": "phone 13800138000",
                    "start_time": {"timestamp": "1783000000"},
                    "end_time": {"timestamp": "1783003600"},
                }
            ]
        ),
        asset_sync=asset_sync,
    )

    status = asyncio.run(service.run_auto_calendar_sync_tick())

    assert status["lastError"] == ""
    assert status["lastResult"]["source"] == "auto"
    assert status["lastResult"]["interviewLike"] == 1
    assert status["lastResult"]["bitableResumeSynced"] == 1
    assert status["lastResult"]["bitableResumeSkipped"] == 0
    assert status["lastResult"]["bitableResumeErrors"] == 0
    assert asset_sync.calls == ["resume_image"]
    assert asset_sync.resume_image_calls[0]["resumePdfPath"] == "alice.pdf"


def test_auto_backfill_tick_processes_due_candidates_with_limit() -> None:
    store = InMemoryInterviewStore()
    first = _auto_backfill_candidate(store, "first", end_time=1_783_003_000)
    second = _auto_backfill_candidate(store, "second", end_time=1_783_003_100)
    third = _auto_backfill_candidate(store, "third", end_time=1_783_003_200)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        meeting_client=FakeMeetingClient("候选人完整回答了 Agent 项目"),
        evaluation_generator=FakeEvaluationGenerator(),
        asset_sync=FakeAssetSync(),
        now=lambda: 1_783_004_000,
    )

    status = asyncio.run(service.run_auto_backfill_tick(max_per_tick=2, max_attempts=3))

    assert status["enabled"] is True
    assert status["running"] is False
    assert status["maxPerTick"] == 2
    assert status["maxAttempts"] == 3
    assert [item["sessionId"] for item in status["lastProcessed"]] == [
        first.id,
        second.id,
    ]
    assert all(item["status"] == "needs_review" for item in status["lastProcessed"])
    assert status["pendingCount"] == 1
    assert status["inFlightSessionIds"] == []
    assert store.get(first.id).status == "needs_review"
    assert store.get(second.id).status == "needs_review"
    assert store.get(third.id).status == "prepared"


def test_interview_center_schedulers_start_and_stop_background_ticks() -> None:
    async def run_scheduler_once() -> InterviewCenterService:
        service = InterviewCenterService(
            repository=ResumeRepository.in_memory([_resume_record()]),
            store=InMemoryInterviewStore(),
            calendar_client=FakeCalendarClient([]),
            now=lambda: 1_783_004_000,
        )
        service.start_schedulers(
            initial_calendar_delay=0.01,
            initial_backfill_delay=0.01,
        )
        await asyncio.sleep(0.05)
        await service.stop_schedulers()
        return service

    service = asyncio.run(run_scheduler_once())

    assert service.calendar_sync.last_error == "飞书未授权，跳过自动日历同步"
    assert service.backfill_status()["lastRunAt"]
    assert service.scheduler_running is False


def test_review_confirm_and_logs_api_routes_are_compatible() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.status = "needs_review"
    session.interview_evaluation = {
        "summary": "候选人项目扎实",
        "humanReviewRequired": True,
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        asset_sync=FakeAssetSync(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        reviewed = client.post(
            f"/api/interview-center/sessions/{session.id}/review",
            json={"decision": "passed", "note": "通过人工复核"},
        )
        confirmed = client.post(
            f"/api/interview-center/sessions/{session.id}/confirm",
            json={"decision": "rejected", "note": "暂不通过"},
        )
        logs = client.get(
            "/api/interview-center/logs",
            params={"sessionId": session.id, "limit": 5},
        )

    assert reviewed.status_code == 200
    assert reviewed.json()["ok"] is True
    assert reviewed.json()["session"]["status"] == "completed"
    assert reviewed.json()["session"]["interviewEvaluation"]["review"]["decision"] == "passed"
    assert confirmed.status_code == 200
    assert confirmed.json()["session"]["status"] == "completed"
    assert confirmed.json()["session"]["interviewEvaluation"]["review"]["decision"] == "rejected"
    assert logs.status_code == 200
    assert logs.json()["ok"] is True
    assert logs.json()["logs"][0]["message"] == "interview review completed"


def test_review_and_confirm_api_accept_empty_body_like_old_node() -> None:
    store = InMemoryInterviewStore()
    review_session_record = _backfill_session(store)
    review_session_record.status = "needs_review"
    review_session_record.interview_evaluation = {
        "summary": "候选人项目扎实",
        "humanReviewRequired": True,
    }
    store.save(review_session_record)
    confirm_session_record = _backfill_session(store)
    confirm_session_record.status = "needs_review"
    confirm_session_record.interview_evaluation = {
        "summary": "候选人表达清晰",
        "humanReviewRequired": True,
    }
    store.save(confirm_session_record)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        asset_sync=FakeAssetSync(),
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        reviewed = client.post(
            f"/api/interview-center/sessions/{review_session_record.id}/review"
        )
        confirmed = client.post(
            f"/api/interview-center/sessions/{confirm_session_record.id}/confirm"
        )

    assert reviewed.status_code == 200
    assert reviewed.json()["ok"] is True
    assert reviewed.json()["session"]["status"] == "completed"
    assert reviewed.json()["session"]["interviewEvaluation"]["review"]["decision"] == "passed"
    assert reviewed.json()["session"]["interviewEvaluation"]["review"]["note"] == ""
    assert confirmed.status_code == 200
    assert confirmed.json()["ok"] is True
    assert confirmed.json()["session"]["status"] == "completed"
    assert confirmed.json()["session"]["interviewEvaluation"]["review"]["decision"] == "passed"


def test_review_api_preserves_decision_when_note_uses_old_js_string_semantics() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.status = "needs_review"
    session.interview_evaluation = {
        "summary": "candidate completed project discussion",
        "humanReviewRequired": True,
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        asset_sync=FakeAssetSync(),
    )
    app = create_app()
    app.state.interview_center_service = service

    with TestClient(app) as client:
        reviewed = client.post(
            f"/api/interview-center/sessions/{session.id}/review",
            json={"decision": "need_followup", "note": 123},
        )

    assert reviewed.status_code == 200
    review = reviewed.json()["session"]["interviewEvaluation"]["review"]
    assert reviewed.json()["session"]["status"] == "needs_review"
    assert review["decision"] == "need_followup"
    assert review["note"] == "123"


def test_review_api_clips_note_like_old_node_clip_text() -> None:
    store = InMemoryInterviewStore()
    session = _backfill_session(store)
    session.status = "needs_review"
    session.interview_evaluation = {
        "summary": "candidate completed project discussion",
        "humanReviewRequired": True,
    }
    store.save(session)
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        asset_sync=FakeAssetSync(),
    )
    app = create_app()
    app.state.interview_center_service = service
    note = f"  {'x' * 1001}  "

    with TestClient(app) as client:
        reviewed = client.post(
            f"/api/interview-center/sessions/{session.id}/review",
            json={"decision": "passed", "note": note},
        )

    assert reviewed.status_code == 200
    review_note = reviewed.json()["session"]["interviewEvaluation"]["review"]["note"]
    assert review_note == ("x" * 1000) + "..."


def test_feishu_auth_url_route_includes_old_oauth_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_REDIRECT_URI", "http://localhost/callback")
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        oauth_client=FakeOAuthClient(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        response = client.get("/api/interview-center/feishu/auth-url")

    query = parse_qs(urlparse(response.json()["authUrl"]).query)
    scopes = set(query["scope"][0].split())
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["configured"] is True
    assert query["app_id"] == ["cli_app"]
    assert query["redirect_uri"] == ["http://localhost/callback"]
    assert {
        "offline_access",
        "calendar:calendar.event:read",
        "minutes:minutes.transcript:export",
    } <= scopes


def test_feishu_oauth_callback_saves_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEISHU_APP_ID", "cli_app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    store = InMemoryInterviewStore()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        oauth_client=FakeOAuthClient(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        response = client.get(
            "/api/interview-center/feishu/oauth/callback",
            params={"code": "code-1", "state": "state-1"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["connected"] is True
    assert store.get_token()["accessToken"] == "user-access"
    assert store.get_token()["userInfo"]["open_id"] == "ou_1"


def test_feishu_oauth_callback_defaults_to_old_html_redirect() -> None:
    store = InMemoryInterviewStore()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        oauth_client=FakeOAuthClient(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        response = client.get(
            "/api/interview-center/feishu/oauth/callback",
            params={"code": "code-1", "state": "state-1"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "location.replace('/interview-center.html?feishu=connected')" in response.text
    assert store.get_token()["accessToken"] == "user-access"


def test_feishu_oauth_callback_accepts_missing_state_like_old_node() -> None:
    store = InMemoryInterviewStore()
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        oauth_client=FakeOAuthClient(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        response = client.get(
            "/api/interview-center/feishu/oauth/callback",
            params={"code": "code-1"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "location.replace('/interview-center.html?feishu=connected')" in response.text
    assert store.get_token()["accessToken"] == "user-access"
    assert store.get_token()["state"] == ""


def test_feishu_oauth_callback_missing_code_uses_old_html_error() -> None:
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        oauth_client=FakeOAuthClient(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        response = client.get("/api/interview-center/feishu/oauth/callback")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "飞书授权失败：缺少 code" in response.text
    assert "missing_feishu_oauth_code" not in response.text


def test_interview_center_frontend_page_and_assets_are_served() -> None:
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/interview-center.html")
        style = client.get("/assets/interview-center/styles.css")
        api_script = client.get("/assets/interview-center/api.js")
        app_script = client.get("/assets/interview-center/app.js")

    assert page.status_code == 200
    assert "面试中心 - 招聘智能体" in page.text
    assert "/assets/interview-center/styles.css" in page.text
    assert "/assets/interview-center/api.js" in page.text
    assert style.status_code == 200
    assert ".interview-shell" in style.text
    assert api_script.status_code == 200
    assert "/api/interview-center/feishu/status" in api_script.text
    assert app_script.status_code == 200
    assert "runAction(\"正在绑定候选人\"" in app_script.text


def test_feishu_status_and_disconnect_use_stored_token() -> None:
    store = InMemoryInterviewStore()
    store.save_token(
        {
            "accessToken": "user-access",
            "refreshToken": "refresh",
            "expiresAt": 1_783_100_000_000,
            "userInfo": {"open_id": "ou_1", "name": "HR"},
        }
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=store,
        oauth_client=FakeOAuthClient(),
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        before = client.get("/api/interview-center/feishu/status")
        disconnected = client.post("/api/interview-center/feishu/disconnect")
        after = client.get("/api/interview-center/feishu/status")

    assert before.json()["ok"] is True
    assert before.json()["connected"] is True
    assert before.json()["userInfo"]["name"] == "HR"
    assert before.json()["calendarSync"]["enabled"] is True
    assert disconnected.json()["ok"] is True
    assert disconnected.json()["message"] == "已断开飞书日历授权"
    assert after.json()["ok"] is True
    assert after.json()["connected"] is False


def test_feishu_user_token_provider_refreshes_expired_token() -> None:
    store = InMemoryInterviewStore()
    store.save_token(
        {
            "accessToken": "old-user-access",
            "refreshToken": "refresh-1",
            "expiresAt": 1_000,
            "userInfo": {"open_id": "ou_1"},
        }
    )
    provider = FeishuStoredUserTokenProvider(
        store=store,
        refresh_client=FakeTokenRefreshClient(),
        now_ms=lambda: 10_000,
    )

    token = asyncio.run(provider.user_access_token())

    assert token == "new-user-access"
    assert store.get_token()["accessToken"] == "new-user-access"
    assert store.get_token()["refreshToken"] == "refresh-2"
    assert store.get_token()["userInfo"]["open_id"] == "ou_1"


def test_feishu_calendar_client_uses_stored_user_token_and_paginates() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer user-access"
        assert request.url.path == "/open-apis/calendar/v4/calendars/primary/events"
        if request.url.params.get("page_token") == "next":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"items": [{"event_id": "event-2"}], "has_more": False}},
            )
        assert request.url.params["start_time"] == "100"
        assert request.url.params["end_time"] == "200"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [{"event_id": "event-1"}],
                    "has_more": True,
                    "page_token": "next",
                },
            },
        )

    store = InMemoryInterviewStore()
    store.save_token({"accessToken": "user-access", "expiresAt": 999_999_999_999})
    client = FeishuCalendarClient(
        token_provider=FeishuStoredUserTokenProvider(store=store),
        transport=httpx.MockTransport(handler),
    )

    events = asyncio.run(client.list_events(calendar_id="primary", start_time=100, end_time=200))

    assert [event["event_id"] for event in events] == ["event-1", "event-2"]
    assert len(requests) == 2


def test_feishu_doc_client_returns_dry_run_metadata_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"dry-run doc client must not call network: {request.url}")

    monkeypatch.setenv("DRY_RUN", "true")
    store = InMemoryInterviewStore()
    store.save_token({"accessToken": "user-access", "expiresAt": 999_999_999_999})
    client = FeishuInterviewDocClient(
        token_provider=FeishuStoredUserTokenProvider(store=store),
        transport=httpx.MockTransport(handler),
        dry_run=True,
    )

    result = asyncio.run(client.create_document_from_text("Alice 面试问题", "问题正文"))

    assert result["dryRun"] is True
    assert result["documentId"].startswith("dry-run-doc:")
    assert result["contentSynced"] is True
    assert result["contentLength"] == len("问题正文")


def test_feishu_meeting_source_client_collects_doc_relation_and_minutes_sources() -> None:
    requests: list[httpx.Request] = []

    def doc_blocks(text: str) -> dict[str, Any]:
        return {
            "code": 0,
            "data": {
                "items": [
                    {
                        "text": {
                            "elements": [
                                {"text_run": {"content": text}},
                            ]
                        }
                    }
                ]
            },
        }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer user-access"
        path = request.url.path
        if path == "/open-apis/docx/v1/documents/doc-main/blocks":
            return httpx.Response(200, json=doc_blocks("main interview answer"))
        if path == "/open-apis/docx/v1/documents/docLinked/blocks":
            return httpx.Response(200, json=doc_blocks("linked document note"))
        if path == "/open-apis/docx/v1/documents/note-doc/blocks":
            return httpx.Response(200, json=doc_blocks("calendar relation note"))
        if path == "/open-apis/docx/v1/documents/note-artifact/blocks":
            return httpx.Response(200, json=doc_blocks("meeting note artifact"))
        if path == "/open-apis/calendar/v4/calendars/primary/events/mget_instance_relation_info":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "instance_relation_infos": [
                            {
                                "meeting_instance_ids": ["meeting-1"],
                                "meeting_notes": ["note-doc"],
                            }
                        ]
                    },
                },
            )
        if path == "/open-apis/vc/v1/meetings/meeting-1":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"meeting": {"id": "meeting-1", "note_id": "note-1"}}},
            )
        if path == "/open-apis/vc/v1/notes/note-1":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "note": {
                            "artifacts": [
                                {"artifact_type": 2, "doc_token": "note-artifact"},
                            ]
                        }
                    },
                },
            )
        if path == "/open-apis/vc/v1/meetings/meeting-1/recording":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "recording": {"url": "https://feishu.cn/minutes/min-recording"}
                    },
                },
            )
        if path == "/open-apis/minutes/v1/minutes/min-linked/transcript":
            return httpx.Response(200, json={"code": 0, "data": {"content": "linked transcript"}})
        if path == "/open-apis/minutes/v1/minutes/min-recording/transcript":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"content": "recording transcript"}},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    store = InMemoryInterviewStore()
    store.save_token({"accessToken": "user-access", "expiresAt": 999_999_999_999})
    session = store.create(resume_id="resume-1", candidate_name="Alice", job_type="AI")
    session.feishu_event_id = "event-1"
    session.calendar_id = "primary"
    session.start_time = 1_783_000_000
    session.end_time = 1_783_003_600
    session.feishu_doc = {
        "documentId": "doc-main",
        "localText": "question package template",
        "url": "https://feishu.cn/docx/doc-main",
    }
    session.payload = {
        "description": "linked https://feishu.cn/docx/docLinked",
        "meetingUrl": "https://feishu.cn/minutes/min-linked",
        "rawEvent": {"app_link": "https://feishu.cn/calendar/event-1"},
    }
    client = FeishuMeetingSourceClient(
        token_provider=FeishuStoredUserTokenProvider(store=store),
        transport=httpx.MockTransport(handler),
    )

    collected = asyncio.run(client.collect_sources(session))

    assert "main interview answer" in collected["text"]
    assert "linked document note" in collected["text"]
    assert "calendar relation note" in collected["text"]
    assert "meeting note artifact" in collected["text"]
    assert "linked transcript" in collected["text"]
    assert "recording transcript" in collected["text"]
    assert {
        "interview_doc",
        "linked_doc",
        "calendar_relation",
        "meeting_detail",
        "meeting_note",
        "meeting_note_doc",
        "meeting_recording",
        "minutes_transcript",
    } <= set(collected["source"]["types"])
    assert collected["source"]["linkedDocIds"] == ["docLinked", "note-doc", "note-artifact"]
    assert collected["source"]["minuteTokens"] == ["min-linked", "min-recording"]
    assert collected["source"]["meetingNoteIds"] == ["note-1"]
    assert collected["source"]["rawTextLength"] == len(collected["text"])
    assert requests


def test_feishu_meeting_source_client_skips_without_user_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"meeting source client must not call network: {request.url}")

    client = FeishuMeetingSourceClient(
        token_provider=FeishuStoredUserTokenProvider(store=InMemoryInterviewStore()),
        transport=httpx.MockTransport(handler),
    )
    session = InMemoryInterviewStore().create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI",
    )

    collected = asyncio.run(client.collect_sources(session))

    assert collected["text"] == ""
    assert collected["source"]["source"] == "feishu_meeting"
    assert collected["source"]["errors"] == ["feishu_user_token_required"]


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


class FakeMeetingClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def collect_sources(self, session: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "text": self.text,
            "source": {
                "source": "fake_meeting",
                "sessionId": session.id,
                "errors": [],
            },
        }


class FakeEvaluationGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        *,
        resume: dict[str, Any],
        session: Any,
        interview_text: str,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        _ = resume, session, interview_text, source
        self.calls += 1
        return {
            "summary": "候选人项目扎实",
            "overallRecommendation": "pass",
            "risks": [],
            "suggestedRuleChanges": [],
        }


class FailingEvaluationGenerator(FakeEvaluationGenerator):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def generate(
        self,
        *,
        resume: dict[str, Any],
        session: Any,
        interview_text: str,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        _ = resume, session, interview_text, source
        self.calls += 1
        raise self.error


class FakeAssetSync:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.resume_image_calls: list[dict[str, Any]] = []

    async def ensure_resume_image(
        self,
        session: Any,
        resume: dict[str, Any],
        *,
        resume_pdf_path: str,
    ) -> dict[str, Any]:
        self.calls.append("resume_image")
        self.resume_image_calls.append(
            {
                "sessionId": session.id,
                "resumeId": resume.get("id"),
                "resumePdfPath": resume_pdf_path,
            }
        )
        return {"ok": True, "recordId": "resume-image-record"}

    async def ensure_interview_record_image(
        self,
        session: Any,
        resume: dict[str, Any],
    ) -> dict[str, Any]:
        _ = session, resume
        self.calls.append("interview_record_image")
        return {"ok": True}

    async def ensure_evaluation_document(
        self,
        session: Any,
        resume: dict[str, Any],
        document: dict[str, Any],
        *,
        second_round: bool = False,
    ) -> dict[str, Any]:
        _ = resume
        self.calls.append("evaluation_document")
        evaluation_document = {
            "status": "synced",
            "field": "复试结果评价" if second_round else "技能评价",
            "recordId": session.bitable_record_id or "record-1",
            "documentId": document.get("documentId") or "",
            "url": document.get("url") or "",
            "title": document.get("title") or "",
        }
        if second_round:
            session.bitable_second_interview_evaluation_document = evaluation_document
            result_key = "secondInterviewEvaluationDocument"
        else:
            session.bitable_skill_evaluation_document = evaluation_document
            result_key = "skillEvaluationDocument"
        return {
            "ok": True,
            "session": session.to_dict(),
            result_key: evaluation_document,
            "evaluationDocument": evaluation_document,
        }


class FailingAssetSync(FakeAssetSync):
    async def ensure_interview_record_image(
        self,
        session: Any,
        resume: dict[str, Any],
    ) -> dict[str, Any]:
        _ = session, resume
        raise RuntimeError("asset_sync_failed")


class FakeOAuthClient:
    async def exchange_code(self, code: str) -> dict[str, Any]:
        assert code == "code-1"
        return {
            "access_token": "user-access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
        }

    async def user_info(self, access_token: str) -> dict[str, Any]:
        assert access_token == "user-access"
        return {"open_id": "ou_1", "name": "HR"}


class FakeTokenRefreshClient:
    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        assert refresh_token == "refresh-1"
        return {
            "access_token": "new-user-access",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
            "refresh_expires_in": 7200,
        }


class FakeTenantTokenProvider:
    async def tenant_access_token(self) -> str:
        return "tenant-token"


def _resume_record(payload: dict[str, Any] | None = None) -> ResumeRecord:
    resume_payload = {
        "name": "Alice",
        "phone": "13800138000",
        "job_type": "AI应用开发实习生",
        "rawText": "Alice 13800138000 Python LLM Agent",
    }
    resume_payload.update(payload or {})
    return ResumeRecord(
        id="resume-1",
        payload=resume_payload,
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


def _backfill_session(store: InMemoryInterviewStore) -> Any:
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True},
    )
    session.end_time = 1_783_003_600
    return store.save(session)


def _auto_backfill_candidate(
    store: InMemoryInterviewStore,
    suffix: str,
    *,
    end_time: int,
) -> Any:
    session = store.create(
        resume_id="resume-1",
        candidate_name=f"Alice {suffix}",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True, "title": f"Alice {suffix} 面试"},
    )
    session.status = "prepared"
    session.end_time = end_time
    session.feishu_doc = {
        "documentId": f"doc-{suffix}",
        "url": f"https://example.feishu.cn/docx/doc-{suffix}",
    }
    return store.save(session)
