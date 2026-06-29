"""简历审阅工作台领域测试。"""

from __future__ import annotations

from pathlib import Path

from app.db.engine import connect, run_migrations
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume_review.repository import ResumeReviewRepository
from app.domain.resume_review.service import ResumeReviewService


def test_review_migration_creates_tables(tmp_path: Path) -> None:
    """迁移会幂等创建审阅状态和分配队列表。"""

    database = tmp_path / "review.sqlite"
    run_migrations(database)
    run_migrations(database)

    with connect(database) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "resume_review_states",
        "resume_review_events",
        "resume_assignments",
        "resume_saved_views",
    } <= tables


def test_opening_resume_marks_current_user_viewed(tmp_path: Path) -> None:
    """打开工作台上下文会把当前用户标记为已看。"""

    resume_repo, service = _service(tmp_path)
    resume = _save_resume(resume_repo)

    context = service.context_for_resume(resume=resume, user_id="viewer-1")

    assert context["reviewState"]["readStatus"] == "viewed"
    assert service.state_for_resume("resume-1", "viewer-1").read_status == "viewed"


def test_suitable_decision_creates_assignment(tmp_path: Path) -> None:
    """点合适会写审核状态并进入管理员待处理队列。"""

    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)

    result = service.set_decision(
        resume_id="resume-1",
        user_id="viewer-1",
        decision="suitable",
        reason_tags=["岗位匹配"],
        note="建议复核",
        assign_to="local-admin",
    )
    queue = service.queue_for_user("local-admin")

    assert result["state"]["decision"] == "suitable"
    assert result["assignment"]["assignedToUserId"] == "local-admin"
    assert len(queue) == 1
    assert queue[0]["resume"]["id"] == "resume-1"


def test_unsuitable_decision_does_not_create_assignment(tmp_path: Path) -> None:
    """点不合适只写状态，不进入待处理队列。"""

    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)

    result = service.set_decision(
        resume_id="resume-1",
        user_id="viewer-1",
        decision="unsuitable",
        reason_tags=["经验不符"],
        note="暂不匹配",
    )

    assert result["state"]["decision"] == "unsuitable"
    assert result["assignment"] is None
    assert service.queue_for_user("local-admin") == []


def _service(tmp_path: Path) -> tuple[ResumeRepository, ResumeReviewService]:
    database = tmp_path / "review.sqlite"
    resume_repo = ResumeRepository(database)
    review_repo = ResumeReviewRepository(database)
    service = ResumeReviewService(
        review_repo,
        resume_repository=resume_repo,
        default_assignee="local-admin",
    )
    return resume_repo, service


def _save_resume(repository: ResumeRepository) -> Resume:
    resume = Resume(
        id="resume-1",
        name="张三",
        phone="13800138000",
        education="本科",
        major="化工",
        job_type="销售管培生",
        match_score=88,
        linked_owner="宋峰峰",
        linked_platform="boss",
        payload={"rawText": "张三 本科 化工 销售经历"},
    )
    repository.save(resume)
    return Resume.from_record(repository.get("resume-1"))
