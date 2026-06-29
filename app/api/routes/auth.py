"""本地控制面认证接口。

当前阶段使用本地 mock 用户，真实飞书 OAuth 接入时替换这里的用户解析即可。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.domain.resume_review.models import LocalUser

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOCAL_USER = LocalUser(
    id="local-admin",
    name="本地管理员",
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
    owners=["和新红", "宋峰峰"],
    platforms=["boss", "job51", "zhilian"],
)


@router.get("/me")
async def me() -> dict[str, object]:
    """返回本地开发阶段当前用户。"""

    return {
        "user": {
            "id": LOCAL_USER.id,
            "name": LOCAL_USER.name,
            "avatarUrl": "",
        },
        "roles": LOCAL_USER.roles,
        "permissions": LOCAL_USER.permissions,
        "resumeScope": {
            "owners": LOCAL_USER.owners,
            "platforms": LOCAL_USER.platforms,
            "includeUnlinked": True,
        },
    }


@router.post("/logout")
async def logout() -> dict[str, str]:
    """本地 mock 登出。"""

    return {"status": "ok"}
