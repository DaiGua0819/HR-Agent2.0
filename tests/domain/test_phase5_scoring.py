"""Phase 5：JD 匹配与打分引擎测试。"""

from __future__ import annotations

from app.domain.scoring.engine import (
    POSITION_SCORING_VERSION,
    SCORING_VERSION,
    score_automation_contact_match,
    score_resume_for_profile,
)
from app.domain.scoring.jd_match import calculate_jd_match, get_jd_level, match_jd_keywords


def test_jd_keyword_matching_and_levels() -> None:
    """关键词命中和 A/B/C/D 阈值保持旧逻辑。"""

    match = match_jd_keywords("本科 电气 自动化 PLC 项目", ["本科", "PLC", "销售"])
    assert match["matched"] == ["本科", "PLC"]
    assert match["missing"] == ["销售"]
    assert get_jd_level(75) == "A 优先"
    assert get_jd_level(55) == "B 复核"
    assert get_jd_level(35) == "C 暂缓"
    assert get_jd_level(34) == "D 不优先"


def test_position_score_formula_matches_old_threshold_shape() -> None:
    """v5 公式：必须项、加分项、岗位 boost、focus boost、风险扣分。"""

    result = calculate_jd_match(
        "本科 电气 自动化 PLC 产线 调试 EPLAN 电气设计",
        "电气工程师",
    )
    assert result["score"] == 100
    assert result["level"] == "A 优先"
    assert result["roleBoost"] == 15

    weak = calculate_jd_match("高中 行政 前台", "电气工程师")
    assert weak["score"] <= 45
    assert weak["level"] == "D 不优先"

    risky = calculate_jd_match("本科 电气 PLC 无PLC 维修工", "电气工程师")
    assert risky["score"] <= 74
    assert risky["riskPenalty"] == 20


def test_scoring_entrypoints_and_version_constants() -> None:
    """简历评分和自动化联系评分共用同一 JD 引擎。"""

    payload = {
        "name": "张三",
        "education": "本科",
        "major": "电气工程",
        "rawText": "本科 电气 自动化 PLC 产线调试",
        "applied_position": "电气工程师",
    }
    resume_score = score_resume_for_profile(payload, "电气工程师")
    contact_score = score_automation_contact_match("本科 电气 自动化 PLC 产线调试", "电气工程师")
    assert resume_score["level"] in {"A 优先", "B 复核"}
    assert contact_score["score"] == resume_score["score"]
    assert POSITION_SCORING_VERSION == "v5-position-must-bonus"
    assert SCORING_VERSION == "v4-agent-depth-human-feedback"
