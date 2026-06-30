"""Resolve and enforce resume visibility scopes for authenticated users."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.core.text import clean_text
from app.domain.resume.models import Resume
from app.domain.resume_review.models import LocalUser
from app.settings import PROJECT_ROOT

ALL_JOB_TYPES = ["*"]
SCOPE_CONFIG_PATH = PROJECT_ROOT / "config" / "resume_scopes.yaml"


def resume_scope_for_user(
    user: LocalUser,
    *,
    feishu: dict[str, object] | None = None,
    include_unlinked: bool,
) -> dict[str, object]:
    """Build the resume scope exposed to the frontend and enforced by APIs."""

    if _is_admin(user):
        return {
            "owners": user.owners,
            "platforms": user.platforms,
            "jobGroups": ["all"],
            "jobTypes": ALL_JOB_TYPES,
            "includeUnlinked": True,
        }
    configured = _configured_member_scope(user, feishu=feishu)
    return {
        "owners": user.owners,
        "platforms": user.platforms,
        "jobGroups": configured["jobGroups"],
        "jobTypes": configured["jobTypes"],
        "includeUnlinked": include_unlinked,
    }


def resume_visible_to_payload(resume: Resume, payload: dict[str, object]) -> bool:
    """Return whether a resume can be read by the authenticated session payload."""

    if _payload_is_admin(payload):
        return True
    scope = payload.get("resumeScope")
    if not isinstance(scope, dict):
        return False
    return job_type_allowed(_resume_job_type(resume), scope.get("jobTypes"))


def job_type_allowed(job_type: str, allowed_values: object) -> bool:
    """Match a resume job against configured exact names and aliases."""

    allowed = [clean_text(item) for item in _list(allowed_values) if clean_text(item)]
    if "*" in allowed:
        return True
    job = clean_text(job_type)
    if not job:
        return False
    return any(item == job or item in job or job in item for item in allowed)


def allowed_job_types(payload: dict[str, object]) -> list[str]:
    """Return allowed job types from an auth payload."""

    if _payload_is_admin(payload):
        return ALL_JOB_TYPES
    scope = payload.get("resumeScope")
    if not isinstance(scope, dict):
        return []
    return [clean_text(item) for item in _list(scope.get("jobTypes")) if clean_text(item)]


def _configured_member_scope(
    user: LocalUser,
    *,
    feishu: dict[str, object] | None,
) -> dict[str, list[str]]:
    config = _scope_config()
    groups = config.get("jobGroups") if isinstance(config.get("jobGroups"), dict) else {}
    matched_group_keys: list[str] = []
    matched_job_types: list[str] = []
    for rule in _list(config.get("members")):
        if not isinstance(rule, dict) or not _matches_member_rule(user, rule, feishu=feishu):
            continue
        for group_key in _list(rule.get("jobGroups")):
            key = clean_text(group_key)
            if key:
                matched_group_keys.append(key)
                group = groups.get(key) if isinstance(groups, dict) else {}
                if isinstance(group, dict):
                    matched_job_types.extend(_list(group.get("jobTypes")))
        matched_job_types.extend(_list(rule.get("jobTypes")))
    return {
        "jobGroups": _unique(matched_group_keys),
        "jobTypes": _unique([clean_text(item) for item in matched_job_types]),
    }


def _matches_member_rule(
    user: LocalUser,
    rule: dict[str, object],
    *,
    feishu: dict[str, object] | None,
) -> bool:
    names = {clean_text(item) for item in _list(rule.get("names"))}
    open_ids = {clean_text(item) for item in _list(rule.get("openIds"))}
    user_ids = {clean_text(item) for item in _list(rule.get("userIds"))}
    union_ids = {clean_text(item) for item in _list(rule.get("unionIds"))}
    feishu = feishu or {}
    return (
        clean_text(user.name) in names
        or clean_text(feishu.get("openId")) in open_ids
        or clean_text(feishu.get("userId")) in user_ids
        or clean_text(feishu.get("unionId")) in union_ids
    )


@lru_cache(maxsize=1)
def _scope_config() -> dict[str, Any]:
    if not SCOPE_CONFIG_PATH.exists():
        return {}
    with SCOPE_CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data if isinstance(data, dict) else {}


def _resume_job_type(resume: Resume) -> str:
    return resume.job_type or resume.applied_position or ""


def _payload_is_admin(payload: dict[str, object]) -> bool:
    return bool({"super_admin", "admin"} & set(_list(payload.get("roles"))))


def _is_admin(user: LocalUser) -> bool:
    return bool({"super_admin", "admin"} & set(user.roles))


def _list(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _unique(values: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in _list(values):
        text = clean_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
