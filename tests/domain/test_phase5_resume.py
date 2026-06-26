"""Phase 5：简历归一化、去重和列表服务测试。"""

from __future__ import annotations

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


def _record(
    record_id: str,
    *,
    name: str = "候选人",
    phone: str = "13800138000",
    job: str = "销售管培生",
    score: int = 60,
    updated_at: str = "2026-01-01",
) -> ResumeRecord:
    return ResumeRecord(
        id=record_id,
        payload={
            "name": name,
            "phone": phone,
            "education": "本科",
            "applied_position": job,
            "rawText": f"{name} {phone} 本科 {job}",
        },
        phone_key=phone,
        job_type=job,
        match_score=score,
        updated_at=updated_at,
    )
