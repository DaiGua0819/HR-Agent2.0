"""主动联系门槛引擎。

这里的判断只服务“推荐牛人 / 主动打招呼”流程，不能复用到未读聊天筛选。
输入是卡片文本与在线简历弹层文本合并后的证据，输出可测试的通过/跳过理由。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdDecision:
    """主动联系门槛判断结果。"""

    passed: bool
    reason: str
    evidence: dict[str, object]


def evaluate_proactive_threshold(text: str, position: str) -> ThresholdDecision:
    """按岗位判断候选人是否允许主动打招呼。"""

    compact = _compact(text)
    target = _compact(position)
    if "AI应用实习生" in position or "AI应用开发实习生" in position:
        return _skip("ai_intern_not_proactive", compact)
    if "销售管培生" in target:
        return _base_gate(compact, min_education=2, max_age=25)
    if "膨润土销售" in target:
        return _keyword_gate(
            compact,
            min_education=2,
            max_age=35,
            keywords=BENTONITE_SALES_KEYWORDS,
        )
    if "应用技术经理" in target:
        return _keyword_gate(compact, min_education=3, max_age=45, keywords=应用技术_KEYWORDS)
    if "石油钻井泥浆膨润土销售" in target:
        return _keyword_gate(compact, min_education=2, max_age=45, keywords=OIL_SALES_KEYWORDS)
    if "外贸销售经理" in target:
        if _has_any(compact, TRADE_SALES_KEYWORDS):
            return _pass(
                "trade_sales_evidence",
                compact,
                {"keywords": [item for item in TRADE_SALES_KEYWORDS if item in compact]},
            )
        return _skip("missing_trade_sales_evidence", compact)
    if _is_hr_target(target):
        gate = _base_gate(compact, min_education=3, max_age=30)
        if not gate.passed:
            return gate
        if _has_any(compact, HR_MAJOR_KEYWORDS) or _has_any(compact, STEM_KEYWORDS):
            return _pass("hr_major_or_stem", compact, gate.evidence)
        return _skip("missing_hr_or_stem_major", compact, gate.evidence)
    if "国际业务管培生" in target:
        gate = _base_gate(compact, min_education=3, max_age=25)
        if not gate.passed:
            return gate
        if _has_any(compact, INTERNATIONAL_MAJOR_KEYWORDS):
            return _pass("international_major", compact, gate.evidence)
        if _has_any(compact, STEM_KEYWORDS) and _has_any(compact, CET6_KEYWORDS):
            return _pass("stem_with_cet6", compact, gate.evidence)
        return _skip("missing_international_major_or_stem_cet6", compact, gate.evidence)
    if "电气工程师" in target:
        gate = _base_gate(compact, min_education=3, max_age=35)
        if not gate.passed:
            return gate
        if not _has_any(compact, ELECTRICAL_MAJOR_KEYWORDS):
            return _skip("missing_electrical_or_automation_major", compact, gate.evidence)
        if not _has_any(compact, PLC_KEYWORDS):
            return _skip("missing_plc_evidence", compact, gate.evidence)
        return _pass("electrical_plc_match", compact, gate.evidence)
    return _skip("unsupported_position", compact)


def _base_gate(compact: str, *, min_education: int, max_age: int) -> ThresholdDecision:
    education = _education_rank(compact)
    age = _age(compact)
    evidence: dict[str, object] = {"educationRank": education, "age": age}
    if education is None:
        return _skip("missing_education", compact, evidence)
    if education < min_education:
        return _skip("education_below_threshold", compact, evidence)
    if age is None:
        return _skip("missing_age", compact, evidence)
    if age >= max_age:
        return _skip("age_over_or_equal_threshold", compact, evidence)
    return _pass("base_gate_passed", compact, evidence)


def _keyword_gate(
    compact: str,
    *,
    min_education: int,
    max_age: int,
    keywords: tuple[str, ...],
) -> ThresholdDecision:
    gate = _base_gate(compact, min_education=min_education, max_age=max_age)
    if not gate.passed:
        return gate
    matched = [item for item in keywords if item in compact]
    evidence = {**gate.evidence, "keywords": matched}
    if not matched:
        return _skip("missing_required_keyword", compact, evidence)
    return _pass("keyword_gate_passed", compact, evidence)


def _education_rank(compact: str) -> int | None:
    ranks = {
        "中专": 1,
        "高中": 1,
        "大专": 2,
        "专科": 2,
        "本科": 3,
        "学士": 3,
        "硕士": 4,
        "研究生": 4,
        "博士": 5,
    }
    matched = [rank for word, rank in ranks.items() if word in compact]
    return max(matched) if matched else None


def _age(compact: str) -> int | None:
    match = re.search(r"(?<!\d)([1-5]\d)\s*岁", compact)
    if match:
        return int(match.group(1))
    match = re.search(r"年龄[:：]?([1-5]\d)", compact)
    return int(match.group(1)) if match else None


def _is_hr_target(target: str) -> bool:
    return "HRBP" in target.upper() or "人力资源" in target


def _has_any(compact: str, keywords: tuple[str, ...]) -> bool:
    return any(item in compact for item in keywords)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _pass(reason: str, compact: str, evidence: dict[str, object]) -> ThresholdDecision:
    return ThresholdDecision(True, reason, {**evidence, "textSample": compact[:80]})


def _skip(
    reason: str,
    compact: str,
    evidence: dict[str, object] | None = None,
) -> ThresholdDecision:
    return ThresholdDecision(False, reason, {**(evidence or {}), "textSample": compact[:80]})


BENTONITE_SALES_KEYWORDS = ("涂料", "膨润土", "流变助剂")
应用技术_KEYWORDS = ("流变助剂", "膨润土", "工业涂料", "涂料研发", "涂料工程师")
OIL_SALES_KEYWORDS = ("石油", "钻井", "泥浆", "膨润土", "油服")
TRADE_SALES_KEYWORDS = ("外贸", "国际贸易", "英语", "出口", "海外", "化工")
HR_MAJOR_KEYWORDS = ("人力资源", "人资", "劳动与社会保障", "组织发展", "工商管理")
STEM_KEYWORDS = (
    "理工",
    "工科",
    "工程",
    "机械",
    "化工",
    "材料",
    "电气",
    "自动化",
    "计算机",
    "软件",
    "数学",
    "物理",
    "化学",
)
INTERNATIONAL_MAJOR_KEYWORDS = ("国际贸易", "国际经济与贸易", "英语", "俄语", "翻译")
CET6_KEYWORDS = ("英语六级", "CET6", "CET-6", "六级")
ELECTRICAL_MAJOR_KEYWORDS = ("电气工程", "电气", "自动化")
PLC_KEYWORDS = ("PLC", "plc", "可编程控制器")
