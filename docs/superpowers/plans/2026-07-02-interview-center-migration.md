# Interview Center Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the old Node interview center into the current FastAPI service without breaking existing resume, automation, and review workflows.

**Architecture:** Keep the current Python/FastAPI boundaries and add focused interview-center modules for Feishu OAuth/token storage, Bitable routing/asset sync, calendar session sync, preparation, and backfill. Preserve old `/api/interview-center/*` compatibility while using current `ResumeRepository`, `ConversationRepository`, SQLite migrations, dry-run controls, and dependency injection.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, httpx, pytest, PyMuPDF/Pillow render helpers, existing OpenAI-compatible LLM client.

## Global Constraints

- Do not affect existing platform message processing, resume library, review workbench, or interview invite behavior.
- Use TDD: every production behavior change starts with a failing test.
- Keep Feishu write operations dry-run safe unless an existing setting explicitly allows live writes.
- Preserve old interview-center behavior: calendar sync, auto matching, question document creation, 10-minute backfill protection, Bitable route selection, idempotent asset sync, and review confirmation.
- Record every code/config change in `docs/change-snapshots-3.md` with reason, files, result, verification, and risk.
- Do not commit runtime data under `data/`, browser profiles, logs, or worktree directories.

---

## File Structure

- Create `app/features/interview_center/feishu/routes.py`: Bitable route config and keyword resolution.
- Create `app/features/interview_center/feishu/docx.py`: Feishu doc create/read/write boundary with mockable protocol.
- Create `app/features/interview_center/feishu/calendar.py`: calendar event normalization and interview-like detection.
- Create `app/features/interview_center/feishu/meeting.py`: meeting/minutes source collection protocol and default mock-safe client.
- Create `app/features/interview_center/asset_sync.py`: idempotent resume image, interview record image, and evaluation document sync.
- Create `app/features/interview_center/calendar_sync.py`: calendar sync orchestration.
- Create `app/features/interview_center/backfill.py`: interview evaluation backfill orchestration.
- Modify `app/features/interview_center/store.py`: expand `InterviewSession`, add token/log persistence.
- Modify `app/features/interview_center/service.py`: compose new services and expose old-compatible operations.
- Modify `app/features/interview_center/feishu/bitable.py`: field filtering, table routes, real upload contract.
- Modify `app/features/interview_center/feishu/oauth.py`: real token exchange/refresh through store-backed token service.
- Modify `app/api/routes/interview.py`: restore old route surface.
- Modify `app/db/schema.sql` and migrations: add missing interview center columns/tables.
- Test in `tests/features/test_interview_center_migration.py` and extend `tests/features/test_phase6_interview_center.py`.

---

### Task 1: Store And Schema Compatibility

**Files:**
- Modify: `app/db/schema.sql`
- Modify: `app/features/interview_center/store.py`
- Test: `tests/features/test_interview_center_migration.py`
- Docs: `docs/change-snapshots-3.md`

**Interfaces:**
- Produces: `InterviewSession` with old-compatible fields: `feishu_event_id`, `calendar_id`, `start_time`, `end_time`, `status`, `question_set`, `feishu_doc`, `bitable_*`, `interview_evaluation`, `backfill_source`, `payload`.
- Produces: `SQLiteInterviewStore.upsert_from_calendar_event(event: dict[str, Any]) -> InterviewSession`.
- Produces: `SQLiteInterviewStore.append_log(session_id: str, level: str, message: str, payload: dict[str, Any] | None = None) -> None`.
- Produces: `SQLiteInterviewStore.get_token() / save_token() / clear_token()`.

- [x] Write failing tests for upserting by `feishuEventId`, token persistence, and logs.
- [x] Run: `.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`
- [x] Implement schema/store migration with backward-compatible row loading.
- [x] Re-run targeted tests and full existing `tests/features/test_phase6_interview_center.py`.
- [x] Add snapshot entry.

### Task 2: Bitable Routes And Idempotent Record Matching

**Files:**
- Create: `app/features/interview_center/feishu/routes.py`
- Modify: `app/features/interview_center/feishu/bitable.py`
- Test: `tests/features/test_interview_center_migration.py`
- Docs: `docs/change-snapshots-3.md`

**Interfaces:**
- Produces: `resolve_bitable_target(input: dict[str, Any], default_table_id: str = "") -> BitableTarget`.
- Produces: `find_existing_bitable_record(records: list[dict[str, Any]], resume: dict[str, Any]) -> ExistingBitableRecord`.
- Produces: `pick_existing_bitable_fields(fields, field_map)`.

- [x] Write failing tests for AI/HR/运营B route selection, phone-first matching, ambiguous names, and field filtering.
- [x] Run the new tests and confirm failures are behavior failures.
- [x] Implement route constants from the old service and matching helpers.
- [x] Re-run targeted tests.
- [x] Add snapshot entry.

### Task 3: Calendar Sync And Candidate Matching

**Files:**
- Create: `app/features/interview_center/feishu/calendar.py`
- Create: `app/features/interview_center/calendar_sync.py`
- Modify: `app/features/interview_center/candidate_matcher.py`
- Modify: `app/features/interview_center/service.py`
- Modify: `app/api/routes/interview.py`
- Test: `tests/features/test_interview_center_migration.py`
- Docs: `docs/change-snapshots-3.md`

**Interfaces:**
- Produces: `normalize_calendar_event(calendar_id: str, raw: dict[str, Any]) -> dict[str, Any]`.
- Produces: `CalendarSyncService.sync(calendar_id="primary", auto_prepare=False, auto_prepare_limit=12)`.
- API: `POST /api/interview-center/sync`, `GET /api/interview-center/sync/status`, `GET /api/interview-center/sessions`.

- [x] Write failing tests for interview-like detection, event upsert, auto match, non-interview ignore, and API compatibility.
- [x] Implement normalized calendar event flow using injectable calendar client.
- [x] Re-run targeted and old phase6 tests.
- [x] Add snapshot entry.

### Task 4: Prepare Session And Feishu Docx Boundary

**Files:**
- Create: `app/features/interview_center/feishu/docx.py`
- Modify: `app/features/interview_center/question_generator.py`
- Modify: `app/features/interview_center/service.py`
- Modify: `app/api/routes/interview.py`
- Test: `tests/features/test_interview_center_migration.py`
- Docs: `docs/change-snapshots-3.md`

**Interfaces:**
- Produces: `InterviewDocClientProtocol.create_document_from_text(title: str, text: str)`.
- Produces: `InterviewCenterService.prepare_session(session_id: str, force: bool = False)`.
- API: `POST /api/interview-center/sessions/{id}/prepare`.

- [x] Write failing tests for requiring resume binding, generating question set, storing `feishuDoc`, and preserving `prepared_local` when doc write fails.
- [x] Implement doc protocol and service orchestration.
- [x] Re-run targeted and old phase6 tests.
- [x] Add snapshot entry.

### Task 5: Asset Sync To Bitable

**Files:**
- Create: `app/features/interview_center/asset_sync.py`
- Modify: `app/features/interview_center/feishu/bitable.py`
- Modify: `app/features/interview_center/service.py`
- Test: `tests/features/test_interview_center_migration.py`
- Docs: `docs/change-snapshots-3.md`

**Interfaces:**
- Produces: `BitableAssetSync.ensure_resume_image(...)`.
- Produces: `BitableAssetSync.ensure_interview_record_image(...)`.
- Produces: `BitableAssetSync.ensure_evaluation_document(...)`.

- [x] Write failing tests for existing attachment skip, upload/write fields, table route guard, and second interview field selection.
- [x] Implement asset sync using existing render helpers and mockable upload/document clients.
- [x] Re-run targeted tests.
- [x] Add snapshot entry.

### Task 6: Backfill Sources And Evaluation

**Files:**
- Create: `app/features/interview_center/feishu/meeting.py`
- Create: `app/features/interview_center/backfill.py`
- Modify: `app/features/interview_center/feedback_backfill.py`
- Modify: `app/features/interview_center/service.py`
- Modify: `app/api/routes/interview.py`
- Test: `tests/features/test_interview_center_migration.py`
- Docs: `docs/change-snapshots-3.md`

**Interfaces:**
- Produces: `BackfillService.backfill(session_id: str, force=False, early_override=False, early_override_token="")`.
- API: `POST /api/interview-center/sessions/{id}/backfill`, `GET /api/interview-center/sessions/{id}/backfill-source`, `GET /api/interview-center/backfill/status`.

- [x] Write failing tests for 10-minute protection, empty source failure, evaluation persistence, resume update, Bitable asset calls, and review status.
- [x] Implement source collection protocol and backfill orchestration.
- [x] Re-run targeted tests.
- [x] Add snapshot entry.

### Task 7: OAuth And Status Compatibility

**Files:**
- Modify: `app/features/interview_center/feishu/oauth.py`
- Modify: `app/features/interview_center/feishu/client.py`
- Modify: `app/features/interview_center/service.py`
- Modify: `app/api/routes/interview.py`
- Test: `tests/features/test_interview_center_migration.py`
- Docs: `docs/change-snapshots-3.md`

**Interfaces:**
- API: `GET /api/interview-center/feishu/auth-url`, `GET /api/interview-center/feishu/oauth/callback`, `GET /api/interview-center/feishu/status`, `POST /api/interview-center/feishu/disconnect`.

- [x] Write failing tests for auth URL scope, token save on callback with fake HTTP client, status payload, and disconnect.
- [x] Implement token exchange/refresh with dependency injection and dry-run-safe tests.
- [x] Re-run targeted tests.
- [x] Add snapshot entry.

### Task 8: Final Regression And Local Runtime Verification

**Files:**
- Modify only if tests reveal defects.
- Docs: `docs/change-snapshots-3.md`

**Verification commands:**
- `.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py -q`
- `.venv312\Scripts\python.exe -m pytest -q`
- `.venv312\Scripts\python.exe -m ruff check app tests`
- `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`

- [x] Run all verification commands.
- [x] Start local 18080 service only after tests pass, if port is available.
- [x] Smoke test auth + old interview center endpoints with TestClient or local HTTP.
- [x] Add final snapshot entry.

## Completion Evidence

Updated: 2026-07-03.

- Current branch: `interview-center-migration`.
- Latest verified commit before this plan-status update: `261840c 修正飞书授权配置状态判断`.
- Snapshot trail: `docs/change-snapshots-3.md` records migration snapshots `0031` through `0100`, including red/green test evidence, changed files, verification commands, and risk notes for each code/config change.
- Core route surface verified in `app/api/routes/interview.py`: sessions list/detail/create, calendar sync/status, bind, prepare, backfill/source/status, review, confirm, logs, Bitable sync, old Feishu auth-url/callback/status/disconnect, and old fallback error payload.
- Runtime page verified in `frontend/interview-center.html` plus `/assets/interview-center/*`.
- Fresh verification evidence from 2026-07-03:
  - `.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py -q`: `84 passed`, 1 existing `StarletteDeprecationWarning`.
  - `.venv312\Scripts\python.exe -m pytest -q`: `325 passed`, 1 existing `StarletteDeprecationWarning`.
  - `.venv312\Scripts\python.exe -m ruff check app tests`: All checks passed.
  - `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`: passed.
  - `node --check frontend/app.js`, `node --check frontend/interview-center/app.js`, `node --check frontend/interview-center/api.js`, `node --check frontend/interview-center/state.js`: passed.
  - Local HTTP smoke used `CONTROL_PLANE_PORT=18182` and a temporary SQLite database because 18080 is reserved for the user's local service; checked health, page assets, old interview-center endpoints, Feishu status/auth/disconnect, sync/backfill status, and unknown-route 404 payload.
  - Playwright + system Chrome opened `http://127.0.0.1:18182/interview-center.html`; `.interview-shell` rendered with no 4xx/5xx responses, no console errors, and no page errors. The temporary service was stopped after verification.

## Remaining External Verification

- Real Feishu OAuth, calendar events, Docx writes, meeting/minutes reads, and Bitable writes require valid Feishu app credentials, `FEISHU_REDIRECT_URI`, a stored user token, Bitable app/table permissions, and live Feishu data. Local tests cover these boundaries with injectable clients, dry-run guards, and HTTP mocks; final production confidence still requires one authorized Feishu environment smoke.
- Local verification intentionally did not stop or replace an existing 18080 service. The smoke server used 18182 to avoid affecting current business workflows.
