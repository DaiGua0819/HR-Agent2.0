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
    assert POSITION_SCORING_VERSION == "v7-fullstack-engineer-profile"
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


def test_fullstack_engineer_scores_against_ai_native_b2b_platform_jd() -> None:
    """全栈岗位应按工程 Owner、微信生态和 AI 平台交付证据评分。"""

    result = calculate_jd_match(
        (
            "8年 TypeScript JavaScript React Next.js Node.js SQL API 全栈开发 "
            "微信小程序 Taro 上线审核 企业微信 WeCom OAuth JS-SDK 消息回调 客户群 "
            "领域模型 多租户 ReBAC OpenFGA 工作流 幂等 Outbox 审计 "
            "Git Pull Request Code Review 自动化测试 CI/CD UAT 发布回滚 "
            "LangGraph Agent Tool Calling RAG Eval Human-in-the-loop "
            "Tech Lead 工程 Owner 带领2名开发 任务拆解 ToB客户现场 ERP CRM"
        ),
        "全栈工程师",
    )

    assert result["profile"] == "全栈工程师"
    assert result["score"] >= 75
    assert result["missingHardGates"] == []
    assert {item["label"] for item in result["must"]["items"]} >= {
        "TypeScript端到端全栈交付",
        "微信小程序与企业微信生态",
        "复杂业务架构与权限",
        "工程Owner与质量门禁",
        "AI原生研发与Agent工程",
    }


def test_fullstack_engineer_missing_ai_native_gate_cannot_reach_priority() -> None:
    """缺少 Agent、RAG、评估或人工确认证据时不能进入 A 优先。"""

    result = calculate_jd_match(
        (
            "8年 TypeScript React Next.js Node.js SQL API 微信小程序 Taro "
            "企业微信 WeCom OAuth JS-SDK 客户群 多租户 ReBAC OpenFGA 工作流 "
            "Git Pull Request Code Review 自动化测试 CI/CD UAT "
            "Tech Lead 工程 Owner 带领团队 ERP CRM ToB客户现场"
        ),
        "全栈工程师",
    )

    assert "AI原生研发能力" in result["missingHardGates"]
    assert result["score"] <= 74
    assert result["level"] != "A 优先"


def test_fullstack_engineer_spring_does_not_fake_pull_request_evidence() -> None:
    """Spring 中的字母 pr 不能冒充 Pull Request 或 Review 证据。"""

    result = calculate_jd_match(
        (
            "8年 TypeScript React Next.js Node.js Spring SQL 微信小程序 Taro "
            "企业微信 WeCom OAuth JS-SDK 多租户 OpenFGA 工作流 "
            "Agent RAG Eval Tech Lead 带领团队 ERP CRM"
        ),
        "全栈工程师",
    )

    assert "工程Owner能力" in result["missingHardGates"]
    assert result["score"] <= 74


def test_ai_product_manager_platform_suffix_keeps_ai_product_profile() -> None:
    """职位描述包含 AI 原生 B2B 平台时仍应优先识别明确的 AI 产品经理。"""

    result = calculate_jd_match(
        "AI产品经理 B2B销售 企业级产品 CRM 权限 工作流 Agent",
        "AI产品经理（AI原生B2B平台）",
    )

    assert result["profile"] == "AI产品经理"


def test_ai_product_manager_scores_against_b2b_enterprise_product_jd() -> None:
    """AI 产品经理必须同时具备 B2B 销售链路和企业级产品复杂度证据。"""

    result = calculate_jd_match(
        (
            "AI产品经理 4年产品经理 B2B销售 大客户销售 CRM 客户管理 商机管理 "
            "获客 线索 跟进 报价 签约 成交 交付 回款 续约 企业级产品 企业服务 SaaS "
            "多角色 权限管理 审批流 工作流 数据安全 用户访谈 客户现场 真实场景洞察 "
            "产品路线图 MVP 优先级 PRD 验收标准 跨团队交付 AI能力边界 人机协作 "
            "人工确认 纠错机制 客户落地 使用反馈 迭代闭环 0到1 独立负责产品模块 "
            "企业微信 企微API 工作手机 本地服务器 私有化部署 制造业 数据指标 创业团队"
        ),
        "AI产品经理",
    )

    assert result["profile"] == "AI产品经理"
    assert result["score"] >= 75
    assert result["missingHardGates"] == []
    assert result["hardGateCap"] is None
    assert all(item["passed"] for item in result["hardGates"]["items"])
    assert {item["label"] for item in result["must"]["items"]} >= {
        "客户现场与真实场景洞察",
        "产品路线图、MVP与优先级",
        "PRD、验收标准与跨团队交付",
        "AI能力边界、人机协作与纠错",
        "客户落地与反馈迭代闭环",
        "独立0到1产品模块交付",
    }
    assert result["bonus"]["count"] >= 4
    assert result["risks"]["count"] == 0


def test_ai_product_manager_missing_enterprise_gate_is_capped_at_b() -> None:
    """具备 B2B 销售链路但没有企业级复杂产品证据时最高只能 B。"""

    result = calculate_jd_match(
        (
            "AI产品经理 B2B销售 CRM 客户管理 商机管理 获客 跟进 报价 签约 交付 回款 "
            "用户访谈 客户现场 产品路线图 MVP PRD 验收标准 AI能力边界 人工确认 "
            "客户落地 反馈闭环 0到1 独立负责"
        ),
        "AI产品经理",
    )

    assert result["missingHardGates"] == ["企业级产品经验"]
    assert result["hardGateCap"] == 74
    assert result["score"] <= 74
    assert result["level"] != "A 优先"


def test_ai_product_manager_missing_both_gates_is_capped_at_c() -> None:
    """泛 AI 产品经历没有 B2B 销售和企业产品证据时最高只能 C。"""

    result = calculate_jd_match(
        (
            "AI产品经理 Agent Prompt RAG PRD 用户访谈 产品路线图 MVP "
            "AI能力边界 人机协作 0到1"
        ),
        "AI产品经理",
    )

    assert result["missingHardGates"] == ["B2B销售理解", "企业级产品经验"]
    assert result["hardGateCap"] == 54
    assert result["score"] <= 54
    assert result["level"] in {"C 暂缓", "D 不优先"}


def test_ai_product_manager_bare_b2b_and_crm_terms_do_not_pass_grouped_gates() -> None:
    """只有宽泛的 B2B/CRM 名词，没有链路和复杂度证据时不能通过硬门槛。"""

    result = calculate_jd_match("AI产品经理 B2B CRM SaaS", "AI产品经理")

    assert result["missingHardGates"] == ["B2B销售理解", "企业级产品经验"]
    assert result["hardGateCap"] == 54


def test_ai_product_manager_customer_management_and_delivery_do_not_fake_sales_gate() -> None:
    """泛客户管理和项目交付不能冒充 B2B 销售理解。"""

    result = calculate_jd_match(
        (
            "AI产品经理 客户管理 项目交付 企业级产品 ERP 多角色 权限体系 审批流 "
            "客户现场 需求调研 需求全生命周期 PRD 测试验收 部署交付 RAG 人工审核 "
            "客户反馈 版本迭代 0到1 独立负责"
        ),
        "AI产品经理",
    )

    assert "B2B销售理解" in result["missingHardGates"]
    assert "企业级产品经验" not in result["missingHardGates"]


def test_ai_product_manager_sales_automation_and_customer_development_pass_sales_gate() -> None:
    """销售自动化、客户开发、产品定价和签约金额属于完整 B2B 销售证据。"""

    result = calculate_jd_match(
        (
            "AI产品经理 企业服务 ERP 销售自动化 客户开发 产品定价 售前方案 "
            "跟进客户 签约金额 回款 续约 多角色 权限管理 审批流 工作流 "
            "现场调研 产品规划 版本迭代 需求全生命周期 研发测试 上线部署 "
            "项目实施 客户验收 智能体 人工兜底 从0到1"
        ),
        "AI产品经理",
    )

    assert result["missingHardGates"] == []
    assert result["hardGateCap"] is None
    assert {item["label"] for item in result["must"]["items"]} >= {
        "客户现场与真实场景洞察",
        "产品路线图、MVP与优先级",
        "PRD、验收标准与跨团队交付",
        "AI能力边界、人机协作与纠错",
        "客户落地与反馈迭代闭环",
        "独立0到1产品模块交付",
    }
    assert result["score"] >= 75


def test_ai_product_manager_tob_platform_and_system_integration_pass_enterprise_gate() -> None:
    """ToB 平台及多系统集成、中后台和权限配置属于企业产品复杂度证据。"""

    result = calculate_jd_match(
        (
            "AI产品经理 B2B销售 售前 客户开发 报价 签约 回款 "
            "ToB平台 政企产品 中后台 多系统集成 数据中台 权限配置 组织架构 "
            "客户对接 版本推进 PRD UAT 交付验收 Agent 幻觉 人工审核 0→1"
        ),
        "AI产品经理",
    )

    assert result["missingHardGates"] == []
    assert result["hardGateCap"] is None


def test_ai_product_manager_bidding_and_poc_count_as_b2b_sales_cycle() -> None:
    """企业售前中的招投标、POC 和中标属于 B2B 销售链路证据。"""

    result = calculate_jd_match(
        (
            "AI产品经理 售前解决方案 客户拓展 招投标 POC测试 成功中标 "
            "企业级产品 SaaS 多角色 权限管理 审批流"
        ),
        "AI产品经理",
    )

    assert "B2B销售理解" not in result["missingHardGates"]
    assert "企业级产品经验" not in result["missingHardGates"]


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
