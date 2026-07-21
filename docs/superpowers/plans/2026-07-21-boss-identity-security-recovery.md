# BOSS Identity And Security Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent volatile BOSS UI metadata from creating false identity anomalies, preserve trusted identity through production persistence, and eliminate `_security_check` status false positives.

**Architecture:** Conversation fingerprints use stable normalized message text with normalized raw fallback. Stable platform identity remains authoritative only when the candidate name also matches, and persistence cannot overwrite trusted identity after a conflict. Worker runtime status uses explicit BOSS verification evidence rather than generic URL substrings.

**Tech Stack:** Python 3.12, FastAPI, asyncio, SQLite, pytest, Ruff.

## Global Constraints

- Do not read, copy, or modify browser credentials or profile storage.
- Do not bypass BOSS security verification.
- Keep manager anomaly classification unchanged.
- Do not migrate or bulk-update historical database rows.
- Preserve job51 and Zhilian behavior and resume ingestion contracts.

---

### Task 1: Stable Conversation Fingerprints

**Files:**
- Modify: `tests/domain/test_conversation_state_bridge.py`
- Modify: `app/domain/conversation/dedup.py`

**Interfaces:**
- Consumes: `recent_messages_fingerprint(messages: list[ChatMessage], window_size: int = 3) -> str`
- Produces: the same public function with stable `text`-first fingerprint semantics

- [ ] **Step 1: Write the failing test**

Add a test that creates two equivalent `ChatMessage` lists whose `text` is identical but whose `raw_text` changes from a relative timestamp/read state to an absolute timestamp/read state. Assert both fingerprints are equal.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/domain/test_conversation_state_bridge.py -k fingerprint_ignores_volatile_raw_metadata -q`

Expected: FAIL because `_fingerprint_window` currently hashes `raw_text` before `text`.

- [ ] **Step 3: Write minimal implementation**

Change `_fingerprint_window` to hash `normalize_message_text(item.text or item.raw_text)` for each message. Do not change `message_hash` or persistence deduplication in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/domain/test_conversation_state_bridge.py -k fingerprint_ignores_volatile_raw_metadata -q`

Expected: PASS.

### Task 2: Preserve Hard Identity Protection

**Files:**
- Modify: `tests/domain/test_conversation_state_bridge.py`
- Modify: `app/domain/conversation/identity.py`

**Interfaces:**
- Consumes: `resolve_or_create_session(repository, conversation) -> SessionResolution`
- Produces: `_candidate_names_match(stored: str, current: str) -> bool`

- [ ] **Step 1: Write failing same-candidate test**

Create an existing session with a stable platform conversation ID, position, and candidate name. Reopen it with evolved messages and changed volatile raw metadata. Assert the same session is reused and `warnings == []`.

- [ ] **Step 2: Run same-candidate test to verify it fails**

Run: `pytest tests/domain/test_conversation_state_bridge.py -k stable_platform_identity_accepts_same_candidate_with_evolved_messages -q`

Expected: FAIL with `recent_messages_not_matched`.

- [ ] **Step 3: Write failing changed-candidate test**

Reopen the same platform ID and position with a different non-empty candidate name and unrelated messages. Assert `recent_messages_not_matched` remains in warnings.

- [ ] **Step 4: Run changed-candidate test**

Run: `pytest tests/domain/test_conversation_state_bridge.py -k stable_platform_identity_warns_when_candidate_name_changes -q`

Expected: PASS under current behavior; retain it as a safety regression test.

- [ ] **Step 5: Write minimal implementation**

When the existing recent fingerprint is not found, append `recent_messages_not_matched` only if normalized non-empty candidate names do not match. Normalize by removing whitespace and applying `casefold()`.

- [ ] **Step 6: Run both identity tests**

Run: `pytest tests/domain/test_conversation_state_bridge.py -k "stable_platform_identity or fingerprint_ignores_volatile_raw_metadata" -q`

Expected: all selected tests PASS.

### Task 3: Preserve Identity Through Production Persistence

**Files:**
- Modify: `tests/domain/test_conversation_state_bridge.py`
- Modify: `app/agent/persistence.py`
- Modify: `app/domain/conversation/identity.py`
- Modify: `app/domain/conversation/dedup.py`

**Interfaces:**
- Consumes: `ConversationPersistence.attach(state, conversation) -> None`
- Produces: persistent identity conflicts that remain anomalous across repeated observations

- [ ] **Step 1: Add failing production persistence test**

Attach Alice, then attach Bob twice with the same platform conversation ID and position. Assert both Bob observations emit `recent_messages_not_matched`, while the stored name and fingerprint remain Alice's.

- [ ] **Step 2: Add empty-fingerprint and whitespace fallback tests**

Assert an empty historical fingerprint does not permit a changed candidate name, and whitespace-only `text` falls back to `raw_text`.

- [ ] **Step 3: Preserve the trusted fields**

On conflict, preserve candidate name, label, and fingerprint. Do not upsert conflicting messages or overwrite the stored fingerprint in `ConversationPersistence.attach`.

- [ ] **Step 4: Run the complete conversation-state suite**

Run: `pytest tests/domain/test_conversation_state_bridge.py -q`

Expected: PASS.

### Task 4: Align Worker Security Status

**Files:**
- Add: `tests/domain/test_runtime_status.py`
- Modify: `app/domain/automation_monitoring/runtime_status.py`

- [ ] **Step 1: Write the failing `_security_check` test**

Build a BOSS status for `/web/chat/index?_security_check=...` with title `BOSS直聘`. Assert it is authenticated and ready.

- [ ] **Step 2: Retain real verification coverage**

Assert `verify.html` with title `安全验证` remains `security_verification_required`.

- [ ] **Step 3: Implement explicit markers**

Do not search the full URL for generic `security`. Match explicit verification URLs and security titles.

- [ ] **Step 4: Run runtime-status and manager tests**

Run: `pytest tests/domain/test_runtime_status.py tests/scripts/test_agent_manager.py -q`

Expected: PASS.

### Task 5: Regression, Commit, Deploy, And Canary

**Files:**
- Modify only files from Tasks 1-4

- [ ] **Step 1: Run focused suites**

Run: `pytest tests/domain/test_conversation_state_bridge.py tests/domain/test_runtime_status.py tests/scripts/test_agent_manager.py -q`

Expected: PASS.

- [ ] **Step 2: Run static checks**

Run: `ruff check app/agent/persistence.py app/domain/conversation/dedup.py app/domain/conversation/identity.py app/domain/automation_monitoring/runtime_status.py tests/domain/test_conversation_state_bridge.py tests/domain/test_runtime_status.py`

Expected: PASS.

- [ ] **Step 3: Run cross-platform and full suites**

Run the repository's established cross-platform test selection, then `pytest -q`.

Expected: PASS with no new warnings.

- [ ] **Step 4: Commit and push**

Commit only the reviewed identity/status files, tests, and incident documentation. Push `interview-center-migration`.

- [ ] **Step 5: Deploy changed files**

Create a server deployment backup, copy only changed source files, verify SHA256 equality, and restart only Workers that import the changed code. Preserve CloakBrowser processes and profiles.

- [ ] **Step 6: Verify server preflight**

Run manager preflight and data-health. The BOSS chat URL with `_security_check` must report ready when manager blockers are empty.

- [ ] **Step 7: Run safe canaries**

Run job51 and Zhilian canaries for authenticated targets. For each local resume acquisition, verify server file path, file hash, parsed artifact, resume ID, score, and exact session linkage. Run a BOSS canary only after the corresponding account no longer reports security verification.
