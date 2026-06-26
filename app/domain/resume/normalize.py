"""简历字段标准化。

旧 `normalizers.js` 里已有布尔、分数和字符串数组规整；Phase 5 在此基础上补齐
简历库需要的学历、性别、专业、职位与手机号归一化。函数保持纯逻辑，供模型
validator、去重、筛选和打分共用。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.text import clean_text

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

EDUCATION_RANKS = {
    "初中": 1,
    "高中": 2,
    "中专": 2,
    "职高": 2,
    "大专": 3,
    "专科": 3,
    "本科": 4,
    "学士": 4,
    "硕士": 5,
    "研究生": 5,
    "博士": 6,
}


def normalize_boolean(value: Any, *, default: bool = False) -> bool:
    """移植旧 normalizeBoolean：常见真假文本转布尔。"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = clean_text(value).lower()
    if text in {"1", "true", "yes", "y", "是", "有", "开启"}:
        return True
    if text in {"0", "false", "no", "n", "否", "无", "关闭"}:
        return False
    return default


def normalize_score_value(value: Any) -> float | None:
    """移植旧 normalizeScoreValue：解析数字，失败返回 None。"""

    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_bounded_score(value: Any, *, minimum: float = 0, maximum: float = 100) -> float:
    """移植旧 normalizeBoundedScore：把分数限制在闭区间。"""

    score = normalize_score_value(value)
    if score is None:
        return minimum
    return max(minimum, min(maximum, score))


def normalize_string_array(value: Any) -> list[str]:
    """移植旧 normalizeStringArray：规整数组、逗号分隔文本和空值。"""

    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[,，;；\n]+", value)
    elif isinstance(value, list | tuple | set):
        raw_items = list(value)
    else:
        raw_items = [value]
    items = [clean_text(item) for item in raw_items]
    return [item for item in items if item]


def normalize_phone(value: Any) -> str | None:
    """提取中国大陆 11 位手机号；没有证据时返回 None。"""

    text = re.sub(r"[\s\-()（）]+", "", clean_text(value))
    match = _PHONE_RE.search(text)
    return match.group(0) if match else None


def normalize_gender(value: Any) -> str | None:
    """把性别规整为 `男` / `女`；未知返回 None。"""

    text = clean_text(value)
    if not text:
        return None
    if "女" in text:
        return "女"
    if "男" in text:
        return "男"
    return None


def normalize_education(value: Any) -> str | None:
    """把学历文本规整到主要等级，保留最高命中的学历。"""

    text = clean_text(value)
    if not text:
        return None
    matched = [name for name in EDUCATION_RANKS if name in text]
    if not matched:
        return text
    best = max(matched, key=lambda name: EDUCATION_RANKS[name])
    if best == "研究生":
        return "硕士"
    if best == "专科":
        return "大专"
    return best


def education_rank(value: Any) -> int:
    """返回学历等级数字，未知为 0。"""

    normalized = normalize_education(value)
    return EDUCATION_RANKS.get(normalized or "", 0)


def normalize_major(value: Any) -> str | None:
    """专业字段只做空白规整，避免误改原始语义。"""

    text = clean_text(value)
    return text or None


def normalize_position(value: Any) -> str | None:
    """职位/岗位名称规整。"""

    text = clean_text(value)
    return text or None


def normalize_resume_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """清洗旧 payload，并补齐标准字段，原始字段保持不删。"""

    data = dict(payload)
    phone = normalize_phone(
        data.get("phone")
        or data.get("mobile")
        or data.get("phoneNumber")
        or data.get("contact")
        or data.get("rawText")
        or data.get("text")
    )
    if phone:
        data["phone"] = phone
        data["phone_key"] = phone

    education = normalize_education(data.get("education") or data.get("degree"))
    if education:
        data["education"] = education

    gender = normalize_gender(data.get("gender") or data.get("sex"))
    if gender:
        data["gender"] = gender

    major = normalize_major(data.get("major") or data.get("profession"))
    if major:
        data["major"] = major

    position = normalize_position(
        data.get("applied_position") or data.get("position") or data.get("jobType")
    )
    if position:
        data["applied_position"] = position

    name = clean_text(data.get("name") or data.get("candidateName"))
    if name:
        data["name"] = name
    return data
