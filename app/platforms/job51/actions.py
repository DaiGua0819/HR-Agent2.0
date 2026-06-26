"""51job 动作兼容入口。

Phase 3 已按领域拆到 `actions_chat/actions_resume/actions_mode/actions_recommend`。
保留本文件作为旧 import 的轻量聚合层。
"""

from __future__ import annotations

from app.platforms.job51.actions_resume import validate_resume_bytes

__all__ = ["validate_resume_bytes"]
