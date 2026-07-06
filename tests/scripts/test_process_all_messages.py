from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.core.constants import Platform
from scripts.process_all_messages import (
    WorkerTarget,
    drain_all_targets,
    drain_owner,
)


def test_drain_owner_finishes_one_platform_before_starting_next() -> None:
    client = FakeDrainClient(
        {
            ("owner-a", Platform.BOSS): [{"processed": 2, "drained": True}],
            ("owner-a", Platform.JOB51): [{"processed": 1, "drained": True}],
            ("owner-a", Platform.ZHILIAN): [{"processed": 0, "drained": True}],
        }
    )

    result = asyncio.run(
        drain_owner(
            WorkerTarget(owner="owner-a", base_url="http://worker-a"),
            client=client,
            max_rounds=10,
            log=lambda _: None,
        )
    )

    assert client.calls == [
        ("owner-a", Platform.BOSS),
        ("owner-a", Platform.JOB51),
        ("owner-a", Platform.ZHILIAN),
    ]
    assert result["processed"] == 3
    assert [item["platform"] for item in result["platforms"]] == ["boss", "job51", "zhilian"]


def test_drain_all_targets_runs_workers_in_parallel() -> None:
    client = BlockingProcessClient()

    async def run() -> list[dict[str, Any]]:
        task = asyncio.create_task(
            drain_all_targets(
                [
                    WorkerTarget(owner="owner-a", base_url="http://worker-a"),
                    WorkerTarget(owner="owner-b", base_url="http://worker-b"),
                ],
                client=client,
                max_rounds=2,
                log=lambda _: None,
            )
        )
        await client.owner_a_boss_started.wait()
        await asyncio.sleep(0)
        assert ("start", "owner-b", Platform.BOSS) in client.events
        client.release_owner_a_boss.set()
        return await task

    result = asyncio.run(run())

    assert [item["owner"] for item in result] == ["owner-a", "owner-b"]


def test_drain_owner_stops_when_platform_hits_max_rounds() -> None:
    client = FakeDrainClient(
        {
            ("owner-a", Platform.BOSS): [
                {
                    "processed": 2,
                    "drained": False,
                    "stopReason": "max_contacts_reached",
                }
            ],
            ("owner-a", Platform.JOB51): [{"processed": 0}],
        }
    )

    result = asyncio.run(
        drain_owner(
            WorkerTarget(owner="owner-a", base_url="http://worker-a"),
            client=client,
            max_rounds=2,
            log=lambda _: None,
        )
    )

    assert client.calls == [("owner-a", Platform.BOSS)]
    assert client.max_contacts == [("owner-a", Platform.BOSS, 2)]
    assert result["stopped"] is True
    assert result["platforms"][0]["maxRoundsReached"] is True
    assert result["platforms"][0]["stopReason"] == "max_contacts_reached"


class FakeDrainClient:
    def __init__(self, responses: dict[tuple[str, Platform], list[dict[str, Any]]]) -> None:
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls: list[tuple[str, Platform]] = []
        self.max_contacts: list[tuple[str, Platform, int]] = []

    async def drain_messages(
        self,
        target: WorkerTarget,
        platform: Platform,
        *,
        max_contacts: int,
    ) -> dict[str, Any]:
        self.calls.append((target.owner, platform))
        self.max_contacts.append((target.owner, platform, max_contacts))
        queue = self.responses[(target.owner, platform)]
        return {**queue.pop(0), "platform": platform.value}


class BlockingProcessClient:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, Platform]] = []
        self.counts: dict[tuple[str, Platform], int] = defaultdict(int)
        self.owner_a_boss_started = asyncio.Event()
        self.release_owner_a_boss = asyncio.Event()

    async def drain_messages(
        self,
        target: WorkerTarget,
        platform: Platform,
        *,
        max_contacts: int,
    ) -> dict[str, Any]:
        _ = max_contacts
        self.events.append(("start", target.owner, platform))
        self.counts[(target.owner, platform)] += 1
        if target.owner == "owner-a" and platform == Platform.BOSS:
            self.owner_a_boss_started.set()
            await self.release_owner_a_boss.wait()
        self.events.append(("finish", target.owner, platform))
        return {"processed": 1, "drained": True, "platform": platform.value}
