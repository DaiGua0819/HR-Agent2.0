from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.control_plane.main import create_app
from app.domain.automation_monitoring.events import build_contact_event
from app.domain.automation_monitoring.repository import AutomationMonitoringRepository
from app.domain.automation_monitoring.service import AutomationMonitoringService
from fastapi.testclient import TestClient


def test_daily_summary_dedupes_contacts_and_uses_platform_resume_contracts(
    tmp_path: Path,
) -> None:
    repository = AutomationMonitoringRepository(tmp_path / "monitoring.sqlite")
    service = AutomationMonitoringService(repository)
    events = [
        _event(
            event_id="boss-1",
            contact_key="boss-contact",
            platform="boss",
            owner="宋峰峰",
            candidate_name="候选人甲",
            job_type="AI产品经理",
            requested_resume=True,
            resume_acquired=True,
            resume_handling="boss_request_verified_server_imap",
        ),
        _event(
            event_id="boss-2",
            contact_key="boss-contact",
            platform="boss",
            owner="宋峰峰",
            candidate_name="候选人甲",
            job_type="AI产品经理",
            sent_company_info=True,
        ),
        _event(
            event_id="job51-1",
            contact_key="job51-contact-a",
            platform="job51",
            owner="和新红",
            candidate_name="候选人乙",
            job_type="运营B",
            resume_acquired=True,
            resume_handling="local_resume_downloaded",
            resume_file_hash="same-file",
        ),
        _event(
            event_id="job51-2",
            contact_key="job51-contact-b",
            platform="job51",
            owner="和新红",
            candidate_name="候选人丙",
            job_type="运营B",
            resume_acquired=True,
            resume_handling="local_resume_downloaded",
            resume_file_hash="same-file",
        ),
    ]
    repository.upsert_events(events)

    summary = service.daily_summary(date="2026-07-20")

    assert summary["totals"]["processedContacts"] == 3
    assert summary["totals"]["sentCompanyInfo"] == 1
    assert summary["totals"]["requestedResume"] == 1
    assert summary["totals"]["businessResumeAcquisitions"] == 2
    assert summary["facets"] == {
        "owners": ["和新红", "宋峰峰"],
        "platforms": ["boss", "job51"],
        "jobTypes": ["AI产品经理", "运营B"],
    }
    by_key = {
        (item["jobType"], item["platform"]): item
        for item in summary["byJobPlatform"]
    }
    assert by_key[("AI产品经理", "boss")]["businessResumeAcquisitions"] == 1
    assert by_key[("运营B", "job51")]["businessResumeAcquisitions"] == 1


def test_runtime_status_marks_old_heartbeats_stale_and_offline(tmp_path: Path) -> None:
    repository = AutomationMonitoringRepository(tmp_path / "monitoring.sqlite")
    service = AutomationMonitoringService(repository)
    now = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
    repository.upsert_runtime_statuses(
        [
            _status("宋峰峰:boss", "宋峰峰", "boss", now - timedelta(seconds=10)),
            _status("宋峰峰:job51", "宋峰峰", "job51", now - timedelta(seconds=60)),
            _status("宋峰峰:zhilian", "宋峰峰", "zhilian", now - timedelta(seconds=180)),
        ]
    )

    payload = service.runtime_status(now=now)
    assert len(payload["targets"]) == 6
    by_platform = {
        item["platform"]: item
        for item in payload["targets"]
        if item["owner"] == "宋峰峰"
    }

    assert by_platform["boss"]["status"] == "ready"
    assert by_platform["job51"]["status"] == "stale"
    assert by_platform["job51"]["reason"] == "heartbeat_stale"
    assert by_platform["zhilian"]["status"] == "worker_offline"
    assert by_platform["zhilian"]["reason"] == "heartbeat_timeout"
    missing_owner = {
        item["platform"]: item
        for item in payload["targets"]
        if item["owner"] == "和新红"
    }
    assert set(missing_owner) == {"boss", "job51", "zhilian"}
    assert {item["status"] for item in missing_owner.values()} == {"worker_offline"}
    assert {item["reason"] for item in missing_owner.values()} == {"no_heartbeat"}


def test_daily_details_defaults_to_ten_and_adds_resume_download_links(
    tmp_path: Path,
) -> None:
    database = tmp_path / "monitoring.sqlite"
    repository = AutomationMonitoringRepository(database)
    service = AutomationMonitoringService(repository)
    events = []
    for index in range(12):
        event = _event(
            event_id=f"event-{index:02d}",
            contact_key=f"session|session-{index:02d}|message|fingerprint-{index:02d}",
            platform="job51",
            owner="和新红",
            candidate_name=f"候选人{index:02d}",
            job_type="AI产品经理",
        )
        occurred_at = f"2026-07-20T01:{index:02d}:00+00:00"
        event["occurredAt"] = occurred_at
        event["updatedAt"] = occurred_at
        events.append(event)
    repository.upsert_events(events)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resumes (
              id, payload, phone_key, job_type, match_score, parsed_name,
              linked_session_id, linked_platform, linked_owner,
              linked_platform_conversation_id, source_artifact_id, updated_at
            ) VALUES (?, ?, '', ?, 80, ?, ?, 'job51', ?, '', '', ?)
            """,
            (
                "resume-11",
                json.dumps({"name": "候选人11", "filePath": "C:/resumes/resume-11.pdf"}),
                "AI产品经理",
                "候选人11",
                "session-11",
                "和新红",
                "2026-07-20T01:11:00+00:00",
            ),
        )
        connection.commit()

    first_page = service.daily_details(date="2026-07-20")
    second_page = service.daily_details(date="2026-07-20", page=2)

    assert first_page["pageSize"] == 10
    assert first_page["total"] == 12
    assert first_page["pages"] == 2
    assert len(first_page["items"]) == 10
    assert first_page["items"][0]["resumeId"] == "resume-11"
    assert first_page["items"][0]["resumeDownloadUrl"] == "/api/resumes/resume-11/download"
    assert len(second_page["items"]) == 2
    assert all("filePath" not in item for item in first_page["items"])


def test_monitoring_api_is_admin_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "monitoring.sqlite"))
    from app.settings import load_settings

    load_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login",
                json={"username": "member", "password": "member"},
            )
            forbidden = client.get(
                "/api/automation-monitoring/daily-summary?date=2026-07-20"
            )
            client.post("/api/auth/logout")
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin"},
            )
            allowed = client.get(
                "/api/automation-monitoring/daily-summary?date=2026-07-20"
            )
    finally:
        load_settings.cache_clear()

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "monitoring_forbidden"
    assert allowed.status_code == 200
    assert allowed.json()["date"] == "2026-07-20"


def test_contact_event_builder_applies_boss_resume_and_question_semantics() -> None:
    event = build_contact_event(
        owner="宋峰峰",
        platform="boss",
        state={
            "conversation_id": "conversation-1",
            "session_id": "session-1",
            "recent_messages_fingerprint": "message-hash",
            "candidate": {"name": "候选人甲"},
            "applied_position": "AI产品经理",
            "next_action": "request_resume",
            "stage": "request_confirmed",
            "decision": {
                "action": "request_resume",
                "result": {"ok": True, "outcome": "request_confirmed"},
            },
        },
        occurred_at="2026-07-20T01:00:00+00:00",
    )

    assert event.contact_key == "session|session-1|message|message-hash"
    assert event.requested_resume is True
    assert event.resume_acquired is True
    assert event.resume_handling == "boss_request_verified_server_imap"
    assert event.candidate_name == "候选人甲"
    assert event.payload["sessionId"] == "session-1"
    assert event.payload["conversationId"] == "conversation-1"


def _event(
    *,
    event_id: str,
    contact_key: str,
    platform: str,
    owner: str,
    candidate_name: str,
    job_type: str,
    sent_company_info: bool = False,
    requested_resume: bool = False,
    resume_acquired: bool = False,
    resume_handling: str = "",
    resume_file_hash: str = "",
) -> dict[str, object]:
    return {
        "id": event_id,
        "contactKey": contact_key,
        "owner": owner,
        "platform": platform,
        "candidateName": candidate_name,
        "jobType": job_type,
        "occurredAt": "2026-07-20T01:00:00+00:00",
        "action": "process",
        "stage": "completed",
        "processed": True,
        "sentCompanyInfo": sent_company_info,
        "requestedResume": requested_resume,
        "candidateQuestion": False,
        "knowledgeAnswered": False,
        "resumeAcquired": resume_acquired,
        "resumeHandling": resume_handling,
        "resumeFileHash": resume_file_hash,
        "anomaly": False,
        "anomalyReason": "",
        "payload": {},
        "updatedAt": "2026-07-20T01:00:00+00:00",
    }


def _status(
    target_key: str,
    owner: str,
    platform: str,
    checked_at: datetime,
) -> dict[str, object]:
    return {
        "targetKey": target_key,
        "owner": owner,
        "platform": platform,
        "status": "ready",
        "agentReady": True,
        "browserReady": True,
        "cdpReady": True,
        "agentBusy": False,
        "authenticated": True,
        "needsLogin": False,
        "securityVerification": False,
        "accountAbnormal": False,
        "pagePresent": True,
        "paused": False,
        "reason": "",
        "checkedAt": checked_at.isoformat(),
        "receivedAt": checked_at.isoformat(),
    }
