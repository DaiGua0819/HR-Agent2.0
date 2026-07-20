"""Daily automation aggregation and runtime status freshness rules."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.auth.access import ADMIN_OWNERS
from app.core.constants import Platform
from app.domain.automation_monitoring.repository import AutomationMonitoringRepository


class AutomationMonitoringService:
    def __init__(self, repository: AutomationMonitoringRepository) -> None:
        self.repository = repository

    def daily_summary(
        self,
        *,
        date: str,
        platform: str = "",
        owner: str = "",
        job_type: str = "",
    ) -> dict[str, object]:
        start, end = _utc_bounds(date)
        raw_rows = self.repository.list_events(
            start=start.isoformat(),
            end=end.isoformat(),
            platform=platform,
            owner=owner,
            job_type=job_type,
        )
        rows = _daily_candidate_rows(raw_rows)
        facet_rows = rows
        if platform or owner or job_type:
            facet_rows = _daily_candidate_rows(
                self.repository.list_events(
                    start=start.isoformat(),
                    end=end.isoformat(),
                )
            )
        totals = _empty_counts()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        seen: dict[str, set[str]] = defaultdict(set)
        group_seen: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for row in rows:
            group_key = (str(row["job_type"] or "未识别岗位"), str(row["platform"]))
            item = grouped.setdefault(
                group_key,
                {"jobType": group_key[0], "platform": group_key[1], **_empty_counts()},
            )
            _accumulate(row, totals, seen)
            _accumulate(row, item, group_seen[group_key])
        version = (
            f"{len(raw_rows)}:"
            f"{max((str(row['updated_at']) for row in raw_rows), default='')}"
        )
        return {
            "date": date,
            "timezone": "Asia/Shanghai",
            "totals": totals,
            "byJobPlatform": sorted(
                grouped.values(), key=lambda item: (str(item["jobType"]), str(item["platform"]))
            ),
            "coverage": {
                "source": "automation_contact_events",
                "events": len(raw_rows),
                "candidates": len(rows),
            },
            "facets": {
                "owners": sorted({str(row["owner"]) for row in facet_rows if row["owner"]}),
                "platforms": sorted(
                    {str(row["platform"]) for row in facet_rows if row["platform"]}
                ),
                "jobTypes": sorted(
                    {str(row["job_type"]) for row in facet_rows if row["job_type"]}
                ),
            },
            "updatedAt": datetime.now(UTC).isoformat(),
            "version": version,
        }

    def daily_details(
        self,
        *,
        date: str,
        metric: str = "processedContacts",
        platform: str = "",
        owner: str = "",
        job_type: str = "",
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, object]:
        start, end = _utc_bounds(date)
        rows = _daily_candidate_rows(
            self.repository.list_events(
                start=start.isoformat(),
                end=end.isoformat(),
                platform=platform,
                owner=owner,
                job_type=job_type,
            )
        )
        filtered = _dedupe_details(rows, metric)
        safe_size = max(1, min(page_size, 100))
        safe_page = max(1, page)
        start_index = (safe_page - 1) * safe_size
        page_rows = filtered[start_index : start_index + safe_size]
        resume_ids = self.repository.resolve_resume_ids(page_rows)
        return {
            "date": date,
            "metric": metric,
            "total": len(filtered),
            "page": safe_page,
            "pageSize": safe_size,
            "pages": max(1, (len(filtered) + safe_size - 1) // safe_size),
            "items": [
                _event_payload(row, resume_id=resume_ids.get(str(row["id"]), ""))
                for row in page_rows
            ],
        }

    def runtime_status(self, *, now: datetime | None = None) -> dict[str, object]:
        current = now or datetime.now(UTC)
        targets_by_key: dict[str, dict[str, object]] = {}
        for row in self.repository.list_runtime_statuses():
            checked_at = _parse_datetime(row["checked_at"])
            age = max(0, int((current - checked_at).total_seconds())) if checked_at else 10**9
            status = str(row["status"])
            reason = str(row["reason"] or "")
            if age > 120:
                status = "worker_offline"
                reason = reason or "heartbeat_timeout"
            elif age > 45:
                status = "stale"
                reason = reason or "heartbeat_stale"
            targets_by_key[str(row["target_key"])] = {
                    "targetKey": row["target_key"],
                    "owner": row["owner"],
                    "platform": row["platform"],
                    "status": status,
                    "agentReady": bool(row["agent_ready"]),
                    "browserReady": bool(row["browser_ready"]),
                    "cdpReady": bool(row["cdp_ready"]),
                    "agentBusy": bool(row["agent_busy"]),
                    "authenticated": bool(row["authenticated"]),
                    "needsLogin": bool(row["needs_login"]),
                    "securityVerification": bool(row["security_verification"]),
                    "accountAbnormal": bool(row["account_abnormal"]),
                    "pagePresent": bool(row["page_present"]),
                    "paused": bool(row["paused"]),
                    "reason": reason,
                    "checkedAt": row["checked_at"],
                    "ageSeconds": age,
                }
        for owner in ADMIN_OWNERS:
            for platform in (Platform.BOSS, Platform.JOB51, Platform.ZHILIAN):
                target_key = f"{owner}:{platform.value}"
                targets_by_key.setdefault(
                    target_key,
                    {
                        "targetKey": target_key,
                        "owner": owner,
                        "platform": platform.value,
                        "status": "worker_offline",
                        "agentReady": False,
                        "browserReady": False,
                        "cdpReady": False,
                        "agentBusy": False,
                        "authenticated": False,
                        "needsLogin": False,
                        "securityVerification": False,
                        "accountAbnormal": False,
                        "pagePresent": False,
                        "paused": False,
                        "reason": "no_heartbeat",
                        "checkedAt": "",
                        "ageSeconds": None,
                    },
                )
        targets = sorted(
            targets_by_key.values(),
            key=lambda item: (str(item["owner"]), str(item["platform"])),
        )
        return {
            "targets": targets,
            "updatedAt": current.isoformat(),
            "version": ":".join(str(item["checkedAt"]) for item in targets),
        }


def _utc_bounds(date_text: str) -> tuple[datetime, datetime]:
    china = timezone(timedelta(hours=8), name="Asia/Shanghai")
    start = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=china)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _parse_datetime(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _empty_counts() -> dict[str, int]:
    return {
        "processedContacts": 0,
        "sentCompanyInfo": 0,
        "requestedResume": 0,
        "candidateQuestions": 0,
        "knowledgeAnswered": 0,
        "businessResumeAcquisitions": 0,
        "anomalies": 0,
    }


def _daily_candidate_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[_candidate_key(row)].append(row)

    merged_rows: list[dict[str, object]] = []
    flag_columns = (
        "processed",
        "sent_company_info",
        "requested_resume",
        "candidate_question",
        "knowledge_answered",
        "resume_acquired",
        "anomaly",
    )
    fallback_columns = (
        "owner",
        "platform",
        "candidate_name",
        "job_type",
        "resume_handling",
        "resume_file_hash",
    )
    for candidate_key, candidate_rows in grouped.items():
        ordered = sorted(
            candidate_rows,
            key=lambda row: (
                str(row.get("occurred_at") or ""),
                str(row.get("updated_at") or ""),
                str(row.get("id") or ""),
            ),
            reverse=True,
        )
        latest = dict(ordered[0])
        latest["contact_key"] = candidate_key
        for column in flag_columns:
            latest[column] = int(any(bool(row.get(column)) for row in ordered))
        for column in fallback_columns:
            if latest.get(column):
                continue
            latest[column] = next(
                (row.get(column) for row in ordered if row.get(column)),
                latest.get(column),
            )
        reasons: list[str] = []
        for row in ordered:
            reason = str(row.get("anomaly_reason") or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
        if reasons:
            latest["anomaly_reason"] = "; ".join(reasons)
        merged_rows.append(latest)
    return sorted(
        merged_rows,
        key=lambda row: (
            str(row.get("occurred_at") or ""),
            str(row.get("updated_at") or ""),
            str(row.get("id") or ""),
        ),
        reverse=True,
    )


def _candidate_key(row: dict[str, object]) -> str:
    contact_key = str(row.get("contact_key") or "")
    if contact_key.startswith("session|"):
        parts = contact_key.split("|")
        return "|".join(parts[:2]) if len(parts) >= 2 else contact_key
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
    if isinstance(payload, dict):
        session_id = str(payload.get("sessionId") or "")
        if session_id:
            return f"session|{session_id}"
    return contact_key or str(row.get("id") or "")


def _metric_key(row: dict[str, object], metric: str) -> str:
    contact = str(row["contact_key"] or row["id"])
    if metric == "businessResumeAcquisitions" and str(row["platform"]) != "boss":
        return str(row["resume_file_hash"] or "")
    return contact


def _accumulate(row: dict[str, object], counts: dict[str, Any], seen: dict[str, set[str]]) -> None:
    flags = {
        "processedContacts": bool(row["processed"]),
        "sentCompanyInfo": bool(row["sent_company_info"]),
        "requestedResume": bool(row["requested_resume"]),
        "candidateQuestions": bool(row["candidate_question"]),
        "knowledgeAnswered": bool(row["knowledge_answered"]),
        "businessResumeAcquisitions": bool(row["resume_acquired"]),
        "anomalies": bool(row["anomaly"]),
    }
    for metric, enabled in flags.items():
        key = _metric_key(row, metric)
        if enabled and key and key not in seen[metric]:
            seen[metric].add(key)
            counts[metric] += 1


def _dedupe_details(rows: list[dict[str, object]], metric: str) -> list[dict[str, object]]:
    flag_columns = {
        "processedContacts": "processed",
        "sentCompanyInfo": "sent_company_info",
        "requestedResume": "requested_resume",
        "candidateQuestions": "candidate_question",
        "knowledgeAnswered": "knowledge_answered",
        "businessResumeAcquisitions": "resume_acquired",
        "anomalies": "anomaly",
    }
    column = flag_columns.get(metric, "processed")
    result = []
    seen: set[str] = set()
    for row in rows:
        key = _metric_key(row, metric)
        if bool(row[column]) and key and key not in seen:
            seen.add(key)
            result.append(row)
    return result


def _event_payload(
    row: dict[str, object],
    *,
    resume_id: str = "",
) -> dict[str, object]:
    return {
        "id": row["id"],
        "time": row["occurred_at"],
        "platform": row["platform"],
        "owner": row["owner"],
        "candidateName": row["candidate_name"],
        "jobType": row["job_type"],
        "action": row["action"],
        "stage": row["stage"],
        "resumeHandling": row["resume_handling"],
        "anomaly": bool(row["anomaly"]),
        "anomalyReason": row["anomaly_reason"],
        "resumeId": resume_id,
        "resumeDownloadUrl": f"/api/resumes/{resume_id}/download" if resume_id else "",
    }
