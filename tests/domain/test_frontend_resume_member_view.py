"""Frontend contract tests for resume library member view."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_admin_resume_preview_has_right_click_conversation_modal_contract() -> None:
    """Admins can open a guarded read-only conversation modal from the preview."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="resumeConversationModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert "function handleResumePreviewContextMenu(event)" in script
    assert "if (!isAdminUser() || !state.selectedId) return" in script
    assert "event.preventDefault()" in script
    assert 'api(`/api/resumes/${resumeId}/conversation`' in script
    assert "resumeConversationAbortController" in script
    assert "resumeConversationRequestSequence" in script
    assert "resume-conversation-date" in script
    assert "if (requestSequence !== state.resumeConversationRequestSequence) return" in script
    assert "if (state.selectedId !== resumeId) return" in script


def test_member_right_click_keeps_browser_default_menu() -> None:
    """Member context menus must not be intercepted by the conversation affordance."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    block = script.split("function handleResumePreviewContextMenu(event)", 1)[1].split(
        "async function openResumeConversation", 1
    )[0]

    assert block.index("if (!isAdminUser() || !state.selectedId) return") < block.index(
        "event.preventDefault()"
    )


def test_resume_conversation_failure_and_selection_clears_cannot_leave_stale_modal() -> None:
    """Conversation errors and every selection reset must cancel the visible conversation."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    close_call = "closeResumeConversation({ immediate: true })"
    selected_clear = 'state.selectedId = ""'

    conversation_block = script.split("async function openResumeConversation()", 1)[1].split(
        "function selectedReviewState()", 1
    )[0]
    failure_block = conversation_block.split("} catch (error) {", 1)[1].split(
        "} finally {", 1
    )[0]
    assert "if (state.selectedId !== resumeId) return" in failure_block
    assert failure_block.index("if (state.selectedId !== resumeId) return") < failure_block.index(
        '$("resumeConversationMessages").innerHTML'
    )

    auth_block = script.split("function handleAuthExpired(error)", 1)[1].split(
        "function escapeHtml", 1
    )[0]
    queue_block = script.split("function applySharedQueueData", 1)[1].split(
        "function renderRows", 1
    )[0]
    advance_block = script.split("async function advanceAfterReviewAction(id)", 1)[1].split(
        "async function requestInterview", 1
    )[0]
    logout_block = script.split("async function logout()", 1)[1].split("async function init", 1)[0]

    for block in (auth_block, queue_block, logout_block):
        assert block.index(close_call) < block.index(selected_clear)

    clear_positions = [
        index
        for index in range(len(advance_block))
        if advance_block.startswith(selected_clear, index)
    ]
    assert len(clear_positions) == 2
    assert all(advance_block.rfind(close_call, 0, index) != -1 for index in clear_positions)


def test_resume_conversation_modal_has_smooth_open_close_states() -> None:
    """The conversation modal should expose a complete animated lifecycle."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'modal.dataset.state = "opening"' in script
    assert 'modal.dataset.state = "open"' in script
    assert 'modal.dataset.state = "closing"' in script
    assert "requestAnimationFrame" in script
    assert "transitionend" in script
    assert "resumeConversationCloseTimer" in script
    assert '.resume-conversation-root[data-state="open"] .resume-conversation-dialog' in styles
    assert 'translateY(12px) scale(0.985)' in styles
    assert '240ms cubic-bezier(0.22, 1, 0.36, 1)' in styles
    assert '160ms cubic-bezier(0.4, 0, 1, 1)' in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


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

    assert "Carh HR" in html
    assert "TalentStream HR" not in html
    assert 'class="ts-app-shell"' in html
    assert 'class="ts-filter-card"' in html
    assert 'class="ts-resume-surface"' in html
    assert 'id="miniList"' in html
    assert 'id="resumePreview"' in html
    assert 'id="resumeTableBlock"' not in html
    assert "function bindDockEffect" in script
    assert ".candidate-card" in styles
    assert ".ts-resume-surface" in styles


def test_authenticated_resume_library_uses_carh_brand_header() -> None:
    """The authenticated top bar should use the CARH brand and hide scope details."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    auth_script = (ROOT / "frontend" / "auth.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'aria-label="Carh HR"' in html
    assert '<img src="/assets/carh-logo.png" alt="长安仁恒科技股份有限公司" />' in html
    assert "<strong>Carh HR</strong>" in html
    assert (ROOT / "frontend" / "carh-logo.png").exists()
    assert '<strong id="userName">加载中</strong>' in html
    assert 'id="userScope"' not in html
    assert "userScope" not in auth_script

    brand_mark_block = styles.split(".ts-brand-mark {", 1)[1].split("}", 1)[0]
    brand_img_block = styles.split(".ts-brand-mark img {", 1)[1].split("}", 1)[0]
    brand_block = styles.split(".ts-brand {", 1)[1].split("}", 1)[0]
    brand_text_block = styles.split(".ts-brand strong {", 1)[1].split("}", 1)[0]
    user_name_block = styles.split(".user-card strong {", 1)[1].split("}", 1)[0]

    assert "justify-content: center" in brand_block
    assert "background: #fff" in brand_mark_block
    assert "object-fit: contain" in brand_img_block
    assert "color: #2563eb" in brand_text_block
    assert "text-align: center" in brand_text_block
    assert "font-weight: 900" in user_name_block
    assert "font-size: 16px" in user_name_block
    assert "border-radius: 999px" in user_name_block
    assert "box-shadow: 0 10px 24px" in user_name_block
    assert "background: rgba(255, 255, 255, 0.9)" in user_name_block


def test_frontend_lands_on_resume_library_after_login() -> None:
    """The authenticated app should treat the Stitch resume page as the landing page."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'const landingView = canView("resumes") ? "resumes" : uiAccess().defaultView' in script
    assert "setView(landingView)" in script


def test_resume_library_auth_expiry_returns_to_login_instead_of_loading_forever() -> None:
    """A 401 from a resume API request should send the user back to Feishu login."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "/assets/app.js?v=20260722-fullstack-filter-v1" in html
    assert "function handleAuthExpired" in script
    assert "登录已失效，请重新使用飞书授权登录" in script
    assert 'error.status === 401' in script
    assert "handleAuthExpired(error)" in script
    assert '$("emptyState").textContent = "登录已失效，请重新使用飞书授权登录"' in script


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

    assert "20260722-monitoring-account-height-v1" in html
    assert 'class="sidebar"' not in html
    shell_block = styles.split(".member-resume-mode .ts-app-shell {", 1)[1].split("}", 1)[0]

    assert "min-height: 100vh" in shell_block


def test_global_search_uses_debounced_resume_library_search_without_result_panel() -> None:
    """The resume-library search should refresh live without autocomplete UI."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="ts-global-search"' in html
    assert 'id="globalSearch"' in html
    assert 'role="combobox"' not in html
    assert 'aria-controls="globalSearchResults"' not in html
    assert 'id="globalSearchResults"' not in html
    assert "function bindGlobalSearchToFilters()" in script
    assert "bindGlobalSearchToFilters()" in script
    assert 'globalSearch.addEventListener("input"' in script
    assert 'globalSearch.addEventListener("compositionstart"' in script
    assert 'globalSearch.addEventListener("compositionend"' in script
    assert 'globalSearch.addEventListener("keydown"' in script
    assert "const queryField = $(\"filters\")?.q;" in script
    assert "queryField.value = globalSearch.value" in script
    assert 'if (state.view !== "resumes") return;' in script
    assert "scheduleResumeFilterRefresh();" in script
    assert "loadResumes({ fromFilter: true })" in script
    search_binding = script.split("function bindGlobalSearchToFilters()", 1)[1].split(
        "function applyResumeFilters()", 1
    )[0]
    assert 'setView("resumes")' not in search_binding
    assert "function searchGlobalResumes(query)" not in script
    assert "function positionGlobalSearchResults()" not in script
    assert "function renderGlobalSearchResults(items, query)" not in script
    assert "openGlobalSearchResult" not in script
    assert 'globalSearchResults' not in script
    assert "ts-command-search__panel" not in styles
    assert "ts-command-search__item" not in styles


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
    assert '["needs_more_info", "待补充"]' not in script
    assert '!["undecided", "queue", "processed"].includes(key)' in script
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
    assert (
        html.index('id="segmentPanel"')
        < html.index('id="statusTabs"')
        < html.index('id="jobTabsBlock"')
    )
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
    filter_actions_block = styles.split(".filter-actions {", 1)[1].split("}", 1)[0]

    assert "20260722-monitoring-account-height-v1" in html
    assert "grid-template-rows: minmax(0, 1fr)" in page_block
    assert 'id="filterToggleBtn"' in html
    assert 'id="filterPanel"' in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in filters_block
    assert "grid-column: 1 / -1" not in filter_actions_block
    assert "align-self: center" in filter_actions_block
    assert "justify-content: center" in filter_actions_block
    assert ".filter-actions .ts-btn--primary" not in styles
    assert "transition: max-height" in styles


def test_resume_filters_auto_apply_and_only_keep_centered_reset() -> None:
    """Selecting a filter option should immediately apply filters without a submit button."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    filter_form = html.split('<form class="filters ts-filter-form" id="filters">', 1)[1].split(
        "</form>",
        1,
    )[0]

    assert 'type="submit"' not in filter_form
    assert 'ts-btn--primary' not in filter_form
    assert ">筛选<" not in filter_form
    assert 'type="reset"' in filter_form
    assert "重置筛选" in filter_form
    assert "function applyResumeFilters()" in script
    assert "function bindAutoApplyResumeFilters()" in script
    assert '$("filters").addEventListener("change"' in script
    assert "applyResumeFilters();" in script
    assert "bindAutoApplyResumeFilters();" in script


def test_resume_sort_defaults_and_resets_to_latest_imported() -> None:
    """The resume library should open and reset with newest imported resumes first."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    sort_select = html.split('<select name="sort">', 1)[1].split("</select>", 1)[0]

    assert '<option value="created-desc" selected>最新入库</option>' in sort_select
    assert '<option value="score" selected>' not in sort_select


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
    assert 'class="filter-field--compact import-date-filter-field"' in filter_form
    assert 'class="filter-field--compact sort-filter-field"' in filter_form
    assert filter_form.index('name="education"') < filter_form.index('name="school_level"')
    assert filter_form.index('name="graduation_year"') < filter_form.index('name="sort"')
    assert filter_form.index('name="sort"') < filter_form.index('name="import_date_range"')
    assert 'select name="school_level" multiple' not in filter_form
    assert 'select name="graduation_year" multiple' not in filter_form
    assert '<select name="school_level">' in filter_form
    assert '<option value="">院校等级</option>' in filter_form
    assert '<select name="graduation_year">' in filter_form
    assert '<option value="">毕业时间</option>' in filter_form
    assert '<select name="import_date_range" multiple>' in filter_form
    assert '<option value="">入库日期</option>' in filter_form
    assert '<option value="today">今天</option>' in filter_form
    assert '<option value="last_7_days">近7天</option>' in filter_form
    assert '<span>排序</span>' not in filter_form
    assert '<option value="name">姓名</option>' not in filter_form
    assert ".filter-field--compact" in styles
    assert ".visually-hidden" in styles


def test_compact_filter_selects_use_smooth_custom_dropdowns() -> None:
    """The four compact filter selects should keep form values while opening with smooth motion."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function initializeSmoothFilterSelects()" in script
    assert 'document.querySelectorAll(".filter-field--compact select")' in script
    assert 'select.classList.add("smooth-select__native")' in script
    assert 'wrapper.className = "smooth-select"' in script
    assert 'button.className = "smooth-select__button"' in script
    assert 'menu.className = "smooth-select__menu"' in script
    assert "document.body.appendChild(menu)" in script
    assert "function positionSmoothSelectMenu(wrapper)" in script
    assert "positionSmoothSelectMenu(wrapper)" in script
    assert 'window.addEventListener("scroll", updateOpenSmoothSelectMenuPosition, true)' in script
    assert 'wrapper.classList.toggle("is-open")' in script
    assert 'select.value = option.value' in script
    assert "select.multiple" in script
    assert "function applyImportDateRangeParams(params, values)" in script
    assert "function syncImportDateCalendar(select)" in script
    assert "function addImportDateCalendar(menu, select)" in script
    assert 'if (key === "import_date_range")' in script
    assert "select.dataset.dateFrom" in script
    assert "select.dataset.dateTo" in script
    assert 'params.set("date_from", range.dateFrom)' in script
    assert 'params.set("date_to", range.dateTo)' in script
    assert "select.dispatchEvent(new Event(\"change\", { bubbles: true }))" in script
    assert "initializeSmoothFilterSelects();" in script

    native_block = styles.split(".smooth-select__native {", 1)[1].split("}", 1)[0]
    menu_block = styles.split(".smooth-select__menu {", 1)[1].split("}", 1)[0]
    open_menu_block = styles.split(".smooth-select__menu.is-open {", 1)[1].split(
        "}",
        1,
    )[0]

    assert "position: absolute" in native_block
    assert "opacity: 0" in native_block
    assert "position: fixed" in menu_block
    assert "z-index: 1000" in menu_block
    assert "transform: translateY(-6px) scale(0.98)" in menu_block
    assert "transition: opacity 0.18s ease" in menu_block
    assert "opacity: 1" in open_menu_block
    assert "transform: translateY(0) scale(1)" in open_menu_block
    assert ".import-date-filter-field {" not in styles
    assert ".smooth-select__calendar" in styles


def test_serene_talent_theme_is_loaded_without_replacing_native_controls() -> None:
    """The Stitch migration should keep native controls while using the new theme."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "20260722-monitoring-account-height-v1" in html
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


def test_serene_talent_theme_uses_blue_white_palette() -> None:
    """The authenticated workspace should use a blue-white palette instead of purple."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "--ts-surface: #f8fbff" in styles
    assert "--ts-surface-low: #eff6ff" in styles
    assert "--ts-primary: #2563eb" in styles
    assert "--ts-primary-container: #1d4ed8" in styles
    assert "#3525cd" not in styles
    assert "#4f46e5" not in styles
    assert "rgba(53, 37, 205" not in styles


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
    assert '<select name="import_date_range" multiple>' in html
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
        "AI产品经理",
        "全栈工程师",
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
        "AI产品经理",
        "全栈开发",
    ]:
        assert f'"{label}"' in script
    assert "if (values.includes(\"*\")) return uniqueJobTypes(RESUME_LIBRARY_JOB_TYPES)" in script
    assert "function canonicalResumeJobType(value)" in script
    assert 'compact.includes("资深全栈工程")' in script
    assert 'compact === "全栈开发"' in script
    assert "function uniqueJobTypes(values)" in script
    assert "counts.set(job, Math.max" in script


def test_resume_action_dock_removes_viewed_and_more_info_actions() -> None:
    """The review action dock should no longer render viewed or needs-more-info actions."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    action_markup = html.split('<div class="ts-action-dock" id="actionDock">', 1)[1].split(
        "</div>",
        1,
    )[0]
    assert 'id="viewedBtn"' not in action_markup
    assert 'id="moreInfoBtn"' not in action_markup
    assert "已看" not in action_markup
    assert "待补充" not in action_markup
    assert 'id="suitableBtn"' in action_markup
    assert 'id="unsuitableBtn"' in action_markup
    assert 'id="interviewBtn"' in action_markup
    assert '$("viewedBtn")' not in script
    assert '$("moreInfoBtn")' not in script
    assert ".member-resume-mode #moreInfoBtn" not in styles


def test_action_dock_stacks_admin_actions_while_members_keep_horizontal_choices() -> None:
    """Admins stack three review actions, while members keep the two-choice horizontal layout."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert ".member-resume-mode #interviewBtn" in styles
    hidden_interview_block = styles.split(".member-resume-mode #interviewBtn", 1)[1].split(
        "}", 1
    )[0]
    assert "display: none" in hidden_interview_block

    summary_start = '<aside id="summaryContent" class="summary-content ts-summary-stack">'
    summary_markup = html.split(summary_start, 1)[1].split("</aside>", 1)[0]
    assert 'id="summaryCards"' in summary_markup
    assert 'id="actionDock"' in summary_markup
    dock_block = styles.split(".ts-action-dock {", 1)[1].split("}", 1)[0]
    button_block = styles.split(".action-dock-btn {", 1)[1].split("}", 1)[0]
    member_dock_block = styles.split(".member-resume-mode .ts-action-dock {", 1)[1].split(
        "}", 1
    )[0]
    member_button_block = styles.split(".member-resume-mode .action-dock-btn {", 1)[1].split(
        "}", 1
    )[0]

    assert "position: sticky" in dock_block
    assert "bottom: 0" in dock_block
    assert "flex-direction: column" in dock_block
    assert "justify-content: stretch" in dock_block
    assert "padding: 10px 0 0" in dock_block
    assert "width: 100%" in button_block
    assert "flex-direction: row" in member_dock_block
    assert "flex: 1 1 0" in member_button_block


def test_interview_action_uses_pale_blue_white_style() -> None:
    """The interview action should not use the heavier primary blue fill."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    assert "#actionDock #interviewBtn {" in styles
    interview_block = styles.split("#actionDock #interviewBtn {", 1)[1].split("}", 1)[0]

    assert "color: var(--ts-primary)" in interview_block
    assert "rgba(239, 246, 255, 0.98)" in interview_block
    assert "rgba(219, 234, 254, 0.86)" in interview_block
    assert "rgba(147, 197, 253, 0.82)" in interview_block


def test_resume_filters_remove_visible_job_input_and_use_education_select() -> None:
    """Resume filters should rely on job tabs without rendering a duplicate job input."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="job-filter-field"' not in html
    assert "<span>岗位</span>" not in html
    assert 'placeholder="岗位"' not in html
    assert '<input name="job_type" type="hidden" />' in html
    assert ".member-resume-mode .job-filter-field" not in styles
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


def test_collapsed_library_centers_and_expands_resume_preview_image() -> None:
    """Collapsing the library should let the PDF preview use the remaining centered width."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    collapsed_surface_block = styles.split(
        ".ts-resume-workspace.is-library-collapsed .ts-resume-surface {",
        1,
    )[1].split("}", 1)[0]
    collapsed_preview_block = styles.split(
        ".ts-resume-workspace.is-library-collapsed .image-preview {",
        1,
    )[1].split("}", 1)[0]
    collapsed_stage_block = styles.split(
        ".ts-resume-workspace.is-library-collapsed .resume-image-stage {",
        1,
    )[1].split("}", 1)[0]
    collapsed_link_block = styles.split(
        ".ts-resume-workspace.is-library-collapsed .resume-download-link {",
        1,
    )[1].split("}", 1)[0]

    assert "min-width: 0" in collapsed_surface_block
    assert "place-items: start center" in collapsed_preview_block
    assert "justify-items: center" in collapsed_stage_block
    assert "padding: 10px" in collapsed_stage_block
    assert "width: min(100%, 1040px)" in collapsed_link_block
    assert "margin-inline: auto" in collapsed_link_block


def test_resume_image_preview_left_click_downloads_file() -> None:
    """The resume preview image should be wrapped in a download link."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "resume-download-link" in script
    assert "download class=\"resume-download-link\"" in script
    assert "'/api/resumes/' + resume.id + '/download'" in script
    assert ".resume-download-link" in styles


def test_resume_preview_supports_multi_page_pdf_stack() -> None:
    """PDF previews should stack page images vertically without changing page width."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    render_block = script.split("function renderResumePreview(context)", 1)[1].split(
        "function renderContext",
        1,
    )[0]
    open_block = script.split("async function openResume(id)", 1)[1].split(
        "function resumeText",
        1,
    )[0]
    page_image_block = styles.split(".resume-page-image {", 1)[1].split("}", 1)[0]

    assert "function resumePreviewPagesUrl(resume)" in script
    assert "previewPagesUrl: resumePreviewPagesUrl(resume)" in script
    assert "function loadResumePreviewPages(context)" in script
    assert "api(pagesUrl, { signal: controller.signal })" in script
    assert "requestSequence !== state.resumePreviewPagesRequestSequence" in script
    assert "state.selectedId !== resumeId" in script
    assert "state.resumePreviewPagesAbortController.abort()" in open_block
    assert "RESUME_PREVIEW_INITIAL_PAGE_LOAD_COUNT = 2" in script
    assert "RESUME_PREVIEW_NEXT_PAGE_ROOT_MARGIN" in script
    assert "function shouldEagerLoadPreviewPage(page)" in script
    assert "function observeResumePreviewPages()" in script
    assert "new IntersectionObserver" in script
    assert "loadPreviewPageImage(nextImage)" in script
    assert "normalizedPreviewPages(context)" in render_block
    assert "renderPreviewPageStack(resume, pages)" in render_block
    assert "resume-page-stack" in script
    assert "resume-page-frame" in script
    assert "data-preview-page" in script
    assert "data-preview-page-src" in script
    assert ".resume-page-stack" in styles
    assert ".resume-page-frame" in styles
    assert "gap: 18px" in styles
    assert "width: min(100%, 920px)" in styles
    assert "max-height" not in page_image_block


def test_resume_preview_uses_local_pdfjs_canvas_renderer_with_image_fallback() -> None:
    """PDF resumes should render through local PDF.js canvas before falling back to images."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    vendor_root = ROOT / "frontend" / "vendor" / "pdfjs"
    assert (vendor_root / "build" / "pdf.mjs").exists()
    assert (vendor_root / "build" / "pdf.worker.mjs").exists()
    assert (vendor_root / "cmaps").is_dir()
    assert (vendor_root / "standard_fonts").is_dir()
    assert (vendor_root / "wasm").is_dir()
    assert (vendor_root / "VERSION").read_text(encoding="utf-8").strip() == "pdfjs-dist@6.1.200"

    assert "/assets/app.js?v=20260722-fullstack-filter-v1" in html
    assert "PDFJS_VENDOR_BASE = \"/assets/vendor/pdfjs\"" in script
    assert 'import(`${PDFJS_VENDOR_BASE}/build/pdf.mjs`)' in script
    assert "GlobalWorkerOptions.workerSrc" in script
    assert "cMapUrl: `${PDFJS_VENDOR_BASE}/cmaps/`" in script
    assert "standardFontDataUrl: `${PDFJS_VENDOR_BASE}/standard_fonts/`" in script
    assert "wasmUrl: `${PDFJS_VENDOR_BASE}/wasm/`" in script
    assert "function resumePreviewPdfUrl(resume, file = {})" in script
    assert "function renderPdfjsPreview(context)" in script
    assert "function renderResumePreviewImageFallback(context)" in script
    assert "renderPdfjsPreview(context)" in script
    assert "renderResumePreviewImageFallback(context)" in script
    assert "RESUME_PDFJS_INITIAL_PAGE_RENDER_COUNT = 2" in script
    assert "RESUME_PDFJS_RENDER_CONCURRENCY = 2" in script
    assert "RESUME_PDFJS_INITIAL_PAGE_RENDER_TIMEOUT_MS = 1600" in script
    assert "RESUME_PDFJS_PAGE_RENDER_TIMEOUT_MS = 3000" in script
    assert "state.resumePdfRenderQueue" in script
    assert "function queuePdfjsPages(context, key, generation, pageNumbers)" in script
    assert "function pumpPdfjsRenderQueue(context, key, generation)" in script
    assert "function renderPdfjsPageFallback(pageNumber, context, key, generation)" in script
    assert "function loadPdfjsImageFallbackStack(context, key, generation)" in script
    assert "function renderPdfjsImageFallbackStack(context, key, generation, pages)" in script
    assert "loadPdfjsImageFallbackStack(context, key, generation).then((rendered) =>" in script
    assert "if (rendered) return;" in script
    assert "function fallbackRemainingPdfjsPages(context, key, generation)" in script
    assert "function pdfjsPageRenderTimeoutMs(pageNumber)" in script
    assert "function waitForPdfjsRenderTask(renderTask, pageNumber)" in script
    assert (
        "RESUME_PDFJS_INITIAL_PAGE_RENDER_COUNT ? RESUME_PDFJS_INITIAL_PAGE_RENDER_TIMEOUT_MS"
        in script
    )
    assert "resume_pdfjs_page_render_timeout" in script
    assert "renderTask.cancel()" in script
    assert "state.resumePdfForcePageImageFallback = true" in script
    assert "if (state.resumePdfForcePageImageFallback)" in script
    assert "fallbackRemainingPdfjsPages(context, key, generation)" in script
    assert "Array.from({ length: firstPageCount }, (_, index) => index + 1)" in script
    assert "RESUME_PDFJS_NEXT_PAGE_ROOT_MARGIN" not in script
    assert "RESUME_PDFJS_SCROLL_ACTIVATION_RATIO" not in script
    assert "function observePdfjsPages(context, key, generation)" not in script
    assert "function activePdfjsPageNearScroll(preview)" not in script
    assert "state.resumePdfRenderGeneration" in script
    assert "state.resumePdfRenderTasks" in script
    assert "cancelResumePdfRendering()" in script
    assert "if (resumePreviewPdfUrl(resume)) continue;" in script
    assert "offscreenCanvas" in script
    assert "resume-pdfjs-page--fallback" in script
    assert ".resume-pdfjs-stack" in styles
    assert ".resume-pdfjs-page-canvas" in styles
    assert ".resume-pdfjs-page--loaded" in styles
    assert ".resume-pdfjs-page--fallback" in styles


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
    assert "prefetchFollowingResumePreviewImages(state.selectedId)" in script
    assert "loadResumes({ preferCache: true })" in script


def test_resume_filters_debounce_cancel_stale_requests_and_delay_prefetch() -> None:
    """Rapid filter changes should only render the latest resume list request."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    apply_block = script.split("function applyResumeFilters()", 1)[1].split(
        "function bindAutoApplyResumeFilters()",
        1,
    )[0]

    assert "const RESUME_FILTER_DEBOUNCE_MS = 250" in script
    assert "const RESUME_PREFETCH_AFTER_FILTER_MS = 500" in script
    assert "resumeFilterDebounceTimer" in script
    assert "resumeListAbortController" in script
    assert "resumeListRequestSequence" in script
    assert "new AbortController()" in script
    assert "state.resumeListAbortController.abort()" in script
    assert "clearTimeout(state.resumeFilterDebounceTimer)" in script
    assert "setTimeout" in script
    assert "scheduleResumeFilterRefresh()" in script
    assert "scheduleResumePrefetchAfterFilter()" in script
    assert "loadResumes({ fromFilter: true })" in script
    assert "loadResumes();" not in apply_block


def test_job_tabs_are_cache_first_without_clearing_context_cache() -> None:
    """Switching job tabs should render cached lists and keep detail cache warm."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    job_tabs_block = script.split("function buildJobTabs()", 1)[1].split(
        "function queryFromFilters",
        1,
    )[0]
    clear_cache_block = script.split("function clearResumePrefetchCache()", 1)[1].split(
        "async function clearResumePrefetchCacheAfterMutation",
        1,
    )[0]
    load_block = script.split("async function loadResumes", 1)[1].split(
        "async function loadQueue",
        1,
    )[0]

    assert "loadResumes({ fromFilter: true, preferCache: true })" in job_tabs_block
    assert "clearResumePrefetchCache()" not in job_tabs_block
    assert "state.resumeContextCache.clear()" not in clear_cache_block
    assert "fromFilter && cached" in load_block
    assert "applyResumeListData(cached, { stale: true })" in load_block
    assert "refreshCachedResumeList(cacheKey, requestSequence, fromFilter)" in load_block


def test_job_tab_switch_prefetches_neighbor_jobs_without_blocking_current_page() -> None:
    """After a job switch, the library should warm nearby job tabs."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function prefetchAdjacentJobFirstPages()" in script
    assert "state.lastJobTabPrefetchKey" in script
    assert "prefetchAdjacentJobFirstPages()" in script
    assert "resumeListCacheKeyForJob(job, 1)" in script


def test_job_tab_prefetch_waits_until_current_list_is_rendered() -> None:
    """Job switches should not start adjacent prefetches before the current list is visible."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    load_block = script.split("async function loadResumes", 1)[1].split(
        "async function loadQueue",
        1,
    )[0]
    refresh_block = script.split("async function refreshCachedResumeList", 1)[1].split(
        "async function loadResumes",
        1,
    )[0]
    schedule_block = script.split("function scheduleResumePrefetchAfterFilter()", 1)[
        1
    ].split("async function refreshCachedResumeList", 1)[0]

    assert "scheduleResumePrefetchAfterFilter();" in load_block
    assert "scheduleResumePrefetchAfterFilter();" in refresh_block
    assert "prefetchAdjacentJobFirstPages();" not in load_block
    assert "prefetchAdjacentJobFirstPages();" not in refresh_block
    assert "prefetchNextResumePages();" in schedule_block
    assert "prefetchAdjacentJobFirstPages();" in schedule_block


def test_candidate_list_uses_slim_resume_fields_without_raw_text_fallback() -> None:
    """Candidate cards should render from slim list fields, not full resume payload text."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    render_block = script.split("function renderMiniList()", 1)[1].split(
        "function renderPagination",
        1,
    )[0]

    assert "resumeListMajor(resume)" in render_block
    assert "resumeListSchool(resume)" in render_block
    assert "resumeListSchoolTierBadge(resume)" in render_block
    assert "resumeSchool(resume)" not in render_block
    assert "resumeSchoolTierBadge(resume)" not in render_block
    assert "resumeRawText(resume)" not in render_block
    assert "rawText" not in render_block


def test_open_resume_updates_selection_and_cancels_stale_context() -> None:
    """Fast contact switches should ignore stale review-context responses."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    open_block = script.split("async function openResume(id)", 1)[1].split(
        "function resumeText",
        1,
    )[0]

    assert "resumeContextAbortController" in script
    assert "resumeContextRequestSequence" in script
    assert "function updateResumeSelectionDom(previousId, nextId)" in script
    assert "function renderOptimisticResumeContext(resume)" in script
    assert "updateResumeSelectionDom(previousId, id)" in open_block
    assert "renderOptimisticResumeContext(resume)" in open_block
    assert "new AbortController()" in open_block
    assert "state.resumeContextAbortController.abort()" in open_block
    assert "requestSequence !== state.resumeContextRequestSequence" in open_block
    assert "api(`/api/resumes/${id}/review-context`, { signal: controller.signal })" in open_block
    assert "renderRows();" not in open_block
    assert "renderMiniList();" not in open_block


def test_resume_library_prefetches_next_ten_preview_images_without_marking_viewed() -> None:
    """Opening a resume should delay nearby preview prefetches without touching review-context."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "function prefetchFollowingResumePreviewImages" in script
    preview_block = script.split(
        "function prefetchFollowingResumePreviewImages",
        1,
    )[1].split("async function openResume", 1)[0]

    assert "const RESUME_PREVIEW_PREFETCH_LIMIT = 10" in script
    assert "const RESUME_PREVIEW_PREFETCH_CONCURRENCY = 2" in script
    assert "resumePreviewImageQueue" in script
    assert "resumePreviewImageInFlight" in script
    assert "resumePreviewImageCache" in script
    assert "function followingResumePreviewCandidates(selectedId)" in script
    assert "function enqueueResumePreviewImagePrefetch(url)" in script
    assert "function runResumePreviewImagePrefetchQueue()" in script
    assert "state.resumePreviewImageActiveCount < RESUME_PREVIEW_PREFETCH_CONCURRENCY" in script
    assert "result.length >= RESUME_PREVIEW_PREFETCH_LIMIT" in script
    assert "state.resumePageCache.get(resumeListCacheKey(page))" in script
    assert "resumePreviewImageUrl(resume)" in script
    assert "new Image()" in script
    assert "image.src = url" in script
    assert "followingResumePreviewCandidates(selectedId).forEach(({ url }) => {" in script
    assert "enqueueResumePreviewImagePrefetch(url)" in preview_block
    assert "function scheduleFollowingResumePreviewImages(selectedId)" in script
    assert "RESUME_PREVIEW_PREFETCH_DELAY_MS" in script
    assert "scheduleFollowingResumePreviewImages(id)" in script
    assert "review-context" not in preview_block


def test_resume_prefetch_cache_is_invalidated_after_filters_and_review_actions() -> None:
    """Changing filters or saving review state must not reuse stale preloaded pages."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function clearResumePrefetchCache()" in script
    assert "clearResumePrefetchCache();" in script
    assert "await clearResumePrefetchCacheAfterMutation()" in script
    assert "function clearResumePrefetchCacheAfterMutation()" in script
    assert "clearResumePreviewImagePrefetchQueue()" in script


def test_review_actions_advance_to_next_resume() -> None:
    """Review buttons should save the action and then open the next resume."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "async function advanceAfterReviewAction(id)" in script
    assert "await advanceAfterReviewAction(id)" in script
    assert 'setDecision(state.selectedId, "suitable")' in script
    assert 'setDecision(state.selectedId, "unsuitable")' in script
    assert 'setDecision(state.selectedId, "needs_more_info")' not in script
    assert "markViewedAndAdvance(state.selectedId)" not in script


def test_member_suitable_tab_replaces_review_actions_with_push_action() -> None:
    """Members should push suitable resumes explicitly instead of re-marking them."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function renderActionDock()" in script
    assert 'isMemberUser() && state.tab === "suitable"' in script
    assert 'suitableBtn.textContent = "推送"' in script
    assert "member-push-btn" in script
    push_block = styles.split("#actionDock .member-push-btn {", 1)[1].split("}", 1)[0]
    pushed_block = styles.split("#actionDock .member-push-btn:disabled {", 1)[1].split("}", 1)[0]
    assert "#16a34a" in push_block
    assert "var(--ts-primary)" not in push_block
    assert "color: #065f46" in pushed_block
    assert "#dcfce7" in pushed_block
    assert "#16a34a" in pushed_block
    assert "pushSelectedResumeToAdmin" in script
    assert "是否推送给管理员" in script
    assert "/push-to-admin" in script
    assert 'setDecision(state.selectedId, "suitable")' in script
    assert 'setDecision(state.selectedId, "unsuitable")' in script


def test_authorized_reviewers_see_named_member_decisions_and_hover_popover() -> None:
    """All authorized users should see grouped reviewer names from the shared decision list."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "function reviewerDecisions(resume)" in script
    assert "reviewerDecisions" in script
    assert "function memberDecisionBadgeMarkup(resume)" in script
    assert "function memberDecisionSummaryMarkup(resume)" in script
    assert "reviewerDecisionDisplayName" in script
    assert "function reviewerDecisionDisplayTime(item)" in script
    assert "function reviewerDecisionDate(value, compact = false)" in script
    assert "reviewerDecisionDisplayTime(item), true" in script
    assert "成员判断" in script
    assert "成员合适" not in script
    assert "成员不合适" not in script
    assert "历史成员" not in script
    assert "member-decision-badge" in script
    assert "function showReviewerDecisionPopover" in script
    assert "function hideReviewerDecisionPopover" in script
    assert "reviewerDecisionPopoverRoot" in script
    assert 'id="reviewerDecisionPopoverRoot"' in html
    assert "已推送" in script
    assert "合适时间：" in script
    assert "不合适时间：" in script
    assert "推送时间：" in script
    assert "member-decision-list" in script
    assert ".member-decision-badge" in styles
    assert ".reviewer-decision-popover-root" in styles
    popover_block = styles.split(".reviewer-decision-popover-root {", 1)[1].split("}", 1)[0]
    assert "position: fixed" in popover_block
    assert "z-index: 4000" in popover_block
    assert ".candidate-card:hover .member-decision-popover" not in styles
    assert ".member-decision-list" in styles


def test_admin_decision_refreshes_shared_queue_instead_of_falling_back_to_all_resumes() -> None:
    """Completing a queue task should refresh the shared pending set immediately."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    advance_block = script.split("async function advanceAfterReviewAction(id)", 1)[1].split(
        "function requestInterview()",
        1,
    )[0]

    assert 'if (state.tab === "queue")' in advance_block
    assert "await loadQueue();" in advance_block


def test_resume_library_dispatches_to_shared_queue_when_queue_tab_is_active() -> None:
    """Returning from My Tasks must not render all resumes under an active queue tab."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    set_view_block = script.split("function setView(view)", 1)[1].split(
        "async function loadUser()",
        1,
    )[0]
    dispatcher_block = script.split("function loadCurrentResumeCollection", 1)[1].split(
        "async function loadUser()",
        1,
    )[0]

    assert 'if (view === "resumes") loadCurrentResumeCollection();' in set_view_block
    assert 'if (state.tab === "queue") return loadQueue();' in dispatcher_block
    assert "return loadResumes(options);" in dispatcher_block


def test_removed_top_level_pages_keep_tasks_inside_resume_library() -> None:
    """Queue work stays in resume tabs after removing redundant top-level pages."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    for view in ("queue", "automation", "rules"):
        assert f'data-view="{view}"' not in html
        assert f'data-page="{view}"' not in html
    assert "我的任务" not in html
    assert ">自动化<" not in html
    assert ">规则库<" not in html
    assert '["queue", "待我处理"]' in script
    assert '["processed", "已处理"]' in script
    assert 'const AVAILABLE_VIEWS = new Set(Object.keys(pages));' in script


def test_shared_queue_uses_resume_request_abort_and_sequence_guards() -> None:
    """A late queue response must not overwrite a newer all-resume request."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    queue_block = script.split("async function loadQueue", 1)[1].split(
        "function renderRows()",
        1,
    )[0]

    assert "state.resumeListAbortController.abort()" in queue_block
    assert "state.resumeListRequestSequence += 1" in queue_block
    assert "signal: controller.signal" in queue_block
    assert "requestSequence !== state.resumeListRequestSequence" in queue_block
    assert 'loadAssignmentCollection("pending", "queue"' in queue_block
    assert "state.tab !== tab" in queue_block


def test_queue_job_facets_are_separate_from_full_resume_facets() -> None:
    """Pending counts must never reuse or overwrite the full resume-library facets."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    state_block = script.split("const state = {", 1)[1].split("};", 1)[0]
    status_tabs_block = script.split("function buildTabs()", 1)[1].split(
        "function buildJobTabs()",
        1,
    )[0]
    job_tabs_block = script.split("function buildJobTabs()", 1)[1].split(
        "function queryFromFilters",
        1,
    )[0]
    list_block = script.split("function applyResumeListData", 1)[1].split(
        "function resumePreviewImageUrl",
        1,
    )[0]
    queue_block = script.split("async function loadQueue", 1)[1].split(
        "function renderRows()",
        1,
    )[0]

    assert "resumeJobFacets" in state_block
    assert "queueJobFacets" in state_block
    assert "processedJobFacets" in state_block
    assert "queueSummaryLoaded" in state_block
    assert "isProcessed ? state.processedJobFacets : state.resumeJobFacets" in job_tabs_block
    assert "state.resumeJobFacets = data.jobFacets || [];" in list_block
    assert 'if (collection === "processed") state.processedJobFacets = facets;' in queue_block
    assert "else state.queueJobFacets = facets;" in queue_block
    assert "state.queueTotal = Number(data.queueTotal" in queue_block
    assert "state.queueVersion = data.version || state.queueVersion;" in queue_block
    assert "buildJobTabs();" in queue_block
    assert 'params.set("job_type", state.jobType)' in queue_block
    assert 'if (state.tab === "queue") return loadQueue();' in job_tabs_block
    assert "buildJobTabs();" in status_tabs_block


def test_admin_queue_summary_polls_every_three_seconds_and_refreshes_on_version_change() -> None:
    """Visible admin sessions poll a light summary and load full tasks only after a change."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    polling_block = script.split("async function refreshQueueSummary", 1)[1].split(
        "async function loadQueue",
        1,
    )[0]
    login_block = script.split("async function afterLogin(user)", 1)[1].split(
        "async function logout()",
        1,
    )[0]
    logout_block = script.split("async function logout()", 1)[1].split(
        "async function init()",
        1,
    )[0]

    assert "const QUEUE_SUMMARY_POLL_MS = 3000;" in script
    assert 'api("/api/resume-review/queue-summary"' in polling_block
    assert "data.version !== state.queueVersion" in polling_block
    assert "renderQueueCountIndicators();" in polling_block
    assert "await loadQueue({ preserveSelection: true });" in polling_block
    assert 'document.visibilityState !== "visible"' in polling_block
    assert "state.queueSummaryInFlight" in polling_block
    assert 'document.addEventListener("visibilitychange"' in script
    assert 'window.addEventListener("focus"' in script
    assert "startQueueSummaryPolling();" in login_block
    assert "stopQueueSummaryPolling();" in logout_block
    assert 'id="queueNavCount"' not in html
    assert 'id="queueTabCount"' not in html
    assert 'data-tab="queue"' in script


def test_queue_summary_cleanup_remains_wired_without_task_page() -> None:
    """Queue polling still stops cleanly after removing the standalone task page."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    stop_block = script.split("function stopQueueSummaryPolling()", 1)[1].split(
        "function scheduleQueueSummaryPoll",
        1,
    )[0]

    assert "refreshQueueNow" not in script
    assert 'id="refreshQueueBtn"' not in (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "state.queueSummaryAbortController.abort()" in stop_block
    assert "clearTimeout(state.queueSummaryTimer)" in stop_block


def test_queue_list_failure_keeps_last_counts_and_retries_on_next_summary_poll() -> None:
    """A transient full-list failure must not turn known pending counts back into zero."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    queue_block = script.split("async function loadQueue", 1)[1].split(
        "function applySharedQueueData",
        1,
    )[0]

    assert "if (!preserveSelection)" in queue_block
    assert "applySharedQueueData" in queue_block
    assert 'state.queueVersion = "";' in queue_block


def test_queue_uses_resume_library_pagination_without_standalone_task_page() -> None:
    """Pending tasks page through the resume library after removing My Tasks."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'id="resumePagination"' in html
    assert 'id="queuePagination"' not in html
    assert "function renderQueuePagination()" not in script
    assert "function renderQueue(items)" not in script
    assert "renderPagination();" in script
    assert 'if (state.tab === "queue") return loadQueue();' in script


def test_hiding_page_aborts_inflight_queue_summary() -> None:
    """A hidden admin page must not finish a summary request and start a full queue refresh."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    visibility_block = script.split('document.addEventListener("visibilitychange"', 1)[1].split(
        'window.addEventListener("focus"',
        1,
    )[0]

    assert "state.queueSummaryAbortController.abort()" in visibility_block


def test_reviewer_badge_click_keeps_the_top_level_popover_open() -> None:
    """Focus followed by click must not immediately toggle the reviewer popover closed."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    bind_block = script.split("function bindReviewerDecisionPopovers()", 1)[1].split(
        "function memberDecisionSummaryMarkup",
        1,
    )[0]
    click_block = bind_block.split('badge.addEventListener("click"', 1)[1].split("});", 1)[0]

    assert "showReviewerDecisionPopover(badge);" in click_block
    assert "hideReviewerDecisionPopover();" not in click_block


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

    assert "20260722-monitoring-account-height-v1" in html
    assert "function resumeSchoolTierBadge(resume)" in script
    assert 'if (level.includes("985")) return "985"' in script
    assert 'if (level.includes("211")) return "211"' in script
    assert 'class="candidate-card__heading"' in script
    assert 'class="school-tier-badge"' in script
    assert ".candidate-card__heading" in styles
    assert ".school-tier-badge" in styles


def test_candidate_score_capsule_is_aligned_in_fixed_heading_column() -> None:
    """Candidate scores should occupy the same fixed column on every card."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function resumeScoreLabel(resume)" in script
    assert 'if (rawValue === "" || rawValue == null) return "--"' in script
    assert 'class="candidate-card__score' in script
    assert 'class="candidate-card__heading-status"' in script
    assert 'title="简历评分"' in script
    heading_block = styles.split(".candidate-card__heading {", 1)[1].split("}", 1)[0]
    score_block = styles.split(".candidate-card__score {", 1)[1].split("}", 1)[0]
    status_block = styles.split(".candidate-card__heading-status {", 1)[1].split("}", 1)[0]
    assert "display: grid" in heading_block
    assert "grid-template-columns: minmax(0, 1fr) 46px 61px 112px" in heading_block
    assert "min-width: 36px" in score_block
    assert "justify-self: center" in score_block
    assert "grid-column: 4" in status_block


def test_candidate_card_metadata_uses_aligned_columns() -> None:
    """School, tier, date, platform, and read status should line up across cards."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'class="candidate-card__meta-item candidate-card__meta-school"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-tier"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-date"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-platform"' in script
    assert 'class="candidate-card__meta-item candidate-card__meta-read"' in script
    assert '<span class="candidate-card__meta-label">院校</span>' not in script
    assert "candidate-card__meta-label" not in script
    assert "candidate-card__read-badge" in script
    meta_block = styles.split(".candidate-card__meta {", 1)[1].split("}", 1)[0]

    assert "display: grid" in meta_block
    assert "grid-template-columns:" in meta_block
    assert ".candidate-card__meta-item" in styles
    assert ".candidate-card__meta-school" in styles
    assert ".candidate-card__meta-label" not in styles
    assert "text-overflow: ellipsis" in styles


def test_candidate_card_shows_major_account_and_compact_date() -> None:
    """Candidate cards should show major, account owner, and short import dates."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function resumeMajor(resume)" in script
    assert '["major", "profession", "specialty"]' in script
    assert "function resumeCompactImportDate(resume)" in script
    assert "return `${match[1].slice(2)}-${match[2]}-${match[3]}`" in script
    assert "function resumePlatformAccountLabel(resume)" in script
    assert 'if (platform === "51job") platform = "51"' in script
    assert "return account ? `${platform} ' ${account}` : platform" in script
    assert 'class="candidate-card__job-main"' in script
    assert 'class="candidate-card__major"' in script
    assert 'resumeListMajor(resume) || "暂未提取到"' in script
    assert "resumeListCompactImportDate(resume)" in script
    assert "resumePlatformAccountLabel(resume)" in script
    assert ".candidate-card__major" in styles


def test_candidate_card_account_label_only_uses_collector_accounts() -> None:
    """Reviewer names must not be shown as collection account labels."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "const RESUME_COLLECTOR_ACCOUNT_LABELS = {" in script
    assert '"宋峰峰": "宋"' in script
    assert '"宋锋峰": "宋"' in script
    assert '"和新红": "和"' in script
    assert "function resumeCollectorAccountLabel(resume)" in script
    assert "Object.prototype.hasOwnProperty.call(RESUME_COLLECTOR_ACCOUNT_LABELS, owner)" in script
    assert "owner.slice(0, 1)" not in script


def test_candidate_card_major_stays_near_job_title() -> None:
    """Major text should sit next to the job title instead of the far edge."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    job_block = styles.split(".candidate-card__job {", 1)[1].split("}", 1)[0]
    major_block = styles.split(".candidate-card__major {", 1)[1].split("}", 1)[0]

    assert "justify-content: flex-start" in job_block
    assert "gap: 6px" in job_block
    assert "justify-content: space-between" not in job_block
    assert "text-align: right" not in major_block


def test_candidate_cards_are_larger_and_read_status_is_frosted_badge() -> None:
    """Candidate cards should be larger and make read status visually distinct."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    card_block = styles.split(".candidate-card {", 1)[1].split("}", 1)[0]
    heading_block = styles.split(".candidate-card__heading strong {", 1)[1].split("}", 1)[0]
    job_block = styles.split(".candidate-card__job {", 1)[1].split("}", 1)[0]
    meta_block = styles.split(".candidate-card__meta {", 1)[1].split("}", 1)[0]
    read_badge_block = styles.split(".candidate-card__read-badge {", 1)[1].split("}", 1)[0]
    unread_block = styles.split(".candidate-card__read-badge--unread {", 1)[1].split("}", 1)[0]
    viewed_block = styles.split(".candidate-card__read-badge--viewed {", 1)[1].split("}", 1)[0]

    assert "min-height: 95px" in card_block
    assert "padding: 13px 12px" in card_block
    assert "gap: 8px" in card_block
    assert "align-content: center" in card_block
    assert "font-size: 16px" in heading_block
    assert "font-size: 13px" in job_block
    assert "font-size: 12px" in meta_block
    assert "backdrop-filter: blur(10px)" in read_badge_block
    assert "border-radius: 999px" in read_badge_block
    assert "rgba(37, 99, 235" in unread_block
    assert "rgba(0, 108, 73" in viewed_block


def test_active_candidate_card_uses_blue_gradient_selection() -> None:
    """The selected candidate card should only add a light blue-white background."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    active_block = styles.split(".candidate-card.active {", 1)[1].split("}", 1)[0]

    active_background = (
        "background: linear-gradient(135deg, "
        "rgba(239, 246, 255, 0.96), rgba(219, 234, 254, 0.72))"
    )
    assert active_background in active_block
    assert "border-color: rgba(147, 197, 253, 0.78)" in active_block
    assert "border-left-color: rgba(37, 99, 235, 0.72)" in active_block
    assert "\n  color:" not in active_block


def test_active_candidate_card_uses_focus_pop_motion() -> None:
    """Selecting cards via click or arrow movement should trigger a subtle macOS-like motion."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    focus_block = styles.split(".candidate-card--focus-pop {", 1)[1].split("}", 1)[0]

    assert 'candidate-card--focus-pop' in script
    assert "resume.id === state.selectedId" in script
    assert "animation: candidateFocusPop 0.34s" in focus_block
    assert "@keyframes candidateFocusPop" in styles
    assert "scale(1.035)" in styles


def test_candidate_card_metadata_stays_inside_card_on_narrow_panes() -> None:
    """The card should clip long school/platform text instead of letting it spill outside."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    card_block = styles.split(".candidate-card {", 1)[1].split("}", 1)[0]
    meta_block = styles.split(".candidate-card__meta {", 1)[1].split("}", 1)[0]
    item_block = styles.split(".candidate-card__meta-item {", 1)[1].split("}", 1)[0]

    assert "overflow: hidden" in card_block
    assert "width: 100%" in meta_block
    assert "max-width: 100%" in meta_block
    assert "grid-template-columns: minmax(0, 1fr)" in meta_block
    assert "overflow: hidden" in item_block
    assert "text-overflow: ellipsis" in item_block


def test_candidate_card_content_is_vertically_centered() -> None:
    """Candidate card text should sit evenly between the top and bottom edges."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    card_block = styles.split(".candidate-card {", 1)[1].split("}", 1)[0]
    meta_block = styles.split(".candidate-card__meta {", 1)[1].split("}", 1)[0]

    assert "align-content: center" in card_block
    assert "line-height: 1.35" in meta_block
    assert "transform:" not in meta_block


def test_resume_summary_panel_uses_tighter_horizontal_padding() -> None:
    """The right summary column should give more width back to the resume content."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    preview_grid_block = styles.split(".ts-preview-grid {", 1)[1].split("}", 1)[0]
    resize_handle_block = styles.split(".summary-resize-handle {", 1)[1].split("}", 1)[0]
    summary_block = styles.split(".summary-content {", 1)[1].split("}", 1)[0]
    card_block = styles.split(".ts-summary-card {", 1)[1].split("}", 1)[0]

    assert 'id="previewGrid"' in html
    assert 'id="summaryResizeHandle"' in html
    assert 'role="separator"' in html
    assert 'aria-controls="summaryContent"' in html
    assert 'aria-valuemin="180"' in html
    assert (
        "grid-template-columns: minmax(0, 1fr) 10px var(--summary-panel-width)"
        in preview_grid_block
    )
    assert "--summary-panel-width: 276px" in preview_grid_block
    assert "cursor: col-resize" in resize_handle_block
    assert "touch-action: none" in resize_handle_block
    assert "padding: 12px 10px" in summary_block
    assert "padding: 10px" in card_block
    assert "function bindSummaryPanelResize()" in script
    assert "SUMMARY_PANEL_STORAGE_KEY" in script
    assert "const SUMMARY_PANEL_MIN_WIDTH = 180" in script
    assert "setSummaryPanelWidth" in script
    assert 'localStorage.setItem(SUMMARY_PANEL_STORAGE_KEY' in script
    assert 'handle.addEventListener("pointerdown"' in script
    assert 'window.addEventListener("pointermove"' in script
    assert "bindSummaryPanelResize();" in script


def test_resume_summary_panel_collapses_with_floating_actions() -> None:
    """The summary panel should collapse smoothly with floating admin actions."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    preview_grid_block = styles.split(".ts-preview-grid {", 1)[1].split("}", 1)[0]
    collapse_button_block = styles.split(".summary-collapse-btn {", 1)[1].split("}", 1)[0]
    collapsed_grid_block = styles.split(".ts-preview-grid.is-summary-collapsed {", 1)[1].split(
        "}", 1
    )[0]
    collapsed_handle_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .summary-resize-handle {",
        1,
    )[1].split("}", 1)[0]
    collapsed_summary_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .summary-content {",
        1,
    )[1].split("}", 1)[0]
    collapsed_cards_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .ts-summary-cards {",
        1,
    )[1].split("}", 1)[0]
    floating_dock_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .ts-action-dock {",
        1,
    )[1].split("}", 1)[0]
    floating_dock_hover_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .ts-action-dock:hover,",
        1,
    )[1].split("}", 1)[0]
    collapsed_preview_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .resume-preview {",
        1,
    )[1].split("}", 1)[0]

    assert 'id="summaryCollapseBtn"' in html
    assert 'aria-controls="summaryContent actionDock"' in html
    assert 'aria-expanded="true"' in html
    assert "transition: grid-template-columns 0.28s" in preview_grid_block
    assert "grid-template-rows: minmax(0, 1fr)" in preview_grid_block
    assert "position: absolute" in collapse_button_block
    assert "grid-template-columns: minmax(0, 1fr) 0px 0px" in collapsed_grid_block
    assert "grid-column: 2" in collapsed_handle_block
    assert "grid-row: 1" in collapsed_handle_block
    assert "grid-column: 1 / -1" in collapsed_summary_block
    assert "grid-row: 1" in collapsed_summary_block
    assert "overflow: visible" in collapsed_summary_block
    assert "opacity: 0" in collapsed_cards_block
    assert "pointer-events: none" in collapsed_cards_block
    assert "position: absolute" in floating_dock_block
    assert "top: 54px" in floating_dock_block
    assert "right: 14px" in floating_dock_block
    assert "transform-origin: top right" in floating_dock_block
    assert "scale(0.5)" in floating_dock_block
    assert "scale(1)" in floating_dock_hover_block
    assert "grid-column: 1 / -1" in collapsed_preview_block
    assert "grid-row: 1" in collapsed_preview_block
    assert "SUMMARY_PANEL_COLLAPSED_STORAGE_KEY" in script
    assert "function setSummaryPanelCollapsed(collapsed" in script
    assert "function bindSummaryPanelCollapse()" in script
    assert "summaryCollapseBtn" in script
    assert "is-summary-collapsed" in script


def test_collapsed_summary_resume_image_fills_preview_frame_width() -> None:
    """Collapsed summary mode should enlarge the resume to fill the preview frame width."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    collapsed_image_preview_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .image-preview {",
        1,
    )[1].split("}", 1)[0]
    collapsed_stage_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .resume-image-stage {",
        1,
    )[1].split("}", 1)[0]
    collapsed_link_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .resume-download-link {",
        1,
    )[1].split("}", 1)[0]
    collapsed_image_block = styles.split(
        ".ts-preview-grid.is-summary-collapsed .resume-image-stage img {",
        1,
    )[1].split("}", 1)[0]

    assert "grid-template-rows: minmax(0, 1fr)" in collapsed_image_preview_block
    assert "min-height: 0" in collapsed_image_preview_block
    assert "display: block" in collapsed_stage_block
    assert "height: 100%" in collapsed_stage_block
    assert "align-content: start" in collapsed_stage_block
    assert "overflow: auto" in collapsed_stage_block
    assert "display: block" in collapsed_link_block
    assert "height: auto" in collapsed_link_block
    assert "\n  width: 100%;" in collapsed_image_block
    assert "\n  height: auto;" in collapsed_image_block
    assert "max-height: none" in collapsed_image_block
    assert "object-fit: contain" in collapsed_image_block


def test_stitch_workspace_keeps_candidate_list_and_preview_same_viewport() -> None:
    """The Stitch workspace should keep candidates and resume preview in one viewport."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    workbench_block = styles.split(".ts-resume-workspace {", 1)[1].split("}", 1)[0]

    assert "grid-template-columns: 408px minmax(0, 1fr)" in workbench_block
    assert "height: calc(100vh - 88px)" in workbench_block


def test_stitch_workspace_fits_codex_side_browser_viewport() -> None:
    """The authenticated resume browser should adapt to the narrow Codex side pane."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "/assets/styles.css?v=20260722-monitoring-account-height-v1" in html
    assert "@media (max-width: 700px)" in styles
    side_browser_block = styles.split("@media (max-width: 700px)", 1)[1]
    body_block = side_browser_block.split("body {", 1)[1].split("}", 1)[0]
    topbar_block = side_browser_block.split(".ts-topbar {", 1)[1].split("}", 1)[0]
    workspace_block = side_browser_block.split(".ts-resume-workspace {", 1)[1].split("}", 1)[0]
    action_dock_block = side_browser_block.split(".ts-action-dock {", 1)[1].split("}", 1)[0]

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


def test_candidate_card_dock_effect_is_subtle() -> None:
    """Candidate cards should still follow the cursor without growing too aggressively."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'bindDockEffect($("miniList"), ".candidate-card", { maxScale: 1.08' in script
    assert "radius: 120" in script
    assert "marginFactor: 8" in script


def test_resume_pagination_uses_editable_frosted_page_status() -> None:
    """The page status should be a frosted capsule with an Enter-to-jump page input."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="resumePageInput"' in script
    assert 'class="pagination-input"' in script
    assert "data-page-input" in script
    assert 'type="number"' in script
    assert 'event.key !== "Enter"' in script
    target_page_script = (
        "const targetPage = Math.min("
        "Math.max(1, Number(pageInput.value) || current), pages)"
    )
    assert target_page_script in script
    assert "state.page = targetPage" in script
    assert "loadResumes({ preferCache: true })" in script

    status_block = styles.split(".pagination-status {", 1)[1].split("}", 1)[0]
    input_block = styles.split(".pagination-input {", 1)[1].split("}", 1)[0]

    assert "border-radius: 999px" in status_block
    assert "background: rgba(31, 41, 55, 0.84)" in status_block
    assert "color: #f8fafc" in status_block
    assert "font-weight: 800" in status_block
    assert "backdrop-filter: blur(12px)" in status_block
    assert "width: 38px" in input_block
    assert "text-align: center" in input_block


def test_interview_button_confirms_in_place_then_reports_result() -> None:
    """Interview invite should confirm and report results without changing views."""

    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="interviewConfirmModal"' in html
    assert 'role="alertdialog"' in html
    assert 'id="interviewConfirmSubmitBtn"' in html
    assert 'id="interviewFeedback"' in html
    assert "function openInterviewConfirm()" in script
    assert "async function submitInterviewInvite()" in script
    request_block = script.split("async function requestInterview()", 1)[1].split(
        "function openInterviewConfirm()", 1
    )[0]
    assert 'setView("interviews")' not in request_block
    assert "openInterviewConfirm();" in request_block
    assert '"dryRun": true' in script
    assert '"confirmLive": true' in script
    assert '"dryRun": false' in script
    assert 'showInterviewFeedback("success"' in script
    assert 'showInterviewFeedback("error"' in script
    assert ".interview-confirm-dialog" in styles
    assert '.interview-feedback[data-tone="success"]' in styles
    assert "async function confirmInterviewInvite()" in script
    assert "async function selectInterviewSession(sessionId)" in script
    assert "renderInterviewPreflight" in script
    assert '"selectedSessionId": sessionId' in script
    assert "data-select-interview-session" in script
    assert "确认发起约面试" in script


def test_processed_interview_assignments_have_tab_badge_and_timeline() -> None:
    """Completed interview tasks should remain inspectable with operator and time."""

    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert '["processed", "已处理"]' in script
    assert "async function loadProcessed" in script
    assert 'loadAssignmentCollection("completed", "processed"' in script
    assert 'params.set("status", status)' in script
    assert "processedJobFacets" in script
    assert "processedTotal" in script
    assert 'completionAction === "interview_invited"' in script
    assert "已约面试" in script
    assert "data-processed-resume-id" in script
    assert "completedByUserName" in script
    assert "completedAt" in script
    assert "处理时间：" in script
    assert "payload?.completedAssignment" in script
