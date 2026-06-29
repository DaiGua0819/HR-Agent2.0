"""Shared dry-run/live-on-confirm runner for 51job and Zhilian.

This module intentionally keeps business decisions in ``ConversationRunner``.
It only wires a real CDP page to the platform adapter, performs lightweight
preflight checks, and prints a human-readable summary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from typing import Any
from urllib.request import urlopen

from app.agent.persistence import build_persistence_from_settings
from app.agent.runner import ConversationRunner
from app.browser.cloak import cdp_url_for
from app.browser.manager import BrowserManager
from app.browser.reliable_actions import reliable_click_element, reliable_scroll
from app.browser.selector_validation import detect_login_page
from app.core.constants import Platform
from app.platforms.job51 import actions_chat as job51_chat
from app.platforms.job51 import selectors as job51_selectors
from app.platforms.job51.actions_resume_close import cleanup_resume_overlays
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.zhilian import actions as zhilian_actions
from app.platforms.zhilian import selectors as zhilian_selectors
from app.platforms.zhilian.adapter import ZhilianAdapter
from app.settings import load_settings


def run(platform: Platform) -> None:
    """Run one platform once from a thin wrapper."""

    asyncio.run(_main_async(platform))


async def _main_async(platform: Platform) -> None:
    args = _parse_args(platform)
    live = _resolve_mode(args)
    owner = _resolve_owner(args.owner, platform)
    settings = load_settings()
    worker = settings.worker_for_owner(owner)
    cdp_url = cdp_url_for(worker.cdp_port)
    os.environ["HR_AGENT_BROWSER_BACKEND"] = "cloak"
    _print_step(f"1/4 mode guard passed: {'LIVE' if live else 'dry-run'}")
    version = _probe_cdp(cdp_url)
    _print_step(f"2/4 CloakBrowser CDP connected: {version.get('Browser', '')}")

    manager = BrowserManager(owner=owner, cdp_port=worker.cdp_port, backend="cloak")
    try:
        await manager.start()
        page = manager.page_for(owner, platform)
        if platform == Platform.JOB51:
            await job51_chat.open_chat_page(page)
        await asyncio.sleep(max(args.wait, 0))
        login = await detect_login_page(page, platform)
        if login.logged_out:
            _fail(f"{platform.value} is not logged in; please log in and retry.")
        _print_step("3/4 login preflight passed")

        adapter = _adapter_for(platform, page, owner=owner, dry_run=not live)
        missing = await _health_check(platform, adapter)
        if missing:
            print("Selector preflight failed; fix selectors before processing:")
            for item in missing:
                print(f"- {item}")
            raise SystemExit(2)
        _print_step("4/4 selector preflight passed")

        summaries = await _process(adapter, platform, args.limit)
        _print_summary(platform, summaries, live=live)
    finally:
        await _close_manager(manager)
        await _close_runtime_resources()


def _parse_args(platform: Platform) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Process {platform.value} unread conversations once; dry-run by default."
    )
    parser.add_argument("--owner", default="", help="Owner name from config/accounts.yaml")
    parser.add_argument("--limit", type=int, default=3, help="Maximum conversations")
    parser.add_argument("--wait", type=float, default=3.0, help="Seconds to wait after attach")
    parser.add_argument("--live", action="store_true", help="Actually send/request after checks")
    parser.add_argument("--confirm-live", action="store_true", help="Required with --live")
    return parser.parse_args()


def _resolve_mode(args: argparse.Namespace) -> bool:
    if args.live:
        if not args.confirm_live:
            _fail("--live requires --confirm-live.")
        os.environ["DRY_RUN"] = "false"
        load_settings.cache_clear()
        return True
    os.environ["DRY_RUN"] = "true"
    load_settings.cache_clear()
    return False


def _resolve_owner(owner: str, platform: Platform) -> str:
    settings = load_settings()
    if owner:
        settings.worker_for_owner(owner)
        return owner
    for worker in settings.workers:
        if platform in worker.accounts:
            return worker.owner
    _fail(f"No worker configured for platform={platform.value}")
    return ""


def _probe_cdp(cdp: str) -> dict[str, Any]:
    try:
        with urlopen(f"{cdp.rstrip('/')}/json/version", timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:
        _fail(f"CDP not reachable: {cdp}. {error}")
    return {}


def _adapter_for(platform: Platform, page: Any, *, owner: str, dry_run: bool):
    if platform == Platform.JOB51:
        return Job51Adapter(page, owner=owner, dry_run=dry_run)
    if platform == Platform.ZHILIAN:
        return ZhilianAdapter(page, owner=owner, dry_run=dry_run)
    raise ValueError(f"Unsupported platform: {platform}")


async def _health_check(platform: Platform, adapter: Any) -> list[str]:
    page = adapter.page
    await adapter.select_positions(None)
    unread = await adapter.select_unread_filter()
    missing: list[str] = []
    if not unread.get("selected"):
        missing.append(f"unread filter not active: {unread}")
    if platform == Platform.JOB51:
        required = {"thread list": job51_selectors.THREAD_ITEM}
        conditional = {
            "chat input after opening candidate": job51_selectors.CHAT_INPUT,
            "send button when sending": job51_selectors.SEND_BUTTON,
        }
    else:
        required = {
            "thread list": zhilian_selectors.SESSION_ITEM,
            "chat ready/input": zhilian_selectors.CHAT_READY,
            "message list": zhilian_selectors.MESSAGE_ITEM,
        }
    for name, selector in required.items():
        count = len(await page.query_all(selector))
        print(f"preflight required {name}: count={count} selector={selector}", flush=True)
        if count == 0:
            missing.append(f"{name}: {selector}")
    for name, selector in locals().get("conditional", {}).items():
        count = len(await page.query_all(selector))
        print(f"preflight conditional {name}: count={count} selector={selector}", flush=True)
    return missing


async def _process(adapter: Any, platform: Platform, limit: int) -> list[dict[str, Any]]:
    conversation_repository, artifact_store = build_persistence_from_settings()
    if platform == Platform.ZHILIAN:
        return await _process_zhilian(
            adapter,
            limit,
            conversation_repository=conversation_repository,
            artifact_store=artifact_store,
        )

    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_items = max(1, limit)
    scrolls = 0
    idle_scans = 0
    while len(summaries) < max_items and idle_scans < 3:
        progressed = False
        for row_state in await _candidate_row_states(adapter, platform):
            if len(summaries) >= max_items:
                break
            label = str(row_state.get("label") or "").strip()
            row_keys = _seen_keys_for_row(row_state)
            if seen.intersection(row_keys) or _skip_label(platform, label):
                continue
            if platform == Platform.JOB51:
                await cleanup_resume_overlays(adapter.page)
            row = await _find_candidate_row(adapter, platform, row_state)
            if row is None:
                continue
            label = (await row.text()).strip()
            if seen.intersection(_seen_keys_for_row({**row_state, "label": label})) or _skip_label(
                platform, label
            ):
                continue
            before_actions = len(getattr(adapter.page, "reliable_actions", []))
            click = await reliable_click_element(
                adapter.page,
                row,
                label=f"{platform.value}候选人会话",
                verify=lambda: _verify_chat_ready(adapter, platform),
            )
            if not click.get("ok"):
                continue
            state = await ConversationRunner(
                adapter,
                conversation_repository=conversation_repository,
                artifact_store=artifact_store,
            ).run_current()
            summary = _summary_from_state(state)
            summary["reliableActions"] = getattr(adapter.page, "reliable_actions", [])[
                before_actions:
            ]
            if platform == Platform.JOB51:
                summary["cleanup"] = await cleanup_resume_overlays(adapter.page)
            summaries.append(summary)
            seen.update(_seen_keys_for_processed_item(row_state, summary))
            progressed = True
        if len(summaries) >= max_items:
            break
        if progressed:
            idle_scans = 0
            continue
        scrolled = await _scroll_thread_list(adapter, platform, scrolls)
        scrolls += 1
        idle_scans = 0 if scrolled else idle_scans + 1
    return summaries


async def _process_zhilian(
    adapter: Any,
    limit: int,
    *,
    conversation_repository: Any,
    artifact_store: Any,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_items = max(1, limit)
    scrolls = 0
    idle_scans = 0
    while len(summaries) < max_items and idle_scans < 3:
        before_actions = len(getattr(adapter.page, "reliable_actions", []))
        ref = await adapter.find_next_unread_thread()
        if ref is None:
            scrolled = await _scroll_thread_list(adapter, Platform.ZHILIAN, scrolls)
            scrolls += 1
            idle_scans = 0 if scrolled else idle_scans + 1
            continue
        if ref.conversation_id in seen:
            idle_scans += 1
            continue
        state = await ConversationRunner(
            adapter,
            conversation_repository=conversation_repository,
            artifact_store=artifact_store,
        ).run_current()
        conversation_id = str(state.get("conversation_id") or ref.conversation_id)
        seen.update({ref.conversation_id, conversation_id})
        summary = _summary_from_state(state)
        summary["reliableActions"] = getattr(adapter.page, "reliable_actions", [])[
            before_actions:
        ]
        summaries.append(summary)
        idle_scans = 0
    return summaries


async def _candidate_row_states(adapter: Any, platform: Platform) -> list[dict[str, object]]:
    if platform == Platform.JOB51:
        return await job51_chat.read_unread_row_states(adapter.page)
    return await zhilian_actions.read_unread_row_states(adapter.page)


async def _find_candidate_row(
    adapter: Any,
    platform: Platform,
    state: dict[str, object],
) -> Any | None:
    rows = await _candidate_rows(adapter, platform)
    row_id = str(state.get("id") or "").lstrip("_")
    label = str(state.get("label") or "").strip()
    if row_id:
        for row in rows:
            current_id = str(await row.attr("id") or "").lstrip("_")
            if current_id == row_id:
                return row
    if label:
        for row in rows:
            if (await row.text()).strip() == label:
                return row
    index = _safe_int(state.get("index"))
    if 0 <= index < len(rows):
        return rows[index]
    return None


async def _candidate_rows(adapter: Any, platform: Platform) -> list[Any]:
    selector = (
        job51_selectors.THREAD_ITEM
        if platform == Platform.JOB51
        else zhilian_selectors.SESSION_ITEM
    )
    return await adapter.page.query_all(selector)


async def _scroll_thread_list(adapter: Any, platform: Platform, scrolls: int) -> bool:
    if scrolls >= 8:
        return False
    if platform == Platform.JOB51:
        result = await reliable_scroll(
            adapter.page,
            amount=720,
            container_selector="#conversation-list",
        )
        return bool(result.get("scrolled"))
    result = await reliable_scroll(adapter.page, amount=720)
    return bool(result.get("scrolled"))


async def _verify_chat_ready(adapter: Any, platform: Platform) -> dict[str, object]:
    selector = (
        job51_selectors.CHAT_INPUT
        if platform == Platform.JOB51
        else zhilian_selectors.CHAT_READY
    )
    return {"verified": await adapter.page.wait_for(selector, timeout_ms=6500)}


def _skip_label(platform: Platform, label: str) -> bool:
    if platform == Platform.JOB51:
        return job51_chat.should_skip_thread_label(label)
    compact = "".join(label.split())
    return not compact or any(
        term in compact for term in ("平台推荐", "系统提示", "广告", "职位助手")
    )


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _seen_keys_for_row(row_state: dict[str, object]) -> set[str]:
    keys: set[str] = set()
    row_id = str(row_state.get("id") or "").strip()
    label = str(row_state.get("label") or "").strip()
    index = str(row_state.get("index") or "").strip()
    if row_id:
        keys.add(f"row:{row_id.lstrip('_')}")
    if label:
        keys.add(f"label:{_compact(label)}")
    if index:
        keys.add(f"index:{index}")
    return keys


def _seen_keys_for_processed_item(
    row_state: dict[str, object],
    summary: dict[str, Any],
) -> set[str]:
    keys = _seen_keys_for_row(row_state)
    conversation_id = str(summary.get("conversationId") or "").strip()
    session_id = str(summary.get("sessionId") or "").strip()
    if conversation_id:
        keys.add(f"conversation:{conversation_id}")
    if session_id:
        keys.add(f"session:{session_id}")
    candidate = summary.get("candidate") if isinstance(summary.get("candidate"), dict) else {}
    name = str(candidate.get("name") or candidate.get("label") or "").strip()
    job = str(summary.get("job") or candidate.get("applied_position") or "").strip()
    fingerprint = str(summary.get("recentMessagesFingerprint") or "").strip()
    if name and job and fingerprint:
        keys.add(f"fingerprint:{_compact(name)}|{_compact(job)}|{fingerprint}")
    return keys


def _compact(value: str) -> str:
    return "".join(str(value or "").split()).lower()


def _summary_from_state(state: dict[str, Any]) -> dict[str, Any]:
    messages = state.get("messages") if isinstance(state.get("messages"), list) else []
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    candidate_status = (
        state.get("candidate_status") if isinstance(state.get("candidate_status"), dict) else {}
    )
    return {
        "sessionId": state.get("session_id") or "",
        "conversationId": state.get("conversation_id") or "",
        "recentMessagesFingerprint": state.get("recent_messages_fingerprint") or "",
        "candidate": state.get("candidate") if isinstance(state.get("candidate"), dict) else {},
        "job": state.get("applied_position") or "",
        "lastMessage": messages[-1] if messages else {},
        "action": state.get("next_action") or "",
        "stage": state.get("stage") or "",
        "ruleSource": state.get("rule_source") or "",
        "sentMessages": state.get("sent_messages") or [],
        "artifactWritten": bool(result.get("downloaded") and result.get("filePath")),
        "candidateStatusWritten": bool(candidate_status),
        "candidateStatus": candidate_status,
        "decision": decision,
    }


def _print_summary(platform: Platform, items: list[dict[str, Any]], *, live: bool) -> None:
    mode = "LIVE" if live else "dry-run"
    failed = sum(1 for item in items if item.get("action") == "send_failed")
    skipped = sum(1 for item in items if item.get("action") == "skip")
    processed = max(0, len(items) - failed - skipped)
    print(f"\n===== {platform.value} {mode} summary =====")
    print(
        f"processed={processed} skipped={skipped} failed={failed} total={len(items)}",
        flush=True,
    )
    for index, item in enumerate(items, start=1):
        candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
        print(f"\n[{index}] conversation: {item.get('conversationId')}")
        print(f"session: {item.get('sessionId') or ''}")
        print(f"candidate: {candidate.get('name') or candidate.get('label') or ''}")
        print(f"job: {item.get('job') or candidate.get('applied_position') or ''}")
        print(f"rule source: {item.get('ruleSource') or 'not matched'}")
        print(f"last message: {json.dumps(_jsonable(item.get('lastMessage')), ensure_ascii=False)}")
        print(f"intended action: {item.get('action')}")
        print(f"reason/stage: {item.get('stage')}")
        if item.get("sentMessages"):
            print(f"messages: {json.dumps(_jsonable(item['sentMessages']), ensure_ascii=False)}")
        if item.get("reliableActions"):
            print(
                "reliable actions: "
                f"{json.dumps(_jsonable(item['reliableActions']), ensure_ascii=False)}"
            )
        print(f"artifact written: {bool(item.get('artifactWritten'))}")
        print(f"candidate status written: {bool(item.get('candidateStatusWritten'))}")
        print(f"decision: {json.dumps(_jsonable(decision), ensure_ascii=False)}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value)}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if hasattr(value, "__dataclass_fields__"):
            return _jsonable(asdict(value))
        return str(value)


async def _close_manager(manager: BrowserManager) -> None:
    try:
        await manager.close()
    except Exception:
        pass


async def _close_runtime_resources() -> None:
    try:
        from app.agent.checkpointer import close_checkpointer

        await close_checkpointer()
    except Exception:
        pass


def _print_step(message: str) -> None:
    print(f"[ok] {message}", flush=True)


def _fail(message: str) -> None:
    print(f"[error] {message}", flush=True)
    raise SystemExit(2)
