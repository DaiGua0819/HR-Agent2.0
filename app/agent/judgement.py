"""结构化 LLM 判断与规则回退。

模型只能给出 `not_asked / waiting / accept / reject / unclear`。模型失败、超时或
返回非法值时，使用关键词规则兜底。
"""

from __future__ import annotations

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
    if any(term in text for term in REJECT_TERMS):
        return JudgementResult(status="reject", evidence=text, source="rule_fallback")
    if text.startswith(ACCEPT_ACK_PREFIXES) and not any(
        term in text for term in HESITATION_TERMS
    ):
        return JudgementResult(status="accept", evidence=text, source="rule_fallback")
    if any(term in text for term in ACCEPT_TERMS):
        return JudgementResult(status="accept", evidence=text, source="rule_fallback")
    return JudgementResult(status="unclear", evidence=text, source="rule_fallback")
