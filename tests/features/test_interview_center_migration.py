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
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["connected"] is True
    assert store.get_token()["accessToken"] == "user-access"
    assert store.get_token()["userInfo"]["open_id"] == "ou_1"


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

    assert before.json()["connected"] is True
    assert before.json()["userInfo"]["name"] == "HR"
    assert disconnected.json()["ok"] is True
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

    async def collect_sources(self, session: Any) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": {
                "source": "fake_meeting",
                "sessionId": session.id,
                "errors": [],
            },
        }


class FakeEvaluationGenerator:
    async def generate(
        self,
        *,
        resume: dict[str, Any],
        session: Any,
        interview_text: str,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        _ = resume, session, interview_text, source
        return {
            "summary": "候选人项目扎实",
            "overallRecommendation": "pass",
            "risks": [],
            "suggestedRuleChanges": [],
        }


class FakeAssetSync:
    def __init__(self) -> None:
        self.calls: list[str] = []

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
        _ = session, resume, document, second_round
        self.calls.append("evaluation_document")
        return {"ok": True}


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


def _backfill_session(store: InMemoryInterviewStore) -> Any:
    session = store.create(
        resume_id="resume-1",
        candidate_name="Alice",
        job_type="AI应用开发实习生",
        payload={"isInterviewLike": True},
    )
    session.end_time = 1_783_003_600
    return store.save(session)
