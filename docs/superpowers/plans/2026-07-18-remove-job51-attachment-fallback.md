# Remove Job51 Attachment Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop sending an automatic attachment-resume message when a 51 online resume cannot be exported.

**Architecture:** The Job51 adapter continues attempting the online download and native request control. If both fail, it returns an unhandled result; `ConversationRunner` converts that result into `request_resume_failed`, allowing the manager anomaly policy to stop safely.

**Tech Stack:** Python 3.12, asyncio, pytest.

## Global Constraints

- Do not change BOSS or Zhilian behavior.
- Do not remove online-resume download attempts or the native 51 request button.
- Do not send substitute text when export and native request are unavailable.

---

### Task 1: Replace the text fallback with an explicit failure

**Files:**
- Modify: `tests/agent/test_job51_phase3.py`
- Modify: `app/platforms/job51/actions_resume.py`
- Modify: `app/agent/runner.py`

**Interfaces:**
- Consumes: `Job51Adapter.request_resume()` and `ConversationRunner.run_current()`.
- Produces: an unhandled result with reason `online_resume_not_exportable_attachment_request_unavailable` and no sent message.

- [x] **Step 1: Write the failing tests**

Change the existing fallback tests to assert `state["stage"] == "request_resume_action_failed"`, `result["requested"] is False`, and `page.sent_messages == []`.

- [x] **Step 2: Verify the tests fail**

Run: `pytest tests/agent/test_job51_phase3.py -k "online_resume and native_request" -q`

Expected: FAIL because the runner currently sends the attachment fallback message.

- [x] **Step 3: Remove the fallback production path**

Remove `ATTACHMENT_REQUEST_FALLBACK_MESSAGE`, stop returning `needsAttachmentRequest` and `attachmentRequestMessage`, and make `ConversationRunner._request_resume()` return the adapter result directly.

- [x] **Step 4: Verify focused and regression tests**

Run: `pytest tests/agent/test_job51_phase3.py -q`

Expected: PASS.

Run: `pytest tests/agent/test_job51_phase3.py tests/agent/test_runner.py -q`

Expected: PASS.

- [x] **Step 5: Run code quality checks**

Run: `ruff check app tests`

Expected: PASS.
