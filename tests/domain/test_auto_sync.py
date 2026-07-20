from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest
from app.api.routes.auto_sync import router as auto_sync_router
from app.db.engine import run_migrations
from app.domain.auto_sync.auth import build_encrypted_sync_request
from app.domain.auto_sync.locking import SingleInstanceLock
from app.domain.auto_sync.service import AutoSyncService
from app.domain.auto_sync.worker import AutoSyncWorker, AutoSyncWorkerConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scripts.run_auto_sync import build_worker


def test_single_instance_lock_prevents_overlapping_workers(tmp_path: Path) -> None:
    lock_path = tmp_path / "auto-sync.lock"

    with SingleInstanceLock(lock_path):
        try:
            with SingleInstanceLock(lock_path):
                raise AssertionError("second worker unexpectedly acquired the lock")
        except RuntimeError as error:
            assert str(error) == "auto_sync_worker_already_running"

    with SingleInstanceLock(lock_path):
        assert lock_path.is_file()


def test_worker_requires_explicit_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings import load_settings

    monkeypatch.setenv("AUTO_SYNC_ENABLED", "false")
    load_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="AUTO_SYNC_ENABLED must be true"):
            build_worker()
    finally:
        load_settings.cache_clear()


def test_internal_sync_requires_valid_hmac_and_rejects_stale_request(tmp_path: Path) -> None:
    app = _sync_app(tmp_path, secret="shared-secret")
    body = _batch_body()
    invalid_body, invalid_headers = build_encrypted_sync_request(body, "wrong-secret")
    stale_body, stale_headers = build_encrypted_sync_request(
        body,
        "shared-secret",
        timestamp=1,
    )

    with TestClient(app) as client:
        missing = client.post("/api/internal/sync/batch", content=body)
        invalid = client.post(
            "/api/internal/sync/batch",
            content=invalid_body,
            headers=invalid_headers,
        )
        stale = client.post(
            "/api/internal/sync/batch",
            content=stale_body,
            headers=stale_headers,
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert stale.status_code == 401


def test_valid_batch_uploads_file_and_merges_records_idempotently(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    files_root = tmp_path / "server-files"
    run_migrations(database)
    app = _sync_app(tmp_path, database=database, files_root=files_root)
    body = _batch_body()
    encrypted_body, headers = build_encrypted_sync_request(body, "shared-secret")

    with TestClient(app) as client:
        first = client.post(
            "/api/internal/sync/batch",
            content=encrypted_body,
            headers=headers,
        )
        second = client.post(
            "/api/internal/sync/batch",
            content=encrypted_body,
            headers=headers,
        )

    assert first.status_code == 200
    assert first.json()["applied"] is True
    assert first.json()["resumesInserted"] == 1
    assert first.json()["sessionsInserted"] == 1
    assert first.json()["messagesInserted"] == 1
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    with sqlite3.connect(database) as connection:
        payload = json.loads(
            connection.execute("SELECT payload FROM resumes WHERE id = 'resume-1'").fetchone()[0]
        )
        assert connection.execute("SELECT COUNT(*) FROM sync_receipts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0] == 1
    stored_file = Path(payload["filePath"])
    assert stored_file.is_file()
    assert stored_file.read_bytes() == b"%PDF-1.4\ncontent\n%%EOF"
    assert stored_file.is_relative_to(files_root)


def test_sync_batch_merges_monitoring_events_and_runtime_statuses(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    run_migrations(database)
    app = _sync_app(tmp_path, database=database)
    payload = json.loads(_batch_body())
    payload["batchId"] = "batch-monitoring"
    payload["operationEvents"] = [
        {
            "id": "event-1",
            "contactKey": "contact-1",
            "owner": "宋峰峰",
            "platform": "boss",
            "candidateName": "候选人甲",
            "jobType": "AI产品经理",
            "occurredAt": "2026-07-20T01:00:00+00:00",
            "action": "request_resume",
            "stage": "request_confirmed",
            "processed": True,
            "sentCompanyInfo": False,
            "requestedResume": True,
            "candidateQuestion": False,
            "knowledgeAnswered": False,
            "resumeAcquired": True,
            "resumeHandling": "boss_request_verified_server_imap",
            "resumeFileHash": "",
            "anomaly": False,
            "anomalyReason": "",
            "payload": {},
            "updatedAt": "2026-07-20T01:00:00+00:00",
        }
    ]
    payload["runtimeStatuses"] = [
        {
            "targetKey": "宋峰峰:boss",
            "owner": "宋峰峰",
            "platform": "boss",
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
            "checkedAt": "2026-07-20T01:00:00+00:00",
            "receivedAt": "2026-07-20T01:00:00+00:00",
        }
    ]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    encrypted_body, headers = build_encrypted_sync_request(body, "shared-secret")

    with TestClient(app) as client:
        first = client.post(
            "/api/internal/sync/batch", content=encrypted_body, headers=headers
        )
        second = client.post(
            "/api/internal/sync/batch", content=encrypted_body, headers=headers
        )

    assert first.status_code == 200
    assert first.json()["operationEventsUpserted"] == 1
    assert first.json()["runtimeStatusesUpserted"] == 1
    assert second.json()["idempotent"] is True
    with sqlite3.connect(database) as connection:
        event_count = connection.execute(
            "SELECT COUNT(*) FROM automation_contact_events"
        ).fetchone()[0]
        status_count = connection.execute(
            "SELECT COUNT(*) FROM automation_runtime_status"
        ).fetchone()[0]
        assert event_count == 1
        assert status_count == 1


def test_existing_resume_keeps_server_fields_but_receives_link_and_file(tmp_path: Path) -> None:
    database = tmp_path / "server.sqlite"
    run_migrations(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resumes (id, payload, phone_key, job_type, match_score, updated_at)
            VALUES ('resume-1', ?, 'server-phone', 'AI产品经理', 91, '2026-07-14T00:00:00+00:00')
            """,
            (json.dumps({"name": "服务器人工姓名", "major": "人工修正专业"}, ensure_ascii=False),),
        )
        connection.commit()
    app = _sync_app(tmp_path, database=database)
    body = _batch_body()
    encrypted_body, headers = build_encrypted_sync_request(body, "shared-secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/internal/sync/batch",
            content=encrypted_body,
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["resumesUpdated"] == 1
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT payload, phone_key, match_score, linked_session_id "
            "FROM resumes WHERE id='resume-1'"
        ).fetchone()
    payload = json.loads(row[0])
    assert payload["name"] == "服务器人工姓名"
    assert payload["major"] == "人工修正专业"
    assert row[1] == "server-phone"
    assert row[2] == 91
    assert row[3] == "session-1"
    assert Path(payload["filePath"]).is_file()


def test_worker_persists_batch_until_ack_and_advances_cursors_after_success(
    tmp_path: Path,
) -> None:
    database = tmp_path / "local.sqlite"
    state_path = tmp_path / "sync" / "state.json"
    pending_dir = tmp_path / "sync" / "pending"
    resume_file = tmp_path / "resume.pdf"
    resume_file.write_bytes(b"%PDF-1.4\ncontent\n%%EOF")
    run_migrations(database)
    _insert_local_records(database, resume_file)
    worker = AutoSyncWorker(
        AutoSyncWorkerConfig(
            database_path=database,
            server_url="http://sync.invalid",
            secret="shared-secret",
            state_path=state_path,
            pending_dir=pending_dir,
            source="local-test",
        )
    )

    first = worker.prepare_pending_batch()
    retry = worker.prepare_pending_batch()

    assert first is not None
    assert retry is not None
    assert retry.batch_id == first.batch_id
    assert len(first.payload["resumes"]) == 1
    assert len(first.payload["sessions"]) == 1
    assert len(first.payload["messages"]) == 1
    assert first.payload["resumes"][0]["file"]["sha256"]
    assert list(pending_dir.glob("*.json"))

    worker.acknowledge(first)

    assert worker.prepare_pending_batch() is None
    assert not list(pending_dir.glob("*.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["resumeCursor"]["id"] == "resume-1"
    assert state["sessionCursor"]["id"] == "session-1"
    assert state["messageCursor"]["id"] == "message-1"


def test_worker_collects_incremental_monitoring_rows(tmp_path: Path) -> None:
    database = tmp_path / "local.sqlite"
    run_migrations(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO automation_contact_events (
              id, contact_key, owner, platform, candidate_name, job_type,
              occurred_at, action, stage, processed, sent_company_info,
              requested_resume, candidate_question, knowledge_answered,
              resume_acquired, resume_handling, resume_file_hash, anomaly,
              anomaly_reason, payload, updated_at
            ) VALUES (
              'event-1', 'contact-1', '宋峰峰', 'boss', '候选人甲', 'AI产品经理',
              '2026-07-20T01:00:00+00:00', 'request_resume', 'request_confirmed',
              1, 0, 1, 0, 0, 1, 'boss_request_verified_server_imap', '', 0,
              '', '{}', '2026-07-20T01:00:00+00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO automation_runtime_status (
              target_key, owner, platform, status, agent_ready, browser_ready,
              cdp_ready, agent_busy, authenticated, needs_login,
              security_verification, account_abnormal, page_present, paused,
              reason, checked_at, received_at
            ) VALUES (
              '宋峰峰:boss', '宋峰峰', 'boss', 'ready', 1, 1, 1, 0, 1, 0,
              0, 0, 1, 0, '', '2026-07-20T01:00:00+00:00',
              '2026-07-20T01:00:00+00:00'
            )
            """
        )
        connection.commit()
    worker = AutoSyncWorker(
        AutoSyncWorkerConfig(
            database_path=database,
            server_url="http://sync.invalid",
            secret="shared-secret",
            state_path=tmp_path / "state.json",
            pending_dir=tmp_path / "pending",
        )
    )

    pending = worker.prepare_pending_batch()

    assert pending is not None
    assert [item["id"] for item in pending.payload["operationEvents"]] == ["event-1"]
    assert [item["targetKey"] for item in pending.payload["runtimeStatuses"]] == [
        "宋峰峰:boss"
    ]
    worker.acknowledge(pending)
    assert worker.prepare_pending_batch() is None


def test_worker_upgrades_legacy_state_with_monitoring_cursors(tmp_path: Path) -> None:
    database = tmp_path / "local.sqlite"
    state_path = tmp_path / "state.json"
    run_migrations(database)
    state_path.write_text(
        json.dumps(
            {
                "resumeCursor": {"timestamp": "", "id": ""},
                "sessionCursor": {"timestamp": "", "id": ""},
                "messageCursor": {"timestamp": "", "id": ""},
                "lastSuccessAt": "",
                "lastError": "",
                "consecutiveFailures": 0,
            }
        ),
        encoding="utf-8",
    )
    worker = AutoSyncWorker(
        AutoSyncWorkerConfig(
            database_path=database,
            server_url="http://sync.invalid",
            secret="shared-secret",
            state_path=state_path,
            pending_dir=tmp_path / "pending",
        )
    )

    assert worker.prepare_pending_batch() is None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["operationEventCursor"] == {"timestamp": "", "id": ""}
    assert state["runtimeStatusCursor"] == {"timestamp": "", "id": ""}


def test_worker_bootstrap_skips_existing_rows_but_collects_future_changes(tmp_path: Path) -> None:
    database = tmp_path / "local.sqlite"
    run_migrations(database)
    _insert_local_records(database, tmp_path / "missing.pdf")
    worker = AutoSyncWorker(
        AutoSyncWorkerConfig(
            database_path=database,
            server_url="http://sync.invalid",
            secret="shared-secret",
            state_path=tmp_path / "state.json",
            pending_dir=tmp_path / "pending",
        )
    )

    worker.bootstrap_current()
    assert worker.prepare_pending_batch() is None

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO conversation_messages (
              id, session_id, sender, text, raw_text, sent_at,
              platform_message_id, message_hash, created_at
            ) VALUES ('message-2', 'session-1', 'other', '新消息', '新消息', '11:00', '',
                      'hash-message-2', '2026-07-15T00:00:00+00:00')
            """
        )
        connection.commit()

    pending = worker.prepare_pending_batch()
    assert pending is not None
    assert [item["id"] for item in pending.payload["messages"]] == ["message-2"]
    assert [item["id"] for item in pending.payload["sessions"]] == ["session-1"]


def test_failed_delivery_keeps_pending_batch_and_records_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "local.sqlite"
    run_migrations(database)
    _insert_local_records(database, tmp_path / "missing.pdf")
    worker = AutoSyncWorker(
        AutoSyncWorkerConfig(
            database_path=database,
            server_url="http://sync.invalid",
            secret="shared-secret",
            state_path=tmp_path / "state.json",
            pending_dir=tmp_path / "pending",
        )
    )

    def fail_delivery(*_args: object) -> dict[str, object]:
        raise RuntimeError("server unavailable")

    monkeypatch.setattr(worker, "send_pending", fail_delivery)

    with pytest.raises(RuntimeError, match="server unavailable"):
        worker.run_once()

    assert list((tmp_path / "pending").glob("batch-*.json"))
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["consecutiveFailures"] == 1
    assert "server unavailable" in state["lastError"]


def test_sync_incremental_queries_have_dedicated_indexes(tmp_path: Path) -> None:
    database = tmp_path / "indexed.sqlite"
    run_migrations(database)

    with sqlite3.connect(database) as connection:
        resume_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(resumes)")
        }
        message_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(conversation_messages)")
        }

    assert "idx_resumes_updated" in resume_indexes
    assert "idx_conversation_messages_created" in message_indexes


def _sync_app(
    tmp_path: Path,
    *,
    secret: str = "shared-secret",
    database: Path | None = None,
    files_root: Path | None = None,
) -> FastAPI:
    resolved_database = database or tmp_path / "server.sqlite"
    run_migrations(resolved_database)
    app = FastAPI()
    app.state.auto_sync_secret = secret
    app.state.auto_sync_service = AutoSyncService(
        resolved_database,
        files_root=files_root or tmp_path / "files",
    )
    app.include_router(auto_sync_router)
    return app


def _batch_body() -> bytes:
    content = b"%PDF-1.4\ncontent\n%%EOF"
    import hashlib

    digest = hashlib.sha256(content).hexdigest()
    payload = {
        "batchId": "batch-1",
        "source": "local-test",
        "createdAt": "2026-07-14T00:00:00+00:00",
        "resumes": [
            {
                "id": "resume-1",
                "payload": {
                    "name": "本地姓名",
                    "major": "本地专业",
                    "filePath": "C:/local/resume.pdf",
                },
                "phoneKey": "13800000000",
                "jobType": "AI产品经理",
                "matchScore": 88,
                "updatedAt": "2026-07-14T01:00:00+00:00",
                "parsedName": "本地姓名",
                "linkedSessionId": "session-1",
                "linkedPlatform": "job51",
                "linkedOwner": "宋峰峰",
                "linkedPlatformConversationId": "conversation-1",
                "sourceArtifactId": "artifact-1",
                "file": {
                    "sha256": digest,
                    "filename": "resume.pdf",
                    "mediaType": "application/pdf",
                    "contentBase64": base64.b64encode(content).decode("ascii"),
                },
            }
        ],
        "sessions": [
            {
                "id": "session-1",
                "platform": "job51",
                "owner": "宋峰峰",
                "candidateName": "本地姓名",
                "position": "AI产品经理",
                "appliedPosition": "AI产品经理",
                "platformConversationId": "conversation-1",
                "label": "",
                "currentStage": "resume_received",
                "nextAction": "download_resume",
                "recentMessagesFingerprint": "fingerprint",
                "identityConfidence": "high",
                "identityWarnings": "[]",
                "lastSeenAt": "2026-07-14T01:00:00+00:00",
                "createdAt": "2026-07-14T00:00:00+00:00",
                "updatedAt": "2026-07-14T01:00:00+00:00",
            }
        ],
        "messages": [
            {
                "id": "message-1",
                "sessionId": "session-1",
                "sender": "other",
                "text": "你好",
                "rawText": "你好",
                "sentAt": "10:00",
                "platformMessageId": "",
                "messageHash": "message-hash-1",
                "createdAt": "2026-07-14T01:00:00+00:00",
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _insert_local_records(database: Path, resume_file: Path) -> None:
    payload = {
        "name": "候选人",
        "filePath": str(resume_file),
        "sourcePlatform": "job51",
        "sourceOwner": "宋峰峰",
    }
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO conversation_sessions (
              id, platform, owner, candidate_name, position, applied_position,
              platform_conversation_id, label, current_stage, next_action,
              recent_messages_fingerprint, identity_confidence, identity_warnings,
              last_seen_at, created_at, updated_at
            ) VALUES ('session-1', 'job51', '宋峰峰', '候选人', 'AI产品经理', 'AI产品经理',
                      'conversation-1', '', '', '', '', 'high', '[]',
                      '2026-07-14T00:00:00+00:00', '2026-07-14T00:00:00+00:00',
                      '2026-07-14T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT INTO conversation_messages (
              id, session_id, sender, text, raw_text, sent_at,
              platform_message_id, message_hash, created_at
            ) VALUES ('message-1', 'session-1', 'other', '你好', '你好', '10:00', '',
                      'hash-message-1', '2026-07-14T00:00:00+00:00')
            """
        )
        connection.execute(
            """
            INSERT INTO resumes (
              id, payload, phone_key, job_type, match_score, updated_at,
              parsed_name, linked_session_id, linked_platform, linked_owner,
              linked_platform_conversation_id, source_artifact_id
            ) VALUES ('resume-1', ?, '13800000000', 'AI产品经理', 88,
                      '2026-07-14T00:00:00+00:00', '候选人', 'session-1', 'job51',
                      '宋峰峰', 'conversation-1', 'artifact-1')
            """,
            (json.dumps(payload, ensure_ascii=False),),
        )
        connection.commit()
