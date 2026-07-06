"""Terminal orchestration for draining all platform messages across workers."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from app.accounts.manager import AccountManager
from app.core.constants import Platform

DEFAULT_MAX_ROUNDS = 300
DEFAULT_TIMEOUT_SECONDS = 300.0
PLATFORM_ORDER: tuple[Platform, ...] = (Platform.BOSS, Platform.JOB51, Platform.ZHILIAN)


@dataclass(frozen=True)
class WorkerTarget:
    owner: str
    base_url: str


class ProcessMessagesClient(Protocol):
    async def drain_messages(
        self,
        target: WorkerTarget,
        platform: Platform,
        *,
        max_contacts: int,
    ) -> dict[str, Any]:
        """Drain unread contacts for a worker/platform pair."""


@dataclass(frozen=True)
class HttpProcessMessagesClient:
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    async def drain_messages(
        self,
        target: WorkerTarget,
        platform: Platform,
        *,
        max_contacts: int,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=target.base_url,
            timeout=self.timeout_seconds,
        ) as client:
            response = await client.post(
                f"/automation/{platform.value}/drain-messages",
                json={"maxContacts": max_contacts},
            )
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {}


async def drain_all_targets(
    targets: Sequence[WorkerTarget],
    *,
    client: ProcessMessagesClient,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    platform_order: Sequence[Platform] = PLATFORM_ORDER,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Drain every worker in parallel while keeping each worker's platform order serial."""

    return await asyncio.gather(
        *(
            drain_owner(
                target,
                client=client,
                max_rounds=max_rounds,
                platform_order=platform_order,
                log=log,
            )
            for target in targets
        )
    )


async def drain_owner(
    target: WorkerTarget,
    *,
    client: ProcessMessagesClient,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    platform_order: Sequence[Platform] = PLATFORM_ORDER,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Drain one owner's platforms in boss -> 51job -> zhilian order."""

    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")

    platform_results: list[dict[str, Any]] = []
    total_processed = 0
    stopped = False
    for platform in platform_order:
        result = await drain_platform(
            target,
            platform,
            client=client,
            max_rounds=max_rounds,
            log=log,
        )
        platform_results.append(result)
        total_processed += int(result["processed"])
        if result["maxRoundsReached"]:
            stopped = True
            break
    return {
        "owner": target.owner,
        "baseUrl": target.base_url,
        "processed": total_processed,
        "stopped": stopped,
        "platforms": platform_results,
    }


async def drain_platform(
    target: WorkerTarget,
    platform: Platform,
    *,
    client: ProcessMessagesClient,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Ask the worker to drain a platform in one terminal round."""

    rounds: list[dict[str, Any]] = []
    payload = await client.drain_messages(target, platform, max_contacts=max_rounds)
    processed = _safe_int(payload.get("processed"))
    contacts = _safe_contacts(payload.get("contacts"))
    stop_reason = str(payload.get("stopReason") or "drained")
    max_contacts_reached = stop_reason == "max_contacts_reached"
    item = {
        "round": 1,
        "processed": processed,
        "conversationId": str(payload.get("conversationId") or ""),
        "stage": str(payload.get("stage") or ""),
        "nextAction": str(payload.get("nextAction") or ""),
        "drained": bool(payload.get("drained")),
        "stopReason": stop_reason,
        "contacts": contacts,
    }
    rounds.append(item)
    log(_format_round_log(target, platform, item))
    for index, contact in enumerate(contacts, start=1):
        log(_format_contact_log(target, platform, index, contact))
    return {
        "platform": platform.value,
        "processed": processed,
        "rounds": rounds,
        "maxRoundsReached": max_contacts_reached,
        "stopReason": stop_reason,
    }


def load_worker_targets() -> list[WorkerTarget]:
    manager = AccountManager()
    return [
        WorkerTarget(owner=worker.owner, base_url=worker.base_url)
        for worker in manager.workers
    ]


def main() -> int:
    args = _parse_args()
    client = HttpProcessMessagesClient(timeout_seconds=args.timeout)
    results = asyncio.run(
        drain_all_targets(
            load_worker_targets(),
            client=client,
            max_rounds=args.max_rounds,
        )
    )
    total_processed = sum(int(item["processed"]) for item in results)
    stopped = any(bool(item["stopped"]) for item in results)
    print(f"summary totalProcessed={total_processed} stopped={str(stopped).lower()}")
    for owner_result in results:
        print(
            "summary "
            f"owner={owner_result['owner']} "
            f"processed={owner_result['processed']} "
            f"stopped={str(owner_result['stopped']).lower()}"
        )
    return 1 if stopped else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drain all worker messages from the terminal."
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=DEFAULT_MAX_ROUNDS,
        help="Maximum contacts per owner/platform drain before stopping.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout seconds for each worker process-messages call.",
    )
    args = parser.parse_args()
    if args.max_rounds < 1:
        parser.error("--max-rounds must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def _format_round_log(
    target: WorkerTarget,
    platform: Platform,
    item: dict[str, Any],
) -> str:
    return (
        f"owner={target.owner} platform={platform.value} round={item['round']} "
        f"processed={item['processed']} conversationId={item['conversationId']} "
        f"stage={item['stage']} nextAction={item['nextAction']} "
        f"drained={str(item.get('drained', False)).lower()} "
        f"stopReason={item.get('stopReason', '')}"
    )


def _format_contact_log(
    target: WorkerTarget,
    platform: Platform,
    index: int,
    contact: dict[str, Any],
) -> str:
    return (
        f"owner={target.owner} platform={platform.value} contact={index} "
        f"conversationId={contact.get('conversationId', '')} "
        f"stage={contact.get('stage', '')} "
        f"nextAction={contact.get('nextAction', '')}"
    )


def _safe_contacts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
