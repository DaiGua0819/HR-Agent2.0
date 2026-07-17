from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from app.db.engine import run_migrations
from app.features.feishu_bot.models import BotActor, BotQueryPlan
from app.features.feishu_bot.queries import ReadOnlyRecruitmentQueries


def _member() -> BotActor:
    return BotActor(
        open_id="ou-member",
        display_name="菜花",
        role="member",
        job_types=("AI产品经理",),
        review_user_id="feishu:review-member",
        permissions=frozenset({"query:summary", "query:resumes", "query:reviews"}),
    )


def _admin() -> BotActor:
    return BotActor(
        open_id="ou-admin",
        display_name="王鑫力",
        role="admin",
        job_types=("*",),
        review_user_id="feishu:review-admin",
        permissions=frozenset(
            {
                "query:summary",
                "query:resumes",
                "query:reviews",
                "query:workers",
                "query:errors",
                "query:all_jobs",
                "query:shared_queue",
            }
        ),
    )


def test_daily_summary_uses_platform_contract_and_filters_member_jobs(tmp_path: Path) -> None:
    database, runs_dir = _seed_database(tmp_path)
    queries = ReadOnlyRecruitmentQueries(database, manager_runs_dir=runs_dir)
    plan = BotQueryPlan(intent="daily_summary", date="2026-07-16")

    member_result = asyncio.run(queries.execute(_member(), plan))
    admin_result = asyncio.run(queries.execute(_admin(), plan))

    assert member_result.data["totals"] == {
        "processedContacts": 2,
        "bossHandoffs": 1,
        "localUniqueFiles": 1,
        "businessResumeAcquisitions": 2,
        "resumeRequestsWaiting": 0,
        "anomalies": 1,
    }
    assert {row["job"] for row in member_result.data["byJobPlatform"]} == {
        "AI产品经理"
    }
    assert admin_result.data["totals"]["processedContacts"] == 3
    assert admin_result.data["totals"]["localUniqueFiles"] == 2
    assert member_result.coverage["source"] == "agent_manager_run_jsonl_plus_resume_artifacts"


def test_resume_counts_and_recent_resumes_never_return_sensitive_fields(
    tmp_path: Path,
) -> None:
    database, runs_dir = _seed_database(tmp_path)
    queries = ReadOnlyRecruitmentQueries(database, manager_runs_dir=runs_dir)

    counts = asyncio.run(
        queries.execute(_member(), BotQueryPlan(intent="resume_counts"))
    )
    recent = asyncio.run(
        queries.execute(
            _member(),
            BotQueryPlan(intent="recent_resumes", limit=10),
        )
    )

    assert counts.data == {
        "total": 1,
        "byJob": [{"jobType": "AI产品经理", "count": 1}],
    }
    assert len(recent.data["items"]) == 1
    item = recent.data["items"][0]
    assert item == {
        "id": "resume-ai",
        "name": "候选人甲",
        "jobType": "AI产品经理",
        "score": 91,
        "platform": "job51",
        "owner": "宋峰峰",
        "updatedAt": "2026-07-16T02:30:00+00:00",
    }
    assert "payload" not in item
    assert "phone" not in item
    assert "filePath" not in item
    assert "rawText" not in item


def test_member_job_scope_uses_exact_canonical_match_not_substring(
    tmp_path: Path,
) -> None:
    database, runs_dir = _seed_database(tmp_path)
    with sqlite3.connect(database) as connection:
        _insert_resume(
            connection,
            resume_id="resume-generic-product",
            name="候选人丁",
            job="产品经理",
            score=80,
            platform="job51",
            owner="宋峰峰",
            updated_at="2026-07-16T03:00:00+00:00",
        )
        connection.commit()
    actor = BotActor(
        open_id="ou-generic-product-member",
        display_name="产品岗位成员",
        role="member",
        job_types=("产品经理",),
        permissions=frozenset({"query:resumes"}),
    )
    queries = ReadOnlyRecruitmentQueries(database, manager_runs_dir=runs_dir)

    result = asyncio.run(
        queries.execute(actor, BotQueryPlan(intent="resume_counts"))
    )

    assert result.data == {
        "total": 1,
        "byJob": [{"jobType": "产品经理", "count": 1}],
    }


def test_review_summary_is_personal_for_member_and_shared_for_admin(tmp_path: Path) -> None:
    database, runs_dir = _seed_database(tmp_path)
    queries = ReadOnlyRecruitmentQueries(database, manager_runs_dir=runs_dir)
    plan = BotQueryPlan(intent="review_summary")

    member_result = asyncio.run(queries.execute(_member(), plan))
    admin_result = asyncio.run(queries.execute(_admin(), plan))

    assert member_result.data == {
        "scope": "personal",
        "decisions": {"suitable": 1},
        "total": 1,
    }
    assert admin_result.data["scope"] == "admin"
    assert admin_result.data["sharedPending"] == 2
    assert admin_result.data["decisions"]["suitable"] == 2


def test_worker_and_error_queries_are_admin_only(tmp_path: Path) -> None:
    database, runs_dir = _seed_database(tmp_path)
    worker_calls = 0

    async def worker_statuses() -> list[dict[str, object]]:
        nonlocal worker_calls
        worker_calls += 1
        return [
            {
                "owner": "宋峰峰",
                "agentReady": True,
                "browserReady": True,
                "agentBusy": False,
                "browserBackend": "cloak",
                "secret": "must-not-leak",
            }
        ]

    queries = ReadOnlyRecruitmentQueries(
        database,
        manager_runs_dir=runs_dir,
        worker_status_provider=worker_statuses,
    )

    with pytest.raises(PermissionError, match="query:workers"):
        asyncio.run(
            queries.execute(_member(), BotQueryPlan(intent="worker_status"))
        )
    with pytest.raises(PermissionError, match="query:errors"):
        asyncio.run(
            queries.execute(_member(), BotQueryPlan(intent="recent_errors"))
        )

    workers = asyncio.run(
        queries.execute(_admin(), BotQueryPlan(intent="worker_status"))
    )
    errors = asyncio.run(
        queries.execute(_admin(), BotQueryPlan(intent="recent_errors", limit=5))
    )

    assert worker_calls == 1
    assert workers.data["items"] == [
        {
            "owner": "宋峰峰",
            "platform": "all",
            "status": "ready",
            "agentReady": True,
            "browserReady": True,
            "agentBusy": False,
            "browserBackend": "cloak",
            "error": "",
        }
    ]
    assert "secret" not in workers.data["items"][0]
    assert errors.data["items"] == [
        {
            "timestamp": "2026-07-16T02:00:00+00:00",
            "owner": "宋峰峰",
            "platform": "job51",
            "reason": "candidate_identity_mismatch",
        }
    ]


def _seed_database(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "resumes.sqlite"
    runs_dir = tmp_path / "agent_manager" / "runs"
    runs_dir.mkdir(parents=True)
    run_migrations(database)
    with sqlite3.connect(database) as connection:
        _insert_session(
            connection,
            session_id="session-ai-boss",
            platform="boss",
            candidate="候选人甲",
            job="AI Product Manager",
            conversation_id="boss-ai-1",
        )
        _insert_session(
            connection,
            session_id="session-ai-job51",
            platform="job51",
            candidate="候选人乙",
            job="AI产品经理",
            conversation_id="job51-ai-1",
        )
        _insert_session(
            connection,
            session_id="session-ai-job51-duplicate-file",
            platform="job51",
            candidate="候选人乙重复记录",
            job="AI产品经理",
            conversation_id="job51-ai-duplicate-file",
        )
        _insert_session(
            connection,
            session_id="session-op-job51",
            platform="job51",
            candidate="候选人丙",
            job="B端社交媒体运营",
            conversation_id="job51-op-1",
        )
        _insert_resume(
            connection,
            resume_id="resume-ai",
            name="候选人甲",
            job="AI Product Manager",
            score=91,
            platform="job51",
            owner="宋峰峰",
            updated_at="2026-07-16T02:30:00+00:00",
        )
        _insert_resume(
            connection,
            resume_id="resume-op",
            name="候选人丙",
            job="B端社交媒体运营",
            score=87,
            platform="job51",
            owner="和新红",
            updated_at="2026-07-16T02:40:00+00:00",
        )
        _insert_artifact(
            connection,
            artifact_id="artifact-ai-1",
            session_id="session-ai-job51",
            job="AI产品经理",
            file_hash="hash-ai",
        )
        _insert_artifact(
            connection,
            artifact_id="artifact-ai-duplicate",
            session_id="session-ai-job51-duplicate-file",
            job="AI产品经理",
            file_hash="hash-ai",
        )
        _insert_artifact(
            connection,
            artifact_id="artifact-op-1",
            session_id="session-op-job51",
            job="B端社交媒体运营",
            file_hash="hash-op",
        )
        _insert_review_state(
            connection,
            state_id="state-member-ai",
            user_id="feishu:review-member",
            resume_id="resume-ai",
            decision="suitable",
        )
        _insert_review_state(
            connection,
            state_id="state-member-op",
            user_id="feishu:review-member",
            resume_id="resume-op",
            decision="unsuitable",
        )
        _insert_review_state(
            connection,
            state_id="state-admin-op",
            user_id="feishu:review-admin",
            resume_id="resume-op",
            decision="suitable",
        )
        _insert_assignment(connection, "assignment-ai", "resume-ai")
        _insert_assignment(connection, "assignment-op", "resume-op")
        connection.commit()

    events = [
        _contact_event(
            timestamp="2026-07-16T01:00:00+00:00",
            owner="宋峰峰",
            platform="boss",
            conversation_id="boss-ai-1",
            response={
                "processed": 1,
                "nextAction": "request_resume",
                "decision": {
                    "action": "request_resume",
                    "result": {
                        "requested": True,
                        "confirmed": True,
                        "downloaded": False,
                    },
                },
            },
        ),
        _contact_event(
            timestamp="2026-07-16T02:00:00+00:00",
            owner="宋峰峰",
            platform="job51",
            conversation_id="job51-ai-1",
            response={"processed": 1, "nextAction": "wait"},
            anomaly=True,
            reason="candidate_identity_mismatch",
        ),
        _contact_event(
            timestamp="2026-07-16T03:00:00+00:00",
            owner="和新红",
            platform="job51",
            conversation_id="job51-op-1",
            response={"processed": 1, "nextAction": "wait"},
        ),
    ]
    (runs_dir / "run.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )
    return database, runs_dir


def _insert_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    platform: str,
    candidate: str,
    job: str,
    conversation_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO conversation_sessions (
          id, platform, owner, candidate_name, position, applied_position,
          platform_conversation_id, label, current_stage, next_action,
          recent_messages_fingerprint, identity_confidence, identity_warnings,
          last_seen_at, created_at, updated_at
        ) VALUES (?, ?, '宋峰峰', ?, ?, ?, ?, '', '', '', '', 'high', '[]',
                  '2026-07-16T03:00:00+00:00', '2026-07-16T00:00:00+00:00',
                  '2026-07-16T03:00:00+00:00')
        """,
        (session_id, platform, candidate, job, job, conversation_id),
    )


def _insert_resume(
    connection: sqlite3.Connection,
    *,
    resume_id: str,
    name: str,
    job: str,
    score: int,
    platform: str,
    owner: str,
    updated_at: str,
) -> None:
    payload = {
        "name": name,
        "phone": "13800138000",
        "email": "candidate@example.com",
        "rawText": "完整简历正文",
        "filePath": "C:/secret/resume.pdf",
    }
    connection.execute(
        """
        INSERT INTO resumes (
          id, payload, phone_key, job_type, match_score, updated_at,
          parsed_name, linked_platform, linked_owner
        ) VALUES (?, ?, '13800138000', ?, ?, ?, ?, ?, ?)
        """,
        (
            resume_id,
            json.dumps(payload, ensure_ascii=False),
            job,
            score,
            updated_at,
            name,
            platform,
            owner,
        ),
    )


def _insert_artifact(
    connection: sqlite3.Connection,
    *,
    artifact_id: str,
    session_id: str,
    job: str,
    file_hash: str,
) -> None:
    connection.execute(
        """
        INSERT INTO resume_artifacts (
          id, session_id, platform, owner, position, file_path, file_hash,
          source_kind, parse_status, created_at, updated_at
        ) VALUES (?, ?, 'job51', '宋峰峰', ?, 'C:/secret/resume.pdf', ?,
                  'attachment', 'parsed', '2026-07-16T02:15:00+00:00',
                  '2026-07-16T02:15:00+00:00')
        """,
        (artifact_id, session_id, job, file_hash),
    )


def _insert_review_state(
    connection: sqlite3.Connection,
    *,
    state_id: str,
    user_id: str,
    resume_id: str,
    decision: str,
) -> None:
    connection.execute(
        """
        INSERT INTO resume_review_states (
          id, user_id, user_name, resume_id, read_status, decision,
          created_at, updated_at
        ) VALUES (?, ?, '审阅人', ?, 'viewed', ?,
                  '2026-07-16T00:00:00+00:00', '2026-07-16T00:00:00+00:00')
        """,
        (state_id, user_id, resume_id, decision),
    )


def _insert_assignment(
    connection: sqlite3.Connection,
    assignment_id: str,
    resume_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO resume_assignments (
          id, resume_id, from_user_id, assigned_to_user_id, status,
          created_at, updated_at
        ) VALUES (?, ?, 'feishu:member', 'shared-admin-inbox', 'pending',
                  '2026-07-16T00:00:00+00:00', '2026-07-16T00:00:00+00:00')
        """,
        (assignment_id, resume_id),
    )


def _contact_event(
    *,
    timestamp: str,
    owner: str,
    platform: str,
    conversation_id: str,
    response: dict[str, object],
    anomaly: bool = False,
    reason: str = "",
) -> dict[str, object]:
    return {
        "event": "contact_result",
        "timestamp": timestamp,
        "owner": owner,
        "platform": platform,
        "summary": {"processed": 1, "conversationId": conversation_id},
        "response": response,
        "classification": {"is_anomaly": anomaly, "reasons": [reason] if reason else []},
    }
