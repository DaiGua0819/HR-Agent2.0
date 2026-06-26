"""候选人记忆与多重匹配。

Phase 1 使用进程内存，按姓名 + 岗位 + 聊天 key + 页面 label 组合，避免同名串线。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CandidateMemoryStore:
    """候选人会话记忆。"""

    records: dict[str, dict[str, object]] = field(default_factory=dict)

    def key(self, owner: str, platform: str, name: str, job: str, label: str) -> str:
        """生成稳定记忆 key。"""

        parts = [owner, platform, _compact(name), _compact(job), _compact(label)]
        return "|".join(parts)

    def get(
        self, owner: str, platform: str, name: str, job: str, label: str
    ) -> dict[str, object] | None:
        """读取候选人记忆。"""

        return self.records.get(self.key(owner, platform, name, job, label))

    def put(
        self,
        owner: str,
        platform: str,
        name: str,
        job: str,
        label: str,
        value: dict[str, object],
    ) -> None:
        """保存候选人记忆。"""

        self.records[self.key(owner, platform, name, job, label)] = value


GLOBAL_MEMORY = CandidateMemoryStore()


def find_candidate_memory(
    owner: str,
    platform: str,
    candidate_name: str,
    job: str = "",
    label: str = "",
) -> dict[str, object] | None:
    """查找候选人历史记忆。"""

    return GLOBAL_MEMORY.get(owner, platform, candidate_name, job, label)


def _compact(value: str) -> str:
    return "".join(str(value or "").split()).lower()
