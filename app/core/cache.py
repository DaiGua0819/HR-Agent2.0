"""简单 TTL 内存缓存。

对应旧 `ttlCache.js`。本阶段只作为内存桩使用，不跨进程持久化，也不写真实数据库。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _CacheItem(Generic[V]):
    value: V
    expires_at: float


class TtlCache(Generic[K, V]):
    """按 key 保存带过期时间的内存值。"""

    def __init__(self, ttl_seconds: float = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[K, _CacheItem[V]] = {}

    def get(self, key: K) -> V | None:
        """读取未过期值；过期值会被惰性清理。"""

        item = self._items.get(key)
        if item is None:
            return None
        if item.expires_at < monotonic():
            self._items.pop(key, None)
            return None
        return item.value

    def set(self, key: K, value: V, *, ttl_seconds: float | None = None) -> None:
        """写入一个值，可覆盖默认 TTL。"""

        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        self._items[key] = _CacheItem(value=value, expires_at=monotonic() + ttl)

    def delete(self, key: K) -> None:
        """删除指定 key。"""

        self._items.pop(key, None)

    def clear(self) -> None:
        """清空全部缓存。"""

        self._items.clear()

    def prune(self) -> int:
        """清理过期项并返回删除数量。"""

        now = monotonic()
        expired = [key for key, item in self._items.items() if item.expires_at < now]
        for key in expired:
            self._items.pop(key, None)
        return len(expired)
