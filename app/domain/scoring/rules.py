"""评分规则加载与内存更新。

本阶段规则默认来自内置 JD profiles；采纳/拒绝建议只改变内存快照，不写真实 DB 或配置文件。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.domain.scoring.engine import (
    POSITION_SCORING_VERSION,
    POSITION_SCORING_VERSION_DESCRIPTION,
    POSITION_SCORING_VERSION_NAME,
)
from app.domain.scoring.jd_profiles import get_jd_profile, list_jd_profiles

_RULE_OVERRIDES: dict[str, dict[str, Any]] = {}


def load_scoring_rules(job_type: str) -> dict[str, Any]:
    """加载指定岗位的评分规则。"""

    profile = get_jd_profile(job_type)
    data = asdict(profile)
    data.update(_RULE_OVERRIDES.get(profile.name, {}))
    return {
        "version": POSITION_SCORING_VERSION,
        "versionName": POSITION_SCORING_VERSION_NAME,
        "description": POSITION_SCORING_VERSION_DESCRIPTION,
        "profile": data,
    }


def list_scoring_rules() -> dict[str, Any]:
    """返回全部岗位评分规则。"""

    return {
        "version": POSITION_SCORING_VERSION,
        "profiles": [asdict(profile) for profile in list_jd_profiles()],
    }


def update_rule_override(job_type: str, patch: dict[str, Any]) -> dict[str, Any]:
    """更新内存规则覆盖；真实配置写入留到最后阶段。"""

    profile = get_jd_profile(job_type)
    current = _RULE_OVERRIDES.setdefault(profile.name, {})
    current.update(patch)
    return load_scoring_rules(profile.name)
