# Job51 Scroll And Batch Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve per-contact safety while preparing the 51 page once per manager batch and eliminating unnecessary repeated clicks and scrolling.

**Architecture:** The manager forwards its run id as an internal batch id. `WorkerRuntime` reuses a prepared platform page for that batch, performs one final refresh before declaring the queue empty, and keeps the existing one-contact response contract. Browser actions gain correct click-only semantics, container-scoped scrolling, context reuse, and conditional cleanup waits.

**Tech Stack:** Python 3.12, FastAPI, asyncio, Playwright CDP, pytest, Ruff.

## Global Constraints

- Keep manager anomaly accounting and graceful stop behavior per contact.
- Do not change BOSS or Zhilian business behavior.
- Do not process a real platform contact during automated verification.
- Keep current internal endpoint paths compatible.

---

### Task 1: Reuse page preparation within one manager batch

**Files:**
- Modify: `tests/agent/test_phase4_runtime.py`
- Modify: `tests/scripts/test_agent_manager.py`
- Modify: `app/worker/runtime.py`
- Modify: `app/worker/server.py`
- Modify: `app/control_plane/worker_client.py`
- Modify: `app/control_plane/dispatcher.py`
- Modify: `app/api/routes/automation.py`
- Modify: `scripts/agent_manager.py`

**Interfaces:**
- Consumes: `WorkerRuntime.process_messages(platform, exclude_ids=None, batch_id="")`.
- Produces: internal `batchId` forwarding and one final refresh before `processed=0`.

- [ ] Add runtime tests for same-batch reuse, final refresh, and new-batch preparation.
- [ ] Add route/client/manager tests proving the run id reaches the Worker as `batchId`.
- [ ] Run the focused tests and verify failures are caused by missing batch support.
- [ ] Add `_prepared_message_batches`, forward `batch_id`, and retry once after final refresh.
- [ ] Re-run focused tests and commit the task.

### Task 2: Avoid redundant position selection

**Files:**
- Modify: `tests/agent/test_job51_phase3.py`
- Modify: `app/platforms/job51/dom_scripts.py`
- Modify: `app/platforms/job51/actions_chat.py`

**Interfaces:**
- Produces: `job51.position_filter_state` and an idempotent `select_positions()` result with `changed`.

- [ ] Add tests proving an already-selected all-position filter is not clicked again.
- [ ] Run the tests and verify the click count currently increases.
- [ ] Add the position state probe and verified state transition.
- [ ] Re-run focused tests and commit the task.

### Task 3: Scope candidate and attachment scrolling to their containers

**Files:**
- Modify: `tests/agent/test_job51_phase3.py`
- Modify: `app/platforms/job51/dom_scripts.py`
- Modify: `app/platforms/job51/actions_resume_close.py`

**Interfaces:**
- Produces: conditional `#conversation-list.scrollTop` adjustment and `job51.restore_resume_chat_scroll` cleanup.

- [ ] Add contract tests rejecting centered `scrollIntoView` and requiring container boundary checks.
- [ ] Add tests requiring header attachment priority and chat scroll restoration after cleanup.
- [ ] Run tests and verify they fail against the current scripts.
- [ ] Replace both candidate scroll paths, update attachment selection, and restore saved chat position after overlay cleanup.
- [ ] Re-run focused tests and commit the task.

### Task 4: Remove duplicate candidate and chat-context reads

**Files:**
- Modify: `tests/agent/test_job51_phase3.py`
- Modify: `app/platforms/job51/actions_chat.py`
- Modify: `app/platforms/job51/actions_resume.py`
- Modify: `app/platforms/job51/adapter.py`

**Interfaces:**
- Consumes: `request_or_download_resume(page, candidate_name="", applied_position="", memory=None)`.
- Produces: one cached `Conversation` snapshot per selected contact.

- [ ] Add a counting fake page test proving successful identity opening is verified once.
- [ ] Add a direct-resume test proving chat context is parsed once before the resume action.
- [ ] Run tests and verify the new assertions fail.
- [ ] Trust the successful `click_thread_by_state()` verification, cache adapter context, and pass identity into resume handling.
- [ ] Re-run focused tests and commit the task.

### Task 5: Remove idle cleanup waits and run regression verification

**Files:**
- Modify: `tests/agent/test_job51_phase3.py`
- Modify: `app/platforms/job51/actions_resume_close.py`

**Interfaces:**
- Produces: no fixed sleep when close probes report that no overlay exists.

- [ ] Add tests that record sleep calls for empty and closed overlay paths.
- [ ] Run the tests and verify the empty-overlay test fails.
- [ ] Sleep only after an actual close action and use the existing overlay transition poll for completion.
- [ ] Run `pytest tests/platforms/test_reliable_actions.py tests/agent/test_job51_phase3.py tests/agent/test_phase4_runtime.py tests/scripts/test_agent_manager.py -q`.
- [ ] Run `ruff check app scripts tests` and `git diff --check`.
- [ ] Review the final diff against the design, commit, and push the optimization.
