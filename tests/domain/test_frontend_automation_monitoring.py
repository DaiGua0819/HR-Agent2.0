from pathlib import Path

from app.control_plane.main import create_app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def test_admin_dashboard_contains_daily_monitoring_surfaces() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "monitoringDate",
        "monitoringDateButton",
        "monitoringDateLabel",
        "monitoringPlatform",
        "monitoringOwner",
        "monitoringJobType",
        "monitoringKpiGrid",
        "monitoringJobRows",
        "monitoringJobChart",
        "monitoringJobChartTotal",
        "monitoringJobChartLegend",
        "monitoringAccountStatusGrid",
    ):
        assert f'id="{element_id}"' in html

    assert 'type="date" tabindex="-1" aria-hidden="true"' in html
    assert 'id="quickFilters"' not in html
    assert 'id="dailyRows"' not in html
    assert 'id="dailyEmpty"' not in html
    assert "最近处理明细" not in html
    assert 'id="runtimeStatusGrid"' not in html
    assert 'id="runtimeStatusUpdatedAt"' not in html
    assert "/api/automation-monitoring/daily-summary" in script
    assert "/api/automation-monitoring/runtime-status" in script
    assert "function renderMonitoringAccountStatuses(items = [])" in script
    assert "async function loadAutomationRuntimeStatus()" in script
    assert "monitoringRuntimeAbortController: null" in script
    assert 'label: "处理中"' in script
    assert 'label: "待登录"' in script
    assert 'label: "安全验证"' in script
    assert 'label: "账号异常"' in script
    assert 'label: "Worker 离线"' in script
    assert 'heartbeat_timeout: "心跳超时"' in script
    assert 'no_heartbeat: "暂无心跳"' in script
    assert "reason.slice(3)" not in script
    assert "renderQuickFilters" not in script
    assert "renderDailyRows" not in script
    assert "dailyEmpty" not in script
    assert "MONITORING_SUMMARY_POLL_MS = 15000" in script
    assert "monitoringSummaryAbortController: null" in script
    assert 'monitoringSummaryRequestKey: ""' in script
    assert "state.monitoringSummaryAbortController.abort()" in script
    assert "signal: controller.signal" in script
    assert "const requestKey = monitoringQuery().toString()" in script
    assert "requestKey !== monitoringQuery().toString()" in script
    assert "document.visibilityState" in script
    assert "function formatMonitoringDate(value)" in script
    assert 'return `${year}/${month}/${day}`' in script
    assert "monitoringDate.showPicker()" in script
    assert "openAutomationDetails" in script
    assert "window.location.assign(`/app/automation-details?${query}`)" in script
    assert "if (!isAdminUser()) return" in script
    assert '["sentCompanyInfo",' not in script
    assert '["anomalies",' not in script
    assert "monitoring-job-stat--danger" not in script
    assert "function normalizeMonitoringCount(value)" in script
    assert "Number.isFinite(number) ? number : 0" in script
    assert "function groupMonitoringJobs(items = [])" in script
    assert "function buildMonitoringJobChartSlices(items = [])" in script
    assert "function renderMonitoringJobChart(items = [])" in script
    assert "tooltip.offsetWidth" in script
    assert 'tooltip.classList.toggle("is-below"' in script
    assert 'label: "其他岗位"' in script
    assert "MONITORING_JOB_CHART_COLORS" in script
    assert ".monitoring-kpi" in styles
    assert ".monitoring-date-control" in styles
    assert ".monitoring-job-chart" in styles
    assert ".monitoring-job-chart-tooltip" in styles
    assert ".monitoring-job-chart-tooltip.is-below" in styles
    assert ".monitoring-account-status-grid" in styles
    assert ".monitoring-account-status-row" in styles
    assert "grid-auto-flow: column" in styles
    assert "height: 500px" in styles
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in styles
    assert "grid-template-columns: minmax(240px, 1fr) 76px 76px" in styles
    assert "grid-template-rows: auto auto auto max-content" in styles
    assert "min-width: 140px" in styles
    assert "@media (min-width: 1181px)" in styles
    assert "height: 100vh" in styles
    assert "overflow-y: auto" in styles
    assert "@media (max-width: 1320px)" in styles


def test_automation_details_page_is_admin_guarded_and_queries_details() -> None:
    html_path = ROOT / "frontend" / "automation-details.html"
    script_path = ROOT / "frontend" / "automation-details.js"

    assert html_path.is_file()
    assert script_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    script = script_path.read_text(encoding="utf-8")

    assert 'id="automationDetailsTable"' in html
    assert 'id="detailsPagination"' in html
    assert "/assets/automation-details.js?v=20260720-weekly-data-v3" in html
    assert "/api/auth/me" in script
    assert "/api/automation-monitoring/daily-details" in script
    assert 'query.set("page_size", "10")' in script
    assert 'request_resume: "求简历"' in script
    assert 'request_resume_action_failed: "求简历失败"' in script
    assert 'online_resume_button_not_found: "未找到在线简历按钮"' in script
    assert 'boss_request_verified_server_imap: "已求简历，等待服务器邮箱入库"' in script
    assert 'local_resume_downloaded: "简历已下载并入库"' in script
    assert 'resume_requested_waiting: "已求简历，等待候选人发送"' in script
    assert "function resumeHandlingLabel(value)" in script
    for action in ("ask_basic_conditions", "escalate", "send_failed"):
        assert f"{action}:" in script
    for stage in (
        "candidate_rejected",
        "chat_context_not_ready",
        "direct_resume_prompt_send_failed",
        "ignored_position",
        "last_message_not_candidate",
        "resume_download_unavailable_skipped",
        "screening_unclear",
        "unconfigured_position",
    ):
        assert f"{stage}:" in script
    assert "function actionLabel(value)" in script
    assert 'String(value).split(";")' in script
    assert "basic_phrase_send_failed:" in script
    assert 'return resumeHandlingLabels[value] || "其他简历状态"' in script
    assert "function stageLabel(value)" in script
    assert "function formatAutomationDate(value)" in script
    assert "function formatAutomationDateTime(value)" in script
    assert "formatAutomationDate(query.get(\"date\")" in script
    assert 'return stageLabels[value] || "其他阶段"' in script
    assert 'anomalyReasonLabels[item] || "其他异常"' in script
    assert "resumeDownloadUrl" in script
    assert "下载简历" in html
    assert 'window.location.replace("/index.html")' in script

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/app/automation-details")

    assert response.status_code == 200
    assert "每日处理明细" in response.text
