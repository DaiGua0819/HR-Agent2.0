"""51job 人才望远镜模式判断与切换。"""

from __future__ import annotations

from app.browser.base import BrowserPage
from app.platforms.job51 import selectors


async def recommend_mode_state(page: BrowserPage) -> dict[str, object]:
    """读取 51job 推荐页当前是传统人才望远镜还是 AI 淘金。"""

    raw = await _safe_eval_dict(page, "job51.recommend_mode_state")
    if raw:
        return raw
    active = await page.query(selectors.RECOMMEND_MODE_SWITCH_ACTIVE)
    cards = await page.query_all(selectors.RECOMMEND_CARD)
    return {"traditional": bool(cards and active is None), "aiGold": active is not None}


async def click_recommend_mode_switch(page: BrowserPage) -> dict[str, object]:
    """点击外层 `.ai-mode-switch`，不点内部 SVG。"""

    clicked = await page.click(selectors.RECOMMEND_MODE_SWITCH)
    if clicked:
        await page.eval_js("job51.set_recommend_traditional_mode", True)
    return {"clicked": clicked}


async def ensure_recommend_traditional_mode(page: BrowserPage) -> dict[str, object]:
    """确保推荐页处于传统人才望远镜模式。"""

    before = await recommend_mode_state(page)
    if before.get("traditional"):
        return {"ok": True, "switched": False, "before": before}
    click = await click_recommend_mode_switch(page)
    after = await recommend_mode_state(page)
    return {
        "ok": bool(after.get("traditional")),
        "switched": bool(click.get("clicked")),
        "before": before,
        "after": after,
    }


async def _safe_eval_dict(page: BrowserPage, script: str) -> dict[str, object]:
    try:
        value = await page.eval_js(script)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
