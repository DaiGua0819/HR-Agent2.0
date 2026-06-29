# Manager Dashboard UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working slice of the new HR Agent manager console: dashboard, service status, clearer navigation, interview center entry, and safer automation controls.

**Architecture:** Keep the current static frontend and FastAPI backend. Add a dashboard API that aggregates existing repository, review, decision, worker, and dry-run data; then replace the local static workbench shell with multi-view pages driven by that API. Reuse existing resume review, automation, monitoring, and interview routes rather than rewriting business logic.

**Tech Stack:** FastAPI, SQLite repositories, existing static HTML/CSS/JS, pytest, ruff, compileall.

## Global Constraints

- Do not connect real Feishu or ordinary Chrome.
- Keep CloakBrowser-only browser direction untouched.
- Keep platform processing logic in `ConversationRunner` and platform adapters; this UI work must not duplicate job rules.
- Do not remove dry-run safeguards.
- Keep files focused and below roughly 400 lines where practical.
- No secrets or absolute deployment paths in source.

---

## File Structure

- Create `app/api/routes/dashboard.py`: manager dashboard API DTO and aggregation.
- Modify `app/control_plane/main.py`: include dashboard router.
- Modify `frontend/index.html`: replace old local-preview shell with manager console sections.
- Modify `frontend/app.js`: add multi-view state, dashboard loading, service actions, resume review interactions, interview entry.
- Modify `frontend/styles.css`: add polished dashboard/workbench/interview/control styles.
- Test `tests/domain/test_manager_dashboard_ui.py`: API-level coverage for dashboard overview and permission-shaped payload.

## Task 1: Dashboard API

**Files:**
- Create: `app/api/routes/dashboard.py`
- Modify: `app/control_plane/main.py`
- Test: `tests/domain/test_manager_dashboard_ui.py`

**Interfaces:**
- Consumes: `ResumeRepository.count()`, `ResumeReviewService.queue_for_user(user_id)`, `Dispatcher.worker_statuses()`, `recent_decisions(limit)`, `settings.dry_run`.
- Produces: `GET /api/dashboard/overview` returning `date`, `dryRun`, `kpis`, `services`, `recentRecords`, `quickFilters`.

- [ ] **Step 1: Write failing API test**

```python
def test_dashboard_overview_returns_manager_payload(tmp_path):
    app = create_control_plane_app()
    with TestClient(app) as client:
        response = client.get("/api/dashboard/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["date"]
    assert isinstance(payload["dryRun"], bool)
    assert {item["key"] for item in payload["kpis"]} >= {
        "resumeCount",
        "pendingReview",
        "decisionCount",
        "workerReady",
    }
    assert isinstance(payload["services"], list)
    assert isinstance(payload["recentRecords"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/domain/test_manager_dashboard_ui.py -q`

Expected: FAIL because `/api/dashboard/overview` does not exist.

- [ ] **Step 3: Implement dashboard API**

Implement `dashboard.py` with:

```python
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/overview")
async def overview(request: Request) -> dict[str, object]:
    repository = getattr(request.app.state, "resume_repository", None) or ResumeRepository.from_settings()
    review_service = getattr(request.app.state, "resume_review_service", None)
    dispatcher = getattr(request.app.state, "dispatcher", None)
    services = await _worker_statuses(dispatcher)
    decisions = recent_decisions(12)
    pending_review = len(review_service.queue_for_user("admin")["items"]) if review_service else 0
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "dryRun": settings.dry_run,
        "kpis": _kpis(repository.count(), pending_review, len(decisions), services),
        "services": services,
        "recentRecords": _records(decisions),
        "quickFilters": _quick_filters(),
    }
```

- [ ] **Step 4: Include router**

Add `from app.api.routes.dashboard import router as dashboard_router` and `app.include_router(dashboard_router)` in `app/control_plane/main.py`.

- [ ] **Step 5: Run test**

Run: `pytest tests/domain/test_manager_dashboard_ui.py -q`

Expected: PASS.

## Task 2: App Shell And Navigation

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Interfaces:**
- Consumes: `GET /api/auth/me`
- Produces: views named `dashboard`, `resumes`, `queue`, `interviews`, `automation`, `rules`.

- [ ] **Step 1: Replace static shell markup**

Use this view structure:

```html
<nav class="nav">
  <button class="active" data-view="dashboard">经理驾驶舱</button>
  <button data-view="resumes">简历库</button>
  <button data-view="queue">待我处理</button>
  <button data-view="interviews">面试中心</button>
  <button data-view="automation">自动化控制</button>
  <button data-view="rules">规则与知识库</button>
</nav>
```

- [ ] **Step 2: Add JS view switching**

Implement:

```javascript
function setView(view) {
  state.view = view;
  document.querySelectorAll("[data-page]").forEach((node) => {
    node.hidden = node.dataset.page !== view;
  });
  document.querySelectorAll("[data-view]").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === view);
  });
}
```

- [ ] **Step 3: Smoke manually**

Run local server and click each nav item. Expected: only one page section visible, active nav moves.

## Task 3: Manager Dashboard Frontend

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Interfaces:**
- Consumes: `GET /api/dashboard/overview`
- Produces: KPI strip, service grid, recent records table, quick action controls.

- [ ] **Step 1: Add dashboard loader**

Implement:

```javascript
async function loadDashboard() {
  const payload = await api("/api/dashboard/overview");
  renderKpis(payload.kpis || []);
  renderServices(payload.services || []);
  renderDailyRecords(payload.recentRecords || []);
  renderSafety(payload);
}
```

- [ ] **Step 2: Add service action handlers**

Implement handlers for buttons:

```javascript
async function runProcess(platform, owner) {
  await api(`/automation/${platform}/process-messages?owner=${encodeURIComponent(owner)}`, { method: "POST" });
  await loadDashboard();
}
```

- [ ] **Step 3: Add safe UI behavior**

Show `DRY_RUN 已开启` when `payload.dryRun` is true; show red warning when false.

## Task 4: Resume Review Workbench Polish

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Interfaces:**
- Consumes existing `/api/resumes`, `/api/resumes/{id}/review-context`, `/api/resumes/{id}/review-decision`, `/api/resume-review/queue`.
- Produces three-pane fixed review layout and stable review actions.

- [ ] **Step 1: Preserve existing resume loading**

Keep current filters and `loadResumes()` behavior.

- [ ] **Step 2: Move review actions into fixed right panel**

Ensure `已看 / 合适 / 不合适 / 待补充 / 约面试` are always visible when a resume is selected.

- [ ] **Step 3: Add interview entry**

`约面试` calls the existing interview placeholder route if available, then opens `interviews` view with a visible status message.

## Task 5: Interview Center Placeholder Page

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Interfaces:**
- Consumes existing `app/api/routes/interview.py` routes when wired.
- Produces first-class `面试中心` page with session list placeholder, candidate panel, question panel, Feishu status panel.

- [ ] **Step 1: Add interview center section**

Create three columns:

```text
面试会话列表 / 候选人详情 / 面试题与飞书同步
```

- [ ] **Step 2: Render current selection**

When launched from a resume, show candidate name, job, platform, and source.

- [ ] **Step 3: Provide buttons**

Buttons: `生成题目`, `同步飞书`, `生成图片`, `反馈回填`. If backend call is not wired in this slice, show a clear disabled or mock-safe state.

## Task 6: Verification And Commit

**Files:**
- All touched files.

**Interfaces:**
- Produces a pushed commit with working first UI slice.

- [ ] **Step 1: Run tests**

Run:

```powershell
pytest tests -q
ruff check .
python -m compileall app scripts run_control_plane.py run_worker.py
```

- [ ] **Step 2: Start local server**

Run:

```powershell
python run_control_plane.py
```

Expected: `http://127.0.0.1:8080/index.html` shows the new manager console.

- [ ] **Step 3: Commit**

Run:

```powershell
git add app frontend tests docs
git commit -m "实现管理者驾驶舱首版界面"
git push origin main
```

## Self-Review

- Spec coverage: dashboard, resume review, interview entry, automation controls, roles/scope-shaped UI, and service status have tasks.
- Deliberate first-slice exclusions: full Feishu OAuth UI, complete interview session backend UI, and advanced saved filter views remain later phases.
- Placeholder scan: no implementation step depends on unspecified field names; disabled UI states are explicit for backend pieces not wired in this slice.
- Type consistency: dashboard route returns `kpis`, `services`, `recentRecords`, and `dryRun`; frontend tasks consume those exact names.
