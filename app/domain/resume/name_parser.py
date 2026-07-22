"""Extract a trustworthy candidate display name from resume evidence."""

from __future__ import annotations

import re
from pathlib import Path

_LABEL_PREFIX_RE = re.compile(r"^(?:[●•·]\s*)?(姓\s*名|名字|name)\s*[:：]?\s*", re.IGNORECASE)
_LABELED_NAME_RE = re.compile(
    r"(?:姓\s*名|名字|name)\s*[:：]\s*([\u4e00-\u9fffA-Za-z·.'-]{2,24}(?:\s+[A-Za-z.'-]{2,20}){0,3})",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(
    r"(个人信息|基本信息|个人简历|简历|resume|curriculum vitae|cv)",
    re.IGNORECASE,
)
_ANONYMOUS_RE = re.compile(r"(?:先生|女士|同学|小姐|老师)$")
_PLATFORM_PLACEHOLDER_RE = re.compile(r"(平台|候选人|求职者|未知|匿名|待补充|未命名)")
_CHINESE_NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,6}(?:·[\u4e00-\u9fff]{1,8})*")
_PLATFORM_ALIAS_RE = re.compile(
    r"[\u4e00-\u9fff]{2,6}(?:[（(][\u4e00-\u9fff]{2,6}[）)])?(?:\s+[A-Za-z][A-Za-z .'-]{1,30})?"
)
_ENGLISH_NAME_RE = re.compile(r"[A-Za-z][A-Za-z.'-]{1,30}(?:\s+[A-Za-z][A-Za-z.'-]{1,30}){0,3}")
_BLOCKED_EXACT = {
    "姓",
    "姓名",
    "个人",
    "个人信息",
    "基本信息",
    "联系方式",
    "联系信息",
    "教育背景",
    "工作背景",
    "工作经历",
    "工作经验",
    "项目经历",
    "项目经验",
    "实习经历",
    "校园经历",
    "求职意向",
    "应聘职位",
    "目标职位",
    "个人优势",
    "个人简介",
    "自我评价",
    "专业技能",
    "技能特长",
    "获奖经历",
    "培训经历",
    "个人简历",
    "简历",
    "personal",
    "profile",
    "resume",
    "cv",
    "contact",
    "education",
    "experience",
    "objective",
    "summary",
    "project",
    "projects",
    "skills",
    "endobj",
    "obj",
    "stream",
}
_BLOCKED_FRAGMENT_RE = re.compile(
    r"(公司|有限|大学|学院|学校|项目|职位|岗位|经理|工程师|运营|销售|顾问|实习|"
    r"背景|经历|经验|信息|联系|电话|手机|邮箱|地址|学历|专业|出生|性别|年龄|"
    r"应聘|求职|目标|评价|技能|职责|工作|教育|简历|人才|招聘)"
)


def parse_resume_name(text: str, *, file_name: str = "") -> str:
    """Return a strict document or file-name candidate, or an empty string."""

    candidate_lines = _candidate_lines(text)
    for line in candidate_lines:
        match = _LABELED_NAME_RE.search(line)
        if match:
            candidate = _clean_name(match.group(1))
            if _looks_like_name(candidate):
                return candidate

    for line in candidate_lines:
        value = _LABEL_PREFIX_RE.sub("", line).strip()
        value = _NOISE_RE.sub("", value).strip(" _-—:：●•·")
        if _looks_like_name(value):
            return value
    return parse_resume_name_from_file(file_name)


def parse_resume_name_from_file(file_name: str) -> str:
    """Extract a candidate name from known 51job, Zhilian, or BOSS file names."""

    stem = _file_stem(file_name)
    if not stem:
        return ""
    patterns = (
        r"^(?:51job|job51)[_-]([^_]+)(?:_|$)",
        r"^zhilian[_-](?!resume(?:_|$)|attachment(?:_|$))([^_]+)(?:_|$)",
        r"】([^_]+)(?:_|$)",
        r"^([\u4e00-\u9fff·]{2,10})_(?:\d{2}岁|\d+年|AI|运营|全栈|产品|销售|智联)",
    )
    for pattern in patterns:
        match = re.search(pattern, stem, re.IGNORECASE)
        if not match:
            continue
        candidate = _clean_name(match.group(1))
        if _looks_like_name(candidate):
            return candidate
    return ""


def choose_resume_name(
    *,
    platform_name: str,
    document_name: str = "",
    file_name: str = "",
) -> str:
    """Choose a display name without letting weak PDF text overwrite platform identity."""

    platform = _clean_name(platform_name)
    document = _clean_name(document_name)
    file_candidate = parse_resume_name_from_file(file_name)
    platform_valid = _looks_like_platform_name(platform)
    platform_anonymous = platform_valid and _is_anonymous_name(platform)

    if platform_valid and not platform_anonymous:
        return platform
    if _looks_like_name(document) and not _is_anonymous_name(document):
        return document
    if _looks_like_name(file_candidate) and not _is_anonymous_name(file_candidate):
        return file_candidate
    if platform_valid:
        return platform
    if _looks_like_name(file_candidate):
        return file_candidate
    if _looks_like_name(document):
        return document
    return platform if platform and not _PLATFORM_PLACEHOLDER_RE.search(platform) else ""


def is_trustworthy_resume_name(value: str) -> bool:
    """Return whether a stored value is plausible enough to preserve during repair."""

    return _looks_like_platform_name(_clean_name(value))


def is_anonymous_resume_name(value: str) -> bool:
    """Return whether a plausible platform name is intentionally masked."""

    return _is_anonymous_name(_clean_name(value))


def _candidate_lines(text: str) -> list[str]:
    lines = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = " ".join(raw.strip().split())
        if line:
            lines.append(line)
        if len(lines) >= 80:
            break
    return lines


def _looks_like_name(value: str) -> bool:
    candidate = _clean_name(value)
    if not candidate or len(candidate) > 40:
        return False
    if any(char.isdigit() for char in candidate) or "@" in candidate:
        return False
    if candidate.casefold() in _BLOCKED_EXACT:
        return False
    if _BLOCKED_FRAGMENT_RE.search(candidate):
        return False
    return bool(
        _CHINESE_NAME_RE.fullmatch(candidate)
        or _ENGLISH_NAME_RE.fullmatch(candidate)
    )


def _looks_like_platform_name(value: str) -> bool:
    if not value or _PLATFORM_PLACEHOLDER_RE.search(value):
        return False
    if _looks_like_name(value):
        return True
    return bool(_PLATFORM_ALIAS_RE.fullmatch(value) and not _BLOCKED_FRAGMENT_RE.search(value))


def _is_anonymous_name(value: str) -> bool:
    return bool(_ANONYMOUS_RE.search(value))


def _clean_name(value: str) -> str:
    return " ".join(str(value or "").strip(" \t\r\n_-—:：●•").split())


def _file_stem(file_name: str) -> str:
    name = Path(str(file_name or "")).name
    while name and Path(name).suffix.casefold() in {".pdf", ".doc", ".docx", ".txt"}:
        name = Path(name).stem
    return _NOISE_RE.sub("", name).strip(" _-—:：")
