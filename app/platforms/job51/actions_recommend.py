"""51job 人才望远镜主动联系动作。"""

from __future__ import annotations

from app.agent.proactive.thresholds import evaluate_proactive_threshold
from app.browser.base import BrowserPage
from app.platforms.job51 import selectors
from app.platforms.job51.actions_mode import ensure_recommend_traditional_mode


async def open_recommend_page(page: BrowserPage) -> None:
    """通过人才望远镜入口进入推荐页，不直接打开 URL。"""

    clicked = await page.click(selectors.RECOMMEND_ENTRY)
    if not clicked:
        raise RuntimeError("job51_recommend_entry_missing")


async def select_recommend_position(page: BrowserPage, target_position: str) -> dict[str, object]:
    """选择 51job 人才望远镜目标岗位。"""

    result = await page.eval_js("job51.select_recommend_position", target_position)
    if isinstance(result, dict):
        return result
    return {
        "selected": bool(await page.click(selectors.RECOMMEND_POSITION_TAB)),
        "label": target_position,
    }


async def collect_recommend_candidate_cards(page: BrowserPage) -> list[dict[str, object]]:
    """采集推荐候选人卡片。"""

    value = await page.eval_js("job51.recommend_cards")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


async def proactive_greet(
    page: BrowserPage,
    *,
    target_position: str,
    dry_run: bool = False,
) -> dict[str, object]:
    """复用共享门槛引擎筛选 51job 推荐卡片并点击立即 Hi 聊。"""

    await open_recommend_page(page)
    mode = await ensure_recommend_traditional_mode(page)
    if not mode.get("ok"):
        return {"greeted": 0, "blocked": True, "reason": "traditional_mode_not_verified"}
    await select_recommend_position(page, target_position)
    greeted = 0
    matched: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for index, card in enumerate(await collect_recommend_candidate_cards(page)):
        if card.get("viewed"):
            skipped.append({"index": index, "reason": "already_viewed_badge"})
            continue
        text = str(card.get("text") or "")
        detail = await probe_recommend_candidate_detail(page, index)
        evidence = "\n".join([text, str(detail.get("text") or "")])
        decision = evaluate_proactive_threshold(evidence, target_position)
        if not decision.passed:
            skipped.append({"index": index, "reason": decision.reason})
            continue
        matched.append({"index": index, "reason": decision.reason})
        if not dry_run:
            await page.eval_js("job51.select_recommend_card", index)
            button = await page.query(selectors.RECOMMEND_GREET_BUTTON)
            if button is None:
                skipped.append({"index": index, "reason": "greet_button_missing"})
                continue
            await button.click()
            greeted += 1
    return {"greeted": greeted, "matched": matched, "skipped": skipped, "dryRun": dry_run}


async def probe_recommend_candidate_detail(page: BrowserPage, dom_index: int) -> dict[str, object]:
    """打开并读取候选人详情证据；Phase 3 由 FakePage 模拟。"""

    value = await page.eval_js("job51.probe_recommend_candidate_detail", dom_index)
    return value if isinstance(value, dict) else {}


async def scroll_recommend_cards(page: BrowserPage) -> dict[str, object]:
    """推荐卡片小幅滚动边界。"""

    value = await page.eval_js("job51.scroll_recommend_cards")
    return value if isinstance(value, dict) else {"scrolled": False}


def extract_recommend_candidate_name(text: str) -> str:
    """从 51job 推荐卡片文本中提取候选人名。"""

    first = str(text or "").strip().splitlines()[0:1]
    return first[0].strip() if first else ""
