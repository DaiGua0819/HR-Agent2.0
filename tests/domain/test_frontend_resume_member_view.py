"""Frontend contract tests for resume library member view."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_resume_library_uses_ten_items_per_page() -> None:
    """The resume library should request ten resumes per page by default."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'page_size: "10"' in script
    assert "resumePagination" in script


def test_member_resume_library_hides_admin_table_block() -> None:
    """Normal members hide the upper resume table while admins keep it."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="resumeTableBlock"' in html
    assert "member-resume-mode" in script
    assert ".member-resume-mode #resumeTableBlock" in styles
    page_block = styles.split(
        '.member-resume-mode [data-page="resumes"].active {', 1
    )[1].split("}", 1)[0]
    member_block = styles.split(".member-resume-mode .library-panel {", 1)[1].split("}", 1)[0]
    tabs_block = styles.split(".tabs {", 1)[1].split("}", 1)[0]

    assert "grid-template-rows: max-content minmax(560px, max-content)" in page_block
    assert "position: sticky" not in member_block
    assert "min-height: max-content" in member_block
    assert "min-height" in tabs_block
    assert "overflow-y: hidden" in tabs_block


def test_member_resume_library_has_large_job_tabs_above_status_tabs() -> None:
    """Members choose allowed jobs from a large job-tab strip above status tabs."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="jobTabsBlock"' in html
    assert html.index('id="jobTabsBlock"') < html.index('id="statusTabs"')
    assert "function buildJobTabs()" in script
    assert "resumeScope" in script and "jobFacets" in script
    assert "visibleStatusTabs()" in script
    assert 'key !== "needs_more_info" && key !== "queue"' in script
    assert ".job-tabs-panel" in styles
    assert ".job-tabs button" in styles
    assert "min-height: 48px" in styles
    job_tabs_block = styles.split(".job-tabs {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(8, minmax(0, 1fr))" in job_tabs_block
    assert "max-height: 118px" in job_tabs_block
    assert "overflow-x: hidden" in job_tabs_block


def test_resume_filters_have_enough_space_for_admin_fields() -> None:
    """Admin resume filters should not be clipped by the upper library panel."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    page_block = styles.split('[data-page="resumes"].active {', 1)[1].split("}", 1)[0]
    filters_block = styles.split(".filters {", 1)[1].split("}", 1)[0]

    assert "20260630-tdesign-refresh" in html
    assert "grid-template-rows: minmax(540px, 58vh) minmax(560px, auto)" in page_block
    assert "grid-template-columns: repeat(8, minmax(112px, 1fr))" in filters_block
    assert "padding: 10px 12px 14px" in filters_block


def test_tdesign_theme_adapter_is_loaded_without_replacing_native_controls() -> None:
    """The first TDesign pass should be a native-control-safe theme adapter."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "20260630-tdesign-refresh" in html
    assert "TDesign theme adapter" in styles
    for token in [
        "--td-brand-color",
        "--td-radius-medium",
        "--td-component-stroke",
        "--td-shadow-2",
    ]:
        assert token in styles
    assert "button, input, select { font: inherit; }" in styles
    assert '<select name="education">' in html
    assert '<input name="manual_review" type="checkbox" value="true" />' in html


def test_admin_resume_library_uses_legacy_all_job_tabs_and_labels() -> None:
    """Admins should see the old full resume-library job list with legacy labels."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "const RESUME_LIBRARY_JOB_TYPES = [" in script
    for job_type in [
        "AI应用开发实习生",
        "应用技术经理（工业涂料领域）",
        "膨润土销售人员",
        "销售管培生",
        "HRBP",
        "人力资源管培生",
        "国际业务管培生",
        "销售工程师（石油钻井泥浆膨润土）_湖州",
        "电气工程师",
        "运营A",
        "运营B",
        "外部财务产品顾问",
        "投资交易策略研究员（量化与市场情绪方向）",
        "AI智能体解决方案负责人",
    ]:
        assert f'"{job_type}"' in script
    for label in [
        "AI实习生",
        "应用技术",
        "人资管培",
        "石油销售",
        "财务顾问",
        "投资策略研究",
        "AI方案负责人",
    ]:
        assert f'"{label}"' in script
    assert "if (values.includes(\"*\")) return uniqueJobTypes(RESUME_LIBRARY_JOB_TYPES)" in script
    assert "function canonicalResumeJobType(value)" in script
    assert "function uniqueJobTypes(values)" in script
    assert "counts.set(job, Math.max" in script


def test_member_resume_library_hides_more_info_action() -> None:
    """Members do not need the needs-more-info review action."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert ".member-resume-mode #moreInfoBtn" in styles
    block = styles.split(".member-resume-mode #moreInfoBtn", 1)[1].split("}", 1)[0]
    assert "display: none" in block


def test_member_filters_hide_duplicate_job_and_use_education_select() -> None:
    """Member filters should rely on job tabs and offer fixed education choices."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="job-filter-field"' in html
    assert ".member-resume-mode .job-filter-field" in styles
    assert '<select name="education">' in html
    for degree in ["大专", "本科", "硕士", "博士"]:
        assert f'<option value="{degree}">{degree}</option>' in html
    assert 'class="date-filter-start"' in html
    assert 'class="date-filter-end"' in html


def test_resume_image_preview_has_single_scroll_container() -> None:
    """The rendered resume image should not create a nested vertical scrollbar."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    image_stage_block = styles.split(".resume-image-stage {", 1)[1].split("}", 1)[0]

    assert "overflow: auto" not in image_stage_block
    assert "overflow: visible" in image_stage_block


def test_resume_keyboard_navigation_crosses_page_boundaries() -> None:
    """Left/right shortcuts should move between resumes and across pages."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function bindResumeKeyboardNavigation()" in script
    assert "function shouldIgnoreResumeShortcut(event)" in script
    assert 'event.key === "ArrowLeft"' in script
    assert 'event.key === "ArrowRight"' in script
    assert "moveToAdjacentResume(-1)" in script
    assert "moveToAdjacentResume(1)" in script
    assert "state.page = targetPage" in script
    assert "direction > 0 ? state.resumes[0]" in script
    assert "state.resumes[state.resumes.length - 1]" in script
    assert "INPUT" in script and "TEXTAREA" in script and "SELECT" in script


def test_resume_library_prefetches_next_two_pages() -> None:
    """Resume browsing should preload two following list pages for fast next-page moves."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "resumePageCache" in script
    assert "resumeContextCache" in script
    assert "function resumeListCacheKey(page)" in script
    assert "function prefetchNextResumePages()" in script
    assert "for (const page of [state.page + 1, state.page + 2])" in script
    assert "state.resumePageCache.set(cacheKey, data)" in script
    assert "prefetchFirstResumeContext(data)" in script
    assert "loadResumes({ preferCache: true })" in script


def test_resume_prefetch_cache_is_invalidated_after_filters_and_review_actions() -> None:
    """Changing filters or saving review state must not reuse stale preloaded pages."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function clearResumePrefetchCache()" in script
    assert "clearResumePrefetchCache();" in script
    assert "await clearResumePrefetchCacheAfterMutation()" in script
    assert "function clearResumePrefetchCacheAfterMutation()" in script


def test_review_actions_advance_to_next_resume() -> None:
    """Review buttons should save the action and then open the next resume."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "async function advanceAfterReviewAction(id)" in script
    assert "async function markViewedAndAdvance(id)" in script
    assert 'api(`/api/resumes/${id}/view`, { method: "POST" })' in script
    assert "await advanceAfterReviewAction(id)" in script
    assert 'setDecision(state.selectedId, "suitable")' in script
    assert 'setDecision(state.selectedId, "unsuitable")' in script
    assert 'setDecision(state.selectedId, "needs_more_info")' in script
    assert "markViewedAndAdvance(state.selectedId)" in script


def test_resume_summary_shows_degree_and_import_time() -> None:
    """The right summary should keep degree and show import time instead of school."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function resumeSchool(resume)" in script
    assert "function resumeSchoolLevel(resume)" in script
    assert "function resumeEducationLine(resume)" in script
    assert "function resumeImportTime(resume)" in script
    assert "extractSchoolFromResumeText(resume)" in script
    assert "extractSchoolLevelFromResumeText(resume)" in script
    assert 'return degree || "待提取"' in script
    assert "学历：${resumeEducationLine(resume)}" in script
    assert '<p>学历：${escapeHtml(resumeEducationLine(resume))}</p>' in script
    assert '<p>入库时间：${escapeHtml(resumeImportTime(resume))}</p>' in script


def test_candidate_list_shows_school_tier_badge_next_to_name() -> None:
    """The left candidate list should show a compact school-tier badge beside names."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "20260630-tdesign-refresh" in html
    assert "function resumeSchoolTierBadge(resume)" in script
    assert 'if (level.includes("985")) return "985"' in script
    assert 'if (level.includes("211")) return "211"' in script
    assert 'class="mini-heading"' in script
    assert 'class="school-tier-badge"' in script
    assert ".mini-heading" in styles
    assert ".school-tier-badge" in styles


def test_workbench_is_tall_enough_for_ten_member_results() -> None:
    """The member workbench should show ten left-side candidates without scrolling."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    workbench_block = styles.split("grid-template-columns: 220px", 1)[1].split("}", 1)[0]

    assert "min-height: 704px" in workbench_block


def test_interview_button_uses_preflight_then_live_confirmation() -> None:
    """Interview invite should be a two-step preflight/live confirmation flow."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "async function confirmInterviewInvite()" in script
    assert "async function selectInterviewSession(sessionId)" in script
    assert "renderInterviewPreflight" in script
    assert '"confirmLive": true' in script
    assert '"dryRun": false' in script
    assert '"selectedSessionId": sessionId' in script
    assert "data-select-interview-session" in script
    assert "确认发起约面试" in script
