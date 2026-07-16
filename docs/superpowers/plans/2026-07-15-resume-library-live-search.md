# Resume Library Live Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing resume-library search update results automatically 250ms after typing stops, without navigating to the resume library from other pages.

**Architecture:** Keep the existing server-side `/api/resumes?q=...` search and list request cancellation. Extend `bindGlobalSearchToFilters()` with a small search synchronizer that scopes behavior to `state.view === "resumes"`, protects IME composition, reuses the existing debounce timer, and supports Enter for immediate execution.

**Tech Stack:** Vanilla JavaScript, FastAPI static frontend, pytest contract tests.

## Global Constraints

- Live search only runs while `state.view === "resumes"`.
- Debounce remains exactly `250ms` through `RESUME_FILTER_DEBOUNCE_MS`.
- Do not add autocomplete, a result popover, or a backend API.
- Preserve the current job, status, date, education, review, pagination, cache, and permission behavior except that search resets the page to 1.
- Preserve the existing uncommitted score-capsule changes.

---

### Task 1: Add Failing Live-Search Contracts

**Files:**
- Modify: `tests/domain/test_frontend_resume_member_view.py`

**Interfaces:**
- Consumes: `bindGlobalSearchToFilters()`, `scheduleResumeFilterRefresh()`, `loadResumes({ fromFilter: true })`.
- Produces: contract coverage for scoped input, IME handling, Enter execution, and cache-bust versioning.

- [ ] **Step 1: Replace the old Enter-only assertion with live-search assertions**

Update the existing global-search test so it asserts these exact behaviors:

```python
def test_global_search_uses_debounced_resume_library_search_without_result_panel() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="globalSearch"' in html
    assert 'globalSearch.addEventListener("input"' in script
    assert 'globalSearch.addEventListener("compositionstart"' in script
    assert 'globalSearch.addEventListener("compositionend"' in script
    assert 'globalSearch.addEventListener("keydown"' in script
    assert 'if (state.view !== "resumes") return;' in script
    assert 'const queryField = $("filters")?.q;' in script
    assert 'queryField.value = globalSearch.value' in script
    assert 'scheduleResumeFilterRefresh();' in script
    assert 'loadResumes({ fromFilter: true })' in script
    assert 'setView("resumes")' not in script.split("function bindGlobalSearchToFilters()", 1)[1].split("function applyResumeFilters()", 1)[0]
    assert 'id="globalSearchResults"' not in html
    assert "ts-command-search__panel" not in styles
```

- [ ] **Step 2: Add a cache-bust assertion**

```python
assert "/assets/app.js?v=20260715-resume-live-search" in html
```

Update the other two existing app.js version assertions to the same value.

- [ ] **Step 3: Run the focused test and verify RED**

Run:

```powershell
.venv312\Scripts\python.exe -m pytest tests/domain/test_frontend_resume_member_view.py -q -k "global_search"
```

Expected: FAIL because the current code has no `input` or composition listeners and still references the old app.js version.

---

### Task 2: Implement Scoped Debounced Search

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Test: `tests/domain/test_frontend_resume_member_view.py`

**Interfaces:**
- Consumes: `state.view`, `state.page`, `state.resumeFilterDebounceTimer`, `clearResumePrefetchCache()`, `scheduleResumeFilterRefresh()`, `loadResumes()`.
- Produces: `applyGlobalResumeSearch(globalSearch, { immediate = false } = {}) -> void` and updated `bindGlobalSearchToFilters()` listeners.

- [ ] **Step 1: Add the minimal search synchronizer before `bindGlobalSearchToFilters()`**

```javascript
function applyGlobalResumeSearch(globalSearch, { immediate = false } = {}) {
  if (state.view !== "resumes") return;
  const queryField = $("filters")?.q;
  if (!queryField) return;
  queryField.value = globalSearch.value;
  state.page = 1;
  clearResumePrefetchCache();
  if (!immediate) {
    scheduleResumeFilterRefresh();
    return;
  }
  if (state.resumeFilterDebounceTimer) clearTimeout(state.resumeFilterDebounceTimer);
  state.resumeFilterDebounceTimer = null;
  loadResumes({ fromFilter: true }).catch((error) => {
    if (error?.name === "AbortError") return;
    console.debug("resume search refresh failed", error);
  });
}
```

- [ ] **Step 2: Replace the Enter-only binding with input and IME handling**

```javascript
function bindGlobalSearchToFilters() {
  const globalSearch = $("globalSearch");
  if (!globalSearch) return;
  let composing = false;
  globalSearch.addEventListener("compositionstart", () => {
    composing = true;
  });
  globalSearch.addEventListener("compositionend", () => {
    composing = false;
    applyGlobalResumeSearch(globalSearch);
  });
  globalSearch.addEventListener("input", () => {
    if (composing) return;
    applyGlobalResumeSearch(globalSearch);
  });
  globalSearch.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || composing || state.view !== "resumes") return;
    event.preventDefault();
    applyGlobalResumeSearch(globalSearch, { immediate: true });
  });
}
```

- [ ] **Step 3: Update the app.js cache-bust**

Change `frontend/index.html` to:

```html
<script src="/assets/app.js?v=20260715-resume-live-search"></script>
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
.venv312\Scripts\python.exe -m pytest tests/domain/test_frontend_resume_member_view.py -q -k "global_search"
```

Expected: PASS.

- [ ] **Step 5: Commit the behavior**

```powershell
git add frontend/app.js frontend/index.html tests/domain/test_frontend_resume_member_view.py
git commit -m "增加简历库实时搜索"
```

---

### Task 3: Regression And Local Browser Verification

**Files:**
- Verify: `frontend/app.js`
- Verify: `frontend/index.html`
- Verify: `tests/domain/test_frontend_resume_member_view.py`

**Interfaces:**
- Consumes: the completed live-search behavior.
- Produces: automated and local-browser evidence that the feature is responsive and scoped correctly.

- [ ] **Step 1: Run automated regression checks**

```powershell
.venv312\Scripts\python.exe -m pytest tests/domain/test_frontend_resume_member_view.py -q
node --check frontend/app.js
.venv312\Scripts\python.exe -m ruff check app tests
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Start the local service on 18081**

```powershell
$env:CONTROL_PLANE_HOST='127.0.0.1'
$env:CONTROL_PLANE_PORT='18081'
$env:DRY_RUN='true'
.venv312\Scripts\python.exe run_control_plane.py
```

- [ ] **Step 3: Verify the browser behavior with real local resumes**

Open `http://127.0.0.1:18081/api/auth/dev-login?username=admin`, then `http://127.0.0.1:18081/index.html` and confirm:

- Typing in the search field while on the resume library sends one list request about 250ms after typing stops.
- Rapid typing cancels or supersedes older list requests and only the final keyword remains visible.
- Chinese IME composition does not refresh before composition ends.
- Enter refreshes immediately.
- Clearing the field restores results while preserving other selected filters.
- Typing while on dashboard or tasks does not navigate or request resume results.

- [ ] **Step 4: Stop only the local 18081 process**

Verify port 18081 has no listener after the test. Do not stop or modify server 18080 or old 8080.
