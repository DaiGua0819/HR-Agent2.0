"""BOSS 单次处理脚本。

脚本连接已登录的真实 CloakBrowser CDP，只读取 BOSS 会话并让共享
ConversationRunner 判断动作。默认 dry-run，只记录意图；显式 --live --confirm-live
才允许真实发送消息或求简历，且仍会先执行登录态和选择器健康检查。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any
from urllib.request import urlopen

from app.agent.persistence import build_persistence_from_settings
from app.agent.runner import ConversationRunner
from app.browser.cloak import cdp_url_for
from app.browser.manager import BrowserManager
from app.browser.reliable_actions import reliable_click_element
from app.browser.selector_validation import detect_login_page
from app.core.constants import Platform
from app.platforms.boss import actions as boss_actions
from app.platforms.boss import selectors
from app.platforms.boss.adapter import BossAdapter
from app.settings import load_settings

from boss_once_support import print_summary, reliable_actions_since
from boss_targeting import process_boss_targets, select_all_filter


def parse_args() -> argparse.Namespace:
    """解析启动参数。"""

    parser = argparse.ArgumentParser(description="BOSS 真实浏览器处理一次，默认 dry-run")
    parser.add_argument("--owner", default="宋峰峰", help="负责人，需与 accounts.yaml 一致")
    parser.add_argument("--platform", default="boss", choices=["boss"])
    parser.add_argument("--limit", type=int, default=3, help="最多处理几个会话")
    parser.add_argument("--live", action="store_true", help="真实执行发送/求简历动作")
    parser.add_argument("--confirm-live", action="store_true", help="确认本次允许真实执行动作")
    parser.add_argument(
        "--conversation-id",
        action="append",
        default=[],
        help="指定 BOSS 会话 id，可重复传；用于处理已读但已确认的目标会话",
    )
    return parser.parse_args()


async def main_async() -> None:
    """主流程：自检全部通过后再处理。"""

    args = parse_args()
    live = _resolve_mode(args)
    worker = _worker_for_owner(args.owner)
    cdp_url = cdp_url_for(worker.cdp_port)
    os.environ["HR_AGENT_BROWSER_BACKEND"] = "cloak"
    mode_name = "LIVE" if live else "dry-run"
    _print_step(f"1/4 {mode_name} 守卫通过")

    version = _probe_cdp(cdp_url)
    _print_step(f"2/4 CloakBrowser CDP 连通: {version.get('Browser', '')}")

    manager = BrowserManager(owner=args.owner, cdp_port=worker.cdp_port, backend="cloak")
    try:
        await manager.start()
        page = manager.page_for(args.owner, Platform.BOSS)
        if "zhipin.com/web/chat" not in page.url:
            await page.goto(selectors.CHAT_URL)
        await asyncio.sleep(3)

        login = await detect_login_page(page, Platform.BOSS)
        if login.logged_out:
            _fail("BOSS 未登录，请先在该浏览器登录后重试")
        _print_step("3/4 BOSS 登录态检测通过")

        await _dismiss_overlays(page)
        adapter = BossAdapter(page, owner=args.owner, dry_run=not live)
        if args.conversation_id:
            selected = await select_all_filter(page)
            if not selected.get("selected"):
                _fail(f"BOSS 全部筛选不可用，无法处理指定会话: {selected}")
        else:
            unread = await adapter.select_unread_filter()
            if not unread.get("selected"):
                _fail(f"BOSS 未读筛选不可用: {unread}")
            unread_rows = await boss_actions.read_unread_row_states(page)
            if not unread_rows:
                _print_step("4/4 BOSS 没有带数字徽标的真实未读会话")
                print_summary([], live=live)
                return
            print(f"真实未读会话数: {len(unread_rows)}")
        missing, warnings = await _selector_health(page)
        if missing:
            print("选择器可能漂移，先修复再处理。缺失清单:")
            for item in missing:
                print(f"- {item}")
            raise SystemExit(2)
        if warnings:
            print(f"条件选择器警告，不阻断 {mode_name}:")
            for item in warnings:
                print(f"- {item}")
        _print_step("4/4 BOSS 关键选择器健康检查通过")

        conversation_repository, artifact_store = build_persistence_from_settings()
        summaries = (
            await process_boss_targets(
                adapter,
                args.conversation_id,
                conversation_repository=conversation_repository,
                artifact_store=artifact_store,
            )
            if args.conversation_id
            else await _process_boss(
                adapter,
                args.limit,
                conversation_repository=conversation_repository,
                artifact_store=artifact_store,
            )
        )
        print_summary(summaries, live=live)
    finally:
        await _close_manager(manager)
        await _close_runtime_resources()


def _resolve_mode(args: argparse.Namespace) -> bool:
    if args.live:
        if not args.confirm_live:
            _fail("live 模式必须同时传 --confirm-live，避免误触真实发送。")
        if args.owner != "宋峰峰":
            _fail("本次 live 只允许处理 owner=宋峰峰。")
        if args.limit < 1 or args.limit > 10:
            _fail("live 模式 limit 必须在 1 到 3 之间。")
        os.environ["DRY_RUN"] = "false"
        load_settings.cache_clear()
        return True

    settings = load_settings()
    if not settings.dry_run:
        _fail("未传 --live 时不允许非 dry-run。请设置 DRY_RUN=true 或显式使用 live 参数。")
    return False


def _worker_for_owner(owner: str):
    settings = load_settings()
    try:
        return settings.worker_for_owner(owner)
    except ValueError as error:
        _fail(f"owner 不在 accounts.yaml 中: {owner}. {error}")


def _probe_cdp(cdp: str) -> dict[str, Any]:
    try:
        with urlopen(f"{cdp.rstrip('/')}/json/version", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:
        _fail(f"CDP 连不上: {cdp}. {error}")
    return {}


async def _selector_health(page: Any) -> tuple[list[str], list[str]]:
    required_before = {
        "聊天筛选栏": ".chat-top-filter, .chat-message-filter",
        "会话列表/下一条候选人": selectors.SESSION_ITEM,
    }
    missing: list[str] = []
    warnings: list[str] = []
    for name, selector in required_before.items():
        count = len(await page.query_all(selector))
        print(f"选择器检查 {name}: count={count} selector={selector}")
        if count == 0:
            missing.append(f"{name}: {selector}")
    if missing:
        return missing, warnings
    warnings.append(
        "聊天区选择器将在点开真实未读会话后逐条校验，启动前不消费未读状态"
    )
    return missing, warnings


async def _dismiss_overlays(page: Any) -> None:
    """关闭可能遗留的下拉/浮层，避免拦截会话点击。"""

    await page.eval_js(
        """
        () => {
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        }
        """
    )
    for selector in (
        ".dialog-wrap.active .close-btn",
        ".dialog-wrap.active .boss-dialog-close",
        ".dialog-wrap.active [class*='close']",
        ".boss-dialog__wrapper [class*='close']",
        "[data-type='boss-dialog'] [class*='close']",
    ):
        element = await page.query(selector)
        if element is None:
            continue
        await reliable_click_element(page, element, label="BOSS关闭遮挡层")
        break
    await asyncio.sleep(1)


async def _verify_boss_chat_ready(page: Any) -> dict[str, object]:
    """确认点开候选人后 BOSS 聊天区已经可读。"""

    ready = await page.wait_for(selectors.CHAT_INPUT, timeout_ms=6500)
    return {"verified": bool(ready), "reason": "" if ready else "chat_input_not_ready"}


async def _process_boss(
    adapter: BossAdapter,
    limit: int,
    *,
    conversation_repository: Any,
    artifact_store: Any,
) -> list[dict[str, Any]]:
    await adapter.select_positions(None)
    states = await boss_actions.read_unread_row_states(adapter.page)
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unread_state in states:
        if len(summaries) >= limit:
            break
        label = str(unread_state.get("label") or "").strip()
        if _skip_row_label(label):
            continue
        row = await _find_boss_row(adapter.page, unread_state)
        if row is None:
            continue
        label = (await row.text()).strip()
        if _skip_row_label(label):
            continue
        before_actions = len(getattr(adapter.page, "reliable_actions", []))
        click = await reliable_click_element(
            adapter.page,
            row,
            label="BOSS处理候选人会话",
            verify=lambda: _verify_boss_chat_ready(adapter.page),
        )
        if not click.get("ok"):
            summaries.append(
                {
                    "conversationId": label,
                    "action": "skip",
                    "stage": "open_thread_failed",
                    "decision": {"reason": click.get("reason") or "click_not_verified"},
                    "reliableActions": reliable_actions_since(adapter.page, before_actions),
                }
            )
            continue
        context = await _wait_for_context(adapter)
        state = await ConversationRunner(
            adapter,
            conversation_repository=conversation_repository,
            artifact_store=artifact_store,
        ).run_current()
        conversation_id = str(state.get("conversation_id") or label)
        if conversation_id in seen:
            continue
        seen.add(conversation_id)
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        last_message = messages[-1] if messages else _last_message_from_context(context)
        candidate = state.get("candidate") if isinstance(state.get("candidate"), dict) else {}
        decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
        result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
        candidate_status = (
            state.get("candidate_status") if isinstance(state.get("candidate_status"), dict) else {}
        )
        summaries.append(
            {
                "sessionId": state.get("session_id") or "",
                "conversationId": conversation_id,
                "candidate": candidate or {"name": context.candidate.name},
                "job": state.get("applied_position") or context.candidate.applied_position,
                "lastMessage": last_message,
                "action": state.get("next_action") or "",
                "stage": state.get("stage") or "",
                "ruleSource": state.get("rule_source") or "",
                "sentMessages": state.get("sent_messages") or [],
                "artifactWritten": bool(result.get("downloaded") and result.get("filePath")),
                "candidateStatusWritten": bool(candidate_status),
                "candidateStatus": candidate_status,
                "decision": decision,
                "reliableActions": reliable_actions_since(adapter.page, before_actions),
            }
        )
    return summaries


async def _find_boss_row(page: Any, state: dict[str, Any]) -> Any | None:
    row_id = str(state.get("id") or "")
    row_id_norm = row_id.lstrip("_")
    label = str(state.get("label") or "").strip()
    rows = await page.query_all(selectors.SESSION_ITEM)

    if row_id_norm:
        for row in rows:
            current_id = str(await row.attr("id") or "")
            if current_id.lstrip("_") == row_id_norm:
                return row
    if label:
        for row in rows:
            if (await row.text()).strip() == label:
                return row
    index = _safe_int(state.get("index"))
    if 0 <= index < len(rows):
        return rows[index]
    return None


async def _wait_for_context(adapter: BossAdapter, *, timeout_seconds: float = 6):
    """等待 BOSS 会话详情区消息渲染出来。"""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    latest = await adapter.read_chat_context()
    while not latest.messages and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.4)
        latest = await adapter.read_chat_context()
    return latest


def _last_message_from_context(context: Any) -> dict[str, str]:
    if not getattr(context, "messages", None):
        return {}
    message = context.messages[-1]
    return {
        "sender": str(message.sender),
        "text": message.text,
        "raw_text": message.raw_text,
    }


def _skip_row_label(label: str) -> bool:
    compact = "".join(label.split())
    skip_terms = ("平台推荐", "系统消息", "BOSS直聘", "职位助手")
    return not compact or any(term in compact for term in skip_terms)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _close_manager(manager: BrowserManager) -> None:
    try:
        await manager.close()
    except Exception:
        pass


async def _close_runtime_resources() -> None:
    """关闭 LangGraph SQLite checkpointer，避免脚本结束后后台线程挂住。"""

    try:
        from app.agent.checkpointer import close_checkpointer

        await close_checkpointer()
    except Exception:
        pass


def _print_step(message: str) -> None:
    print(f"[OK] {message}", flush=True)


def _fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr, flush=True)
    raise SystemExit(2)


def main() -> None:
    """脚本入口。"""

    asyncio.run(main_async())


if __name__ == "__main__":
    main()
