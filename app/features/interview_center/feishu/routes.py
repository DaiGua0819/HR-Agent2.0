"""Bitable table routing for the interview center.

The old interview center selected a Feishu Bitable table from the candidate's
job text before creating or updating records. This module keeps those default
routes in one place so calendar sync, asset sync, and backfill share the same
target resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.text import clean_text
from app.settings import load_settings


@dataclass(frozen=True)
class BitableRoute:
    """A configured Bitable table route."""

    table_id: str
    table_name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class BitableTarget:
    """Resolved Bitable target for a session/resume input."""

    table_id: str
    table_name: str = ""
    route_matched: bool = False
    route_keyword: str = ""
    job_text: str = ""
    route: BitableRoute | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses and logs."""

        return {
            "tableId": self.table_id,
            "tableName": self.table_name,
            "routeMatched": self.route_matched,
            "routeKeyword": self.route_keyword,
            "jobText": self.job_text,
            "route": {
                "tableId": self.route.table_id,
                "tableName": self.route.table_name,
                "keywords": list(self.route.keywords),
            }
            if self.route
            else None,
        }


DEFAULT_BITABLE_TABLE_ROUTES: tuple[BitableRoute, ...] = (
    BitableRoute(
        table_id="tblJTlyRbGdsbJmM",
        table_name="AI实习生",
        keywords=(
            "AI应用开发实习生",
            "AI应用开发工程师",
            "AI应用开发",
            "AI Agent开发",
            "AI实习生",
            "智能体",
            "Agent",
            "RAG",
        ),
    ),
    BitableRoute(
        table_id="tblbADJqkdRhRlxv",
        table_name="HR",
        keywords=("HRBP", "hrbp", "人力资源管培生", "人力资源", "HR"),
    ),
    BitableRoute(
        table_id="tblt5Wr599vRy9Oq",
        table_name="石油销售",
        keywords=(
            "销售工程师（石油钻井泥浆膨润土）",
            "石油钻井泥浆膨润土销售",
            "石油销售",
        ),
    ),
    BitableRoute(
        table_id="tbl1IXITxRv8uJhg",
        table_name="应用技术",
        keywords=(
            "应用技术经理（工业涂料领域）",
            "应用技术管培生（涂料领域）",
            "应用技术",
            "工业涂料",
        ),
    ),
    BitableRoute(
        table_id="tblbzO2P0T5d0kqE",
        table_name="销售管培生",
        keywords=("销售管培生",),
    ),
    BitableRoute(
        table_id="tblw4hW6JMm6PtML",
        table_name="国际业务管培生",
        keywords=("国际业务管培生",),
    ),
    BitableRoute(
        table_id="tblWR0OsR9y0FUmu",
        table_name="膨润土销售",
        keywords=("膨润土销售人员", "膨润土销售"),
    ),
    BitableRoute(
        table_id="tblWNla7BrBqZv6h",
        table_name="阳原电气工程师",
        keywords=("电气工程师", "阳原电气工程师"),
    ),
    BitableRoute(
        table_id="tbll8HD8jymNLNWg",
        table_name="沙粉销售",
        keywords=("沙粉销售",),
    ),
    BitableRoute(
        table_id="tblmSgGhJCU0rrMX",
        table_name="运营A表",
        keywords=(
            "运营A",
            "企业内容运营负责人（B2B/短视频方向）",
            "企业内容运营负责人",
            "B2B/短视频方向",
            "短视频方向",
            "内容运营负责人",
        ),
    ),
    BitableRoute(
        table_id="tblXyHjYr0Ba1rhe",
        table_name="运营B表",
        keywords=("运营B", "B端社交媒体运营", "社交媒体运营", "B端运营"),
    ),
    BitableRoute(
        table_id="tblEyxP6FuiSPZGO",
        table_name="投资交易策略研究员（量化与市场情绪方向）",
        keywords=(
            "投资交易策略研究员（量化与市场情绪方向）",
            "投资交易策略研究员",
            "量化与市场情绪方向",
        ),
    ),
    BitableRoute(
        table_id="tbloqD6Lc0BXi0vs",
        table_name="外部财务产品顾问",
        keywords=("外部财务产品顾问",),
    ),
    BitableRoute(
        table_id="tblLD6fXxV2RqFcw",
        table_name="AI智能体解决方案负责人",
        keywords=("AI智能体解决方案负责人", "智能体解决方案负责人"),
    ),
)


_ROUTE_SEPARATOR_RE = re.compile(r"[\s_\-—–、，,。；;|/\\()（）\[\]【】]+")


def resolve_bitable_target(
    input: dict[str, Any] | None = None,
    default_table_id: str = "",
) -> BitableTarget:
    """Resolve the old interview-center Bitable route for a session/resume input."""

    data = input or {}
    routes = _default_routes(default_table_id)
    job_text = _bitable_route_job_text(data)
    normalized_job_text = _normalize_route_text(job_text)
    matched_keyword = ""
    matched_route = None
    if normalized_job_text:
        for route in routes:
            matched_keyword = next(
                (
                    keyword
                    for keyword in route.keywords
                    if _normalize_route_text(keyword)
                    and _normalize_route_text(keyword) in normalized_job_text
                ),
                "",
            )
            if matched_keyword:
                matched_route = route
                break
    if matched_route:
        return BitableTarget(
            table_id=matched_route.table_id,
            table_name=matched_route.table_name,
            route_matched=True,
            route_keyword=matched_keyword,
            job_text=job_text,
            route=matched_route,
        )
    return BitableTarget(table_id=default_table_id, job_text=job_text)


def _default_routes(default_table_id: str = "") -> tuple[BitableRoute, ...]:
    routes = [*DEFAULT_BITABLE_TABLE_ROUTES]
    ai_product_manager_table_id = load_settings().feishu.ai_product_manager_table_id
    if ai_product_manager_table_id:
        routes.append(
            BitableRoute(
                table_id=ai_product_manager_table_id,
                table_name="AI产品经理",
                keywords=(
                    "AI产品经理",
                    "AI 产品经理",
                    "AI Product Manager",
                    "AI PM",
                ),
            )
        )
    if not default_table_id:
        return tuple(routes)
    return tuple(
        BitableRoute(
            table_id=default_table_id if route.table_name == "AI实习生" else route.table_id,
            table_name=route.table_name,
            keywords=route.keywords,
        )
        for route in routes
    )


def _bitable_route_job_text(input: dict[str, Any]) -> str:
    session = _dict_value(input.get("session")) or input
    resume = (
        _dict_value(input.get("resume"))
        or _dict_value(session.get("resume"))
        or _dict_value(session.get("matchedResume"))
        or {}
    )
    values = [
        resume.get("jobType"),
        resume.get("job_type"),
        resume.get("appliedPosition"),
        resume.get("applied_position"),
        resume.get("position"),
        resume.get("fileName"),
        resume.get("file_name"),
        session.get("resume", {}).get("jobType")
        if isinstance(session.get("resume"), dict)
        else "",
        session.get("resume", {}).get("job_type")
        if isinstance(session.get("resume"), dict)
        else "",
        session.get("matchedResume", {}).get("jobType")
        if isinstance(session.get("matchedResume"), dict)
        else "",
        session.get("matched_resume", {}).get("job_type")
        if isinstance(session.get("matched_resume"), dict)
        else "",
        session.get("jobType"),
        session.get("job_type"),
        session.get("position"),
        session.get("title"),
        session.get("summary"),
        session.get("description"),
    ]
    return " ".join(clean_text(value) for value in values if clean_text(value))


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_route_text(value: Any) -> str:
    return _ROUTE_SEPARATOR_RE.sub("", clean_text(value)).lower()
