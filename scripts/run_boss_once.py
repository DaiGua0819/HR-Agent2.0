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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from app.agent.persistence import build_persistence_from_settings
from app.agent.runner import ConversationRunner
from app.browser.cloak import cdp_url_for
from app.browser.manager import BrowserManager
from app.browser.selector_validation import detect_login_page
from app.core.constants import Platform
from app.platforms.boss import actions as boss_actions
from app.platforms.boss import selectors
from app.platforms.boss.adapter import BossAdapter
from app.platforms.boss.interaction import boss_click_element
from app.platforms.boss.row_click import click_row_state, find_row_for_state
from app.settings import PROJECT_ROOT, load_settings

from boss_once_support import print_summary, reliable_actions_since
from boss_targeting import process_boss_targets, select_all_filter

BOSS_CANDIDATE_TIMEOUT_SECONDS = 120


def parse_args() -> argparse.Namespace:
    """解析启动参数。"""

    parser = argparse.ArgumentParser(description="BOSS 真实浏览器处理一次，默认 dry-run")
    parser.add_argument("--owner", default="宋峰峰", help="负责人，需与 accounts.yaml 一致")
    parser.add_argument("--platform", default="boss", choices=["boss"])
    parser.add_argument("--limit", type=int, default=3, help="最多处理几个会话")
    parser.add_argument("--live", action="store_true", help="真实执行发送/求简历动作")
    parser.add_argument("--confirm-live", action="store_true", help="确认本次允许真实执行动作")
    parser.add_argument(
        "--max-anomalies",
        type=int,
        default=0,
        help="允许跳过的异常联系人数；超过该值立即停止，默认 0 表示遇到异常即停",
    )
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
                max_anomalies=args.max_anomalies,
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
        if args.limit < 1:
            _fail("live 模式 limit 必须为正整数。")
        if getattr(args, "max_anomalies", 0) < 0:
            _fail("max-anomalies 不能小于 0。")
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
        await boss_click_element(page, element, label="BOSS关闭遮挡层")
        break
    await asyncio.sleep(1)


async def _verify_boss_chat_ready(page: Any) -> dict[str, object]:
    """确认点开候选人后 BOSS 聊天区已经可读。"""

    ready = await page.wait_for(selectors.CHAT_INPUT, timeout_ms=6500)
    return {"verified": bool(ready), "reason": "" if ready else "chat_input_not_ready"}


async def _verify_boss_thread_opened(page: Any, target_state: dict[str, Any]) -> dict[str, object]:
    """确认点击后当前聊天区确实切到了目标 BOSS 会话。"""

    ready = await page.wait_for(selectors.CHAT_INPUT, timeout_ms=6500)
    if not ready:
        return {"verified": False, "reason": "chat_input_not_ready"}
    conversation = await boss_actions.read_chat_context(page, owner="")
    target_id = str(target_state.get("id") or "").lstrip("_")
    current_id = str(conversation.id or "").lstrip("_")
    expected = _expected_boss_identity(target_state)
    actual = {
        "id": current_id,
        "name": conversation.candidate.name,
        "position": _normalize_boss_position(conversation.candidate.applied_position),
    }
    if target_id and current_id == target_id:
        return {
            "verified": True,
            "reason": "conversation_id_matched",
            "expected": expected,
            "actual": actual,
        }
    expected_name = _compact_text(expected["name"])
    actual_name = _compact_text(actual["name"])
    expected_position = _compact_text(expected["position"])
    actual_position = _compact_text(actual["position"])
    position_conflict = bool(
        expected_position and actual_position and expected_position != actual_position
    )
    if expected_name and expected_name == actual_name and not position_conflict:
        return {
            "verified": True,
            "reason": "candidate_identity_matched",
            "expected": expected,
            "actual": actual,
        }
    return {
        "verified": False,
        "reason": "opened_thread_mismatch",
        "expected": expected,
        "actual": actual,
    }


async def _process_boss(
    adapter: BossAdapter,
    limit: int,
    *,
    conversation_repository: Any,
    artifact_store: Any,
    max_anomalies: int = 0,
) -> list[dict[str, Any]]:
    await adapter.select_positions(None)
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    attempted: set[str] = set()
    anomaly_count = 0
    while len(summaries) < limit:
        states = await boss_actions.read_unread_row_states(adapter.page)
        unread_state = next(
            (state for state in states if _boss_state_key(state) not in attempted),
            None,
        )
        if unread_state is None:
            break
        attempted.add(_boss_state_key(unread_state))
        label = str(unread_state.get("label") or "").strip()
        if _skip_row_label(label):
            continue
        row = await _find_boss_row(adapter.page, unread_state)
        if row is None:
            failure = _boss_open_failure_summary(
                unread_state,
                label=label,
                click={"ok": False, "reason": "row_not_found"},
            )
            summaries.append(failure)
            _report_boss_open_failure(failure)
            anomaly_count += 1
            if _boss_anomaly_limit_exceeded(anomaly_count, max_anomalies):
                break
            continue
        label = (await row.text()).strip()
        if _skip_row_label(label):
            continue
        print(f"[BOSS] 准备处理候选人: {label[:120]}", flush=True)
        before_actions = len(getattr(adapter.page, "reliable_actions", []))
        click = await click_row_state(
            adapter.page,
            unread_state,
            label="BOSS候选人会话",
            verify=lambda state=unread_state: _verify_boss_thread_opened(
                adapter.page,
                state,
            ),
        )
        if not click.get("ok"):
            failure = _boss_open_failure_summary(
                unread_state,
                label=label,
                click=click,
                reliable_actions=reliable_actions_since(adapter.page, before_actions),
            )
            summaries.append(failure)
            _report_boss_open_failure(failure)
            anomaly_count += 1
            if _boss_anomaly_limit_exceeded(anomaly_count, max_anomalies):
                break
            continue
        try:
            context = await _wait_for_context(adapter)
            state = await asyncio.wait_for(
                ConversationRunner(
                    adapter,
                    conversation_repository=conversation_repository,
                    artifact_store=artifact_store,
                ).run_current(),
                timeout=BOSS_CANDIDATE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            summaries.append(
                {
                    "conversationId": label,
                    "action": "failed",
                    "stage": "candidate_timeout",
                    "decision": {
                        "reason": "candidate_processing_timeout",
                        "timeoutSeconds": BOSS_CANDIDATE_TIMEOUT_SECONDS,
                    },
                    "reliableActions": reliable_actions_since(adapter.page, before_actions),
                }
            )
            print(f"[BOSS] 候选人处理超时，已跳过: {label[:120]}", flush=True)
            anomaly_count += 1
            if _boss_anomaly_limit_exceeded(anomaly_count, max_anomalies):
                break
            continue
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
        summary = {
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
        summaries.append(summary)
        if _boss_processing_requires_stop(summary):
            anomaly_count += 1
            print(
                f"[BOSS] 候选人动作异常，已跳过（{anomaly_count}/{max_anomalies}）: "
                + json.dumps(summary, ensure_ascii=False, default=str),
                flush=True,
            )
            if _boss_anomaly_limit_exceeded(anomaly_count, max_anomalies):
                break
    return summaries


async def _find_boss_row(page: Any, state: dict[str, Any]) -> Any | None:
    return await find_row_for_state(page, state)


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


def _compact_text(value: str) -> str:
    return "".join(value.split())


def _boss_state_key(state: dict[str, Any]) -> str:
    row_id = str(state.get("id") or "").strip().lstrip("_")
    if row_id:
        return f"id:{row_id}"
    return f"label:{_compact_text(str(state.get('label') or ''))}"


def _boss_processing_requires_stop(summary: dict[str, Any]) -> bool:
    action = str(summary.get("action") or "")
    stage = str(summary.get("stage") or "")
    return action in {"request_resume_failed", "send_failed", "failed"} or stage in {
        "request_resume_action_failed",
        "candidate_timeout",
    }


def _boss_anomaly_limit_exceeded(anomaly_count: int, max_anomalies: int) -> bool:
    if anomaly_count <= max_anomalies:
        return False
    print(
        f"[BOSS] 异常人数已达到 {anomaly_count}，超过允许值 {max_anomalies}，立即停止处理。",
        flush=True,
    )
    return True


def _expected_boss_identity(state: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(state.get("id") or "").strip().lstrip("_"),
        "name": str(state.get("name") or "").strip(),
        "position": _normalize_boss_position(str(state.get("position") or "")),
        "label": str(state.get("label") or "")[:300],
    }


def _normalize_boss_position(value: str) -> str:
    normalized = str(value or "").strip()
    for prefix in ("沟通职位：", "沟通职位:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].strip()
    return normalized


def _boss_open_failure_summary(
    state: dict[str, Any],
    *,
    label: str,
    click: dict[str, Any],
    reliable_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "conversationId": str(state.get("id") or label),
        "candidate": {
            "name": str(state.get("name") or ""),
            "position": str(state.get("position") or ""),
        },
        "action": "skip",
        "stage": "open_thread_failed",
        "decision": {
            "reason": click.get("reason") or "click_not_verified",
            "expected": _expected_boss_identity(state),
            "actual": _last_click_actual(click),
            "click": click,
        },
        "reliableActions": reliable_actions or [],
    }


def _last_click_actual(click: dict[str, Any]) -> dict[str, Any]:
    direct = click.get("actual")
    if isinstance(direct, dict):
        return direct
    attempts = click.get("attempts")
    if not isinstance(attempts, list):
        return {}
    for attempt in reversed(attempts):
        if not isinstance(attempt, dict):
            continue
        verification = attempt.get("verification")
        if isinstance(verification, dict) and isinstance(verification.get("actual"), dict):
            return verification["actual"]
    return {}


def _report_boss_open_failure(summary: dict[str, Any]) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": "boss",
        **summary,
    }
    print(
        "[BOSS] 打开联系人失败，已停止本轮: "
        + json.dumps(payload, ensure_ascii=False, default=str),
        flush=True,
    )
    _write_open_failure_diagnostic(payload)


def _write_open_failure_diagnostic(payload: dict[str, Any]) -> None:
    path = Path(PROJECT_ROOT) / "data" / "diagnostics" / "boss_open_failures.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError as error:
        print(f"[BOSS] 写入打开失败诊断失败: {error}", file=sys.stderr, flush=True)


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
