"""批量简历解析服务。

Phase 5 只做可测的轻量字段解析和内存任务状态流转；文件上传、OCR 和真实入库留到后续。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.text import clean_text
from app.domain.batch.models import BatchItem, BatchJob
from app.domain.batch.repository import GLOBAL_BATCH_REPOSITORY, BatchRepository
from app.domain.resume.normalize import (
    normalize_education,
    normalize_gender,
    normalize_phone,
    normalize_position,
)


class BatchService:
    """批量解析任务用例。"""

    def __init__(self, repository: BatchRepository | None = None) -> None:
        self.repository = repository or GLOBAL_BATCH_REPOSITORY

    def create_job(self, parse_mode: str, files: list[dict[str, Any]]) -> BatchJob:
        """创建任务并立即执行轻量解析。"""

        job = BatchJob(id=str(uuid4()), parse_mode=parse_mode or "auto")
        for file_data in files:
            item = BatchItem(
                id=str(uuid4()),
                job_id=job.id,
                file_name=clean_text(file_data.get("fileName") or file_data.get("name")),
            )
            try:
                content = clean_text(file_data.get("content") or file_data.get("text"))
                item.payload = parse_resume_text(content, file_name=item.file_name)
                item.status = "done"
            except ValueError as exc:
                item.status = "failed"
                item.error = str(exc)
            job.items.append(item)
        job.status = "done" if all(item.status == "done" for item in job.items) else "failed"
        return self.repository.save(job)

    def get_job(self, job_id: str) -> BatchJob | None:
        """读取任务。"""

        return self.repository.get(job_id)

    def list_jobs(self) -> list[BatchJob]:
        """列出任务。"""

        return self.repository.list()

    def set_status(self, job_id: str, status: str) -> BatchJob | None:
        """暂停、继续、取消、重试等状态流转。"""

        job = self.repository.get(job_id)
        if job is None:
            return None
        job.status = status
        return self.repository.save(job)


def parse_resume_text(text: str, *, file_name: str = "") -> dict[str, Any]:
    """从文本简历中提取基础字段。"""

    compact = clean_text(text)
    if not compact:
        raise ValueError("empty_resume_text")
    first_line = clean_text(text.splitlines()[0] if text.splitlines() else "")
    phone = normalize_phone(compact)
    return {
        "name": _guess_name(first_line, file_name),
        "phone": phone,
        "phone_key": phone,
        "gender": normalize_gender(compact),
        "education": normalize_education(compact),
        "applied_position": _guess_position(compact),
        "rawText": compact,
    }


def enqueue_batch_parse(parse_mode: str, file_paths: list[str]) -> str:
    """兼容旧 stub：用路径名创建空内容任务。"""

    service = BatchService()
    files = [{"fileName": path, "content": path} for path in file_paths]
    return service.create_job(parse_mode, files).id


def _guess_name(first_line: str, file_name: str) -> str:
    source = first_line or file_name
    for token in ("简历", "个人", "resume", "CV", "_", "-", "."):
        source = source.replace(token, " ")
    return clean_text(source).split(" ")[0] if clean_text(source) else ""


def _guess_position(text: str) -> str | None:
    for keyword in ("销售管培生", "电气工程师", "HRBP", "AI应用开发实习生", "人力资源"):
        if keyword in text:
            return normalize_position(keyword)
    return None
