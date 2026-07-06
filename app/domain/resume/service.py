"""简历库领域服务。

服务层负责列表筛选、排序、分页、详情、编辑和重新评分编排。读数据来自
`ResumeRepository` 的旧库只读通道；编辑和评分回写只进入 repository 内存桩。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any

from app.core.text import clean_text
from app.domain.resume.job_types import (
    canonical_resume_job_type,
    display_resume_job_type,
    job_type_matches_scope,
)
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
    job_facets: list[dict[str, object]]


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
        self._resume_cache_signature_value: tuple[object, ...] | None = None
        self._resume_cache_items: list[Resume] | None = None

    def list_resumes(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        query: str = "",
        job_type: str = "",
        source_platform: str = "",
        owner: str = "",
        education: str = "",
        school_level: str | Iterable[str] = "",
        graduation_year: str | Iterable[str] = "",
        score_min: int | None = None,
        score_max: int | None = None,
        read_status: str = "",
        decision: str | Iterable[str] = "",
        manual_review: bool = False,
        date_from: str = "",
        date_to: str = "",
        review_states: dict[str, Any] | None = None,
        allowed_job_types: str | Iterable[str] | None = None,
        sort: str = "updated_at",
        descending: bool = True,
    ) -> ResumeListResult:
        """筛选、排序并分页返回简历。"""

        page = max(1, page)
        page_size = min(200, max(1, page_size))
        all_resumes = self._all_resumes_cached()
        facet_resumes = _filter_resumes(
            all_resumes,
            query=query,
            job_type="",
            source_platform=source_platform,
            owner=owner,
            education=education,
            school_level=school_level,
            graduation_year=graduation_year,
            score_min=score_min,
            score_max=score_max,
            read_status=read_status,
            decision=decision,
            manual_review=manual_review,
            date_from=date_from,
            date_to=date_to,
            review_states=review_states or {},
            allowed_job_types=allowed_job_types,
        )
        resumes = _filter_resumes(
            all_resumes,
            query=query,
            job_type=job_type,
            source_platform=source_platform,
            owner=owner,
            education=education,
            school_level=school_level,
            graduation_year=graduation_year,
            score_min=score_min,
            score_max=score_max,
            read_status=read_status,
            decision=decision,
            manual_review=manual_review,
            date_from=date_from,
            date_to=date_to,
            review_states=review_states or {},
            allowed_job_types=allowed_job_types,
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
            job_facets=_job_facets(facet_resumes, allowed_job_types),
        )

    def get_resume(self, resume_id: str) -> Resume | None:
        """读取单条简历。"""

        record = self.repository.get(resume_id)
        return Resume.from_record(record) if record else None

    def update_resume(self, resume_id: str, fields: dict[str, Any]) -> Resume | None:
        """编辑简历字段；写入内存桩。"""

        record = self.repository.update(resume_id, fields)
        if record:
            self._clear_resume_cache()
        return Resume.from_record(record) if record else None

    def rescore_resume(self, resume_id: str) -> dict[str, Any] | None:
        """重新评分并把分数写回内存桩。"""

        resume = self.get_resume(resume_id)
        if resume is None:
            return None
        result = self.scoring_service.score_resume(resume)
        self.repository.update_score(resume_id, int(result["score"]))
        self._clear_resume_cache()
        return result

    def _all_resumes_cached(self) -> list[Resume]:
        signature = self._resume_cache_signature()
        if (
            self._resume_cache_items is not None
            and self._resume_cache_signature_value == signature
        ):
            return self._resume_cache_items
        items = [Resume.from_record(record) for record in self.repository.iter_resumes()]
        self._resume_cache_signature_value = signature
        self._resume_cache_items = items
        return items

    def _resume_cache_signature(self) -> tuple[object, ...]:
        if getattr(self.repository, "_is_memory", False):
            records = list(getattr(self.repository, "_memory_records", {}).values())
            latest_updated_at = max((record.updated_at or "" for record in records), default="")
            return ("memory", len(records), latest_updated_at)
        database_path = self.repository.database_path
        try:
            stat = database_path.stat()
            return (
                "sqlite",
                str(database_path),
                stat.st_mtime_ns,
                stat.st_size,
                self.repository.count(),
            )
        except OSError:
            return ("sqlite-missing", str(database_path), self.repository.count())

    def _clear_resume_cache(self) -> None:
        self._resume_cache_signature_value = None
        self._resume_cache_items = None


def build_resume_service(repository: ResumeRepository | None = None) -> ResumeService:
    """装配简历服务。"""

    return ResumeService(repository or ResumeRepository.from_settings())


def _filter_resumes(
    resumes: list[Resume],
    *,
    query: str,
    job_type: str,
    source_platform: str,
    owner: str,
    education: str,
    school_level: str | Iterable[str],
    graduation_year: str | Iterable[str],
    score_min: int | None,
    score_max: int | None,
    read_status: str,
    decision: str | Iterable[str],
    manual_review: bool,
    date_from: str,
    date_to: str,
    review_states: dict[str, Any],
    allowed_job_types: str | Iterable[str] | None,
) -> list[Resume]:
    needle = clean_text(query).lower()
    job = clean_text(job_type)
    platform = clean_text(source_platform)
    owner_value = clean_text(owner)
    education_value = clean_text(education)
    school_levels = _filter_values(school_level)
    graduation_years = _filter_values(graduation_year)
    decisions = _normalize_decisions(decision)
    allowed_jobs = None if allowed_job_types is None else _filter_values(allowed_job_types)
    start_date = _date_key(date_from)
    end_date = _date_key(date_to)
    result: list[Resume] = []
    for resume in resumes:
        if allowed_jobs is not None and "*" not in allowed_jobs and not _matches_job_scope(
            resume,
            allowed_jobs,
        ):
            continue
        resume_job = resume.job_type or resume.applied_position or ""
        if job and not job_type_matches_scope(resume_job, job):
            continue
        if platform and platform not in _platform_values(resume):
            continue
        if owner_value and owner_value not in {resume.source_owner, resume.linked_owner}:
            continue
        if education_value and education_value not in clean_text(resume.education):
            continue
        if school_levels and not _matches_filter_value(_school_level(resume), school_levels):
            continue
        if graduation_years and _graduation_cohort(resume) not in graduation_years:
            continue
        if score_min is not None and (resume.match_score is None or resume.match_score < score_min):
            continue
        if score_max is not None and (resume.match_score is None or resume.match_score > score_max):
            continue
        state = review_states.get(resume.id)
        state_read = getattr(state, "read_status", "unread")
        state_decision = getattr(state, "decision", "undecided")
        if read_status and state_read != read_status:
            continue
        if decisions and _normalize_decision(state_decision) not in decisions:
            continue
        if manual_review and not _needs_manual_review(resume):
            continue
        updated_date = _date_key(_date_source(resume))
        if start_date and updated_date and updated_date < start_date:
            continue
        if end_date and updated_date and updated_date > end_date:
            continue
        if needle:
            haystack = " ".join(
                clean_text(value)
                for value in [
                    resume.name,
                    resume.gender,
                    resume.phone,
                    resume.education,
                    resume.major,
                    _school(resume),
                    _school_level(resume),
                    resume.applied_position,
                    resume.job_type,
                    resume.parsed_name,
                    resume.linked_platform_conversation_id,
                    resume.payload.get("rawText"),
                    resume.payload.get("text"),
                ]
            ).lower()
            if needle not in haystack:
                continue
        result.append(resume)
    return result


def _sort_resumes(resumes: list[Resume], *, sort: str, descending: bool) -> list[Resume]:
    key, reverse = _sort_mode(sort, descending)

    def sort_value(resume: Resume) -> Any:
        value = _date_source(resume) if key == "updated_at" else getattr(resume, key, None)
        if key == "match_score":
            return value if value is not None else -1
        return clean_text(value)

    return sorted(resumes, key=sort_value, reverse=reverse)


def _filter_values(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    raw_values = [value] if isinstance(value, str) else list(value)
    return [clean_text(item) for item in raw_values if clean_text(item)]


def _normalize_decisions(value: str | Iterable[str] | None) -> set[str]:
    return {_normalize_decision(item) for item in _filter_values(value)}


def _normalize_decision(value: object) -> str:
    text = clean_text(value)
    return "undecided" if text == "pending" else text


def _matches_filter_value(value: str, selected: Iterable[str]) -> bool:
    normalized = clean_text(value)
    return any(item == normalized or item in normalized for item in selected)


def _matches_job_scope(resume: Resume, allowed_jobs: Iterable[str]) -> bool:
    job = clean_text(resume.job_type or resume.applied_position)
    return bool(job) and any(job_type_matches_scope(job, item) for item in allowed_jobs)


def _job_facets(
    resumes: list[Resume],
    allowed_job_types: str | Iterable[str] | None,
) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for resume in resumes:
        job = display_resume_job_type(resume.job_type or resume.applied_position)
        if job:
            counts[job] = counts.get(job, 0) + 1
    allowed = None if allowed_job_types is None else _canonical_job_values(allowed_job_types)
    if allowed and "*" not in allowed:
        return [
            {
                "jobType": job,
                "count": sum(
                    count
                    for actual, count in counts.items()
                    if job_type_matches_scope(actual, job)
                ),
            }
            for job in allowed
        ]
    return [
        {"jobType": job, "count": count}
        for job, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _canonical_job_values(value: str | Iterable[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _filter_values(value):
        canonical = "*" if item == "*" else canonical_resume_job_type(item)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def _payload_value(resume: Resume, *keys: str) -> str:
    for key in keys:
        value = resume.payload.get(key)
        if value not in (None, ""):
            return clean_text(value)
    return ""


def _school(resume: Resume) -> str:
    return _payload_value(resume, "school", "college", "university")


def _school_level(resume: Resume) -> str:
    return _payload_value(resume, "schoolLevel", "school_level", "schoolTier", "school_tier")


def _graduation_cohort(resume: Resume) -> str:
    text = " ".join(
        clean_text(value)
        for value in [
            _payload_value(resume, "graduation", "graduationYear", "graduation_year"),
            resume.payload.get("fileName"),
            resume.payload.get("rawText"),
            resume.payload.get("text"),
        ]
    )
    full_year = re.search(r"20(26|27|28)\s*(?:届|年|毕业|应届)?", text)
    if full_year:
        return full_year.group(1)
    short_year = re.search(r"(?<!\d)(26|27|28)\s*(?:届|年|毕业|应届)", text)
    return short_year.group(1) if short_year else ""


def _needs_manual_review(resume: Resume) -> bool:
    quality = resume.payload.get("parseQuality") or resume.payload.get("parse_quality") or {}
    if isinstance(quality, dict):
        return bool(quality.get("needsManualReview") or quality.get("needs_manual_review"))
    return bool(
        resume.payload.get("needsManualReview") or resume.payload.get("needs_manual_review")
    )


def _date_source(resume: Resume) -> str:
    return clean_text(
        resume.updated_at
        or resume.payload.get("createdAt")
        or resume.payload.get("created_at")
        or resume.payload.get("savedAt")
        or resume.payload.get("receivedAt")
    )


def _date_key(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    normalized = text.replace("/", "-")
    if re.match(r"^\d{4}-\d{2}-\d{2}", normalized):
        return normalized[:10]
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return ""


def _platform_values(resume: Resume) -> set[str]:
    values = {clean_text(resume.source_platform), clean_text(resume.linked_platform)}
    if "51job" in values:
        values.add("job51")
    if "job51" in values:
        values.add("51job")
    return values


def _sort_mode(sort: str, descending: bool) -> tuple[str, bool]:
    if sort in {"score", "jd-score"}:
        return "match_score", True
    if sort == "created-desc":
        return "updated_at", True
    if sort == "created-asc":
        return "updated_at", False
    allowed = {"updated_at", "match_score", "name", "job_type", "education"}
    return (sort if sort in allowed else "updated_at", descending)
