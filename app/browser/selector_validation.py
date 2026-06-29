"""真实页面选择器只读验证。

验证器只做导航、查询和可选的安全入口导航，不点击发送、求简历、下载、打招呼等
业务副作用按钮。输出用于发现 Phase 1-3 迁移选择器在真实页面上的漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.browser.base import BrowserPage
from app.browser.reliable_actions import reliable_click
from app.core.constants import Platform
from app.platforms.boss import selectors as boss
from app.platforms.job51 import selectors as job51
from app.platforms.zhilian import selectors as zhilian

SelectorStatus = Literal["OK", "缺失", "多义"]


@dataclass(frozen=True)
class SelectorSpec:
    """一个需要验证的选择器。"""

    name: str
    selector: str
    source: str
    section: str = "chat"
    allow_many: bool = False


@dataclass(frozen=True)
class SelectorResult:
    """单个选择器验证结果。"""

    platform: Platform
    name: str
    selector: str
    status: SelectorStatus
    count: int
    source: str
    section: str
    sample: str = ""


@dataclass(frozen=True)
class LoginDetection:
    """平台页面登录状态检测结果。"""

    platform: Platform
    logged_out: bool
    reason: str = ""
    url: str = ""
    sample: str = ""


async def detect_login_page(page: BrowserPage, platform: Platform) -> LoginDetection:
    """判断当前页面是否明显处于未登录状态。"""

    url = (await _current_url(page)).lower()
    body = (await _safe_body_text(page)).strip()
    body_lower = body.lower()
    if _looks_like_logged_in_chat(platform, url, body):
        return LoginDetection(platform=platform, logged_out=False, url=url, sample=body[:120])
    markers = _login_url_markers(platform)
    if any(marker in url for marker in markers):
        return LoginDetection(
            platform=platform,
            logged_out=True,
            reason="url_login_marker",
            url=url,
            sample=body[:120],
        )
    login_selector = _login_selector(platform)
    selector_hit = bool(login_selector and await page.query_all(login_selector))
    text_hit = any(term in body_lower for term in _LOGIN_TEXT_TERMS)
    if selector_hit and text_hit:
        return LoginDetection(
            platform=platform,
            logged_out=True,
            reason="login_selector_and_text",
            url=url,
            sample=body[:120],
        )
    return LoginDetection(platform=platform, logged_out=False, url=url, sample=body[:120])


async def validate_platform_selectors(
    page: BrowserPage,
    platform: Platform,
    *,
    follow_safe_navigation: bool = True,
) -> list[SelectorResult]:
    """验证某个平台的关键选择器。"""

    results: list[SelectorResult] = []
    specs = _specs_for(platform)
    current_section = ""
    for spec in specs:
        if spec.section != current_section:
            await _prepare_section(page, platform, spec.section, follow_safe_navigation)
            current_section = spec.section
        results.append(await _validate_one(page, platform, spec))
    return results


async def _validate_one(
    page: BrowserPage,
    platform: Platform,
    spec: SelectorSpec,
) -> SelectorResult:
    elements = await page.query_all(spec.selector)
    count = len(elements)
    if count == 0:
        status: SelectorStatus = "缺失"
    elif count > 1 and not spec.allow_many:
        status = "多义"
    else:
        status = "OK"
    sample = ""
    if elements:
        try:
            sample = (await elements[0].text()).strip().replace("\n", " ")[:80]
        except Exception:
            sample = ""
    return SelectorResult(
        platform=platform,
        name=spec.name,
        selector=spec.selector,
        status=status,
        count=count,
        source=spec.source,
        section=spec.section,
        sample=sample,
    )


async def _prepare_section(
    page: BrowserPage,
    platform: Platform,
    section: str,
    follow_safe_navigation: bool,
) -> None:
    if platform == Platform.BOSS:
        await page.goto(boss.RECOMMEND_URL if section == "recommend" else boss.CHAT_URL)
    elif platform == Platform.ZHILIAN:
        await page.goto(zhilian.RECOMMEND_URL if section == "recommend" else zhilian.CHAT_URL)
    elif follow_safe_navigation and platform == Platform.JOB51:
        if section == "chat":
            await reliable_click(page, job51.CHAT_ENTRY, label="51job选择器验证进入聊天")
        elif section == "recommend":
            await reliable_click(page, job51.RECOMMEND_ENTRY, label="51job选择器验证进入推荐")


def _specs_for(platform: Platform) -> list[SelectorSpec]:
    if platform == Platform.BOSS:
        return _boss_specs()
    if platform == Platform.JOB51:
        return _job51_specs()
    if platform == Platform.ZHILIAN:
        return _zhilian_specs()
    raise ValueError(f"不支持的平台: {platform}")


async def _current_url(page: BrowserPage) -> str:
    try:
        return str(page.url)  # type: ignore[attr-defined]
    except AttributeError:
        pass
    try:
        value = await page.eval_js("location.href")
        return str(value or "")
    except Exception:
        return ""


async def _safe_body_text(page: BrowserPage) -> str:
    try:
        return await page.text()
    except Exception:
        return ""


def _login_url_markers(platform: Platform) -> tuple[str, ...]:
    common = ("login", "passport", "signin", "sso")
    if platform == Platform.BOSS:
        return (*common, "login.zhipin", "account.zhipin", "ka.zhipin")
    if platform == Platform.JOB51:
        return (*common, "login.51job", "passport.51job", "ehirelogin")
    if platform == Platform.ZHILIAN:
        return (*common, "passport.zhaopin", "login.zhaopin", "/s/login")
    return common


def _login_selector(platform: Platform) -> str:
    if platform == Platform.BOSS:
        return ".login-container,.login-box,.login-form,.scan-login,.qrcode-box"
    if platform == Platform.JOB51:
        return ".login-container,.login-box,.login-form"
    if platform == Platform.ZHILIAN:
        return ".login-container,.login-box,.login-form,.qrcode-box,.passport-login"
    return ".login-container,.login-box,.login-form"


def _looks_like_logged_in_chat(platform: Platform, url: str, body: str) -> bool:
    if platform == Platform.JOB51:
        return "ehire.51job.com/revision/chat" in url and all(
            term in body for term in ("人才沟通", "全部职位", "未读")
        )
    return False


_LOGIN_TEXT_TERMS = (
    "登录",
    "扫码登录",
    "二维码",
    "密码登录",
    "验证码登录",
    "手机登录",
    "请先登录",
    "未登录",
    "sign in",
    "log in",
)


def _boss_specs() -> list[SelectorSpec]:
    source = "boss-recruiter-automation/SKILL.md + recruiter_* 旧方法"
    return [
        SelectorSpec("未读筛选", boss.UNREAD_FILTER, source, allow_many=True),
        SelectorSpec("会话列表", boss.SESSION_ITEM, source, allow_many=True),
        SelectorSpec("消息输入框", boss.CHAT_INPUT, source, allow_many=True),
        SelectorSpec("发送按钮", boss.SEND_BUTTON, source, allow_many=True),
        SelectorSpec("己方消息", boss.MINE_MESSAGE, source, allow_many=True),
        SelectorSpec("求简历按钮", boss.REQUEST_RESUME_BUTTON, source, allow_many=True),
        SelectorSpec("岗位下拉", boss.POSITION_FILTER, source, allow_many=True),
        SelectorSpec("推荐岗位", boss.RECOMMEND_POSITION_LABEL, source, "recommend"),
        SelectorSpec("推荐候选卡", boss.RECOMMEND_CARD, source, "recommend", True),
        SelectorSpec("在线简历弹层", boss.RECOMMEND_DIALOG, source, "recommend"),
        SelectorSpec("打招呼按钮", boss.RECOMMEND_GREET_BUTTON, source, "recommend"),
        SelectorSpec("相似推荐块", boss.RECOMMEND_SIMILAR_BLOCK, source, "recommend", True),
    ]


def _job51_specs() -> list[SelectorSpec]:
    source = "51job-recruiter-automation/SKILL.md + job51_* 旧方法"
    return [
        SelectorSpec("人才沟通入口", job51.CHAT_ENTRY, source),
        SelectorSpec("未读筛选", job51.UNREAD_FILTER, source, allow_many=True),
        SelectorSpec("岗位菜单", job51.POSITION_MENU, source, allow_many=True),
        SelectorSpec("会话列表", job51.THREAD_ITEM, source, allow_many=True),
        SelectorSpec("消息输入框", job51.CHAT_INPUT, source),
        SelectorSpec("发送按钮", job51.SEND_BUTTON, source),
        SelectorSpec("己方消息", job51.MINE_MESSAGE, source, allow_many=True),
        SelectorSpec("求简历按钮", job51.REQUEST_RESUME_BUTTON, source, allow_many=True),
        SelectorSpec("附件链接", job51.ATTACHMENT_ENTRY, source, allow_many=True),
        SelectorSpec("人才望远镜入口", job51.RECOMMEND_ENTRY, source, "recommend"),
        SelectorSpec("推荐候选卡", job51.RECOMMEND_CARD, source, "recommend", True),
        SelectorSpec("立即Hi聊按钮", job51.RECOMMEND_GREET_BUTTON, source, "recommend", True),
        SelectorSpec("推荐模式开关", job51.RECOMMEND_MODE_SWITCH, source, "recommend", True),
    ]


def _zhilian_specs() -> list[SelectorSpec]:
    source = "zhilian-recruiter-automation/SKILL.md + zhilian_* 旧方法"
    return [
        SelectorSpec("未读筛选", zhilian.UNREAD_FILTER, source, allow_many=True),
        SelectorSpec("岗位筛选", zhilian.POSITION_FILTER, source, allow_many=True),
        SelectorSpec("会话列表", zhilian.SESSION_ITEM, source, allow_many=True),
        SelectorSpec("聊天就绪", zhilian.CHAT_READY, source, allow_many=True),
        SelectorSpec("消息输入框", zhilian.CHAT_INPUT, source, allow_many=True),
        SelectorSpec("消息项", zhilian.MESSAGE_ITEM, source, allow_many=True),
        SelectorSpec("己方消息", zhilian.MINE_MESSAGE, source, allow_many=True),
        SelectorSpec("要附件按钮", zhilian.REQUEST_RESUME_BUTTON, source, allow_many=True),
        SelectorSpec("推荐候选卡", zhilian.RECOMMEND_CARD, source, "recommend", True),
        SelectorSpec("推荐弹窗", zhilian.RECOMMEND_MODAL, source, "recommend"),
        SelectorSpec("弹窗关闭", zhilian.RECOMMEND_MODAL_CLOSE, source, "recommend", True),
        SelectorSpec("详情左栏", zhilian.RECOMMEND_MODAL_LEFT, source, "recommend"),
        SelectorSpec("详情右栏", zhilian.RECOMMEND_MODAL_RIGHT, source, "recommend"),
    ]
