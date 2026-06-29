"""Role and UI access mapping for authenticated users."""

from __future__ import annotations

from app.auth.feishu_oauth import FeishuProfile
from app.domain.resume_review.models import LocalUser
from app.settings import load_settings

ADMIN_VIEWS = ["dashboard", "resumes", "queue", "interviews", "automation", "rules"]
MEMBER_VIEWS = ["resumes"]
ADMIN_OWNERS = ["和新红", "宋峰峰"]
ALL_PLATFORMS = ["boss", "job51", "zhilian"]


def user_payload(user: LocalUser, *, feishu: dict[str, object] | None = None) -> dict[str, object]:
    """Convert a domain user into the frontend auth payload."""

    is_admin = _is_admin_user(user)
    payload: dict[str, object] = {
        "user": {
            "id": user.id,
            "name": user.name,
            "avatarUrl": (feishu or {}).get("avatarUrl", ""),
        },
        "roles": user.roles,
        "permissions": user.permissions,
        "resumeScope": {
            "owners": user.owners,
            "platforms": user.platforms,
            "includeUnlinked": is_admin,
        },
        "uiAccess": ui_access(user),
    }
    if feishu:
        payload["authProvider"] = "feishu"
        payload["feishu"] = feishu
    return payload


def ui_access(user: LocalUser) -> dict[str, object]:
    """Return the allowed frontend views and actions for a user."""

    is_admin = _is_admin_user(user)
    actions = ["resume:view", "resume:review"]
    if is_admin:
        actions.extend(["interview:invite", "automation:run"])
    return {
        "defaultView": "dashboard" if is_admin else "resumes",
        "views": ADMIN_VIEWS if is_admin else MEMBER_VIEWS,
        "actions": actions,
    }


def feishu_payload(profile: FeishuProfile) -> dict[str, object]:
    """Build a session payload from a verified Feishu profile."""

    match = _admin_match_source(profile)
    if match:
        user = LocalUser(
            id=f"feishu:{profile.open_id}",
            name=profile.name,
            roles=["super_admin"],
            permissions=[
                "resumes:read",
                "resumes:write",
                "resumes:review",
                "resumes:assign",
                "automation:run",
                "monitoring:read",
                "interview:read",
            ],
            owners=ADMIN_OWNERS,
            platforms=ALL_PLATFORMS,
        )
    else:
        user = LocalUser(
            id=f"feishu:{profile.open_id}",
            name=profile.name,
            roles=["member"],
            permissions=["resumes:read", "resumes:review"],
            owners=[profile.name],
            platforms=ALL_PLATFORMS,
        )
    return user_payload(user, feishu=_feishu_diagnostics(profile, match))


def validate_company(profile: FeishuProfile) -> None:
    """Reject Feishu users outside the configured tenant allow-list."""

    settings = load_settings()
    allowed = set(settings.feishu.allowed_tenant_keys)
    if allowed and profile.tenant_key not in allowed:
        raise PermissionError("company_not_allowed")


def _admin_match_source(profile: FeishuProfile) -> str:
    config = load_settings().feishu
    admin_open_ids = set(config.admin_open_ids)
    if profile.open_id in admin_open_ids:
        return "open_id"
    if not admin_open_ids and profile.name in set(config.bootstrap_admin_names):
        return "bootstrap_name"
    return ""


def _feishu_diagnostics(profile: FeishuProfile, admin_match: str) -> dict[str, object]:
    return {
        "openId": profile.open_id,
        "unionId": profile.union_id,
        "userId": profile.user_id,
        "tenantKey": profile.tenant_key,
        "email": profile.email,
        "adminMatchedBy": admin_match or "none",
        "avatarUrl": profile.avatar_url,
    }


def _is_admin_user(user: LocalUser) -> bool:
    return bool({"super_admin", "admin"} & set(user.roles))
