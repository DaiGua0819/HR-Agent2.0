"""Deterministic Chinese renderers for Feishu bot query results."""

from __future__ import annotations

from app.core.text import clean_text
from app.features.feishu_bot.models import BotActor, BotQueryResult

UNAUTHORIZED_TEXT = "当前账号未获授权使用招聘查询机器人。"
GROUP_HELP_TEXT = "为保护招聘数据，本机器人仅在授权用户的单聊中提供查询。"
PERMISSION_DENIED_TEXT = "当前账号无权查询这项招聘数据。"
DATA_UNAVAILABLE_TEXT = "招聘数据暂不可用，请稍后再试。"
POLICY_VIOLATION_TEXT = "本次查询未通过安全校验，请换一种方式提问。"


def render_help(actor: BotActor | None = None) -> str:
    lines = [
        "可查询：岗位处理日报、简历数量、最近简历、审阅统计。",
        "示例：昨天 AI 产品经理处理了多少人？",
    ]
    if actor is not None and actor.is_admin:
        lines.append("管理员还可查询 Worker 状态和最近异常。")
    if actor is not None and actor.can("control:runtime"):
        lines.append("运行控制：启动处理程序、暂停处理程序、查看处理状态。")
    return "\n".join(lines)


def render_query_result(actor: BotActor, result: BotQueryResult) -> str:
    if result.intent == "daily_summary":
        return _render_daily_summary(result)
    if result.intent == "resume_counts":
        return _render_resume_counts(result)
    if result.intent == "recent_resumes":
        return _render_recent_resumes(result)
    if result.intent == "review_summary":
        return _render_review_summary(result)
    if result.intent == "worker_status":
        return _render_worker_status(result)
    if result.intent == "recent_errors":
        return _render_recent_errors(result)
    if result.intent == "help":
        return render_help(actor)
    clarification = clean_text(result.data.get("clarification"))
    return clarification or render_help(actor)


def _render_daily_summary(result: BotQueryResult) -> str:
    data = result.data
    totals = _mapping(data.get("totals"))
    date = clean_text(data.get("date")) or "所选日期"
    lines = [
        f"{date} 处理汇总",
        f"处理联系人：{_integer(totals.get('processedContacts'))} 人",
        f"业务简历获取：{_integer(totals.get('businessResumeAcquisitions'))} 份",
        f"待简历回复：{_integer(totals.get('resumeRequestsWaiting'))} 人",
        f"异常：{_integer(totals.get('anomalies'))} 人",
    ]
    rows = _records(data.get("byJobPlatform"))
    for row in rows[:20]:
        job = clean_text(row.get("job")) or "未归类岗位"
        platform = clean_text(row.get("platform")) or "未知平台"
        processed = _integer(row.get("processedContacts"))
        resumes = _integer(row.get("businessResumeAcquisitions"))
        lines.append(f"{job}｜{platform}：处理 {processed}，简历 {resumes}")
    coverage = result.coverage
    unmapped = _integer(coverage.get("unmappedContacts"))
    if unmapped:
        lines.append(f"覆盖提示：另有 {unmapped} 条处理记录无法映射岗位。")
    if coverage.get("managerRunsAvailable") is False:
        lines.append("覆盖提示：本次未读取到处理运行日志。")
    return "\n".join(lines)


def _render_resume_counts(result: BotQueryResult) -> str:
    data = result.data
    lines = [f"简历共 {_integer(data.get('total'))} 份"]
    for row in _records(data.get("byJob"))[:30]:
        job = clean_text(row.get("jobType")) or "未归类岗位"
        lines.append(f"{job}：{_integer(row.get('count'))} 份")
    return "\n".join(lines)


def _render_recent_resumes(result: BotQueryResult) -> str:
    items = _records(result.data.get("items"))
    if not items:
        return "没有找到符合权限范围的最近简历。"
    lines = ["最近简历"]
    for index, item in enumerate(items[:20], start=1):
        name = clean_text(item.get("name")) or "未命名候选人"
        job = clean_text(item.get("jobType")) or "未归类岗位"
        score = _integer(item.get("score"))
        platform = clean_text(item.get("platform")) or "未知平台"
        owner = clean_text(item.get("owner"))
        suffix = f"｜{owner}" if owner else ""
        lines.append(f"{index}. {name}｜{job}｜{score} 分｜{platform}{suffix}")
    return "\n".join(lines)


def _render_review_summary(result: BotQueryResult) -> str:
    data = result.data
    decisions = _mapping(data.get("decisions"))
    suitable = _integer(decisions.get("suitable"))
    unsuitable = _integer(decisions.get("unsuitable"))
    supplement = _integer(
        decisions.get("needs_supplement") or decisions.get("needsSupplement")
    )
    lines = [
        f"审阅共 {_integer(data.get('total'))} 份",
        f"合适：{suitable}｜不合适：{unsuitable}｜待补充：{supplement}",
    ]
    if clean_text(data.get("scope")) == "admin":
        lines.append(f"共享待处理：{_integer(data.get('sharedPending'))} 份")
    return "\n".join(lines)


def _render_worker_status(result: BotQueryResult) -> str:
    items = _records(result.data.get("items"))
    if not items:
        return "当前没有可用的 Worker 状态。"
    lines = ["Worker 状态"]
    for item in items[:30]:
        owner = clean_text(item.get("owner")) or "未知账号"
        platform = clean_text(item.get("platform")) or "all"
        status = _worker_status_label(clean_text(item.get("status")))
        lines.append(f"{owner}｜{platform}｜{status}")
    return "\n".join(lines)


def _render_recent_errors(result: BotQueryResult) -> str:
    items = _records(result.data.get("items"))
    if not items:
        return "最近没有记录到处理异常。"
    lines = ["最近异常"]
    for index, item in enumerate(items[:20], start=1):
        timestamp = clean_text(item.get("timestamp")) or "时间未知"
        owner = clean_text(item.get("owner")) or "未知账号"
        platform = clean_text(item.get("platform")) or "未知平台"
        reason = clean_text(item.get("reason")) or "未提供原因"
        lines.append(f"{index}. {timestamp}｜{owner}｜{platform}｜{reason}")
    return "\n".join(lines)


def _worker_status_label(value: str) -> str:
    return {
        "ready": "就绪",
        "busy": "处理中",
        "offline": "离线",
        "error": "异常",
    }.get(value.lower(), value or "未知")


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
