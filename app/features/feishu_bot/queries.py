"""Permission-scoped read-only recruitment queries for the Feishu bot."""

from __future__ import annotations

import inspect
import json
import sqlite3
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.text import clean_text
from app.domain.resume.job_types import (
    any_job_type_matches,
    canonical_resume_job_type,
)
from app.features.feishu_bot.models import (
    BotActor,
    BotQueryPlan,
    BotQueryResult,
)

WorkerStatusProvider = Callable[
    [],
    Awaitable[list[dict[str, object]]] | list[dict[str, object]],
]

_INTENT_PERMISSIONS = {
    "daily_summary": "query:summary",
    "resume_counts": "query:resumes",
    "recent_resumes": "query:resumes",
    "review_summary": "query:reviews",
    "worker_status": "query:workers",
    "recent_errors": "query:errors",
}


class ReadOnlyRecruitmentQueries:
    """Execute validated bot plans without exposing a writable repository."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        manager_runs_dir: str | Path | None = None,
        worker_status_provider: WorkerStatusProvider | None = None,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.database_path = Path(database_path)
        self.manager_runs_dir = (
            Path(manager_runs_dir)
            if manager_runs_dir is not None
            else self.database_path.parent / "agent_manager" / "runs"
        )
        self.worker_status_provider = worker_status_provider
        self.timezone_name = timezone_name

    async def execute(self, actor: BotActor, plan: BotQueryPlan) -> BotQueryResult:
        permission = _INTENT_PERMISSIONS.get(plan.intent)
        if permission and not actor.can(permission):
            raise PermissionError(f"feishu_bot_permission_denied:{permission}")
        requested_jobs = _validated_requested_jobs(actor, plan.job_types)
        if plan.intent == "daily_summary":
            return self._daily_summary(actor, plan, requested_jobs)
        if plan.intent == "resume_counts":
            return self._resume_counts(actor, plan, requested_jobs)
        if plan.intent == "recent_resumes":
            return self._recent_resumes(actor, plan, requested_jobs)
        if plan.intent == "review_summary":
            return self._review_summary(actor, requested_jobs)
        if plan.intent == "worker_status":
            return await self._worker_status()
        if plan.intent == "recent_errors":
            return self._recent_errors(plan)
        if plan.intent == "help":
            return BotQueryResult(intent="help", data={})
        return BotQueryResult(
            intent="unsupported",
            data={"clarification": clean_text(plan.clarification)},
        )

    def available_job_types(self, actor: BotActor) -> list[str]:
        """Return only job names the actor is allowed to mention to Codex."""

        if not self.database_path.is_file():
            return [] if actor.is_admin else list(actor.job_types)
        jobs: list[str] = []
        with self._connect() as connection:
            if not _table_exists(connection, "resumes"):
                return [] if actor.is_admin else list(actor.job_types)
            rows = connection.execute("SELECT DISTINCT job_type FROM resumes").fetchall()
        for row in rows:
            job = canonical_resume_job_type(row["job_type"])
            if job and _job_allowed(actor, job) and job not in jobs:
                jobs.append(job)
        return sorted(jobs)

    def _daily_summary(
        self,
        actor: BotActor,
        plan: BotQueryPlan,
        requested_jobs: tuple[str, ...],
    ) -> BotQueryResult:
        date_text = _date_text(plan.date)
        start, end = _daily_utc_bounds(date_text, self.timezone_name)
        rows: dict[tuple[str, str], dict[str, object]] = {}
        manager_contact_events = 0
        unmapped_contacts = 0
        latest_contacts: dict[tuple[str, str, str, str], dict[str, object]] = {}
        with self._connect() as connection:
            sessions_by_conversation = _sessions_by_conversation(connection)
            for event in _manager_events(self.manager_runs_dir):
                if event.get("event") != "contact_result":
                    continue
                timestamp = _parse_iso_datetime(event.get("timestamp"))
                if timestamp is None or not (start <= timestamp < end):
                    continue
                summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
                if int(summary.get("processed") or 0) != 1:
                    continue
                manager_contact_events += 1
                platform = clean_text(event.get("platform")).lower()
                conversation_id = clean_text(summary.get("conversationId"))
                candidates = sessions_by_conversation.get((platform, conversation_id), [])
                if not candidates:
                    unmapped_contacts += 1
                    continue
                session = min(candidates, key=lambda item: _session_distance(item, timestamp))
                job = canonical_resume_job_type(
                    session.get("applied_position") or session.get("position")
                )
                if not _job_selected(actor, job, requested_jobs):
                    continue
                owner = clean_text(event.get("owner") or session.get("owner"))
                candidate = clean_text(session.get("candidate_name"))
                key = (platform, owner, candidate, job)
                current = latest_contacts.get(key)
                if current is None or timestamp > current["timestamp"]:
                    latest_contacts[key] = {
                        "timestamp": timestamp,
                        "platform": platform,
                        "job": job,
                        "event": event,
                    }

            for contact in latest_contacts.values():
                event = contact["event"]
                assert isinstance(event, dict)
                row = _report_row(rows, str(contact["job"]), str(contact["platform"]))
                row["processedContacts"] = int(row["processedContacts"]) + 1
                response = event.get("response") if isinstance(event.get("response"), dict) else {}
                handling = _resume_handling(str(contact["platform"]), response)
                if handling == "boss_request_verified_server_imap":
                    row["bossHandoffs"] = int(row["bossHandoffs"]) + 1
                elif handling == "resume_requested_waiting":
                    row["resumeRequestsWaiting"] = int(row["resumeRequestsWaiting"]) + 1
                classification = (
                    event.get("classification")
                    if isinstance(event.get("classification"), dict)
                    else {}
                )
                if classification.get("is_anomaly"):
                    row["anomalies"] = int(row["anomalies"]) + 1

            seen_hashes: set[str] = set()
            if _table_exists(connection, "resume_artifacts"):
                artifact_rows = connection.execute(
                    """
                    SELECT ra.*, cs.applied_position, cs.position AS session_position
                    FROM resume_artifacts AS ra
                    LEFT JOIN conversation_sessions AS cs ON cs.id = ra.session_id
                    WHERE ra.platform IN ('job51', 'zhilian')
                      AND ra.created_at >= ? AND ra.created_at < ?
                    ORDER BY ra.created_at, ra.id
                    """,
                    (start.isoformat(), end.isoformat()),
                ).fetchall()
                for artifact in artifact_rows:
                    file_hash = clean_text(artifact["file_hash"])
                    if not file_hash or file_hash in seen_hashes:
                        continue
                    job = canonical_resume_job_type(
                        artifact["applied_position"]
                        or artifact["session_position"]
                        or artifact["position"]
                    )
                    if not _job_selected(actor, job, requested_jobs):
                        continue
                    seen_hashes.add(file_hash)
                    row = _report_row(rows, job, clean_text(artifact["platform"]).lower())
                    row["localUniqueFiles"] = int(row["localUniqueFiles"]) + 1

        by_job_platform = list(rows.values())
        for row in by_job_platform:
            row["businessResumeAcquisitions"] = int(row["bossHandoffs"]) + int(
                row["localUniqueFiles"]
            )
        by_job_platform.sort(key=lambda item: (str(item["job"]), str(item["platform"])))
        total_keys = (
            "processedContacts",
            "bossHandoffs",
            "localUniqueFiles",
            "businessResumeAcquisitions",
            "resumeRequestsWaiting",
            "anomalies",
        )
        totals = {
            key: sum(int(row[key]) for row in by_job_platform)
            for key in total_keys
        }
        return BotQueryResult(
            intent="daily_summary",
            data={
                "date": date_text,
                "timezone": self.timezone_name,
                "totals": totals,
                "byJobPlatform": by_job_platform,
            },
            coverage={
                "source": "agent_manager_run_jsonl_plus_resume_artifacts",
                "managerContactEvents": manager_contact_events,
                "deduplicatedManagerContacts": len(latest_contacts),
                "unmappedContacts": unmapped_contacts,
                "managerRunsAvailable": self.manager_runs_dir.is_dir(),
            },
        )

    def _resume_counts(
        self,
        actor: BotActor,
        plan: BotQueryPlan,
        requested_jobs: tuple[str, ...],
    ) -> BotQueryResult:
        if plan.date or plan.date_start or plan.date_end:
            return self._dated_resume_counts(actor, plan, requested_jobs)
        counts: Counter[str] = Counter()
        with self._connect() as connection:
            rows = connection.execute("SELECT job_type FROM resumes").fetchall()
        for row in rows:
            job = canonical_resume_job_type(row["job_type"])
            if _job_selected(actor, job, requested_jobs):
                counts[job] += 1
        by_job = [
            {"jobType": job, "count": count}
            for job, count in sorted(counts.items())
        ]
        return BotQueryResult(
            intent="resume_counts",
            data={"total": sum(counts.values()), "byJob": by_job},
            coverage={"source": "resumes"},
        )

    def _dated_resume_counts(
        self,
        actor: BotActor,
        plan: BotQueryPlan,
        requested_jobs: tuple[str, ...],
    ) -> BotQueryResult:
        start, end = _plan_utc_bounds(plan, self.timezone_name)
        counts: Counter[str] = Counter()
        seen_hashes: set[str] = set()
        with self._connect() as connection:
            if not _table_exists(connection, "resume_artifacts"):
                return BotQueryResult(
                    intent="resume_counts",
                    data={"total": 0, "byJob": []},
                    coverage={"source": "resume_artifacts", "available": False},
                )
            rows = connection.execute(
                """
                SELECT ra.file_hash, ra.position, cs.applied_position,
                       cs.position AS session_position
                FROM resume_artifacts AS ra
                LEFT JOIN conversation_sessions AS cs ON cs.id = ra.session_id
                WHERE ra.created_at >= ? AND ra.created_at < ?
                ORDER BY ra.created_at, ra.id
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        for row in rows:
            file_hash = clean_text(row["file_hash"])
            if not file_hash or file_hash in seen_hashes:
                continue
            job = canonical_resume_job_type(
                row["applied_position"] or row["session_position"] or row["position"]
            )
            if not _job_selected(actor, job, requested_jobs):
                continue
            seen_hashes.add(file_hash)
            counts[job] += 1
        by_job = [
            {"jobType": job, "count": count}
            for job, count in sorted(counts.items())
        ]
        return BotQueryResult(
            intent="resume_counts",
            data={"total": sum(counts.values()), "byJob": by_job},
            coverage={
                "source": "resume_artifacts",
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )

    def _recent_resumes(
        self,
        actor: BotActor,
        plan: BotQueryPlan,
        requested_jobs: tuple[str, ...],
    ) -> BotQueryResult:
        limit = max(1, min(int(plan.limit), 20))
        items: list[dict[str, object]] = []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, payload, job_type, match_score, updated_at,
                       parsed_name, linked_platform, linked_owner
                FROM resumes
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        for row in rows:
            job = canonical_resume_job_type(row["job_type"])
            if not _job_selected(actor, job, requested_jobs):
                continue
            payload = _json_dict(row["payload"])
            items.append(
                {
                    "id": str(row["id"]),
                    "name": clean_text(row["parsed_name"] or payload.get("name"))
                    or "未命名候选人",
                    "jobType": job,
                    "score": row["match_score"],
                    "platform": clean_text(row["linked_platform"]),
                    "owner": clean_text(row["linked_owner"]),
                    "updatedAt": str(row["updated_at"] or ""),
                }
            )
            if len(items) >= limit:
                break
        return BotQueryResult(
            intent="recent_resumes",
            data={"items": items, "totalReturned": len(items)},
            coverage={"source": "resumes", "sensitiveFieldsExcluded": True},
        )

    def _review_summary(
        self,
        actor: BotActor,
        requested_jobs: tuple[str, ...],
    ) -> BotQueryResult:
        decisions: Counter[str] = Counter()
        with self._connect() as connection:
            params: tuple[object, ...] = ()
            user_clause = ""
            if not actor.is_admin:
                if not actor.review_user_id:
                    return BotQueryResult(
                        intent="review_summary",
                        data={"scope": "personal", "decisions": {}, "total": 0},
                        coverage={"reviewUserMapped": False},
                    )
                user_clause = " AND rrs.user_id = ?"
                params = (actor.review_user_id,)
            rows = connection.execute(
                f"""
                SELECT rrs.decision, r.job_type
                FROM resume_review_states AS rrs
                JOIN resumes AS r ON r.id = rrs.resume_id
                WHERE rrs.decision != 'undecided'{user_clause}
                """,
                params,
            ).fetchall()
            for row in rows:
                job = canonical_resume_job_type(row["job_type"])
                if _job_selected(actor, job, requested_jobs):
                    decisions[clean_text(row["decision"])] += 1
            shared_pending = 0
            if actor.is_admin:
                pending_rows = connection.execute(
                    """
                    SELECT r.job_type
                    FROM resume_assignments AS ra
                    JOIN resumes AS r ON r.id = ra.resume_id
                    WHERE ra.assigned_to_user_id = 'shared-admin-inbox'
                      AND ra.status = 'pending'
                    """
                ).fetchall()
                shared_pending = sum(
                    1
                    for row in pending_rows
                    if _job_selected(
                        actor,
                        canonical_resume_job_type(row["job_type"]),
                        requested_jobs,
                    )
                )
        data: dict[str, object] = {
            "scope": "admin" if actor.is_admin else "personal",
            "decisions": dict(sorted(decisions.items())),
            "total": sum(decisions.values()),
        }
        if actor.is_admin:
            data["sharedPending"] = shared_pending
        return BotQueryResult(
            intent="review_summary",
            data=data,
            coverage={"reviewUserMapped": bool(actor.review_user_id) or actor.is_admin},
        )

    async def _worker_status(self) -> BotQueryResult:
        raw: list[dict[str, object]] = []
        if self.worker_status_provider is not None:
            value = self.worker_status_provider()
            raw = await value if inspect.isawaitable(value) else value
        items = []
        for status in raw:
            ready = bool(status.get("agentReady")) and bool(status.get("browserReady"))
            busy = bool(status.get("agentBusy"))
            items.append(
                {
                    "owner": clean_text(status.get("owner")) or "未知负责人",
                    "platform": clean_text(status.get("platform")) or "all",
                    "status": "busy"
                    if busy
                    else "ready"
                    if ready
                    else clean_text(status.get("status")) or "unknown",
                    "agentReady": bool(status.get("agentReady")),
                    "browserReady": bool(status.get("browserReady")),
                    "agentBusy": busy,
                    "browserBackend": clean_text(status.get("browserBackend")),
                    "error": clean_text(status.get("error"))[:300],
                }
            )
        return BotQueryResult(
            intent="worker_status",
            data={"items": items},
            coverage={"providerAvailable": self.worker_status_provider is not None},
        )

    def _recent_errors(self, plan: BotQueryPlan) -> BotQueryResult:
        limit = max(1, min(int(plan.limit), 20))
        items: list[dict[str, object]] = []
        for event in reversed(_manager_events(self.manager_runs_dir)):
            classification = (
                event.get("classification")
                if isinstance(event.get("classification"), dict)
                else {}
            )
            if not classification.get("is_anomaly"):
                continue
            reasons = classification.get("reasons")
            reason = (
                clean_text(reasons[0])
                if isinstance(reasons, list) and reasons
                else clean_text(classification.get("reason"))
            )
            items.append(
                {
                    "timestamp": clean_text(event.get("timestamp")),
                    "owner": clean_text(event.get("owner")),
                    "platform": clean_text(event.get("platform")).lower(),
                    "reason": reason or "unknown_anomaly",
                }
            )
            if len(items) >= limit:
                break
        return BotQueryResult(
            intent="recent_errors",
            data={"items": items},
            coverage={"source": "agent_manager_run_jsonl"},
        )

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise RuntimeError(f"feishu_bot_database_not_found:{self.database_path}")
        uri = self.database_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _validated_requested_jobs(
    actor: BotActor,
    requested: list[str],
) -> tuple[str, ...]:
    result: list[str] = []
    for value in requested:
        job = canonical_resume_job_type(value)
        if not job:
            continue
        if not _job_allowed(actor, job):
            raise PermissionError(f"feishu_bot_job_scope_denied:{job}")
        if job not in result:
            result.append(job)
    return tuple(result)


def _job_allowed(actor: BotActor, job: str) -> bool:
    return "*" in actor.job_types or any_job_type_matches(job, actor.job_types)


def _job_selected(actor: BotActor, job: str, requested: tuple[str, ...]) -> bool:
    if not job or not _job_allowed(actor, job):
        return False
    return not requested or any_job_type_matches(job, requested)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _sessions_by_conversation(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], list[dict[str, object]]]:
    if not _table_exists(connection, "conversation_sessions"):
        return {}
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in connection.execute("SELECT * FROM conversation_sessions"):
        item = dict(row)
        key = (
            clean_text(item.get("platform")).lower(),
            clean_text(item.get("platform_conversation_id")),
        )
        grouped.setdefault(key, []).append(item)
    return grouped


def _session_distance(session: dict[str, object], timestamp: datetime) -> float:
    seen = _parse_iso_datetime(session.get("last_seen_at") or session.get("updated_at"))
    return abs((seen - timestamp).total_seconds()) if seen else float("inf")


def _manager_events(runs_dir: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    if not runs_dir.is_dir():
        return events
    for path in sorted(runs_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
    return events


def _resume_handling(platform: str, response: dict[str, object]) -> str:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    decision = (
        response.get("decision") if isinstance(response.get("decision"), dict) else {}
    )
    next_action = clean_text(response.get("nextAction") or response.get("next_action"))
    action = clean_text(decision.get("action") or response.get("action"))
    requested = bool(result.get("requested") or response.get("requested"))
    confirmed = bool(result.get("confirmed") or response.get("confirmed"))
    if platform == "boss" and requested and confirmed:
        return "boss_request_verified_server_imap"
    if next_action == "request_resume" or action == "request_resume":
        return "resume_requested_waiting"
    return "none"


def _report_row(
    rows: dict[tuple[str, str], dict[str, object]],
    job: str,
    platform: str,
) -> dict[str, object]:
    key = (job, platform)
    if key not in rows:
        rows[key] = {
            "job": job,
            "platform": platform,
            "processedContacts": 0,
            "bossHandoffs": 0,
            "localUniqueFiles": 0,
            "businessResumeAcquisitions": 0,
            "resumeRequestsWaiting": 0,
            "anomalies": 0,
        }
    return rows[key]


def _date_text(value: str) -> str:
    if clean_text(value):
        datetime.strptime(value, "%Y-%m-%d")
        return value
    return datetime.now(_timezone("Asia/Shanghai")).strftime("%Y-%m-%d")


def _daily_utc_bounds(date_text: str, timezone_name: str) -> tuple[datetime, datetime]:
    zone = _timezone(timezone_name)
    local_start = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=zone)
    return local_start.astimezone(UTC), (local_start + timedelta(days=1)).astimezone(UTC)


def _plan_utc_bounds(plan: BotQueryPlan, timezone_name: str) -> tuple[datetime, datetime]:
    if plan.date:
        return _daily_utc_bounds(plan.date, timezone_name)
    zone = _timezone(timezone_name)
    start_text = plan.date_start or datetime.now(zone).strftime("%Y-%m-%d")
    end_text = plan.date_end or start_text
    start = datetime.strptime(start_text, "%Y-%m-%d").replace(tzinfo=zone)
    end = datetime.strptime(end_text, "%Y-%m-%d").replace(tzinfo=zone) + timedelta(days=1)
    if end - start > timedelta(days=31):
        raise ValueError("feishu_bot_date_range_too_large")
    return start.astimezone(UTC), end.astimezone(UTC)


def _timezone(name: str) -> timezone | ZoneInfo:
    if name == "Asia/Shanghai":
        return timezone(timedelta(hours=8), name="Asia/Shanghai")
    return ZoneInfo(name)


def _parse_iso_datetime(value: object) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _json_dict(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
