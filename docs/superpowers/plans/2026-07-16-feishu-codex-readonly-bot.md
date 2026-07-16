# Feishu Codex Read-Only Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Feishu single-chat bot that uses Codex only to plan permission-scoped read-only recruitment queries without changing existing HR Agent behavior.

**Architecture:** A dedicated lark-cli profile consumes Feishu events and replies as a bot. A strict access policy resolves `open_id`, a Codex subprocess emits a schema-constrained query plan, and an independently validated gateway queries SQLite in read-only mode before deterministic rendering.

**Tech Stack:** Python 3.12, SQLite, Pydantic, asyncio subprocesses, lark-cli, Codex CLI, pytest.

## Global Constraints

- Keep all existing FastAPI routes, Worker startup, browser automation, auto-sync and interview-center behavior unchanged.
- The bot is disabled by default and runs only through `scripts/run_feishu_bot.py`.
- No bot tool can write recruitment data or control a Worker.
- No secret, browser profile, token, raw resume text or candidate chat text is exposed to Codex.
- Every production behavior is introduced test-first.

---

### Task 1: Bot persistence and models

**Files:**
- Modify: `app/db/schema.sql`
- Create: `app/features/feishu_bot/models.py`
- Create: `app/features/feishu_bot/repository.py`
- Test: `tests/features/test_feishu_bot_v1.py`

**Interfaces:**
- Produces `BotEvent`, `BotActor`, `BotQueryPlan`, `BotQueryResult` and `FeishuBotRepository`.
- `FeishuBotRepository.claim_event(event)` atomically returns whether an event is new.

- [ ] Write failing schema/repository tests for unique `event_id`, unique `message_id`, lifecycle updates, turn redaction and bounded text.
- [ ] Run the focused tests and confirm failure because the tables and classes do not exist.
- [ ] Add only the two additive bot tables and repository implementation.
- [ ] Re-run focused tests and confirm pass.

### Task 2: Explicit open_id access policy

**Files:**
- Create: `config/feishu_bot_access.yaml`
- Create: `app/features/feishu_bot/access.py`
- Test: `tests/features/test_feishu_bot_v1.py`

**Interfaces:**
- Produces `FeishuBotAccessPolicy.resolve(open_id) -> BotActor | None`.
- `BotActor` contains role, permissions, allowed job types and review user ID.

- [ ] Write failing tests proving unknown users and name-only matches are denied.
- [ ] Write failing tests proving member job scope and admin wildcard scope.
- [ ] Implement YAML loading, canonical job normalization and duplicate-open-id validation.
- [ ] Re-run focused tests.

### Task 3: Read-only recruitment query gateway

**Files:**
- Create: `app/features/feishu_bot/queries.py`
- Test: `tests/features/test_feishu_bot_queries.py`

**Interfaces:**
- Produces `ReadOnlyRecruitmentQueries.execute(actor, plan) -> BotQueryResult`.
- Accepts an optional worker-status provider and manager-runs directory.

- [ ] Write failing tests for daily report counts, BOSS handoffs, distinct local file hashes and anomaly counts.
- [ ] Write failing tests for member SQL-level job filtering and admin global access.
- [ ] Write failing tests for recent resume field redaction, review summary and admin-only tools.
- [ ] Implement read-only SQLite connections, Beijing date bounds, canonical job aggregation and coverage metadata.
- [ ] Re-run query tests.

### Task 4: Codex structured query planner

**Files:**
- Create: `app/features/feishu_bot/codex_planner.py`
- Create: `app/features/feishu_bot/query_plan.schema.json`
- Test: `tests/features/test_feishu_bot_codex.py`

**Interfaces:**
- Produces async `CodexQueryPlanner.plan(actor, question, context) -> BotQueryPlan`.
- Accepts an injectable subprocess runner for tests.

- [ ] Write failing tests for exact Codex argv safety settings and schema parsing.
- [ ] Write failing tests that reject command execution, file changes, MCP calls, web searches, out-of-scope jobs and admin-only intents.
- [ ] Implement the ephemeral Codex JSONL runner in an empty runtime directory.
- [ ] Add a deterministic fallback planner for common Chinese queries when Codex is unavailable.
- [ ] Run an opt-in real Codex smoke test and record latency.

### Task 5: lark-cli event and reply adapters

**Files:**
- Create: `app/features/feishu_bot/lark_cli.py`
- Test: `tests/features/test_feishu_bot_lark_cli.py`

**Interfaces:**
- Produces `LarkEventSource.events()` and `LarkReplyClient.reply(message_id, text, idempotency_key)`.
- The event source waits for the documented stderr ready marker and closes stdin for graceful stop.

- [ ] Write failing process-double tests for ready detection, NDJSON parsing, structured startup failure and graceful shutdown.
- [ ] Write failing reply tests for named profile, bot identity and stable idempotency key.
- [ ] Implement subprocess adapters without shell command construction.
- [ ] Re-run adapter tests.

### Task 6: Bot orchestration service

**Files:**
- Create: `app/features/feishu_bot/service.py`
- Create: `app/features/feishu_bot/render.py`
- Test: `tests/features/test_feishu_bot_service.py`

**Interfaces:**
- Produces `FeishuRecruitmentBot.handle_event(event)` and `serve(stop_event)`.

- [ ] Write failing tests for duplicate suppression, unauthorized users, group-chat help, member query, admin query and reply failure.
- [ ] Implement the processing pipeline and deterministic Chinese renderers.
- [ ] Ensure no denied/duplicate event reaches Codex or the query gateway.
- [ ] Re-run service tests.

### Task 7: Configuration and operational CLI

**Files:**
- Modify: `app/settings.py`
- Create: `app/features/feishu_bot/runtime.py`
- Create: `scripts/run_feishu_bot.py`
- Create: `scripts/manage_feishu_bot.ps1`
- Modify: `.env.example`
- Test: `tests/features/test_feishu_bot_runtime.py`

**Interfaces:**
- Commands: `preflight`, `handle-event`, `serve`, `status`, `stop`.
- Default state is disabled; all paths resolve through project settings.

- [ ] Write failing tests for explicit enable, non-secret named profile, single-instance lock, status and stop request.
- [ ] Implement runtime composition and CLI commands.
- [ ] Add a PowerShell manager that only targets the bot PID/state and uses hidden windows.
- [ ] Re-run runtime tests.

### Task 8: Dedicated Feishu app and live trial

**External state:**
- Create lark-cli profile `hr-agent-readonly-bot` using `config init --new --name`.
- Grant only P2P receive and message-send scopes.
- Enable event `im.message.receive_v1` and restrict app availability.

- [ ] Run `preflight` and resolve any structured scope errors through the Feishu developer console.
- [ ] Populate `config/feishu_bot_access.yaml` with the dedicated app's open IDs.
- [ ] Run one admin and one member single-chat query.
- [ ] Verify member cross-job, worker-status and group-chat attempts do not expose data.
- [ ] Verify duplicate replay produces no second reply.

### Task 9: Regression and delivery

**Files:**
- Test all new files plus existing auth, scope, auto-sync, resume review and runtime suites.

- [ ] Run all Feishu bot tests.
- [ ] Run existing Feishu OAuth, resume scope, review workbench, auto-sync and agent runtime tests.
- [ ] Run `ruff check app scripts tests` and syntax checks.
- [ ] Inspect `git diff --check` and verify no secret or runtime data is staged.
- [ ] Commit with a Chinese message and push `interview-center-migration`.
