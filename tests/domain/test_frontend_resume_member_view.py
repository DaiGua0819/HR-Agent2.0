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


def test_member_resume_library_hides_more_info_action() -> None:
    """Members do not need the needs-more-info review action."""

    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert ".member-resume-mode #moreInfoBtn" in styles
    block = styles.split(".member-resume-mode #moreInfoBtn", 1)[1].split("}", 1)[0]
    assert "display: none" in block


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
