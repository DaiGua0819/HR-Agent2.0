"""Phase 7a：SQLite 持久化与 dry-run 安全网测试。"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from app.browser.fake_page import FakePage
from app.db.engine import run_migrations
from app.domain.batch.repository import BatchRepository
from app.domain.batch.service import BatchService
from app.domain.resume.models import Resume, ResumeRecord
from app.domain.resume.repository import ResumeRepository
from app.domain.scoring.suggestions import RuleSuggestionStore
from app.evaluation.batch_reports import save_batch_report
from app.evaluation.decision_log import SQLiteDecisionSink
from app.evaluation.question_log import record_candidate_question
from app.features.interview_center.store import SQLiteInterviewStore
from app.platforms.boss.adapter import BossAdapter

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "scoring_regression.py"
_SPEC = importlib.util.spec_from_file_location("scoring_regression", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_SCORING_REGRESSION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCORING_REGRESSION)
run_regression = _SCORING_REGRESSION.run_regression


def test_migrations_are_idempotent_on_empty_sqlite(tmp_path: Path) -> None:
    """迁移可在空库重复执行，不破坏已有表。"""

    database = tmp_path / "phase7a.sqlite"
    run_migrations(database)
    run_migrations(database)
    repository = ResumeRepository(database)
    assert repository.count() == 0


def test_resume_repository_writes_and_updates_sqlite(tmp_path: Path) -> None:
    """简历 save/update_score 写入真实 SQLite。"""

    repository = ResumeRepository(tmp_path / "resumes.sqlite")
    repository.save(
        Resume(
            id="resume-1",
            name="Alice",
            phone="13800138000",
            job_type="电气工程师",
            match_score=80,
            payload={"rawText": "Alice 本科 电气 PLC"},
        )
    )
    assert repository.count() == 1
    assert repository.get("resume-1").phone_key == "13800138000"

    repository.update_score("resume-1", 95)
    assert repository.get("resume-1").match_score == 95


def test_resume_repository_auto_scores_operation_resume_on_save(tmp_path: Path) -> None:
    """运营A/B新简历入库时若没有分数，应立即按JD规则写入match_score。"""

    repository = ResumeRepository(tmp_path / "operation_scores.sqlite")
    repository.save(
        Resume(
            id="operation-a-1",
            name="Alice",
            job_type="运营A",
            payload={
                "name": "Alice",
                "education": "本科",
                "rawText": (
                    "3年短视频内容运营 企业号 品牌号 账号定位 月度选题 "
                    "脚本撰写 拍摄剪辑 数据复盘 私信量 有效咨询量 SaaS AI 企业服务"
                ),
            },
        )
    )

    stored = repository.get("operation-a-1")
    assert stored is not None
    assert stored.match_score is not None
    assert stored.match_score >= 75


def test_resume_repository_auto_scores_negative_placeholder_operation_score(
    tmp_path: Path,
) -> None:
    """运营A/B入库时的 -1 占位分也应视为未评分并自动替换。"""

    repository = ResumeRepository(tmp_path / "operation_negative_scores.sqlite")
    repository.save(
        Resume(
            id="operation-b-1",
            name="Bob",
            job_type="运营B",
            match_score=-1,
            payload={
                "name": "Bob",
                "education": "大专",
                "rawText": (
                    "新媒体运营 B2B平台运营 工业品推广 膨润土 钻井泥浆 "
                    "LinkedIn 英文文案 数据复盘 询盘 有效线索"
                ),
            },
        )
    )

    stored = repository.get("operation-b-1")
    assert stored is not None
    assert stored.match_score is not None
    assert stored.match_score >= 75


def test_resume_repository_auto_scores_ai_product_manager_resume_on_save(
    tmp_path: Path,
) -> None:
    """AI 产品经理新简历入库时也应立即按 JD 规则写入 match_score。"""

    repository = ResumeRepository(tmp_path / "ai_product_manager_scores.sqlite")
    repository.save(
        Resume(
            id="ai-pm-1",
            name="Carol",
            job_type="AI产品经理",
            match_score=-1,
            payload={
                "name": "Carol",
                "rawText": (
                    "4年产品经理 B2B销售 CRM 客户管理 商机管理 获客 线索 跟进 报价 "
                    "签约 成交 交付 回款 续约 企业级产品 企业服务 SaaS 多角色 权限管理 "
                    "审批流 工作流 数据安全 客户现场 用户访谈 产品路线图 MVP PRD "
                    "验收标准 跨团队交付 AI能力边界 人机协作 人工确认 纠错机制 "
                    "客户落地 使用反馈 迭代闭环 0到1 独立负责"
                ),
            },
        )
    )

    stored = repository.get("ai-pm-1")
    assert stored is not None
    assert stored.match_score is not None
    assert stored.match_score >= 75


def test_batch_suggestions_evaluation_and_interview_persist(tmp_path: Path) -> None:
    """批量、规则建议、评估日志和面试会话都写入临时 SQLite。"""

    database = tmp_path / "domain.sqlite"
    batch_service = BatchService(BatchRepository(database))
    job = batch_service.create_job(
        "auto",
        [{"fileName": "a.txt", "content": "Alice\n13800138000 本科 电气工程师"}],
    )
    assert batch_service.get_job(job.id).items[0].status == "done"

    suggestions = RuleSuggestionStore(database)
    suggestion = suggestions.create("resume-1", "PLC 权重应更高", job_type="电气工程师")
    assert suggestions.set_status(suggestion.id, "accepted").status == "accepted"

    sink = SQLiteDecisionSink(database)
    sink.record({"event": "dry_run_intent", "platform": "boss", "dryRun": True})
    assert sink.list_recent(limit=1)[0]["platform"] == "boss"

    save_batch_report({"type": "daily", "ok": True}, database)
    record_candidate_question("候选人问薪资", database_path=database)

    store = SQLiteInterviewStore(database)
    session = store.create(resume_id="resume-1", candidate_name="Alice", job_type="电气工程师")
    session.feedback = "通过"
    store.save(session)
    assert store.get(session.id).feedback == "通过"


def test_dry_run_records_intent_without_fake_page_side_effect(monkeypatch) -> None:
    """dry-run=True 时，发送消息只记录意图，不触发 FakePage 发送。"""

    events: list[dict[str, object]] = []
    monkeypatch.setattr("app.core.dry_run.record_decision", lambda event: events.append(event))
    page = FakePage()
    adapter = BossAdapter(page, owner="和新红", dry_run=True)

    result = asyncio.run(adapter.send_message("你好"))

    assert result.message == "dry_run"
    assert page.sent_messages == []
    assert events[0]["action"] == "boss.send_message"


def test_scoring_regression_reads_sqlite_copy(tmp_path: Path) -> None:
    """回归脚本可对 SQLite 副本跑出全量分数。"""

    repository = ResumeRepository(tmp_path / "scores.sqlite")
    repository.save(
        Resume.from_record(
            ResumeRecord(
                id="resume-1",
                payload={"name": "Alice", "rawText": "本科 电气 自动化 PLC"},
                phone_key="13800138000",
                job_type="电气工程师",
                match_score=None,
                updated_at="2026-01-01",
            )
        )
    )
    rows = run_regression(tmp_path / "scores.sqlite")
    assert rows[0]["resumeId"] == "resume-1"
    assert rows[0]["score"] >= 55
