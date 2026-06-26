"""简历库领域服务。

服务层负责列表筛选、排序、分页、详情、编辑和重新评分编排。读数据来自
`ResumeRepository` 的旧库只读通道；编辑和评分回写只进入 repository 内存桩。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from app.core.text import clean_text
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.scoring.service import ScoringService, build_scoring_service


@dataclass(frozen=True)
class ResumeListResult:
    """分页列表结果。"""

    items: list[Resume]
    total: int
    page: int
    page_size: int
    pages: int


class ResumeService:
    """简历列表与详情用例编排。"""

    def __init__(
        self,
        repository: ResumeRepository,
        *,
        scoring_service: ScoringService | None = None,
    ) -> None:
        self.repository = repository
        self.scoring_service = scoring_service or build_scoring_service(repository)

    def list_resumes(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        query: str = "",
        job_type: str = "",
        source_platform: str = "",
        sort: str = "updated_at",
        descending: bool = True,
    ) -> ResumeListResult:
        """筛选、排序并分页返回简历。"""

        page = max(1, page)
        page_size = min(200, max(1, page_size))
        resumes = [Resume.from_record(record) for record in self.repository.iter_resumes()]
        resumes = _filter_resumes(
            resumes,
            query=query,
            job_type=job_type,
            source_platform=source_platform,
        )
        resumes = _sort_resumes(resumes, sort=sort, descending=descending)
        total = len(resumes)
        start = (page - 1) * page_size
        end = start + page_size
        return ResumeListResult(
            items=resumes[start:end],
            total=total,
            page=page,
            page_size=page_size,
            pages=ceil(total / page_size) if total else 0,
        )

    def get_resume(self, resume_id: str) -> Resume | None:
        """读取单条简历。"""

        record = self.repository.get(resume_id)
        return Resume.from_record(record) if record else None

    def update_resume(self, resume_id: str, fields: dict[str, Any]) -> Resume | None:
        """编辑简历字段；写入内存桩。"""

        record = self.repository.update(resume_id, fields)
        return Resume.from_record(record) if record else None

    def rescore_resume(self, resume_id: str) -> dict[str, Any] | None:
        """重新评分并把分数写回内存桩。"""

        resume = self.get_resume(resume_id)
        if resume is None:
            return None
        result = self.scoring_service.score_resume(resume)
        self.repository.update_score(resume_id, int(result["score"]))
        return result


def build_resume_service(repository: ResumeRepository | None = None) -> ResumeService:
    """装配简历服务。"""

    return ResumeService(repository or ResumeRepository.from_settings())


def _filter_resumes(
    resumes: list[Resume],
    *,
    query: str,
    job_type: str,
    source_platform: str,
) -> list[Resume]:
    needle = clean_text(query).lower()
    job = clean_text(job_type)
    platform = clean_text(source_platform)
    result: list[Resume] = []
    for resume in resumes:
        if job and job not in (resume.job_type or resume.applied_position or ""):
            continue
        if platform and platform != resume.source_platform:
            continue
        if needle:
            haystack = " ".join(
                clean_text(value)
                for value in [
                    resume.name,
                    resume.phone,
                    resume.education,
                    resume.major,
                    resume.applied_position,
                    resume.job_type,
                    resume.payload.get("rawText"),
                    resume.payload.get("text"),
                ]
            ).lower()
            if needle not in haystack:
                continue
        result.append(resume)
    return result


def _sort_resumes(resumes: list[Resume], *, sort: str, descending: bool) -> list[Resume]:
    allowed = {"updated_at", "match_score", "name", "job_type", "education"}
    key = sort if sort in allowed else "updated_at"

    def sort_value(resume: Resume) -> Any:
        value = getattr(resume, key, None)
        if key == "match_score":
            return value if value is not None else -1
        return clean_text(value)

    return sorted(resumes, key=sort_value, reverse=descending)
