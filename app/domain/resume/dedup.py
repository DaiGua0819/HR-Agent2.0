"""简历去重逻辑。

Phase 5 只做纯逻辑去重，不删除、不合并真实数据。主要按手机号聚合；没有手机号的
记录保持独立，避免误伤候选人。
"""

from __future__ import annotations

from app.domain.resume.models import Resume, ResumeRecord
from app.domain.resume.normalize import normalize_phone


def find_duplicate_resumes(records: list[ResumeRecord]) -> list[tuple[str, str]]:
    """返回具有相同手机号的记录 id 对。"""

    groups: dict[str, list[str]] = {}
    for record in records:
        phone = normalize_phone(record.phone_key or record.payload.get("phone"))
        if phone:
            groups.setdefault(phone, []).append(record.id)
    duplicates: list[tuple[str, str]] = []
    for ids in groups.values():
        if len(ids) < 2:
            continue
        first = ids[0]
        duplicates.extend((first, other) for other in ids[1:])
    return duplicates


def deduplicate_by_phone(resumes: list[Resume]) -> list[Resume]:
    """按手机号保留第一条简历；无手机号简历全部保留。"""

    seen: set[str] = set()
    result: list[Resume] = []
    for resume in resumes:
        phone = normalize_phone(resume.phone_key or resume.phone)
        if not phone:
            result.append(resume)
            continue
        if phone in seen:
            continue
        seen.add(phone)
        result.append(resume)
    return result
