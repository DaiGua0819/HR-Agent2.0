"""B2B AI 产品经理重评分与推荐报告测试。"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "rescore_b2b_ai_product_manager.py"
_SPEC = importlib.util.spec_from_file_location("rescore_b2b_ai_product_manager", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

apply_latest_scores = _MODULE.apply_latest_scores
build_b2b_ai_pm_report = _MODULE.build_b2b_ai_pm_report


FULL_B2B_AI_PM = (
    "B2B销售 CRM 客户管理 商机管理 获客 线索 跟进 报价 签约 成交 交付 回款 续约 "
    "企业级产品 企业服务 SaaS 多角色 权限管理 审批流 工作流 数据安全 "
    "客户现场 用户访谈 产品路线图 MVP PRD 验收标准 跨团队交付 "
    "AI能力边界 人机协作 人工确认 纠错机制 客户落地 使用反馈 迭代闭环 "
    "0到1 独立负责 企业微信 私有化部署 制造业 数据指标 创业团队"
)


def _save(
    repository: ResumeRepository,
    *,
    resume_id: str,
    name: str,
    job_type: str,
    score: int,
    updated_at: str,
    phone: str,
    raw_text: str,
    file_hash: str = "",
    candidate_name_from_platform: str = "",
) -> None:
    repository.save(
        Resume(
            id=resume_id,
            name=name,
            phone=phone,
            job_type=job_type,
            match_score=score,
            updated_at=updated_at,
            linked_platform="job51",
            linked_owner="和新红",
            payload={
                "name": name,
                "phone": phone,
                "rawText": raw_text,
                "fileHash": file_hash,
                "candidateNameFromPlatform": candidate_name_from_platform,
                "sourcePlatform": "job51",
                "owner": "和新红",
            },
        )
    )


def test_report_scores_only_ai_product_manager_and_deduplicates(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    repository = ResumeRepository(database)
    _save(
        repository,
        resume_id="latest-1",
        name="甲",
        job_type="AI 产品经理",
        score=10,
        updated_at="2026-07-16T03:00:00+00:00",
        phone="13800138000",
        raw_text=FULL_B2B_AI_PM,
        file_hash="hash-a",
    )
    _save(
        repository,
        resume_id="latest-2",
        name="乙",
        job_type="AI产品经理",
        score=20,
        updated_at="2026-07-16T02:00:00+00:00",
        phone="13800138001",
        raw_text=FULL_B2B_AI_PM,
        file_hash="hash-b",
    )
    _save(
        repository,
        resume_id="duplicate-phone",
        name="甲",
        job_type="AI产品经理",
        score=30,
        updated_at="2026-07-15T01:00:00+00:00",
        phone="13800138000",
        raw_text=FULL_B2B_AI_PM,
        file_hash="hash-c",
    )
    _save(
        repository,
        resume_id="duplicate-hash",
        name="乙副本",
        job_type="AI产品经理",
        score=40,
        updated_at="2026-07-14T01:00:00+00:00",
        phone="13800138002",
        raw_text=FULL_B2B_AI_PM,
        file_hash="hash-b",
    )
    _save(
        repository,
        resume_id="other-job",
        name="电气候选人",
        job_type="电气工程师",
        score=90,
        updated_at="2026-07-16T04:00:00+00:00",
        phone="13800138003",
        raw_text="本科 电气 PLC",
    )

    report = build_b2b_ai_pm_report(database, latest_count=2)

    assert report["sourceCount"] == 4
    assert [item["resumeId"] for item in report["latestCandidates"]] == [
        "latest-1",
        "latest-2",
    ]
    assert {item["resumeId"] for item in report["recommendations"]} == {
        "latest-1",
        "latest-2",
    }
    assert all(item["missingHardGates"] == [] for item in report["recommendations"])
    assert repository.get("latest-1").match_score == 10
    assert repository.get("latest-2").match_score == 20


def test_apply_latest_scores_backs_up_and_updates_only_frozen_ids(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    repository = ResumeRepository(database)
    _save(
        repository,
        resume_id="latest-1",
        name="甲",
        job_type="AI产品经理",
        score=10,
        updated_at="2026-07-16T03:00:00+00:00",
        phone="13800138000",
        raw_text=FULL_B2B_AI_PM,
    )
    _save(
        repository,
        resume_id="latest-2",
        name="乙",
        job_type="AI产品经理",
        score=20,
        updated_at="2026-07-16T02:00:00+00:00",
        phone="13800138001",
        raw_text="B2B销售 CRM 获客 跟进 报价 签约 PRD MVP AI能力边界 客户落地 0到1",
    )
    _save(
        repository,
        resume_id="older",
        name="丙",
        job_type="AI产品经理",
        score=30,
        updated_at="2026-07-15T01:00:00+00:00",
        phone="13800138002",
        raw_text=FULL_B2B_AI_PM,
    )

    report = build_b2b_ai_pm_report(database, latest_count=2)
    result = apply_latest_scores(database, report, tmp_path / "backups")

    refreshed = ResumeRepository(database)
    expected = {item["resumeId"]: item["newScore"] for item in report["latestCandidates"]}
    assert Path(result["backupPath"]).exists()
    assert refreshed.get("latest-1").match_score == expected["latest-1"]
    assert refreshed.get("latest-2").match_score == expected["latest-2"]
    assert refreshed.get("older").match_score == 30
    assert [item["resumeId"] for item in result["updatedLatest"]] == [
        "latest-1",
        "latest-2",
    ]


def test_report_prefers_platform_candidate_name_over_misparsed_job_title(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    repository = ResumeRepository(database)
    _save(
        repository,
        resume_id="resume-1",
        name="应聘职位：AI 产品经理（杭州）",
        job_type="AI产品经理",
        score=10,
        updated_at="2026-07-16T03:00:00+00:00",
        phone="13800138000",
        raw_text="应聘职位：AI 产品经理（杭州） 郑阳平 ID：514276901 " + FULL_B2B_AI_PM,
        candidate_name_from_platform="郑阳平",
    )

    report = build_b2b_ai_pm_report(database)

    assert report["recommendations"][0]["candidateName"] == "郑阳平"


def test_report_prefers_parsed_real_name_over_anonymous_platform_name(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    repository = ResumeRepository(database)
    _save(
        repository,
        resume_id="resume-1",
        name="白光远",
        job_type="AI产品经理",
        score=10,
        updated_at="2026-07-16T03:00:00+00:00",
        phone="13800138000",
        raw_text="白光远 产品经理 " + FULL_B2B_AI_PM,
        candidate_name_from_platform="白先生",
    )

    report = build_b2b_ai_pm_report(database)

    assert report["recommendations"][0]["candidateName"] == "白光远"


def test_cli_loads_the_project_next_to_the_script(tmp_path: Path) -> None:
    """直接执行脚本时必须优先加载脚本所在项目，而不是环境中的旧仓库。"""

    database = tmp_path / "resumes.sqlite"
    repository = ResumeRepository(database)
    _save(
        repository,
        resume_id="resume-1",
        name="甲",
        job_type="AI产品经理",
        score=10,
        updated_at="2026-07-16T03:00:00+00:00",
        phone="13800138000",
        raw_text=FULL_B2B_AI_PM,
    )
    report = tmp_path / "report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT_PATH),
            "--database",
            str(database),
            "--report",
            str(report),
        ],
        cwd=_SCRIPT_PATH.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert report.exists()
