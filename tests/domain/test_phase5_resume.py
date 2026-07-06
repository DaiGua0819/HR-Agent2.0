"""Phase 5：简历归一化、去重和列表服务测试。"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.routes.resumes import _resume_payload
from app.domain.resume.dedup import deduplicate_by_phone, find_duplicate_resumes
from app.domain.resume.models import Resume, ResumeRecord
from app.domain.resume.normalize import (
    normalize_education,
    normalize_gender,
    normalize_phone,
    normalize_resume_payload,
)
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService


def test_resume_normalizers_cover_common_fields() -> None:
    """学历、性别、手机号和 payload 标准字段会被规整。"""

    assert normalize_phone("电话：138-0013-8000") == "13800138000"
    assert normalize_gender("女性") == "女"
    assert normalize_education("统招本科") == "本科"
    payload = normalize_resume_payload(
        {
            "candidateName": "  李四 ",
            "mobile": "13800138001",
            "degree": "硕士研究生",
            "sex": "男",
            "position": " 电气工程师 ",
        }
    )
    assert payload["name"] == "李四"
    assert payload["phone_key"] == "13800138001"
    assert payload["education"] == "硕士"
    assert payload["applied_position"] == "电气工程师"


def test_deduplicate_by_phone_keeps_first_resume() -> None:
    """同手机号只保留第一条，无手机号记录不合并。"""

    resumes = [
        Resume(id="a", phone="13800138000", payload={}),
        Resume(id="b", phone="13800138000", payload={}),
        Resume(id="c", phone=None, payload={}),
    ]
    assert [resume.id for resume in deduplicate_by_phone(resumes)] == ["a", "c"]
    records = [
        _record("a", phone="13800138000"),
        _record("b", phone="13800138000"),
        _record("c", phone="13900139000"),
    ]
    assert find_duplicate_resumes(records) == [("a", "b")]


def test_resume_service_filters_sorts_and_paginates_in_memory_records() -> None:
    """列表服务可在无真实 DB 的内存 repository 上完成筛选排序分页。"""

    repository = ResumeRepository.in_memory(
        [
            _record("1", name="王五", job="销售管培生", score=80, updated_at="2026-01-02"),
            _record("2", name="赵六", job="电气工程师", score=90, updated_at="2026-01-03"),
            _record("3", name="钱七", job="电气工程师", score=40, updated_at="2026-01-01"),
        ]
    )
    service = ResumeService(repository)
    page = service.list_resumes(job_type="电气", sort="match_score", page=1, page_size=1)
    assert page.total == 2
    assert page.items[0].name == "赵六"
    assert page.pages == 2

    detail = service.get_resume("1")
    assert detail is not None
    assert detail.applied_position == "销售管培生"
    assert repository.count() == 3


def test_resume_service_reuses_cached_resume_models_until_records_change() -> None:
    """Repeated list filters should not rebuild every resume when records are unchanged."""

    class SpyRepository(ResumeRepository):
        def __init__(self, records: list[ResumeRecord]) -> None:
            super().__init__(":memory:", read_only=True, memory_records=records)
            self.iter_calls = 0

        def iter_resumes(self, *, limit: int | None = None):
            self.iter_calls += 1
            yield from super().iter_resumes(limit=limit)

    repository = SpyRepository(
        [
            _record("1", name="王五", job="销售管培生", score=80, updated_at="2026-01-02"),
            _record("2", name="赵六", job="电气工程师", score=90, updated_at="2026-01-03"),
        ]
    )
    service = ResumeService(repository)

    first = service.list_resumes(job_type="销售", sort="match_score")
    second = service.list_resumes(job_type="电气", sort="match_score")

    assert [resume.id for resume in first.items] == ["1"]
    assert [resume.id for resume in second.items] == ["2"]
    assert repository.iter_calls == 1

    repository._memory_records["3"] = _record(
        "3",
        name="钱七",
        job="电气工程师",
        score=95,
        updated_at="2026-01-04",
    )
    changed = service.list_resumes(job_type="电气", sort="match_score")

    assert [resume.id for resume in changed.items] == ["3", "2"]
    assert repository.iter_calls == 2


def test_resume_service_replicates_legacy_library_filters() -> None:
    """旧站简历库的学校层次、届别、复核、结论和分数筛选应在后端生效。"""

    repository = ResumeRepository.in_memory(
        [
            _record(
                "1",
                name="王五",
                job="销售管培生",
                score=86,
                updated_at="2026-06-26",
                school_level="985 / 211 / 双一流",
                graduation="2027届毕业",
                manual_review=True,
            ),
            _record(
                "2",
                name="赵六",
                job="电气工程师",
                score=72,
                updated_at="2026-06-24",
                school_level="二本",
                graduation="2026届",
            ),
            _record(
                "3",
                name="钱七",
                job="应用技术",
                score=92,
                updated_at="2026-06-25",
                school_level="海外院校",
                graduation="2028年应届",
                manual_review=True,
            ),
        ]
    )
    review_states = {
        "1": SimpleNamespace(read_status="unread", decision="suitable"),
        "2": SimpleNamespace(read_status="viewed", decision="unsuitable"),
        "3": SimpleNamespace(read_status="unread", decision="needs_more_info"),
    }
    service = ResumeService(repository)

    page = service.list_resumes(
        school_level=["985 / 211 / 双一流", "海外院校"],
        graduation_year=["27", "28"],
        decision=["suitable", "needs_more_info"],
        score_min=80,
        score_max=95,
        manual_review=True,
        review_states=review_states,
        sort="created-asc",
    )

    assert [resume.id for resume in page.items] == ["3", "1"]


def test_resume_api_payload_exposes_school_tier_and_education_display() -> None:
    """简历 API 应给前端一个可直接展示的学历、学校和层次组合。"""

    resume = Resume.from_record(
        ResumeRecord(
            id="school",
            payload={
                "name": "罗靖",
                "education": "本科",
                "school": "重庆科技大学",
                "schoolLevel": "一本",
                "applied_position": "运营A",
                "rawText": "罗靖 本科 重庆科技大学 一本",
            },
            phone_key=None,
            job_type="运营A",
            match_score=80,
            updated_at="2026-06-30",
        )
    )

    payload = _resume_payload(resume)

    assert payload["school"] == "重庆科技大学"
    assert payload["schoolLevel"] == "一本"
    assert payload["educationDisplay"] == "本科 · 重庆科技大学（一本）"


def _record(
    record_id: str,
    *,
    name: str = "候选人",
    phone: str = "13800138000",
    job: str = "销售管培生",
    score: int = 60,
    updated_at: str = "2026-01-01",
    school_level: str = "",
    graduation: str = "",
    manual_review: bool = False,
) -> ResumeRecord:
    parse_quality = {"needsManualReview": manual_review}
    return ResumeRecord(
        id=record_id,
        payload={
            "name": name,
            "phone": phone,
            "education": "本科",
            "schoolLevel": school_level,
            "graduation": graduation,
            "parseQuality": parse_quality,
            "applied_position": job,
            "rawText": f"{name} {phone} 本科 {job}",
        },
        phone_key=phone,
        job_type=job,
        match_score=score,
        updated_at=updated_at,
    )
