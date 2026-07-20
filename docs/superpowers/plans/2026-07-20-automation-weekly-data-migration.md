# 近七日招聘数据一次性迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从现有候选人处理记录生成近七日每日投影，一次性幂等导入服务器，并让仪表盘按候选人最新记录展示非零统计。

**Architecture:** 本地投影器以 Agent Manager JSONL 为主数据源，以会话、处理快照和简历表补充，生成稳定的 `automation_contact_events` 每日记录。迁移 CLI 负责 dry-run、JSON 导出和服务器导入；服务端聚合先按候选人归并，最新记录提供展示字段，动作布尔值按日累计。前端隐藏账号状态区域，并用两位年份日期控件调用现有 ISO 日期 API。

**Tech Stack:** Python 3.12、SQLite、Pydantic、FastAPI、原生 JavaScript、CSS、pytest。

## Global Constraints

- 时间边界固定使用 `Asia/Shanghai`。
- 同一候选人同一天只展示一次，跨日期分别统计。
- 最新记录提供动作、阶段和时间；当日动作标记采用 OR 累计。
- 迁移默认 dry-run，只有显式 `--apply` 才写数据库。
- 不新增长期本地监控同步任务，不迁移浏览器凭据。
- 暂时隐藏账号状态区域，不影响现有简历和聊天 Auto Sync。
- 日期显示 `YY/MM/DD`，API 和数据库继续使用 `YYYY-MM-DD`。
- 服务器部署不得修改或重启 `8080`。

---

### Task 1: 候选人每日投影器

**Files:**
- Create: `app/domain/automation_monitoring/daily_projection.py`
- Test: `tests/domain/test_automation_daily_projection.py`

**Interfaces:**
- Produces: `build_daily_projections(database_path: Path, run_dir: Path, start_date: date, end_date: date) -> DailyProjectionExport`
- Produces: `DailyProjectionExport.events: list[AutomationContactEvent]`
- Produces: `DailyProjectionExport.coverage: dict[str, int]`

- [ ] **Step 1: Write failing tests for same-day dedupe and cumulative actions**

Create synthetic Manager JSONL entries where one session is processed twice on the same Beijing day. Assert one event is returned, the second action/time is displayed, and flags from both runs remain true.

```python
def test_projection_keeps_latest_result_and_accumulates_daily_flags(tmp_path: Path) -> None:
    export = build_daily_projections(
        database_path=database_with_session(tmp_path),
        run_dir=manager_runs_with_two_results(tmp_path),
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 20),
    )
    assert len(export.events) == 1
    event = export.events[0]
    assert event.action == "answer_question"
    assert event.requested_resume is True
    assert event.candidate_question is True
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/domain/test_automation_daily_projection.py -q
```

Expected: collection or import failure because `daily_projection.py` does not exist.

- [ ] **Step 3: Implement projection identities and Beijing date parsing**

Implement:

```python
@dataclass(frozen=True)
class DailyProjectionExport:
    events: list[AutomationContactEvent]
    coverage: dict[str, int]
    summary: dict[str, object]

def build_daily_projections(...): ...
```

Use `canonicalSessionId` first, then platform/owner/conversation identity. Build event IDs as `automation-daily-{date}-{sha256(identity)[:24]}` and `contact_key` as `session|<id>` or `conversation|<platform>|<owner>|<id>`.

- [ ] **Step 4: Add fallback-session and cross-day tests**

Assert sessions updated on dates without Manager JSONL still create processed events, and the same session on two different days creates two daily IDs.

- [ ] **Step 5: Add resume and anomaly mapping tests**

Assert verified BOSS requests count as business resume acquisition, 51job/Zhilian require a valid downloaded result or linked artifact, and failed actions set anomaly fields.

- [ ] **Step 6: Run projection tests and verify GREEN**

Run:

```powershell
python -m pytest tests/domain/test_automation_daily_projection.py -q
```

Expected: all projection tests pass.

- [ ] **Step 7: Commit the projection unit**

```powershell
git add app/domain/automation_monitoring/daily_projection.py tests/domain/test_automation_daily_projection.py
git commit -m "新增候选人每日数据投影"
```

### Task 2: 一次性导出与幂等导入 CLI

**Files:**
- Create: `scripts/migrate_automation_daily_events.py`
- Test: `tests/domain/test_automation_daily_migration.py`

**Interfaces:**
- Consumes: `build_daily_projections(...)`
- Produces CLI commands:
  - `export --database PATH --runs PATH --days 7 --output PATH`
  - `import --database PATH --input PATH [--apply]`

- [ ] **Step 1: Write failing export-package test**

Assert the JSON package contains `version`, `timezone`, `startDate`, `endDate`, `events`, `coverage`, `summary`, and a SHA-256 printed by the CLI.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/domain/test_automation_daily_migration.py::test_export_package_is_stable -q
```

Expected: import failure because the migration script does not exist.

- [ ] **Step 3: Implement export command**

Use `argparse` subcommands. Default the end date to current Beijing date and derive `startDate = endDate - 6 days`. Write UTF-8 JSON only when `--output` is supplied and always print the summary and hash.

- [ ] **Step 4: Write dry-run import test**

Create a temporary SQLite database, run import without `--apply`, and assert `automation_contact_events` remains empty while validation counts are returned.

- [ ] **Step 5: Write apply and repeat-import tests**

Apply the same package twice and assert the event count does not increase. Existing IDs must update using `AutomationMonitoringRepository.upsert_events()`.

- [ ] **Step 6: Implement package validation and import**

Reject unsupported versions, invalid date ranges, duplicate event IDs with conflicting bodies, events outside the package range, and malformed Pydantic events. `--apply` calls the repository only after the entire package validates.

- [ ] **Step 7: Run migration tests and verify GREEN**

```powershell
python -m pytest tests/domain/test_automation_daily_migration.py -q
```

- [ ] **Step 8: Commit the migration CLI**

```powershell
git add scripts/migrate_automation_daily_events.py tests/domain/test_automation_daily_migration.py
git commit -m "新增招聘数据一次性迁移工具"
```

### Task 3: 服务端候选人归并与未来稳定身份

**Files:**
- Modify: `app/domain/automation_monitoring/service.py`
- Modify: `app/domain/automation_monitoring/events.py`
- Modify: `tests/domain/test_automation_monitoring.py`

**Interfaces:**
- Produces: `_daily_candidate_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]`
- Changes: `build_contact_event()` emits stable candidate `contact_key` without message fingerprint.

- [ ] **Step 1: Write failing service test for latest display plus OR flags**

Provide two rows with the same candidate key. Assert summary counts one processed contact, both historical action flags remain counted, and details return only the newest row.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/domain/test_automation_monitoring.py -q
```

Expected: existing aggregation returns metric-specific older rows or duplicate detail behavior.

- [ ] **Step 3: Implement candidate-key normalization and daily merge**

Normalize legacy keys such as `session|abc|message|fingerprint` to `session|abc`. Sort by `occurred_at DESC, updated_at DESC, id DESC`; retain the newest row and OR all metric columns into that row.

- [ ] **Step 4: Apply merged rows to summary, facets, version and details**

`daily_summary()` and `daily_details()` must both use the same merged list. Coverage reports raw event count and unique candidate count.

- [ ] **Step 5: Write and implement stable future contact keys**

Change `build_contact_event()` to emit `session|<session_id>` and preserve `recent_messages_fingerprint` inside payload audit fields.

- [ ] **Step 6: Run monitoring regression tests**

```powershell
python -m pytest tests/domain/test_automation_monitoring.py tests/domain/test_auto_sync.py -q
```

- [ ] **Step 7: Commit aggregation changes**

```powershell
git add app/domain/automation_monitoring/service.py app/domain/automation_monitoring/events.py tests/domain/test_automation_monitoring.py
git commit -m "统一每日候选人统计口径"
```

### Task 4: 隐藏账号状态并使用两位年份日期控件

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/automation-details.js`
- Modify: `frontend/styles.css`
- Modify: `tests/domain/test_frontend_automation_monitoring.py`

**Interfaces:**
- Produces: `formatMonitoringDate(value: string) -> string`
- Preserves: API query parameter `date=YYYY-MM-DD`

- [ ] **Step 1: Update frontend contract tests first**

Assert the dashboard contains a visible `monitoringDateLabel`, a hidden ISO date input, no runtime status panel, and no `/runtime-status` request. Assert `formatMonitoringDate("2026-07-20")` displays `26/07/20` through static contract markers.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/domain/test_frontend_automation_monitoring.py -q
```

- [ ] **Step 3: Replace the native visible date input**

Keep `monitoringDate` as the ISO value source but visually hide it. Add a compact button with `monitoringDateLabel`; clicking calls `showPicker()` where supported and falls back to focusing/clicking the native input.

- [ ] **Step 4: Remove runtime panel loading and polling**

Remove the panel HTML, runtime rendering call from dashboard loading, and the 5-second runtime timer. Keep backend runtime API available for future use.

- [ ] **Step 5: Expand job distribution layout**

Change `monitoring-dashboard-grid` to one full-width column and remove runtime-only styles that are no longer referenced.

- [ ] **Step 6: Format details-page date consistently**

Display `26/07/20` in the details subtitle while preserving the full ISO date in API requests and URL parameters.

- [ ] **Step 7: Update cache-bust markers and run frontend checks**

```powershell
python -m pytest tests/domain/test_frontend_automation_monitoring.py tests/domain/test_frontend_resume_member_view.py -q
node --check frontend/app.js
node --check frontend/automation-details.js
```

- [ ] **Step 8: Commit frontend changes**

```powershell
git add frontend/index.html frontend/app.js frontend/automation-details.js frontend/styles.css tests/domain/test_frontend_automation_monitoring.py
git commit -m "优化招聘数据日期与仪表盘布局"
```

### Task 5: 近七日真实数据 dry-run 与本地导入验证

**Files:**
- Generated outside Git: `data/migrations/automation-events-2026-07-14_2026-07-20.json`

- [ ] **Step 1: Export the real seven-day package in dry-run mode**

```powershell
python scripts/migrate_automation_daily_events.py export --database data/resumes.sqlite --runs data/agent_manager/runs --end-date 2026-07-20 --days 7 --output data/migrations/automation-events-2026-07-14_2026-07-20.json
```

Review unique candidates, raw contacts, exact/fallback/unresolved coverage, per-day counts, platform totals and action totals.

- [ ] **Step 2: Import into a database backup copy**

Use SQLite backup API to create a temporary database copy, run import first without `--apply`, then with `--apply` twice. Assert totals are stable after the second apply.

- [ ] **Step 3: Start a local preview on an unused port**

Point `DATABASE_PATH` to the temporary database and start the control plane on `18083` or the next free port. Do not stop the existing local services.

- [ ] **Step 4: Browser verification**

Verify seven date selections, nonzero KPI values where source data exists, candidate dedupe, 10-row details pagination, resume links, hidden runtime panel, two-digit date display, desktop layout and mobile overflow.

### Task 6: Full verification and deployment readiness

**Files:**
- Modify only if tests expose defects.

- [ ] **Step 1: Run focused and cross-domain tests**

```powershell
python -m pytest tests/domain/test_automation_daily_projection.py tests/domain/test_automation_daily_migration.py tests/domain/test_automation_monitoring.py tests/domain/test_auto_sync.py tests/domain/test_frontend_automation_monitoring.py tests/domain/test_frontend_resume_member_view.py tests/domain/test_resume_scope_permissions.py -q
```

- [ ] **Step 2: Run quality checks**

```powershell
python -m ruff check app scripts tests
node --check frontend/app.js
node --check frontend/automation-details.js
git diff --check
```

- [ ] **Step 3: Review deployment package**

Confirm only code, tests, the migration script and the exported JSON intended for secure one-time transfer are included. Do not include `.env`, profiles, tokens, cookies, local logs or the production database.

- [ ] **Step 4: Prepare guarded server deployment**

Before server apply: compare server files, back up code and SQLite, record `8080/18080` PIDs, deploy code, run server smoke checks, import package dry-run, apply once, verify seven-day totals, and restart only `18080`.

