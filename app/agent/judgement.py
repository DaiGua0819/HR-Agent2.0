"""结构化 LLM 判断与规则回退。

模型只能给出 `not_asked / waiting / accept / reject / unclear`。模型失败、超时或
返回非法值时，使用关键词规则兜底。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ALLOWED_STATUSES = {"not_asked", "waiting", "accept", "reject", "unclear"}
ACCEPT_TERMS = ("接受", "可以", "能接受", "没问题", "符合", "愿意", "是的", "有", "本科")
ACCEPT_ACK_PREFIXES = ("好的", "好呀", "好啊")
HESITATION_TERMS = ("再考虑", "考虑一下", "想一下", "想想", "稍后", "再说")
REJECT_TERMS = (
    "不接受",
    "不能",
    "接受不了",
    "无法接受",
    "没法接受",
    "不太能接受",
    "不怎么能接受",
    "不愿意接受",
    "不行",
    "没有",
    "不是",
    "不考虑",
    "拒绝",
    "暂时不",
)


@dataclass(frozen=True)
class JudgementResult:
    """结构化判断结果。"""

    status: str
    evidence: str
    source: str = "rule_fallback"


async def judge_candidate_reply(
    reply_text: str,
    *,
    question: str = "",
    pass_rule: str = "",
    fail_rule: str = "",
    llm: Any | None = None,
) -> JudgementResult:
    """判断候选人回复是否满足筛选规则。"""

    model_status = await _try_model_judge(reply_text, question, pass_rule, fail_rule, llm)
    if model_status in ALLOWED_STATUSES:
        return JudgementResult(status=model_status, evidence=reply_text, source="llm")
    return _rule_judge(reply_text)


async def _try_model_judge(
    reply_text: str,
    question: str,
    pass_rule: str,
    fail_rule: str,
    llm: Any | None,
) -> str | None:
    if llm is None:
        return None
    prompt = {
        "reply": reply_text,
        "question": question,
        "passRule": pass_rule,
        "failRule": fail_rule,
        "allowed": sorted(ALLOWED_STATUSES),
    }
    try:
        if hasattr(llm, "judge"):
            value = llm.judge(prompt)
            if hasattr(value, "__await__"):
                value = await value
        elif callable(llm):
            value = llm(prompt)
            if hasattr(value, "__await__"):
                value = await value
        else:
            return None
    except Exception:
        return None
    if isinstance(value, dict):
        value = value.get("status")
    return str(value).strip() if value is not None else None


def _rule_judge(reply_text: str) -> JudgementResult:
    text = reply_text.strip()
    if not text:
        return JudgementResult(status="waiting", evidence="", source="rule_fallback")
    if any(term in text for term in ("没问题", "没有问题")):
        return JudgementResult(status="accept", evidence=text, source="rule_fallback")
    explicit_reject_terms = tuple(
        term for term in REJECT_TERMS if term not in {"没有", "不是"}
    )
    if any(term in text for term in explicit_reject_terms):
        return JudgementResult(status="reject", evidence=text, source="rule_fallback")
    if text.startswith(ACCEPT_ACK_PREFIXES) and not any(
        term in text for term in HESITATION_TERMS
    ):
        return JudgementResult(status="accept", evidence=text, source="rule_fallback")
    has_positive = any(term in text for term in ACCEPT_TERMS if term != "有") or bool(
        re.search(r"(?:^|我|，|,|。|；|;)有(?:过|相关|经验|接触|了解|做)", text)
    )
    has_generic_negative = any(term in text for term in ("没有", "不是"))
    if has_generic_negative and has_positive:
        return JudgementResult(status="unclear", evidence=text, source="rule_fallback")
    if has_generic_negative:
        return JudgementResult(status="reject", evidence=text, source="rule_fallback")
    if has_positive:
        return JudgementResult(status="accept", evidence=text, source="rule_fallback")
    return JudgementResult(status="unclear", evidence=text, source="rule_fallback")
