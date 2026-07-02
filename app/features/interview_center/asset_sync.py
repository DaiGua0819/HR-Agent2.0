"""Bitable asset synchronization for interview-center sessions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.text import clean_text
from app.features.interview_center.feishu.bitable import (
    BitableClientProtocol,
    find_existing_bitable_record,
)
from app.features.interview_center.feishu.routes import BitableTarget, resolve_bitable_target
from app.features.interview_center.render_resume_image import render_resume_image
from app.features.interview_center.render_summary_image import render_summary_image
from app.features.interview_center.store import InterviewSession, InterviewStoreProtocol, now_iso
from app.settings import PROJECT_ROOT

RESUME_FIELD = "简历"
INTERVIEW_RECORD_FIELD = "面试记录"
SKILL_EVALUATION_FIELD = "技能评价"
SECOND_INTERVIEW_EVALUATION_FIELD = "复试结果评价"


class BitableAssetSync:
    """Synchronize rendered images and evaluation docs to the routed Bitable table."""

    def __init__(
        self,
        *,
        store: InterviewStoreProtocol,
        bitable: BitableClientProtocol,
        default_table_id: str = "",
        output_dir: str | Path | None = None,
        resume_image_renderer: Callable[..., str] | None = None,
        summary_image_renderer: Callable[..., str] | None = None,
    ) -> None:
        self.store = store
        self.bitable = bitable
        self.default_table_id = default_table_id
        self.output_dir = Path(output_dir or PROJECT_ROOT / "data" / "interview_center")
        self.resume_image_renderer = resume_image_renderer or self._render_resume_image
        self.summary_image_renderer = summary_image_renderer or self._render_summary_image

    async def ensure_resume_image(
        self,
        session: InterviewSession,
        resume: dict[str, Any],
        *,
        resume_pdf_path: str,
    ) -> dict[str, Any]:
        """Ensure the resume screenshot is attached to the candidate Bitable record."""

        target = self._resolve_allowed_target(session, resume)
        if target.get("skipped"):
            return target
        if session.bitable_resume_image.get("fileToken") and session.bitable_record_id:
            return {
                "skipped": True,
                "reason": "resume_image_already_synced",
                "recordId": session.bitable_record_id,
            }
        records = await self.bitable.list_records(target["tableId"])
        existing = _existing_record_for_session(session, records, resume)
        if existing.get("skipped"):
            return existing
        record = existing.get("record")
        record_id = _record_id(record)
        tokens = _attachment_tokens((record or {}).get("fields", {}).get(RESUME_FIELD))
        if tokens:
            self._save_record_binding(session, target, record_id)
            return {
                "skipped": True,
                "reason": "bitable_resume_field_already_has_attachment",
                "recordId": record_id,
                "attachmentCount": len(tokens),
            }
        image_path = self.resume_image_renderer(
            session=session,
            resume=resume,
            resume_pdf_path=resume_pdf_path,
            output_path=str(self.output_dir / f"{session.id}_resume.png"),
        )
        file_token = await self.bitable.upload_file(image_path)
        fields = {
            **_candidate_fields(session, resume),
            RESUME_FIELD: [{"file_token": file_token}],
        }
        saved_record = await _write_record(self.bitable, target["tableId"], record_id, fields)
        next_record_id = _record_id(saved_record) or record_id
        resume_image = {
            "status": "synced",
            "field": RESUME_FIELD,
            "recordId": next_record_id,
            "fileToken": file_token,
            "imagePath": str(image_path),
            "syncedAt": now_iso(),
            "tableId": target["tableId"],
            "tableName": target["tableName"],
        }
        session.bitable_record_id = next_record_id
        session.bitable_table_id = target["tableId"]
        session.bitable_table_name = target["tableName"]
        session.bitable_resume_image = resume_image
        saved = self.store.save(session)
        return {
            "ok": True,
            "session": saved.to_dict(),
            "recordId": next_record_id,
            "resumeImage": resume_image,
        }

    async def ensure_interview_record_image(
        self,
        session: InterviewSession,
        resume: dict[str, Any],
    ) -> dict[str, Any]:
        """Ensure the interview summary image is attached to Bitable."""

        if not session.interview_evaluation:
            return {"skipped": True, "reason": "missing_interview_evaluation"}
        target = self._resolve_allowed_target(session, resume)
        if target.get("skipped"):
            return target
        records = await self.bitable.list_records(target["tableId"])
        existing = _existing_record_for_session(session, records, resume)
        if existing.get("skipped"):
            return existing
        record = existing.get("record")
        record_id = _record_id(record)
        tokens = _attachment_tokens((record or {}).get("fields", {}).get(INTERVIEW_RECORD_FIELD))
        if tokens:
            return {
                "skipped": True,
                "reason": "bitable_interview_record_field_already_has_attachment",
                "recordId": record_id,
                "attachmentCount": len(tokens),
            }
        image_path = self.summary_image_renderer(
            session=session,
            resume=resume,
            output_path=str(self.output_dir / f"{session.id}_summary.png"),
        )
        file_token = await self.bitable.upload_file(image_path)
        fields = {
            **_candidate_fields(session, resume),
            INTERVIEW_RECORD_FIELD: [{"file_token": file_token}],
        }
        saved_record = await _write_record(self.bitable, target["tableId"], record_id, fields)
        next_record_id = _record_id(saved_record) or record_id
        interview_record_image = {
            "status": "synced",
            "field": INTERVIEW_RECORD_FIELD,
            "recordId": next_record_id,
            "fileToken": file_token,
            "imagePath": str(image_path),
            "syncedAt": now_iso(),
            "tableId": target["tableId"],
            "tableName": target["tableName"],
        }
        session.bitable_record_id = next_record_id
        session.bitable_table_id = target["tableId"]
        session.bitable_table_name = target["tableName"]
        session.bitable_interview_record_image = interview_record_image
        saved = self.store.save(session)
        return {
            "ok": True,
            "session": saved.to_dict(),
            "recordId": next_record_id,
            "interviewRecordImage": interview_record_image,
        }

    async def ensure_evaluation_document(
        self,
        session: InterviewSession,
        resume: dict[str, Any],
        document: dict[str, Any],
        *,
        second_round: bool = False,
    ) -> dict[str, Any]:
        """Ensure a skill or second-interview evaluation document link is written."""

        if not session.interview_evaluation:
            return {"skipped": True, "reason": "missing_interview_evaluation"}
        target = self._resolve_allowed_target(session, resume)
        if target.get("skipped"):
            return target
        field_name = SECOND_INTERVIEW_EVALUATION_FIELD if second_round else SKILL_EVALUATION_FIELD
        records = await self.bitable.list_records(target["tableId"])
        existing = _existing_record_for_session(session, records, resume)
        if existing.get("skipped"):
            return existing
        record = existing.get("record")
        record_id = _record_id(record)
        existing_text = _extract_field_text((record or {}).get("fields", {}).get(field_name))
        if _has_docx_link(existing_text):
            return {
                "skipped": True,
                "reason": "bitable_evaluation_field_already_has_docx_link",
                "recordId": record_id,
                "field": field_name,
            }
        field_value = (
            document.get("url") or document.get("documentId") or document.get("title") or ""
        )
        fields = {**_candidate_fields(session, resume), field_name: field_value}
        saved_record = await _write_record(self.bitable, target["tableId"], record_id, fields)
        next_record_id = _record_id(saved_record) or record_id
        evaluation_document = {
            "status": "synced",
            "field": field_name,
            "recordId": next_record_id,
            "documentId": document.get("documentId") or "",
            "url": document.get("url") or "",
            "title": document.get("title") or "",
            "syncedAt": now_iso(),
            "tableId": target["tableId"],
            "tableName": target["tableName"],
        }
        session.bitable_record_id = next_record_id
        session.bitable_table_id = target["tableId"]
        session.bitable_table_name = target["tableName"]
        if second_round:
            session.bitable_second_interview_evaluation_document = evaluation_document
            result_key = "secondInterviewEvaluationDocument"
        else:
            session.bitable_skill_evaluation_document = evaluation_document
            result_key = "skillEvaluationDocument"
        saved = self.store.save(session)
        return {
            "ok": True,
            "session": saved.to_dict(),
            "recordId": next_record_id,
            result_key: evaluation_document,
            "evaluationDocument": evaluation_document,
        }

    def _resolve_allowed_target(
        self,
        session: InterviewSession,
        resume: dict[str, Any],
    ) -> dict[str, Any]:
        if not session.payload.get("isInterviewLike"):
            return {"skipped": True, "reason": "not_calendar_interview"}
        target = resolve_bitable_target(
            {"session": session.to_dict(), "resume": resume},
            default_table_id=self.default_table_id,
        )
        if not target.table_id:
            return {"skipped": True, "reason": "missing_bitable_config"}
        if self.default_table_id and not target.route_matched:
            return {
                "skipped": True,
                "reason": "job_not_in_bitable_table",
                "jobText": target.job_text,
                "tableId": target.table_id,
            }
        return _target_payload(target)

    def _save_record_binding(
        self,
        session: InterviewSession,
        target: dict[str, Any],
        record_id: str,
    ) -> None:
        session.bitable_record_id = record_id
        session.bitable_table_id = target["tableId"]
        session.bitable_table_name = target["tableName"]
        self.store.save(session)

    def _render_resume_image(self, **kwargs: Any) -> str:
        resume_pdf_path = kwargs.get("resume_pdf_path")
        if not resume_pdf_path:
            raise ValueError("missing_resume_pdf_path")
        output_path = kwargs["output_path"]
        render_resume_image(resume_pdf_path, output_path)
        return str(output_path)

    def _render_summary_image(self, **kwargs: Any) -> str:
        output_path = kwargs["output_path"]
        session = kwargs["session"]
        render_summary_image(session.to_dict(), output_path)
        return str(output_path)


def _target_payload(target: BitableTarget) -> dict[str, Any]:
    return {
        "tableId": target.table_id,
        "tableName": target.table_name,
        "routeMatched": target.route_matched,
        "routeKeyword": target.route_keyword,
        "jobText": target.job_text,
    }


def _existing_record_for_session(
    session: InterviewSession,
    records: list[dict[str, Any]],
    resume: dict[str, Any],
) -> dict[str, Any]:
    direct_record = None
    if session.bitable_record_id:
        direct_record = next(
            (record for record in records if _record_id(record) == session.bitable_record_id),
            None,
        )
    if direct_record:
        return {"record": direct_record, "reason": "session_record"}
    existing = find_existing_bitable_record(records, resume)
    if existing.reason == "ambiguous_name_match":
        return {
            "skipped": True,
            "reason": "ambiguous_bitable_candidate",
            "count": existing.count,
        }
    return {"record": existing.record, "reason": existing.reason}


async def _write_record(
    bitable: BitableClientProtocol,
    table_id: str,
    record_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    if record_id:
        return await bitable.update_record(table_id, record_id, fields)
    return await bitable.create_record(table_id, fields)


def _candidate_fields(session: InterviewSession, resume: dict[str, Any]) -> dict[str, Any]:
    candidate_name = str(resume.get("name") or session.candidate_name or "")
    return {
        "候选人姓名": candidate_name,
        "姓名": candidate_name,
        "候选人联系电话": resume.get("phone") or resume.get("phone_key") or "",
        "初次沟通日期": int(session.start_time) * 1000 if session.start_time else "",
        "职位": resume.get("jobType") or resume.get("job_type") or session.job_type or "",
    }


def _record_id(record: dict[str, Any] | None) -> str:
    return str((record or {}).get("record_id") or (record or {}).get("id") or "")


def _attachment_tokens(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("file_token") or item.get("fileToken") or item.get("token") or "")
        for item in value
        if isinstance(item, dict)
        and (item.get("file_token") or item.get("fileToken") or item.get("token"))
    ]


def _extract_field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str | int | float):
        return str(value)
    if isinstance(value, list | tuple | set):
        return " ".join(_extract_field_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(
            clean_text(value.get(key))
            for key in ("text", "name", "url", "link", "id")
            if clean_text(value.get(key))
        )
    return str(value)


def _has_docx_link(value: str) -> bool:
    return "feishu.cn/docx/" in value or "larksuite.com/docx/" in value
