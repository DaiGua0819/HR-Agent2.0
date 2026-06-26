"""耗时记录工具。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def measure_elapsed() -> Iterator[callable[[], float]]:
    """返回一个可读取当前耗时秒数的闭包，供后续埋点接入。"""

    started_at = perf_counter()

    def elapsed() -> float:
        return perf_counter() - started_at

    yield elapsed
