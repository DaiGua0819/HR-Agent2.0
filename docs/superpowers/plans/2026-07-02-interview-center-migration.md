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

- [ ] Write failing tests for upserting by `feishuEventId`, token persistence, and logs.
- [ ] Run: `.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`
- [ ] Implement schema/store migration with backward-compatible row loading.
- [ ] Re-run targeted tests and full existing `tests/features/test_phase6_interview_center.py`.
- [ ] Add snapshot entry.

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

- [ ] Write failing tests for AI/HR/运营B route selection, phone-first matching, ambiguous names, and field filtering.
- [ ] Run the new tests and confirm failures are behavior failures.
- [ ] Implement route constants from the old service and matching helpers.
- [ ] Re-run targeted tests.
- [ ] Add snapshot entry.

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

- [ ] Write failing tests for interview-like detection, event upsert, auto match, non-interview ignore, and API compatibility.
- [ ] Implement normalized calendar event flow using injectable calendar client.
- [ ] Re-run targeted and old phase6 tests.
- [ ] Add snapshot entry.

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

- [ ] Write failing tests for requiring resume binding, generating question set, storing `feishuDoc`, and preserving `prepared_local` when doc write fails.
- [ ] Implement doc protocol and service orchestration.
- [ ] Re-run targeted and old phase6 tests.
- [ ] Add snapshot entry.

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

- [ ] Write failing tests for existing attachment skip, upload/write fields, table route guard, and second interview field selection.
- [ ] Implement asset sync using existing render helpers and mockable upload/document clients.
- [ ] Re-run targeted tests.
- [ ] Add snapshot entry.

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

- [ ] Write failing tests for 10-minute protection, empty source failure, evaluation persistence, resume update, Bitable asset calls, and review status.
- [ ] Implement source collection protocol and backfill orchestration.
- [ ] Re-run targeted tests.
- [ ] Add snapshot entry.

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

- [ ] Write failing tests for auth URL scope, token save on callback with fake HTTP client, status payload, and disconnect.
- [ ] Implement token exchange/refresh with dependency injection and dry-run-safe tests.
- [ ] Re-run targeted tests.
- [ ] Add snapshot entry.

### Task 8: Final Regression And Local Runtime Verification

**Files:**
- Modify only if tests reveal defects.
- Docs: `docs/change-snapshots-3.md`

**Verification commands:**
- `.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py -q`
- `.venv312\Scripts\python.exe -m pytest -q`
- `.venv312\Scripts\python.exe -m ruff check app tests`
- `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`

- [ ] Run all verification commands.
- [ ] Start local 18080 service only after tests pass, if port is available.
- [ ] Smoke test auth + old interview center endpoints with TestClient or local HTTP.
- [ ] Add final snapshot entry.
