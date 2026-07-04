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


def test_operation_a_scores_against_b2b_content_growth_jd() -> None:
    """运营A按企业内容运营负责人 JD 识别 B2B 内容、线索和业务转化能力。"""

    result = calculate_jd_match(
        (
            "本科 3年短视频内容运营 企业号 品牌号 创始人IP 账号定位 "
            "月度选题 脚本撰写 拍摄剪辑 数据复盘 私信量 有效咨询量 "
            "SaaS AI 企业服务 工作流 知识库 私有化部署 线索承接"
        ),
        "运营A",
    )

    assert result["profile"] == "运营A"
    assert result["score"] >= 75
    assert {item["label"] for item in result["must"]["items"]} >= {
        "2年以上内容运营经验",
        "账号策略与选题脚本",
        "B2B业务表达",
        "线索与数据复盘",
    }
    assert result["risks"]["count"] == 0


def test_operation_b_scores_against_industrial_social_media_jd() -> None:
    """运营B按工业品/B端社媒 JD 识别膨润土、外贸平台和询盘线索能力。"""

    result = calculate_jd_match(
        (
            "大专 新媒体运营 B2B平台运营 工业品推广 膨润土 矿产品 "
            "铸造 钻井泥浆 猫砂 冶金球团 涂料 短视频 图文 公众号 "
            "LinkedIn Facebook YouTube 英文产品文案 数据复盘 询盘 有效线索"
        ),
        "运营B",
    )

    assert result["profile"] == "运营B"
    assert result["score"] >= 75
    assert {item["label"] for item in result["must"]["items"]} >= {
        "大专及以上学历",
        "新媒体或B2B运营经验",
        "工业品内容理解",
        "询盘与线索复盘",
    }
    assert result["bonus"]["count"] >= 3


def test_operation_profiles_penalize_pure_execution_without_strategy() -> None:
    """纯剪辑/娱乐热点但缺少作品、策略和业务线索意识的候选人不应高分。"""

    result = calculate_jd_match("只会剪辑 娱乐热点 无作品集 不会策划 不看线索", "运营A")

    assert result["profile"] == "运营A"
    assert result["score"] <= 45
    assert result["risks"]["count"] >= 2


def test_ai_product_manager_scores_against_ai_native_product_jd() -> None:
    """AI 产品经理按 PDF JD 识别工作流拆解、Agent 产品设计、Prompt/RAG 和 Eval 闭环。"""

    result = calculate_jd_match(
        (
            "AI产品经理 4年产品经理 B2B 企业服务 AI SaaS Agent Copilot Workflow "
            "用户访谈 真实工作流拆解 痛点分析 付费动机 PRD 用户故事 验收标准 上线复盘 "
            "Prompt RAG Tool Calling LLM 质量指标 任务完成率 采纳率 bad case golden set "
            "Cursor Claude Code ChatGPT SQL Python 0到1 产品 商业化 定价 客户试点"
        ),
        "AI产品经理",
    )

    assert result["profile"] == "AI产品经理"
    assert result["score"] >= 75
    assert {item["label"] for item in result["must"]["items"]} >= {
        "2年以上产品/创业/咨询/解决方案/业务分析经验",
        "用户访谈与真实工作流拆解",
        "AI Agent/Copilot/Workflow 产品设计",
        "Prompt/RAG/Tool Calling/LLM 基础理解",
        "Eval/质量指标/Bad case 闭环",
        "PRD/用户故事/验收标准/上线复盘能力",
    }
    assert result["bonus"]["count"] >= 4
    assert result["risks"]["count"] == 0


def test_ai_product_manager_penalizes_traditional_prd_only_profile() -> None:
    """只有传统 PRD/界面功能经验且无 AI 产品证据时不能高分。"""

    result = calculate_jd_match(
        "只会写 PRD 只关注界面功能 传统 SaaS 聊天框 不愿学习 Prompt Eval Agent RAG",
        "AI Product Manager",
    )

    assert result["profile"] == "AI产品经理"
    assert result["score"] <= 45
    assert result["risks"]["count"] >= 2


def test_ai_product_manager_risks_cap_score_below_priority_level() -> None:
    """AI 产品经理命中多个风险项时，即使有部分经验也不能进入 A 优先。"""

    result = calculate_jd_match(
        (
            "AI产品经理 3年产品经理 用户访谈 工作流拆解 Agent Workflow Prompt RAG "
            "PRD 验收标准 只转述用户需求 缺少业务价值判断 只关注界面功能 "
            "不关心 AI 输出质量和业务结果"
        ),
        "AI产品经理",
    )

    assert result["profile"] == "AI产品经理"
    assert result["score"] <= 74
    assert result["risks"]["count"] >= 2
