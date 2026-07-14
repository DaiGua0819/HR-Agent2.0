# Member Resume Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let members mark resumes as suitable/unsuitable locally, then explicitly push suitable resumes to admin's review queue from the suitable list.

**Architecture:** Reuse `resume_review_states` for every user's decision and `resume_assignments` for admin queue items. Split the current one-step "suitable creates assignment" path into `set_decision()` plus a new explicit `push_to_admin()` path.

**Tech Stack:** FastAPI routes, SQLite-backed domain repository/service, vanilla `frontend/app.js`, static contract tests, pytest.

## Global Constraints

- Members can mark each visible resume suitable or unsuitable.
- Admin can inspect member decisions for each resume.
- A member's suitable click must not create an admin queue assignment.
- Only clicking "推送" from the member suitable list creates the admin assignment.
- "不合适" never enters admin's "待我处理" queue.
- Keep existing resume visibility rules.
- Do not change the old 8080 service in deployment.

---

### Task 1: Domain State And Push API

**Files:**
- Modify: `app/domain/resume_review/repository.py`
- Modify: `app/domain/resume_review/service.py`
- Modify: `app/api/routes/resume_review.py`
- Test: `tests/domain/test_resume_review_workbench.py`

**Interfaces:**
- Produces: `ResumeReviewService.member_decisions_for_resumes(resume_ids: list[str]) -> dict[str, list[dict[str, object]]]`
- Produces: `ResumeReviewService.push_to_admin(resume_id: str, user_id: str, note: str = "", assign_to: str = "") -> dict[str, object]`
- Produces: `POST /api/resumes/{resume_id}/push-to-admin`

- [ ] Write failing tests that `set_decision(..., decision="suitable")` stores state but does not create an assignment.
- [ ] Write failing tests that `push_to_admin()` rejects non-suitable state and creates exactly one pending admin assignment for suitable state.
- [ ] Write failing route tests for `POST /api/resumes/{resume_id}/push-to-admin`.
- [ ] Implement repository helpers to list decisions by resume IDs.
- [ ] Implement service push method and admin decision aggregation.
- [ ] Implement route with existing visibility checks.
- [ ] Run the targeted tests until green.

### Task 2: Resume Payload Shows Member Decisions

**Files:**
- Modify: `app/api/routes/resumes.py`
- Test: `tests/domain/test_phase5_resume.py` or `tests/domain/test_resume_review_workbench.py`

**Interfaces:**
- Produces: each resume payload includes `memberReviewStates: [...]` for admin users.
- Keeps: current user's `reviewState` unchanged.

- [ ] Write failing API/service test that admin list payload includes member decisions.
- [ ] Implement admin-only member review aggregation in `/api/resumes`.
- [ ] Keep member list payload scoped to the current member's own `reviewState`.
- [ ] Run targeted tests until green.

### Task 3: Member Suitable List Push Button

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/index.html` if a new button id is simpler than dynamic relabeling.
- Modify: `frontend/styles.css` only if existing button styles cannot cover the new state.
- Test: `tests/domain/test_frontend_resume_member_view.py`

**Interfaces:**
- Produces: in member mode and `state.tab === "suitable"`, action dock shows a single "推送" button instead of "合适/不合适".
- Produces: clicking "推送" confirms `是否推送给管理员` and calls `/api/resumes/{id}/push-to-admin`.
- Keeps: non-suitable member tabs show "合适/不合适"; admin keeps existing review controls.

- [ ] Write failing static frontend tests for the push button text, confirm prompt, and endpoint.
- [ ] Implement dynamic action dock rendering or button relabeling.
- [ ] Implement `pushSelectedResumeToAdmin()` and refresh after mutation.
- [ ] Run frontend contract tests until green.

### Task 4: Verification

**Files:**
- No production files beyond Tasks 1-3.

- [ ] Run `python -m pytest tests/domain/test_resume_review_workbench.py tests/domain/test_phase5_resume.py tests/domain/test_frontend_resume_member_view.py -q`.
- [ ] Run `python -m pytest tests/domain/test_resume_scope_permissions.py tests/domain/test_auth_login_access.py -q`.
- [ ] Run `python -m ruff check app tests`.
- [ ] Review `git diff --check`.
- [ ] Summarize files changed, behavior, and any test limitations.
