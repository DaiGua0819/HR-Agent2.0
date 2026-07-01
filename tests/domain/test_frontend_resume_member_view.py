"""Frontend contract tests for resume library member view."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_resume_library_uses_ten_items_per_page() -> None:
    """The resume library should request ten resumes per page by default."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'page_size: "10"' in script
    assert "resumePagination" in script


def test_authenticated_resume_library_uses_stitch_layout() -> None:
    """The authenticated resume page should use the Stitch-inspired browsing shell."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "TalentStream HR" in html
    assert 'class="ts-app-shell"' in html
    assert 'class="ts-filter-card"' in html
    assert 'class="ts-resume-surface"' in html
    assert 'id="miniList"' in html
    assert 'id="resumePreview"' in html
    assert 'id="resumeTableBlock"' not in html
    assert "function bindDockEffect" in script
    assert ".candidate-card" in styles
    assert ".ts-resume-surface" in styles


def test_frontend_lands_on_resume_library_after_login() -> None:
    """The authenticated app should treat the Stitch resume page as the landing page."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const landingView = canView("resumes") ? "resumes" : uiAccess().defaultView' in script
    assert "setView(landingView)" in script


def test_member_resume_library_uses_single_stitch_workspace() -> None:
    """Normal members should land in the same airy resume workspace without the legacy table."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="resumeTableBlock"' not in html
    assert "member-resume-mode" in script
    assert ".member-resume-mode .ts-app-shell" in styles
    page_block = styles.split(
        '.member-resume-mode [data-page="resumes"].active {', 1
    )[1].split("}", 1)[0]
    tabs_block = styles.split(".ts-status-tabs {", 1)[1].split("}", 1)[0]

    assert "grid-template-rows: minmax(0, 1fr)" in page_block
    assert "display: flex" in tabs_block
    assert "overflow-x: auto" in tabs_block


def test_member_resume_library_hides_sidebar_navigation() -> None:
    """Members should use the resume library directly without the old left sidebar."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "20260701-stitch-resume" in html
    assert 'class="sidebar"' not in html
    shell_block = styles.split(".member-resume-mode .ts-app-shell {", 1)[1].split("}", 1)[0]

    assert "min-height: 100vh" in shell_block


def test_member_resume_library_has_dock_job_filters_below_status_tabs() -> None:
    """Members choose allowed jobs from the Stitch dock filter row."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="jobTabsBlock"' in html
    assert html.index('id="statusTabs"') < html.index('id="jobTabsBlock"')
    assert "function buildJobTabs()" in script
    assert "resumeScope" in script and "jobFacets" in script
    assert "visibleStatusTabs()" in script
    assert '["undecided", "待判断"]' not in script
    assert '!["undecided", "needs_more_info", "queue"].includes(key)' in script
    assert ".ts-filter-tags-panel" in styles
    assert ".filter-tag" in styles
    assert "bindDockEffect($(\"jobTabs\")" not in script
    job_tabs_block = styles.split(".ts-filter-tags {", 1)[1].split("}", 1)[0]
    filter_tag_block = styles.split(".filter-tag {", 1)[1].split("}", 1)[0]
    assert "display: flex" in job_tabs_block
    assert "flex-wrap: wrap" in job_tabs_block
    assert "transform:" not in filter_tag_block
    assert "margin 0.1s" not in filter_tag_block


def test_resume_status_and_job_filters_are_collapsible_beside_filter_button() -> None:
    """Status tabs and job tags should collapse from a button placed left of filters."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="segmentToggleBtn"' in html
    assert 'id="filterToggleBtn"' in html
    assert html.index('id="segmentToggleBtn"') < html.index('id="filterToggleBtn"')
    assert 'id="segmentPanel"' in html
    assert html.index('id="segmentPanel"') < html.index('id="statusTabs"') < html.index('id="jobTabsBlock"')
    assert html.index('id="jobTabsBlock"') < html.index('id="miniList"')
    assert "function toggleSegmentPanel()" in script
    assert '$("segmentToggleBtn").onclick = toggleSegmentPanel' in script
    assert ".ts-filter-head-actions" in styles
    assert ".ts-segment-panel" in styles
    assert ".ts-segment-panel:not(.is-open)" in styles
    segment_block = styles.split(".ts-segment-panel {", 1)[1].split("}", 1)[0]
    assert "transition: max-height" in segment_block


def test_resume_library_panel_can_collapse_as_a_whole() -> None:
    """The left resume library panel should collapse sideways to enlarge the preview."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="resumeLibraryPanel" class="ts-filter-card"' in html
    assert 'id="libraryToggleBtn"' in html
    assert 'aria-controls="resumeLibraryPanel"' in html
    assert html.index('id="libraryToggleBtn"') < html.index('id="segmentToggleBtn"')
    assert "function toggleLibraryPanel()" in script
    assert '$("libraryToggleBtn").onclick = toggleLibraryPanel' in script
    assert "is-library-collapsed" in script
    assert 'panel.closest(".ts-resume-workspace")' in script
    assert ".ts-resume-workspace.is-library-collapsed" in styles
    collapsed_workspace = styles.split(".ts-resume-workspace.is-library-collapsed {", 1)[1].split(
        "}",
        1,
    )[0]
    assert "grid-template-columns: 56px minmax(0, 1fr)" in collapsed_workspace
    assert ".ts-filter-card.is-library-collapsed" in styles
    collapsed_panel = styles.split(".ts-filter-card.is-library-collapsed {", 1)[1].split(
        "}",
        1,
    )[0]
    assert "inline-size: 56px" in collapsed_panel
    assert ".ts-filter-card.is-library-collapsed .ts-candidate-list" in styles
    assert ".ts-filter-card.is-library-collapsed .pagination" in styles


def test_resume_filters_live_in_collapsible_stitch_card() -> None:
    """Resume filters should fit inside the collapsible Stitch filter panel."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    page_block = styles.split('[data-page="resumes"].active {', 1)[1].split("}", 1)[0]
    filters_block = styles.split(".filters {", 1)[1].split("}", 1)[0]

    assert "20260701-stitch-resume" in html
    assert "grid-template-rows: minmax(0, 1fr)" in page_block
    assert 'id="filterToggleBtn"' in html
    assert 'id="filterPanel"' in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in filters_block
    assert "transition: max-height" in styles


def test_resume_filter_form_uses_aligned_native_selects_for_compact_fields() -> None:
    """The compact filter form should use aligned native selects for low-frequency filters."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    filter_form = html.split('<form class="filters ts-filter-form" id="filters">', 1)[1].split(
        "</form>",
        1,
    )[0]

    for removed_text in [
        "关键词",
        "所有招聘人员",
        "平台",
        "状态",
        "分数",
        "分数上限",
        "入库开始",
        "入库结束",
        "排序",
        "仅查看需复核",
    ]:
        assert removed_text not in filter_form
    for removed_field in [
        'name="owner"',
        'name="platform"',
        'name="decision"',
        'name="score_min"',
        'name="score_max"',
        'name="date_from"',
        'name="date_to"',
        'name="manual_review"',
    ]:
        assert removed_field not in filter_form
    assert '<input name="q" type="hidden" />' in filter_form
    assert 'class="filter-field--compact education-filter-field"' in filter_form
    assert 'class="filter-field--compact school-level-filter-field"' in filter_form
    assert 'class="filter-field--compact graduation-year-filter-field"' in filter_form
    assert 'class="filter-field--compact sort-filter-field"' in filter_form
    assert filter_form.index('name="education"') < filter_form.index('name="school_level"')
    assert filter_form.index('name="graduation_year"') < filter_form.index('name="sort"')
    assert 'select name="school_level" multiple' not in filter_form
    assert 'select name="graduation_year" multiple' not in filter_form
    assert '<select name="school_level">' in filter_form
    assert '<option value="">院校等级</option>' in filter_form
    assert '<select name="graduation_year">' in filter_form
    assert '<option value="">毕业时间</option>' in filter_form
    assert '<span>排序</span>' not in filter_form
    assert '<option value="name">姓名</option>' not in filter_form
    assert ".filter-field--compact" in styles
    assert ".visually-hidden" in styles


def test_serene_talent_theme_is_loaded_without_replacing_native_controls() -> None:
    """The Stitch migration should keep native controls while using the new theme."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "20260701-stitch-resume" in html
    assert "Serene Talent Ledger" in styles
    for token in [
        "--ts-primary",
        "--ts-surface",
        "--ts-outline-variant",
        "--ts-shadow",
    ]:
        assert token in styles
    assert "button, input, select { font: inherit; }" in styles
    assert '<select name="education">' in html
    assert 'name="manual_review"' not in html


def test_stitch_component_layer_styles_dynamic_controls() -> None:
    """Dynamic buttons, tags, segments, and pagination should share Stitch classes."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for helper in [
        "function tsButtonClass",
        "function tsTagClass",
        "function tsSegmentClass",
    ]:
        assert helper in script
    for class_name in [
        ".ts-btn",
        ".ts-btn--primary",
        ".ts-tag",
        ".ts-tag--success",
        ".ts-segment-button",
        ".ts-pagination",
    ]:
        assert class_name in styles
    assert "tsButtonClass(\"primary\")" in script
    assert "tsTagClass(review.decision)" in script
    assert "tsSegmentClass(state.tab === key)" in script
    assert "ts-pagination" in script


def test_stitch_migration_preserves_formdata_and_adds_visual_wrappers() -> None:
    """The Stitch page should style filters/previews without changing query semantics."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="filters ts-filter-form"' in html
    assert 'class="ts-resume-surface"' in html
    assert 'class="detail-block ts-preflight-panel"' in html
    assert 'new FormData($("filters"))' in script
    assert 'params[multiFilterKeys.has(key) ? "append" : "set"](key, cleaned)' in script
    assert '<select name="school_level">' in html
    assert 'select name="school_level" multiple' not in html
    assert 'select name="decision" multiple' not in html
    assert '<select name="graduation_year">' in html
    assert 'select name="graduation_year" multiple' not in html
    assert 'name="date_from"' not in html
    assert 'name="date_to"' not in html
    for class_name in [
        ".ts-filter-form",
        ".ts-resume-surface",
        ".ts-summary-card",
        ".ts-preflight-card",
        ".ts-empty-state",
    ]:
        assert class_name in styles
    assert "ts-preflight-card" in script


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


def test_member_action_dock_only_keeps_suitable_choices_at_bottom_right() -> None:
    """Members should only see suitable/unsuitable actions under the summary cards."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for selector in [
        ".member-resume-mode #viewedBtn",
        ".member-resume-mode #moreInfoBtn",
        ".member-resume-mode #interviewBtn",
    ]:
        assert selector in styles
        block = styles.split(selector, 1)[1].split("}", 1)[0]
        assert "display: none" in block

    summary_markup = html.split('<aside id="summaryContent" class="summary-content ts-summary-stack">', 1)[
        1
    ].split("</aside>", 1)[0]
    assert 'id="summaryCards"' in summary_markup
    assert 'id="actionDock"' in summary_markup
    dock_block = styles.split(".member-resume-mode .ts-action-dock {", 1)[1].split("}", 1)[0]

    assert "position: sticky" in dock_block
    assert "bottom: 0" in dock_block
    assert "justify-content: stretch" in dock_block


def test_member_filters_hide_duplicate_job_and_use_education_select() -> None:
    """Member filters should rely on job tabs and offer fixed education choices."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="job-filter-field"' in html
    assert ".member-resume-mode .job-filter-field" in styles
    assert '<select name="education">' in html
    for degree in ["大专", "本科", "硕士", "博士"]:
        assert f'<option value="{degree}">{degree}</option>' in html
    assert 'class="date-filter-start"' not in html
    assert 'class="date-filter-end"' not in html


def test_resume_image_preview_has_single_scroll_container() -> None:
    """The rendered resume image should not create a nested vertical scrollbar."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    image_stage_block = styles.split(".resume-image-stage {", 1)[1].split("}", 1)[0]

    assert "overflow: auto" not in image_stage_block
    assert "overflow: visible" in image_stage_block


def test_resume_image_preview_left_click_downloads_file() -> None:
    """The resume preview image should be wrapped in a download link."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "resume-download-link" in script
    assert "download class=\"resume-download-link\"" in script
    assert "'/api/resumes/' + resume.id + '/download'" in script
    assert ".resume-download-link" in styles


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


def test_resume_keyboard_navigation_scrolls_selected_card_into_view() -> None:
    """Left/right shortcuts should keep the selected candidate card visible."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function scrollSelectedCandidateIntoView()" in script
    assert '.candidate-card.active' in script
    assert "scrollIntoView" in script
    assert 'block: "nearest"' in script
    assert 'behavior: "smooth"' in script
    assert "requestAnimationFrame(scrollSelectedCandidateIntoView)" in script


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
    """The right summary should show degree with school tier and import time."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function resumeSchool(resume)" in script
    assert "function resumeSchoolLevel(resume)" in script
    assert "function resumeEducationLine(resume)" in script
    assert "function resumeImportTime(resume)" in script
    assert "extractSchoolFromResumeText(resume)" in script
    assert "extractSchoolLevelFromResumeText(resume)" in script
    assert 'return degree || "待提取"' in script
    assert "学历：${resumeEducationLine(resume)}" in script
    assert "const schoolTier = resumeSchoolTierBadge(resume) || resumeSchoolLevel(resume)" in script
    assert 'class="summary-school-level"' in script
    assert '<p>入库时间：${escapeHtml(resumeImportTime(resume))}</p>' in script


def test_resume_summary_removes_source_and_review_cards() -> None:
    """The summary pane should keep only candidate/score cards and the review actions."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert '$("summaryCards").innerHTML = `' in script
    render_context = script.split("function renderContext()", 1)[1]
    render_block = render_context.split('$("summaryCards").innerHTML = `', 1)[1].split("`;", 1)[0]

    assert "<h3>候选人</h3>" in render_block
    assert "<h3>评分</h3>" in render_block
    assert "<h3>来源</h3>" not in render_block
    assert "<h3>审阅</h3>" not in render_block
    assert ".summary-school-level" in styles


def test_candidate_list_shows_school_tier_badge_next_to_name() -> None:
    """The left candidate cards should show a compact school-tier badge beside names."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "20260701-stitch-resume" in html
    assert "function resumeSchoolTierBadge(resume)" in script
    assert 'if (level.includes("985")) return "985"' in script
    assert 'if (level.includes("211")) return "211"' in script
    assert 'class="candidate-card__heading"' in script
    assert 'class="school-tier-badge"' in script
    assert ".candidate-card__heading" in styles
    assert ".school-tier-badge" in styles


def test_candidate_card_metadata_uses_aligned_columns() -> None:
    """School, tier, date, platform, and read status should line up across cards."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="candidate-card__meta-item candidate-card__meta-school"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-tier"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-date"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-platform"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-read"' in script
    meta_block = styles.split(".candidate-card__meta {", 1)[1].split("}", 1)[0]

    assert "display: grid" in meta_block
    assert "grid-template-columns:" in meta_block
    assert ".candidate-card__meta-item" in styles
    assert ".candidate-card__meta-school" in styles
    assert "text-overflow: ellipsis" in styles


def test_resume_summary_panel_uses_tighter_horizontal_padding() -> None:
    """The right summary column should give more width back to the resume content."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    summary_block = styles.split(".summary-content {", 1)[1].split("}", 1)[0]
    card_block = styles.split(".ts-summary-card {", 1)[1].split("}", 1)[0]

    assert "padding: 12px 10px" in summary_block
    assert "padding: 10px" in card_block


def test_stitch_workspace_keeps_candidate_list_and_preview_same_viewport() -> None:
    """The Stitch workspace should keep candidates and resume preview in one viewport."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    workbench_block = styles.split(".ts-resume-workspace {", 1)[1].split("}", 1)[0]

    assert "grid-template-columns: 378px minmax(0, 1fr)" in workbench_block
    assert "height: calc(100vh - 88px)" in workbench_block


def test_stitch_workspace_fits_codex_side_browser_viewport() -> None:
    """The authenticated resume browser should adapt to the narrow Codex side pane."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "/assets/styles.css?v=20260701-stitch-resume-summary-actions" in html
    assert "@media (max-width: 700px)" in styles
    side_browser_block = styles.split("@media (max-width: 700px)", 1)[1]
    body_block = side_browser_block.split("body {", 1)[1].split("}", 1)[0]
    topbar_block = side_browser_block.split(".ts-topbar {", 1)[1].split("}", 1)[0]
    workspace_block = side_browser_block.split(".ts-resume-workspace {", 1)[1].split("}", 1)[0]
    action_dock_block = side_browser_block.split(
        ".member-resume-mode .ts-action-dock {", 1
    )[1].split("}", 1)[0]

    assert "overflow-x: hidden" in body_block
    assert "overflow-y: auto" in body_block
    assert "padding: 10px" in topbar_block
    assert "grid-template-columns: minmax(0, 1fr)" in workspace_block
    assert "min-height: 0" in workspace_block
    assert "gap: 6px" in action_dock_block
    assert "padding: 8px 0 0" in action_dock_block


def test_stitch_dock_effects_skip_job_tabs() -> None:
    """The exported Stitch dock motion should stay off job tabs while remaining on cards/actions."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function bindDockEffect" in script
    assert "requestAnimationFrame" in script
    assert "mousemove" in script
    assert "mouseleave" in script
    assert "candidate-card" in script
    assert "filter-tag" in script
    assert "action-dock-btn" in script
    assert "bindDockEffect($(\"jobTabs\")" not in script
    assert ".candidate-card" in styles
    assert ".filter-tag" in styles
    assert ".action-dock-btn" in styles


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
