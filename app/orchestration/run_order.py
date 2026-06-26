"""控制面串行运行顺序。"""

from __future__ import annotations

from dataclasses import dataclass

from app.accounts.manager import AccountManager
from app.core.constants import Platform


@dataclass(frozen=True)
class RunTarget:
    """一次自动化派发目标。"""

    owner: str
    platform: Platform


def load_run_order(manager: AccountManager | None = None) -> list[RunTarget]:
    """按 accounts.yaml 的 open_order 生成串行派发目标。"""

    manager = manager or AccountManager()
    return [RunTarget(owner=item.owner, platform=item.platform) for item in manager.open_order]
