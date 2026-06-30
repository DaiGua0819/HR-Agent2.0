"""JD 岗位档案。

这里承接旧 `JD_MATCH_PROFILES` 的职责：每个岗位由必须项、加分项、风险项和别名组成。
Phase 5 先放入控制面常用岗位的内置档案；后续可替换为配置/DB 读取而不改变打分引擎。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.resume.job_types import OPERATION_A, OPERATION_B


@dataclass(frozen=True)
class JdRule:
    """一个 JD 规则项，命中任一关键词即认为该项有证据。"""

    label: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class JdProfile:
    """岗位评分档案。"""

    name: str
    aliases: tuple[str, ...]
    must_have: tuple[JdRule, ...]
    bonus: tuple[JdRule, ...]
    risks: tuple[JdRule, ...]


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
