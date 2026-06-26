"""日志初始化入口。"""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """配置控制面和 worker 共享的简洁日志格式。"""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
