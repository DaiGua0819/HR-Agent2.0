"""Run one Zhilian unread-message pass; dry-run by default."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run one Zhilian processing pass."""

    from app.core.constants import Platform

    from platform_once_common import run

    run(Platform.ZHILIAN)


if __name__ == "__main__":
    main()
