"""JD 岗位档案。

这里承接旧 `JD_MATCH_PROFILES` 的职责：每个岗位由必须项、加分项、风险项和别名组成。
Phase 5 先放入控制面常用岗位的内置档案；后续可替换为配置/DB 读取而不改变打分引擎。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.resume.job_types import (
    AI_PRODUCT_MANAGER,
    FULLSTACK_ENGINEER,
    OPERATION_A,
    OPERATION_B,
)


@dataclass(frozen=True)
class JdRule:
    """一个 JD 规则项，命中任一关键词即认为该项有证据。"""

    label: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class JdHardGate:
    """由多个证据组构成的岗位硬门槛。"""

    label: str
    keyword_groups: tuple[tuple[str, ...], ...]
    minimum_groups: int = 0


@dataclass(frozen=True)
class JdProfile:
    """岗位评分档案。"""

    name: str
    aliases: tuple[str, ...]
    must_have: tuple[JdRule, ...]
    bonus: tuple[JdRule, ...]
    risks: tuple[JdRule, ...]
    hard_gates: tuple[JdHardGate, ...] = ()


JD_PROFILES: dict[str, JdProfile] = {
    OPERATION_A: JdProfile(
        name=OPERATION_A,
        aliases=("企业内容运营负责人", "B2B短视频", "品牌内容运营负责人", "企业获客", "创始人IP"),
        must_have=(
            JdRule("2年以上内容运营经验", ("2年", "3年", "4年", "5年", "内容运营", "短视频运营")),
            JdRule("账号策略与选题脚本", ("账号定位", "内容策划", "月度选题", "脚本", "选题")),
            JdRule("B2B业务表达", ("B2B", "企业服务", "SaaS", "AI", "私有化", "知识库", "工作流")),
            JdRule("线索与数据复盘", ("数据复盘", "私信", "线索", "有效咨询", "转化", "留资")),
        ),
        bonus=(
            JdRule("企业号或品牌号案例", ("企业号", "品牌号", "公司号", "作品链接", "完整案例")),
            JdRule("拍摄剪辑把控", ("拍摄", "剪辑", "拍剪", "封面", "发布")),
            JdRule("跨部门业务协同", ("老板", "销售", "产品", "交付", "跨部门")),
            JdRule("AI工具提效", ("AI工具", "AIGC", "ChatGPT", "大模型")),
        ),
        risks=(
            JdRule("没有作品集", ("没作品集", "无作品集", "不能提供作品", "没有案例")),
            JdRule("只会剪辑不策划", ("只会剪辑", "不会策划", "不做策划")),
            JdRule("娱乐热点导向", ("娱乐热点", "追热点", "泛娱乐", "段子")),
            JdRule("缺少线索意识", ("不看线索", "只看播放量", "不看转化")),
        ),
    ),
    OPERATION_B: JdProfile(
        name=OPERATION_B,
        aliases=("B端社交媒体运营", "社交媒体运营", "工业品运营", "膨润土运营", "B2B外贸账号"),
        must_have=(
            JdRule("大专及以上学历", ("大专", "专科", "本科", "硕士", "博士")),
            JdRule(
                "新媒体或B2B运营经验",
                ("新媒体运营", "短视频运营", "内容运营", "B2B平台运营", "工业品推广"),
            ),
            JdRule(
                "工业品内容理解",
                ("膨润土", "工业品", "矿产品", "化工原料", "铸造", "钻井泥浆", "猫砂"),
            ),
            JdRule("询盘与线索复盘", ("数据复盘", "询盘", "私信", "有效线索", "客户线索")),
        ),
        bonus=(
            JdRule(
                "多平台运营",
                ("抖音", "视频号", "小红书", "公众号", "LinkedIn", "Facebook", "YouTube"),
            ),
            JdRule("英文或外贸内容", ("英语", "英文", "外贸", "阿里国际站", "中国制造网")),
            JdRule("完整内容流程", ("选题", "脚本", "拍摄", "发布", "复盘", "线索整理")),
            JdRule(
                "工业应用场景",
                ("冶金球团", "涂料", "环保吸附", "工厂展示", "发货现场", "检测过程"),
            ),
        ),
        risks=(
            JdRule("没有B端意识", ("只做C端", "娱乐热点", "不懂B端")),
            JdRule("不会文案策划", ("不会写文案", "不会脚本", "只会发布")),
            JdRule("没有数据意识", ("不看数据", "不复盘", "不看询盘")),
        ),
    ),
    "销售管培生": JdProfile(
        name="销售管培生",
        aliases=("销售", "销售管培", "业务管培"),
        must_have=(
            JdRule("学历大专及以上", ("大专", "专科", "本科", "硕士", "博士")),
            JdRule("销售或客户意向", ("销售", "客户", "业务", "市场拓展")),
        ),
        bonus=(
            JdRule("接受出差", ("出差", "驻外", "外勤")),
            JdRule("化工或材料行业", ("化工", "材料", "涂料", "膨润土")),
        ),
        risks=(
            JdRule("明确不接受出差", ("不接受出差", "不能出差")),
            JdRule("无销售意向", ("不考虑销售", "不做销售")),
        ),
    ),
    "电气工程师": JdProfile(
        name="电气工程师",
        aliases=("电气", "自动化工程师", "电气工程"),
        must_have=(
            JdRule("本科及以上", ("本科", "硕士", "博士")),
            JdRule("电气或自动化", ("电气", "自动化", "机电")),
            JdRule("PLC 经验", ("PLC", "西门子", "三菱", "控制器")),
        ),
        bonus=(
            JdRule("现场项目", ("产线", "现场", "调试", "项目")),
            JdRule("电气设计", ("EPLAN", "电气设计", "低压配电")),
        ),
        risks=(
            JdRule("无 PLC 证据", ("无PLC", "没有PLC")),
            JdRule("仅维修经验", ("维修工", "设备维修")),
        ),
    ),
    "HRBP": JdProfile(
        name="HRBP",
        aliases=("人力资源", "人力资源管培生", "HR"),
        must_have=(
            JdRule("本科及以上", ("本科", "硕士", "博士")),
            JdRule("人力资源或理工科", ("人力资源", "工商管理", "心理学", "理工", "化工")),
        ),
        bonus=(
            JdRule("招聘或组织经验", ("招聘", "培训", "绩效", "员工关系")),
            JdRule("制造业背景", ("制造业", "工厂", "化工")),
        ),
        risks=(
            JdRule("非人力方向", ("市场营销", "财务会计", "行政前台")),
        ),
    ),
    "AI应用开发实习生": JdProfile(
        name="AI应用开发实习生",
        aliases=("AI应用开发", "AI实习", "人工智能应用"),
        must_have=(
            JdRule("编程基础", ("Python", "JavaScript", "TypeScript", "FastAPI")),
            JdRule("AI 工具经验", ("LLM", "大模型", "LangChain", "Agent", "OpenAI")),
        ),
        bonus=(
            JdRule("项目落地", ("项目", "上线", "自动化", "RAG")),
            JdRule("前后端能力", ("React", "Vue", "数据库", "API")),
        ),
        risks=(
            JdRule("无技术证据", ("无编程", "不会编程")),
        ),
    ),
    FULLSTACK_ENGINEER: JdProfile(
        name=FULLSTACK_ENGINEER,
        aliases=(
            "资深全栈工程师",
            "Full Stack Engineer",
            "Fullstack Engineer",
        ),
        must_have=(
            JdRule(
                "TypeScript端到端全栈交付",
                (
                    "TypeScript",
                    "JavaScript",
                    "React",
                    "Next.js",
                    "Node.js",
                    "全栈",
                    "前后端",
                    "SQL",
                    "API",
                ),
            ),
            JdRule(
                "微信小程序与企业微信生态",
                (
                    "微信小程序",
                    "小程序",
                    "mini program",
                    "Taro",
                    "uni-app",
                    "企业微信",
                    "企微",
                    "WeCom",
                    "JS-SDK",
                    "客户群",
                    "外部联系人",
                ),
            ),
            JdRule(
                "复杂业务架构与权限",
                (
                    "领域模型",
                    "多租户",
                    "RBAC",
                    "ABAC",
                    "ReBAC",
                    "OpenFGA",
                    "权限",
                    "工作流",
                    "状态机",
                    "幂等",
                    "Outbox",
                    "审计",
                ),
            ),
            JdRule(
                "工程Owner与质量门禁",
                (
                    "工程 Owner",
                    "工程Owner",
                    "Tech Lead",
                    "技术负责人",
                    "Pull Request",
                    "Code Review",
                    "代码审查",
                    "自动化测试",
                    "CI/CD",
                    "UAT",
                    "发布回滚",
                    "任务拆解",
                ),
            ),
            JdRule(
                "AI原生研发与Agent工程",
                (
                    "Coding Agent",
                    "Agent",
                    "Tool Calling",
                    "RAG",
                    "Eval",
                    "评估集",
                    "Human-in-the-loop",
                    "人工确认",
                    "LangGraph",
                    "大模型",
                ),
            ),
        ),
        bonus=(
            JdRule(
                "复杂授权与安全边界",
                ("OpenFGA", "SpiceDB", "Casbin", "ReBAC", "最小权限", "数据安全"),
            ),
            JdRule(
                "工作流与长事务",
                ("LangGraph", "n8n", "Temporal", "BPMN", "工作流引擎", "长事务"),
            ),
            JdRule(
                "企业系统与ToB集成",
                ("ERP", "CRM", "ToB", "企业服务", "系统集成", "客户现场", "FDE"),
            ),
            JdRule(
                "微信生态深度交付",
                ("客户联系", "客户群", "服务商代开发", "多企业授权", "消息回调", "上线审核"),
            ),
            JdRule(
                "团队带教与研发组织",
                ("带领", "带队", "导师", "Mentor", "任务拆解", "DoR", "DoD", "迭代主持"),
            ),
        ),
        risks=(
            JdRule(
                "只能承担单端局部开发",
                ("只做前端", "只做后端", "只负责页面", "只负责接口", "不做全栈"),
            ),
            JdRule(
                "盲信AI且缺少验证",
                ("复制粘贴", "盲信生成", "不写测试", "无需测试", "不做代码审查"),
            ),
            JdRule(
                "偏好推倒重来或空谈架构",
                ("推倒重来", "全部重写", "只谈架构", "不能落地", "不做渐进迁移"),
            ),
            JdRule(
                "拒绝Review与带教",
                ("不做Review", "不愿Review", "不愿带人", "拒绝带人"),
            ),
        ),
        hard_gates=(
            JdHardGate(
                "端到端全栈交付",
                keyword_groups=(
                    ("TypeScript", "JavaScript"),
                    ("React", "Next.js", "Vue", "前端"),
                    ("Node.js", "Node", "后端", "API", "SQL", "PostgreSQL"),
                ),
                minimum_groups=3,
            ),
            JdHardGate(
                "微信与企微实战",
                keyword_groups=(
                    ("微信小程序", "小程序", "mini program", "Taro", "uni-app"),
                    ("企业微信", "企微", "WeCom", "JS-SDK", "客户群", "外部联系人"),
                ),
                minimum_groups=2,
            ),
            JdHardGate(
                "工程Owner能力",
                keyword_groups=(
                    (
                        "Pull Request",
                        "Code Review",
                        "代码审查",
                        "自动化测试",
                        "CI/CD",
                        "UAT",
                    ),
                    (
                        "Tech Lead",
                        "工程 Owner",
                        "工程Owner",
                        "技术负责人",
                        "带领",
                        "带队",
                        "任务拆解",
                    ),
                ),
                minimum_groups=2,
            ),
            JdHardGate(
                "AI原生研发能力",
                keyword_groups=(
                    ("Coding Agent", "Agent", "大模型", "LLM"),
                    (
                        "Tool Calling",
                        "RAG",
                        "Eval",
                        "评估集",
                        "Human-in-the-loop",
                        "人工确认",
                        "LangGraph",
                    ),
                ),
                minimum_groups=2,
            ),
        ),
    ),
    AI_PRODUCT_MANAGER: JdProfile(
        name=AI_PRODUCT_MANAGER,
        aliases=("AI 产品经理", "AI Product Manager", "AI PM", "AI产品", "AI产品负责人"),
        must_have=(
            JdRule(
                "客户现场与真实场景洞察",
                (
                    "客户现场",
                    "销售一线",
                    "用户访谈",
                    "客户访谈",
                    "客户对接",
                    "客户沟通",
                    "需求挖掘",
                    "一线调研",
                    "驻场",
                    "现场调研",
                    "业务调研",
                    "需求调研",
                    "现场演示",
                    "群聊",
                    "录音",
                    "真实场景",
                    "场景洞察",
                    "痛点分析",
                    "需求洞察",
                ),
            ),
            JdRule(
                "产品路线图、MVP与优先级",
                (
                    "产品路线图",
                    "路线图",
                    "MVP",
                    "版本规划",
                    "产品规划",
                    "迭代规划",
                    "版本迭代",
                    "版本推进",
                    "产品演进",
                    "蓝图设计",
                    "优先级",
                    "需求优先级",
                    "产品范围",
                ),
            ),
            JdRule(
                "PRD、验收标准与跨团队交付",
                (
                    "PRD",
                    "验收标准",
                    "跨团队",
                    "设计研发测试",
                    "需求全生命周期",
                    "产品全生命周期",
                    "需求评审",
                    "方案设计",
                    "研发测试",
                    "测试验收",
                    "上线部署",
                    "部署交付",
                    "项目实施",
                    "实施交付",
                    "项目验收",
                    "UAT",
                    "交付验收",
                    "上线验收",
                    "交付质量",
                    "项目推进",
                ),
            ),
            JdRule(
                "AI能力边界、人机协作与纠错",
                (
                    "AI能力边界",
                    "能力边界",
                    "人机协作",
                    "人工确认",
                    "人工干预",
                    "人工介入",
                    "人工审核",
                    "人工兜底",
                    "纠错机制",
                    "反馈闭环",
                    "容错",
                    "降级",
                    "fallback",
                    "幻觉",
                    "bad case",
                    "评估体系",
                    "测试集",
                    "可控",
                    "可追溯",
                    "RAG",
                    "工作流编排",
                    "多模态",
                    "语音识别",
                ),
            ),
            JdRule(
                "客户落地与反馈迭代闭环",
                (
                    "客户落地",
                    "落地实施",
                    "客户实施",
                    "客户反馈",
                    "使用反馈",
                    "反馈迭代",
                    "迭代闭环",
                    "上线落地",
                    "项目落地",
                    "项目交付",
                    "交付验收",
                    "上线验收",
                    "实施上线",
                    "现场支持",
                    "客户验收",
                    "客户培训",
                    "试点",
                    "POC",
                    "售后支持",
                    "运维优化",
                    "持续优化",
                ),
            ),
            JdRule(
                "独立0到1产品模块交付",
                (
                    "0到1",
                    "0 到 1",
                    "从0到1",
                    "从 0 到 1",
                    "0→1",
                    "0-1",
                    "0~1",
                    "独立负责",
                    "独立交付",
                    "从需求到上线",
                    "全流程交付",
                ),
            ),
        ),
        bonus=(
            JdRule(
                "企业微信与审批生态经验",
                ("企业微信", "企微", "企微API", "企微 API", "审批流", "微信生态"),
            ),
            JdRule(
                "工作手机、本地部署与软硬件结合经验",
                ("工作手机", "本地服务器", "本地部署", "私有化部署", "硬件部署", "软硬件"),
            ),
            JdRule(
                "农资、制造业、快消或工业品行业经验",
                ("农资", "制造业", "快消", "工业品", "企业服务", "B2B平台", "供应链", "物流"),
            ),
            JdRule(
                "产品数据与经营指标驱动",
                ("数据指标", "活跃度", "使用率", "转化率", "经营分析", "数据驱动", "衡量标准"),
            ),
            JdRule(
                "创业团队与不确定环境快速迭代",
                ("创业团队", "创业公司", "不确定", "快速迭代", "敏捷迭代", "从0到1"),
            ),
        ),
        risks=(
            JdRule(
                "只写PRD，不做客户访谈或现场验证",
                ("只会写 PRD", "只写PRD", "不做用户访谈", "不做客户访谈", "不做现场验证"),
            ),
            JdRule(
                "把AI当万能接口，缺少边界与人工兜底",
                ("AI万能", "万能接口", "不考虑AI边界", "没有人工兜底", "无需人工确认"),
            ),
            JdRule(
                "只有C端或界面功能经验",
                ("只有C端", "纯C端", "只关注界面功能", "只做界面", "缺少企业产品经验"),
            ),
            JdRule(
                "只转述需求，缺少真实问题与价值判断",
                ("只转述需求", "缺少业务价值判断", "不能判断真实业务价值", "客户要什么就做什么"),
            ),
            JdRule(
                "上线后不参与客户落地与反馈闭环",
                ("上线就结束", "不参与客户落地", "不跟进客户反馈", "不负责落地"),
            ),
            JdRule(
                "把AI产品理解成传统SaaS加聊天框",
                ("传统 SaaS", "聊天框", "SaaS + 一个聊天框", "SaaS+聊天框"),
            ),
        ),
        hard_gates=(
            JdHardGate(
                label="B2B销售理解",
                keyword_groups=(
                    (
                        "B2B销售",
                        "企业销售",
                        "大客户销售",
                        "销售管理",
                        "商机管理",
                        "销售自动化",
                        "客户开发",
                        "客户拓展",
                        "售前",
                        "销售策略",
                        "渠道销售",
                        "产品定价",
                        "CRM",
                        "SCRM",
                    ),
                    (
                        "获客",
                        "线索",
                        "销售跟进",
                        "客户跟进",
                        "跟进客户",
                        "报价",
                        "签约",
                        "签约金额",
                        "合同金额",
                        "成交",
                        "招投标",
                        "投标",
                        "中标",
                        "POC",
                        "商务谈判",
                        "市场开拓",
                        "回款",
                        "续约",
                        "渠道",
                        "渠道管理",
                    ),
                ),
            ),
            JdHardGate(
                label="企业级产品经验",
                keyword_groups=(
                    (
                        "企业级产品",
                        "企业服务",
                        "B2B产品",
                        "B2B 产品",
                        "ToB",
                        "To B",
                        "B端产品",
                        "B 端产品",
                        "B端平台",
                        "B 端平台",
                        "政企产品",
                        "政企平台",
                        "企业级AI",
                        "企业级 AI",
                        "企业软件",
                        "SaaS",
                        "CRM",
                        "SCRM",
                        "ERP",
                        "协同平台",
                    ),
                    (
                        "多角色",
                        "多权限",
                        "权限管理",
                        "权限体系",
                        "权限配置",
                        "数据权限",
                        "审批流",
                        "审核流程",
                        "工作流",
                        "流程驱动",
                        "流程管理",
                        "数据安全",
                        "组织协作",
                        "组织架构",
                        "中后台",
                        "前中后台",
                        "中台",
                        "数据中台",
                        "系统集成",
                        "多系统",
                        "多系统集成",
                        "数据集成",
                        "多租户",
                        "配置化",
                        "规则引擎",
                    ),
                ),
            ),
        ),
    ),
}


def get_jd_profile(job_type: str | None) -> JdProfile:
    """按岗位名/别名取档案，未命中时回退销售管培生。"""

    text = job_type or ""
    for profile in JD_PROFILES.values():
        if profile.name in text or any(alias in text for alias in profile.aliases):
            return profile
    return JD_PROFILES["销售管培生"]


def list_jd_profiles() -> list[JdProfile]:
    """列出全部内置岗位档案。"""

    return list(JD_PROFILES.values())
