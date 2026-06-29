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
