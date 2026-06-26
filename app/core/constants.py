"""全局枚举与常量。"""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    """三平台统一拼写，避免 BOSS/51job/智联在各层漂移。"""

    BOSS = "boss"
    JOB51 = "job51"
    ZHILIAN = "zhilian"
