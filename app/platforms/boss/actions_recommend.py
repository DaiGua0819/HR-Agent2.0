"""BOSS 推荐牛人动作。"""

from __future__ import annotations

from app.agent.proactive.thresholds import evaluate_proactive_threshold
from app.browser.base import BrowserPage
from app.browser.reliable_actions import reliable_click_element
from app.platforms.boss import selectors


async def open_recommend_page(page: BrowserPage) -> None:
    """打开 BOSS 推荐牛人页。"""

    await page.goto(selectors.RECOMMEND_URL)


async def proactive_greet(
    page: BrowserPage,
    *,
    target_position: str,
    dry_run: bool = False,
) -> dict[str, object]:
    """按主动联系门槛处理 BOSS 推荐牛人候选人。"""

    await open_recommend_page(page)
    await _ensure_recommend_position(page, target_position)
    cards = await _safe_eval_list(page, "boss.recommend_cards")
    greeted = 0
    skipped: list[dict[str, object]] = []
    matched: list[dict[str, object]] = []
    for index, card in enumerate(cards):
        if card.get("similar") or card.get("alreadyGreeted"):
            skipped.append({"index": index, "reason": "similar_or_already_greeted"})
            continue
        await page.eval_js("boss.open_recommend_card", index)
        resume = await _safe_eval_dict(page, "boss.read_recommend_resume_dialog")
        evidence_text = "\n".join(
            str(item or "") for item in (card.get("text"), resume.get("text"))
        )
        decision = evaluate_proactive_threshold(evidence_text, target_position)
        if not decision.passed:
            skipped.append({"index": index, "reason": decision.reason})
            await page.eval_js("boss.close_recommend_resume_dialog")
            continue
        matched.append({"index": index, "reason": decision.reason})
        if not dry_run:
            button = await page.query(selectors.RECOMMEND_GREET_BUTTON)
            if button is None:
                skipped.append({"index": index, "reason": "greet_button_missing"})
                await page.eval_js("boss.close_recommend_resume_dialog")
                continue
            click = await reliable_click_element(page, button, label="BOSS推荐打招呼")
            if click.get("ok"):
                greeted += 1
            else:
                skipped.append({"index": index, "reason": "greet_click_failed", "click": click})
        await page.eval_js("boss.close_recommend_resume_dialog")
    return {"greeted": greeted, "matched": matched, "skipped": skipped, "dryRun": dry_run}


async def _ensure_recommend_position(page: BrowserPage, target_position: str) -> None:
    summary = await _safe_eval_dict(page, "boss.recommend_summary")
    current = str(summary.get("selectedPosition") or "")
    if target_position and _compact(current) != _compact(target_position):
        await page.eval_js("boss.select_recommend_position", target_position)


async def _safe_eval_dict(
    page: BrowserPage, script: str, arg: object | None = None
) -> dict[str, object]:
    try:
        value = await page.eval_js(script, arg)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


async def _safe_eval_list(page: BrowserPage, script: str) -> list[dict[str, object]]:
    try:
        value = await page.eval_js(script)
    except Exception:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: str) -> str:
    return "".join(str(value or "").split())
