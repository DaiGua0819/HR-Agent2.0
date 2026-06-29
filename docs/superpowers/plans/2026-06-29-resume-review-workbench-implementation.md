# Resume Review Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first resume review workspace with filtering, fixed resume viewing, viewed/unviewed state, suitable/unsuitable decisions, and a “待我处理” queue.

**Architecture:** Keep the existing FastAPI control plane and add a focused `resume_review` domain module. Serve a lightweight static frontend from `frontend/` so the feature works locally without introducing a Node build pipeline. Use a mock current user endpoint for local testing now, while preserving boundaries for real Feishu auth later.

**Tech Stack:** FastAPI, SQLite, Pydantic/dataclasses, vanilla HTML/CSS/JavaScript, existing `ResumeService` and `ResumeRepository`.

## Global Constraints

- Implement only in `hr-agent/`; do not modify the old server.
- Keep frontend and backend responsibilities separate.
- Do not connect real Feishu in this phase; expose a local mock `/api/auth/me`.
- Preserve existing resume APIs and add review APIs alongside them.
- Each file should stay focused and around 400 lines or less.
- Run local verification after implementation.

---

### Task 1: Add Review Domain And Tables

**Files:**
- Modify: `app/db/schema.sql`
- Modify: `app/db/engine.py`
- Create: `app/domain/resume_review/models.py`
- Create: `app/domain/resume_review/repository.py`
- Create: `app/domain/resume_review/service.py`

**Interfaces:**
- Produces: `ResumeReviewService.mark_viewed(resume_id, user_id)`
- Produces: `ResumeReviewService.set_decision(resume_id, user_id, decision, reason_tags, note, assign_to)`
- Produces: `ResumeReviewService.context_for_resume(resume, user_id)`
- Produces: `ResumeReviewService.queue_for_user(user_id)`

- [ ] Add four tables: `resume_review_states`, `resume_review_events`, `resume_assignments`, `resume_saved_views`.
- [ ] Add idempotent migrations by relying on `CREATE TABLE IF NOT EXISTS` in `schema.sql`.
- [ ] Implement repository methods for state upsert, event append, assignment creation, and queue listing.
- [ ] Implement service rules: opening a resume marks it viewed; suitable creates an assignment; unsuitable does not.
- [ ] Add focused tests for viewed state and suitable assignment creation.

### Task 2: Add Auth And Review APIs

**Files:**
- Create: `app/api/routes/auth.py`
- Create: `app/api/routes/resume_review.py`
- Modify: `app/api/routes/resumes.py`
- Modify: `app/control_plane/main.py`

**Interfaces:**
- Produces: `GET /api/auth/me`
- Produces: `GET /api/resumes/{resume_id}/review-context`
- Produces: `POST /api/resumes/{resume_id}/view`
- Produces: `POST /api/resumes/{resume_id}/review-decision`
- Produces: `GET /api/resume-review/queue`

- [ ] Add a local mock current user with super admin permissions.
- [ ] Wire `ResumeReviewService` into `app.state`.
- [ ] Add review context endpoint combining resume, review state, score payload, and artifact/session metadata already present on the resume.
- [ ] Add decision endpoint with `suitable`, `unsuitable`, and `needs_more_info`.
- [ ] Extend resume list filtering with read status, decision, owner, platform, score, education, and keyword filters where data exists.
- [ ] Add API tests using in-memory repositories or temporary SQLite.

### Task 3: Serve Local Frontend

**Files:**
- Modify: `app/control_plane/main.py`
- Modify: `frontend/index.html`
- Create: `frontend/styles.css`
- Create: `frontend/app.js`

**Interfaces:**
- Produces: `GET /index.html` and `/app/resumes` browser entry.
- Consumes: `/api/auth/me`, `/api/resumes`, `/api/resumes/{id}/review-context`, review decision APIs.

- [ ] Mount static frontend files from `frontend/`.
- [ ] Keep `/api/*` routes unaffected.
- [ ] Make `/` redirect or return `frontend/index.html` for local browser use.
- [ ] Keep all frontend files static and dependency-free.

### Task 4: Build Resume Library UI

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `frontend/app.js`

**Interfaces:**
- Produces UI state: filters, selected resume id, review context, queue tab.

- [ ] Build AppShell with sidebar and top user/scope display.
- [ ] Build status tabs: 全部、未看、已看、待判断、合适、不合适、待补充、待我处理.
- [ ] Build filter bar: keyword, owner, platform, job type, score min, score max, education.
- [ ] Build dense resume table with “查看 / 合适 / 不合适”.
- [ ] Fetch and render data from existing APIs.

### Task 5: Build Review Workbench UI

**Files:**
- Modify: `frontend/styles.css`
- Modify: `frontend/app.js`

**Interfaces:**
- Consumes: `ReviewContext`.
- Produces: user decisions through review APIs.

- [ ] Build three-column workbench: current list, fixed preview pane, right summary panel.
- [ ] Use text preview first; if file path/PDF exists, show file metadata and a fixed preview placeholder.
- [ ] Add right panel sections for summary, score, source, chat/session bridge, and review state.
- [ ] Add fixed bottom action bar: 已看、合适、不合适、待补充、下一份.
- [ ] After a decision succeeds, refresh list and move to the next resume.

### Task 6: Verify Locally

**Files:**
- Modify only if verification exposes issues.

**Commands:**
- `.venv312\Scripts\python.exe -m pytest tests -q`
- `.venv312\Scripts\python.exe -m ruff check .`
- `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`
- `.venv312\Scripts\python.exe run_control_plane.py`

- [ ] Run tests and static checks.
- [ ] Start local control plane.
- [ ] Confirm `http://127.0.0.1:8080/index.html` renders the workbench.
- [ ] Commit implementation with a Chinese commit name.
