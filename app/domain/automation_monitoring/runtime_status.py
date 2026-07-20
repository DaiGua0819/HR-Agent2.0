"""Build six logical platform status snapshots from one-owner browser workers."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

from app.core.constants import Platform
from app.domain.automation_monitoring.models import AutomationRuntimeStatus


async def build_runtime_statuses(
    *,
    owner: str,
    browser: Any,
    agent_ready: bool,
    browser_ready: bool,
    cdp_ready: bool,
    agent_busy: bool,
    active_platform: str = "",
    paused: set[Platform] | None = None,
) -> list[AutomationRuntimeStatus]:
    timestamp = datetime.now(UTC).isoformat()
    pages = getattr(browser, "pages", {}) if browser is not None else {}
    backend = str(getattr(browser, "backend", "")) if browser is not None else ""
    results = []
    for platform in (Platform.BOSS, Platform.JOB51, Platform.ZHILIAN):
        page = pages.get(platform) if isinstance(pages, dict) else None
        url = str(getattr(page, "url", "") or "")
        title = await _page_title(page)
        text = f"{url} {title}".lower()
        security = _contains(text, "verify.html", "安全验证", "security", "captcha", "滑块")
        needs_login = _contains(text, "login", "signin", "passport", "请登录", "扫码登录")
        abnormal = _contains(text, "账号异常", "账号受限", "操作频繁", "账号冻结", "封禁")
        page_present = page is not None
        authenticated = bool(
            page_present
            and (backend == "fake" or not needs_login)
            and not security
            and not abnormal
        )
        is_paused = platform in (paused or set())
        if not agent_ready or not browser_ready or not cdp_ready:
            status, reason = "worker_offline", "worker_or_browser_not_ready"
        elif not page_present:
            status, reason = "page_missing", "platform_page_missing"
        elif security:
            status, reason = "security_verification", "security_verification_required"
        elif abnormal:
            status, reason = "account_abnormal", "account_abnormal"
        elif needs_login:
            status, reason = "needs_login", "login_required"
        elif is_paused:
            status, reason = "paused", "platform_paused"
        elif agent_busy and active_platform == platform.value:
            status, reason = "processing", ""
        else:
            status, reason = "ready", ""
        results.append(
            AutomationRuntimeStatus(
                targetKey=f"{owner}:{platform.value}",
                owner=owner,
                platform=platform.value,
                status=status,
                agentReady=agent_ready,
                browserReady=browser_ready,
                cdpReady=cdp_ready,
                agentBusy=bool(agent_busy and active_platform == platform.value),
                authenticated=authenticated,
                needsLogin=needs_login,
                securityVerification=security,
                accountAbnormal=abnormal,
                pagePresent=page_present,
                paused=is_paused,
                reason=reason,
                checkedAt=timestamp,
                receivedAt=timestamp,
            )
        )
    return results


async def _page_title(page: Any) -> str:
    if page is None:
        return ""
    title = getattr(page, "title", None)
    if not callable(title):
        return ""
    try:
        value = title()
        if inspect.isawaitable(value):
            value = await value
        return str(value or "")
    except Exception:
        return ""


def _contains(text: str, *markers: str) -> bool:
    return any(marker.lower() in text for marker in markers)
