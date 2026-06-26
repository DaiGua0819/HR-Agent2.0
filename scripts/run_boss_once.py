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
from dataclasses import asdict
from typing import Any
from urllib.request import urlopen

from app.agent.runner import ConversationRunner
from app.browser.playwright_cdp import PlaywrightCDPConnection, connect_cdp_browser
from app.browser.selector_validation import detect_login_page
from app.core.constants import Platform
from app.platforms.boss import selectors
from app.platforms.boss.adapter import BossAdapter
from app.settings import load_settings

from boss_targeting import process_boss_targets, select_all_filter


def parse_args() -> argparse.Namespace:
    """解析启动参数。"""

    parser = argparse.ArgumentParser(description="BOSS 真实浏览器处理一次，默认 dry-run")
    parser.add_argument("--owner", default="宋峰峰", help="负责人，需与 accounts.yaml 一致")
    parser.add_argument("--cdp", default="http://127.0.0.1:9333", help="BOSS CDP 地址")
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
    _guard_owner(args.owner)
    _configure_boss_cdp(args.cdp)
    mode_name = "LIVE" if live else "dry-run"
    _print_step(f"1/4 {mode_name} 守卫通过")

    version = _probe_cdp(args.cdp)
    _print_step(f"2/4 CDP 连通: {version.get('Browser', '')}")

    connection = await connect_cdp_browser(args.cdp)
    try:
        page = await connection.ensure_page(
            name="boss",
            url=selectors.CHAT_URL,
            url_hint="zhipin.com",
        )
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
            if not await page.query_all(selectors.SESSION_ITEM):
                _print_step("4/4 BOSS 未读列表为空")
                _print_summary([], live=live)
                return
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

        summaries = (
            await process_boss_targets(adapter, args.conversation_id)
            if args.conversation_id
            else await _process_boss(adapter, args.limit)
        )
        _print_summary(summaries, live=live)
    finally:
        await _close_connection(connection)
        await _close_runtime_resources()


def _resolve_mode(args: argparse.Namespace) -> bool:
    if args.live:
        if not args.confirm_live:
            _fail("live 模式必须同时传 --confirm-live，避免误触真实发送。")
        if args.owner != "宋峰峰":
            _fail("本次 live 只允许处理 owner=宋峰峰。")
        if args.limit < 1 or args.limit > 3:
            _fail("live 模式 limit 必须在 1 到 3 之间。")
        os.environ["DRY_RUN"] = "false"
        load_settings.cache_clear()
        return True

    settings = load_settings()
    if not settings.dry_run:
        _fail("未传 --live 时不允许非 dry-run。请设置 DRY_RUN=true 或显式使用 live 参数。")
    return False


def _guard_owner(owner: str) -> None:
    settings = load_settings()
    try:
        settings.worker_for_owner(owner)
    except ValueError as error:
        _fail(f"owner 不在 accounts.yaml 中: {owner}. {error}")


def _configure_boss_cdp(cdp: str) -> None:
    os.environ["AGENT_CDP_BOSS"] = cdp
    os.environ["HR_AGENT_BROWSER_BACKEND"] = "real-per-platform"


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

    first = await _first_candidate_row(page)
    if first is None:
        return ["没有找到可点击候选人会话"], warnings
    await first.click()
    await asyncio.sleep(1)

    required_after = {
        "消息抽取": selectors.MESSAGE_ITEM,
        "输入框": selectors.CHAT_INPUT,
        "发送按钮": selectors.SEND_BUTTON,
    }
    optional_after = {
        "己方消息 mine 校验": selectors.MINE_MESSAGE,
        "求简历按钮": selectors.REQUEST_RESUME_BUTTON,
    }
    for name, selector in required_after.items():
        count = await _count_with_wait(page, selector)
        print(f"点进会话后检查 {name}: count={count} selector={selector}")
        if count == 0:
            missing.append(f"{name}: {selector}")
    for name, selector in optional_after.items():
        count = len(await page.query_all(selector))
        print(f"条件选择器检查 {name}: count={count} selector={selector}")
        if count == 0:
            warnings.append(f"{name}: {selector}")
    return missing, warnings


async def _dismiss_overlays(page: Any) -> None:
    """关闭可能遗留的下拉/浮层，避免拦截会话点击。"""

    await page.eval_js(
        """
        () => {
          const clickFirst = (selectors) => {
            for (const selector of selectors) {
              const el = document.querySelector(selector);
              if (el) {
                el.click();
                return true;
              }
            }
            return false;
          };
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
          clickFirst([
            ".dialog-wrap.active .close-btn",
            ".dialog-wrap.active .boss-dialog-close",
            ".dialog-wrap.active [class*='close']",
            ".boss-dialog__wrapper [class*='close']",
            "[data-type='boss-dialog'] [class*='close']"
          ]);
          document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
          document.body.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
          document.body.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        }
        """
    )
    await asyncio.sleep(1)


async def _count_with_wait(page: Any, selector: str, *, timeout_seconds: float = 6) -> int:
    """等待异步详情区渲染完成后再统计。"""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_count = 0
    while True:
        last_count = len(await page.query_all(selector))
        if last_count:
            return last_count
        if asyncio.get_running_loop().time() >= deadline:
            return last_count
        await asyncio.sleep(0.4)


async def _process_boss(adapter: BossAdapter, limit: int) -> list[dict[str, Any]]:
    await adapter.select_positions(None)
    rows = await adapter.page.query_all(selectors.SESSION_ITEM)
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if len(summaries) >= limit:
            break
        label = (await row.text()).strip()
        if _skip_row_label(label):
            continue
        await row.click()
        context = await _wait_for_context(adapter)
        state = await ConversationRunner(adapter).run_current()
        conversation_id = str(state.get("conversation_id") or label)
        if conversation_id in seen:
            continue
        seen.add(conversation_id)
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        last_message = messages[-1] if messages else _last_message_from_context(context)
        candidate = state.get("candidate") if isinstance(state.get("candidate"), dict) else {}
        summaries.append(
            {
                "conversationId": conversation_id,
                "candidate": candidate or {"name": context.candidate.name},
                "job": state.get("applied_position") or context.candidate.applied_position,
                "lastMessage": last_message,
                "action": state.get("next_action") or "",
                "stage": state.get("stage") or "",
                "decision": state.get("decision") or {},
            }
        )
    return summaries


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


def _print_summary(items: list[dict[str, Any]], *, live: bool) -> None:
    mode_name = "LIVE" if live else "dry-run"
    print(f"\n===== BOSS {mode_name} 小结 =====")
    print(f"处理会话数: {len(items)}")
    if not items:
        print("没有处理到候选人会话。可能没有未读，或会话列表选择器未返回候选人行。")
        return
    for index, item in enumerate(items, start=1):
        candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
        print(f"\n[{index}] 会话: {item.get('conversationId')}")
        print(f"候选人: {candidate.get('name') or ''}")
        print(f"识别岗位: {item.get('job') or candidate.get('applied_position') or '未识别'}")
        last_message = json.dumps(
            _jsonable(item.get("lastMessage") or {}),
            ensure_ascii=False,
        )
        print(f"最后消息: {last_message}")
        print(f"打算动作: {item.get('action') or '无'}")
        print(f"原因/阶段: {item.get('stage') or ''}")
        print(f"决策详情: {json.dumps(_jsonable(decision), ensure_ascii=False)}")


def _skip_row_label(label: str) -> bool:
    compact = "".join(label.split())
    skip_terms = ("平台推荐", "系统消息", "BOSS直聘", "职位助手")
    return not compact or any(term in compact for term in skip_terms)


async def _first_candidate_row(page: Any):
    for row in await page.query_all(selectors.SESSION_ITEM):
        label = (await row.text()).strip()
        if not _skip_row_label(label):
            return row
    return None


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return str(value)


async def _close_connection(connection: PlaywrightCDPConnection) -> None:
    try:
        await connection.close()
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
    print(f"[OK] {message}")


def _fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    """脚本入口。"""

    asyncio.run(main_async())


if __name__ == "__main__":
    main()
