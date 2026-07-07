# 51job Identity And Resume Download Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make 51job processing stop on true identity/opening anomalies and prevent stale resume preview downloads from being recorded under the wrong candidate.

**Architecture:** Treat right-side chat/header identity as the source of truth, but build a stronger expected identity from the left unread row. Before downloading, require a clean preview state; after download, verify the PDF text matches the current candidate or position before saving/recording artifacts. Batch processing should run as three single-candidate passes so a first-candidate failure stops immediately.

**Tech Stack:** Python 3.12, Playwright CDP wrapper, SQLite, pytest, existing `ConversationRunner`, `Job51Adapter`, `ResumeArtifactStore`.

## Global Constraints

- Do not change worker API semantics.
- Do not change frontend behavior.
- Do not process 51job after a `candidate_identity_mismatch`, unclosed resume overlay, traceback, timeout, or failed summary.
- Do not write a resume artifact if downloaded file content does not match the current candidate context.
- Final business filename should use current candidate context, not a stale/platform-provided filename.
- Quarantine or mark known wrong artifacts before the next resume sync.

---

## File Structure

- Modify: `app/platforms/job51/actions_chat.py`
  - Parse left-row labels when DOM attributes are missing.
  - Improve opened-candidate verification diagnostics.
- Modify: `app/platforms/job51/dom_scripts.py`
  - Expose stronger unread row fields and resume overlay state.
  - Support right-header identity fallback from label text.
- Modify: `app/platforms/job51/actions_resume_close.py`
  - Loop cleanup until resume overlays are actually gone or report `remaining`.
- Modify: `app/platforms/job51/actions_resume.py`
  - Refuse download if stale overlays cannot be closed.
  - Verify preview/download identity before saving.
- Modify: `app/platforms/job51/resume_files.py`
  - Validate resume file text against candidate context.
  - Stop trusting platform filename for final business filename.
- Modify: `scripts/platform_once_common.py`
  - Treat unclosed 51job overlays as a failed item.
- Create: `scripts/run_job51_guarded_batches.py`
  - Run both 51job accounts in batches of 3, implemented as `limit=1` repeated 3 times per account.
- Modify: `tests/agent/test_job51_phase3.py`
  - Add regression tests for label identity, stale overlay cleanup, and wrong resume blocking.
- Create or modify: `tests/agent/test_job51_guarded_batches.py`
  - Test immediate stop semantics for guarded batch runner.

---

### Task 1: Parse 51job Left-Row Identity When DOM Fields Are Missing

**Files:**
- Modify: `app/platforms/job51/actions_chat.py`
- Modify: `tests/agent/test_job51_phase3.py`

**Interfaces:**
- Produces: `_infer_name_from_label(label: str) -> str`
- Produces: `_infer_latest_message_from_label(label: str) -> str`
- Updates: `_normalize_unread_rows(value: object) -> list[dict[str, object]]`

- [ ] **Step 1: Write failing tests**

Add to `tests/agent/test_job51_phase3.py`:

```python
def test_job51_normalize_unread_rows_infers_name_from_plain_label() -> None:
    rows = _normalize_unread_rows(
        [
            {
                "index": 0,
                "id": "",
                "label": "1\n王欣睿\n15:05\n您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。",
                "name": "",
                "position": "",
                "latestMessage": "",
                "unreadCount": 1,
            }
        ]
    )

    assert rows[0]["name"] == "王欣睿"
    assert rows[0]["latest_message"] == "您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/agent/test_job51_phase3.py::test_job51_normalize_unread_rows_infers_name_from_plain_label -q
```

Expected: FAIL because `_normalize_unread_rows()` currently keeps empty `name`.

- [ ] **Step 3: Implement minimal parsing helpers**

In `app/platforms/job51/actions_chat.py`, add helpers near `_compact_identity_text`:

```python
_TIME_LINE_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")
_UNREAD_COUNT_PATTERN = re.compile(r"^\d+$")


def _infer_name_from_label(label: str) -> str:
    lines = [line.strip() for line in str(label or "").splitlines() if line.strip()]
    for line in lines:
        if _UNREAD_COUNT_PATTERN.match(line) or _TIME_LINE_PATTERN.match(line):
            continue
        if line.startswith("[") or line in {"已投", "快捷回复", "不匹配"}:
            continue
        if len(line) <= 16 and not any(mark in line for mark in ("您好", "职位", "岗位", "公司")):
            return line
    return ""


def _infer_latest_message_from_label(label: str) -> str:
    lines = [line.strip() for line in str(label or "").splitlines() if line.strip()]
    candidates = [
        line
        for line in lines
        if not _UNREAD_COUNT_PATTERN.match(line)
        and not _TIME_LINE_PATTERN.match(line)
        and line not in {"已投", "快捷回复", "不匹配"}
        and not line.startswith("[")
    ]
    return candidates[-1] if len(candidates) >= 2 else ""
```

Then update `_normalize_unread_rows()`:

```python
name = str(item.get("name") or item.get("candidateName") or "")
latest = str(
    item.get("latest_message")
    or item.get("latestMessage")
    or item.get("message")
    or ""
)
if not name:
    name = _infer_name_from_label(label)
if not latest:
    latest = _infer_latest_message_from_label(label)
```

and assign:

```python
"name": name,
"latest_message": latest,
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/agent/test_job51_phase3.py::test_job51_normalize_unread_rows_infers_name_from_plain_label -q
```

Expected: PASS.

---

### Task 2: Make Opened Candidate Verification More Diagnostic And Less Brittle

**Files:**
- Modify: `app/platforms/job51/actions_chat.py`
- Modify: `tests/agent/test_job51_phase3.py`

**Interfaces:**
- Updates: `_verify_opened_candidate_once(page, expected, chat_ready: bool) -> dict[str, object]`
- Produces failure details with `actual.source`, `actual.headerText`, and expected fields.

- [ ] **Step 1: Write failing test**

Add:

```python
def test_job51_verify_opened_candidate_accepts_right_header_name_without_position() -> None:
    page = RightHeaderIdentityPage(
        right_header={
            "opened": True,
            "source": "right_header",
            "actual": {
                "name": "王欣睿",
                "position": "",
                "label": "王欣睿\n沟通职位：",
                "headerText": "王欣睿\n沟通职位：",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": "1\n王欣睿\n15:05\n您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。",
                "name": "王欣睿",
                "position": "",
            },
            chat_ready=True,
            timeout_ms=50,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
```

- [ ] **Step 2: Run test**

```powershell
pytest tests/agent/test_job51_phase3.py::test_job51_verify_opened_candidate_accepts_right_header_name_without_position -q
```

Expected: FAIL if current right-header payload with empty position is not accepted.

- [ ] **Step 3: Update verification fallback**

In `_verify_opened_candidate_once()`, after reading context, compute label-name fallback:

```python
expected_name_from_label = _infer_name_from_label(expected_label)
effective_expected_name = expected_name or expected_name_from_label
name_ok = bool(
    effective_expected_name
    and actual_name
    and _text_matches(actual_name, effective_expected_name)
)
```

Keep `position_conflict` only when both sides are non-empty:

```python
position_conflict = bool(
    expected_position
    and actual_position
    and not _position_matches(actual_position, expected_position)
)
```

Set opened:

```python
opened = bool(
    chat_ready
    and (label_ok or (name_ok and not position_conflict) or (actual_name and position_ok))
)
```

- [ ] **Step 4: Run focused verification tests**

```powershell
pytest tests/agent/test_job51_phase3.py -q -k "verify_opened_candidate or normalize_unread_rows"
```

Expected: PASS.

---

### Task 3: Harden 51job Resume Overlay Cleanup

**Files:**
- Modify: `app/platforms/job51/actions_resume_close.py`
- Modify: `scripts/platform_once_common.py`
- Modify: `tests/agent/test_job51_phase3.py`

**Interfaces:**
- Produces: `OVERLAY_STATE_JS`
- Updates: `cleanup_resume_overlays(page) -> dict[str, object]` to include `remaining: list[str]`
- Updates: `_cleanup_job51()` handling in `scripts/platform_once_common.py`.

- [ ] **Step 1: Write failing test**

Add a fake page test where `#IMResumePrint` remains visible after close attempt:

```python
def test_job51_cleanup_reports_remaining_resume_overlay() -> None:
    page = StubbornResumeOverlayPage()

    result = asyncio.run(cleanup_resume_overlays(page))

    assert result["closed"] == 0
    assert "online_resume_preview" in result["remaining"]
```

Implement `StubbornResumeOverlayPage` in the existing fake page section:

```python
class StubbornResumeOverlayPage:
    async def query_all(self, selector: str):
        return []

    async def eval_js(self, script: str, arg: object | None = None):
        if script == job51_dom_scripts.OVERLAY_STATE_JS:
            return {"remaining": ["online_resume_preview"]}
        return {"closed": False, "reason": "close_not_found"}

    async def press(self, selector: str, key: str, timeout_ms: int = 1000):
        return True
```

- [ ] **Step 2: Run test**

```powershell
pytest tests/agent/test_job51_phase3.py::test_job51_cleanup_reports_remaining_resume_overlay -q
```

Expected: FAIL because `OVERLAY_STATE_JS` and `remaining` are not implemented.

- [ ] **Step 3: Implement overlay state and loop cleanup**

In `app/platforms/job51/actions_resume_close.py`, add:

```python
OVERLAY_STATE_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      rect.width > 0 && rect.height > 0;
  };
  const remaining = [];
  if (visible(document.querySelector("#IMResumePrint"))) remaining.push("online_resume_preview");
  if (visible(document.querySelector(".annex-resume"))) remaining.push("annex_resume_preview");
  if (visible(document.querySelector(".el-dialog, .el-message-box"))) remaining.push("dialog");
  return { remaining };
}
"""
```

Update `cleanup_resume_overlays()` to run up to 3 passes and return remaining:

```python
for _ in range(3):
    state = await _overlay_state(page)
    if not state.get("remaining"):
        return {"closed": closed, "actions": actions, "remaining": []}
    preview = await close_resume_preview(page)
    ...
return {"closed": closed, "actions": actions, "remaining": state.get("remaining", [])}
```

Add:

```python
async def _overlay_state(page: BrowserPage) -> dict[str, object]:
    try:
        result = await page.eval_js(OVERLAY_STATE_JS)
    except Exception as error:
        return {"remaining": [], "error": str(error)}
    return result if isinstance(result, dict) else {"remaining": []}
```

- [ ] **Step 4: Make process stop on unclosed overlay**

In `scripts/platform_once_common.py`, after `_cleanup_job51(adapter.page, phase="before_candidate")`, if `remaining` is non-empty, append a failure summary:

```python
cleanup = await _cleanup_job51(adapter.page, phase="before_candidate")
if cleanup.get("remaining"):
    summaries.append(
        _failure_summary(
            row_state,
            action="failed",
            stage="stale_resume_overlay_not_closed",
            reason="stale_resume_overlay_not_closed",
            reliable_actions=getattr(adapter.page, "reliable_actions", [])[before_actions:],
            extra={"cleanup": cleanup},
        )
    )
    seen.update(row_keys)
    return summaries
```

- [ ] **Step 5: Run tests**

```powershell
pytest tests/agent/test_job51_phase3.py -q -k "cleanup or overlay"
```

Expected: PASS.

---

### Task 4: Validate Downloaded Resume Identity Before Saving

**Files:**
- Modify: `app/platforms/job51/resume_files.py`
- Modify: `app/platforms/job51/actions_resume.py`
- Modify: `tests/agent/test_job51_phase3.py`

**Interfaces:**
- Produces: `resume_identity_guard(content: bytes, candidate_name: str, applied_position: str) -> dict[str, object]`
- Updates: `save_resume_bytes(...)` to return `{"ok": False, "blocked": True, "reason": "resume_identity_mismatch"}` on mismatch.

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_job51_resume_identity_guard_blocks_wrong_candidate_pdf() -> None:
    wrong_pdf = minimal_pdf_with_text("王海洋 应聘职位：AI应用开发实习生")

    result = save_resume_bytes(
        wrong_pdf,
        candidate_name="王莉",
        applied_position="AI 产品经理",
        filename="51job_王海洋_AI应用开发实习生.pdf",
        memory=InMemoryResumeDownloadMemory(),
    )

    assert result["ok"] is False
    assert result["reason"] == "resume_identity_mismatch"


def test_job51_resume_identity_guard_accepts_matching_position_pdf() -> None:
    content = minimal_pdf_with_text("赵冰洋 应聘职位：B端社交媒体运营")

    result = save_resume_bytes(
        content,
        candidate_name="赵冰洋",
        applied_position="B端社交媒体运营",
        filename="51job_赵冰洋_B端社交媒体运营.pdf",
        memory=InMemoryResumeDownloadMemory(),
    )

    assert result["ok"] is True
```

Add a helper if the test file does not already have one:

```python
def minimal_pdf_with_text(text: str) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    return document.tobytes()
```

- [ ] **Step 2: Run tests**

```powershell
pytest tests/agent/test_job51_phase3.py -q -k "resume_identity_guard"
```

Expected: FAIL because identity guard does not exist.

- [ ] **Step 3: Implement PDF identity guard**

In `app/platforms/job51/resume_files.py`, add:

```python
def resume_identity_guard(
    content: bytes,
    *,
    candidate_name: str,
    applied_position: str,
) -> dict[str, object]:
    text = _extract_resume_text_preview(content)
    compact_text = _compact_text(text)
    compact_name = _compact_text(candidate_name)
    compact_position = _compact_text(applied_position)
    name_ok = bool(compact_name and compact_name in compact_text)
    position_ok = bool(compact_position and compact_position in compact_text)
    if name_ok or position_ok:
        return {"blocked": False, "nameMatched": name_ok, "positionMatched": position_ok}
    return {
        "blocked": True,
        "reason": "resume_identity_mismatch",
        "candidateName": candidate_name,
        "appliedPosition": applied_position,
        "textPreview": text[:300],
    }
```

Add:

```python
def _extract_resume_text_preview(content: bytes) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:
        return ""
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            return "\n".join(page.get_text() for page in document[:2])
    except Exception:
        return ""


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()
```

Call it inside `save_resume_bytes()` after signature validation and context guard:

```python
identity = resume_identity_guard(
    bytes(content),
    candidate_name=candidate_name,
    applied_position=applied_position,
)
if identity.get("blocked"):
    return {"ok": False, "blocked": True, **identity}
```

- [ ] **Step 4: Stop trusting platform filename**

In `_write_resume_file()`, replace:

```python
stem = _safe_filename(
    filename
    or f"51job_{candidate_name}_{applied_position}_{digest[:8]}.{file_type}"
)
```

with:

```python
stem = _safe_filename(f"51job_{candidate_name}_{applied_position}_{digest[:8]}.{file_type}")
```

- [ ] **Step 5: Run tests**

```powershell
pytest tests/agent/test_job51_phase3.py -q -k "resume_identity_guard or save_resume_bytes"
```

Expected: PASS.

---

### Task 5: Guarded 51job Batch Runner With True Immediate Stop

**Files:**
- Create: `scripts/run_job51_guarded_batches.py`
- Create: `tests/agent/test_job51_guarded_batches.py`

**Interfaces:**
- Produces CLI: `python scripts/run_job51_guarded_batches.py --owners 和新红 宋峰峰 --batch-size 3 --live --confirm-live`
- Internally runs `scripts/run_job51_once.py --limit 1` repeatedly.

- [ ] **Step 1: Write test for stop semantics**

Create `tests/agent/test_job51_guarded_batches.py`:

```python
from scripts.run_job51_guarded_batches import should_stop_after_output


def test_job51_guarded_batch_stops_on_identity_mismatch() -> None:
    output = """
===== job51 LIVE summary =====
processed=0 skipped=0 failed=1 total=1
decision: {"action": "failed", "reason": "candidate_identity_mismatch"}
"""

    result = should_stop_after_output(output, returncode=0)

    assert result.stop is True
    assert result.reason == "candidate_identity_mismatch"


def test_job51_guarded_batch_continues_on_clean_single_item() -> None:
    output = "processed=1 skipped=0 failed=0 total=1"

    result = should_stop_after_output(output, returncode=0)

    assert result.stop is False
```

- [ ] **Step 2: Run test**

```powershell
pytest tests/agent/test_job51_guarded_batches.py -q
```

Expected: FAIL because script does not exist.

- [ ] **Step 3: Implement runner**

Create `scripts/run_job51_guarded_batches.py` with:

```python
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SUMMARY_RE = re.compile(r"processed=(\d+)\s+skipped=(\d+)\s+failed=(\d+)\s+total=(\d+)")
STOP_PATTERNS = (
    "candidate_identity_mismatch",
    "resume_identity_mismatch",
    "stale_resume_overlay_not_closed",
    "Traceback (most recent call last)",
    "TimeoutError",
    "[error]",
)


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: str = ""


def should_stop_after_output(output: str, *, returncode: int) -> StopDecision:
    if returncode != 0:
        return StopDecision(True, f"process_exit_code={returncode}")
    for pattern in STOP_PATTERNS:
        if pattern in output:
            return StopDecision(True, pattern)
    match = None
    for item in SUMMARY_RE.finditer(output):
        match = item
    if match is None:
        return StopDecision(True, "summary_not_found")
    failed = int(match.group(3))
    if failed > 0:
        return StopDecision(True, f"failed_count={failed}")
    return StopDecision(False, "")
```

Add CLI loop that runs:

```python
cmd = [
    sys.executable,
    "scripts/run_job51_once.py",
    "--owner",
    owner,
    "--limit",
    "1",
    "--live",
    "--confirm-live",
]
```

Loop `batch_size` times per owner and stop immediately when `should_stop_after_output()` returns `stop=True`.

- [ ] **Step 4: Run tests**

```powershell
pytest tests/agent/test_job51_guarded_batches.py -q
```

Expected: PASS.

---

### Task 6: Quarantine Known Wrong 2026-07-07 Artifacts

**Files/Data:**
- Modify data only after backup: `data/resumes.sqlite`
- Move or quarantine files under: `data/downloads/job51/quarantine/20260707_wrong_identity/`

**Interfaces:**
- No code interface.
- Produces clean DB state where wrong artifacts are `parse_status='failed'`.

- [ ] **Step 1: Back up database**

Run:

```powershell
Copy-Item data/resumes.sqlite data/backups/resumes_before_job51_wrong_artifact_quarantine_$(Get-Date -Format yyyyMMdd_HHmmss).sqlite
```

- [ ] **Step 2: Mark wrong artifacts failed**

Run:

```powershell
$py='C:/Users/24471/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
@'
import sqlite3

wrong_ids = [
    "artifact_4cd0839319f7e16abf1893a0",
    "artifact_23694eabfbec5955f41b2c18",
]

with sqlite3.connect("data/resumes.sqlite") as con:
    con.execute(
        """
        update resume_artifacts
        set parse_status='failed',
            error='resume_identity_mismatch: downloaded PDF belongs to 王海洋 / AI应用开发实习生, not linked candidate',
            updated_at=datetime('now')
        where id in (?, ?)
        """,
        wrong_ids,
    )
    con.commit()
'@ | & $py -
```

- [ ] **Step 3: Move the two PDFs to quarantine**

Run:

```powershell
New-Item -ItemType Directory -Force data/downloads/job51/quarantine/20260707_wrong_identity
Move-Item -LiteralPath "data/downloads/job51/51job_王海洋_AI应用开发实习生_湖州(806431932).pdf" -Destination "data/downloads/job51/quarantine/20260707_wrong_identity/"
Move-Item -LiteralPath "data/downloads/job51/51job_王海洋_AI应用开发实习生_湖州(806431932)_759c1ff8.pdf" -Destination "data/downloads/job51/quarantine/20260707_wrong_identity/"
```

- [ ] **Step 4: Verify DB state**

Run:

```powershell
$py='C:/Users/24471/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
@'
import sqlite3
with sqlite3.connect("data/resumes.sqlite") as con:
    con.row_factory = sqlite3.Row
    for row in con.execute("""
      select id, candidate_name_from_platform, position, parse_status, error
      from resume_artifacts
      where id in ('artifact_4cd0839319f7e16abf1893a0', 'artifact_23694eabfbec5955f41b2c18')
    """):
        print(dict(row))
'@ | & $py -
```

Expected: both rows have `parse_status='failed'`.

---

### Task 7: Regression And Manual Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused tests**

```powershell
pytest tests/agent/test_job51_phase3.py tests/agent/test_job51_guarded_batches.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader runtime tests**

```powershell
pytest tests/agent/test_phase4_runtime.py -q
```

Expected: PASS.

- [ ] **Step 3: Run lint**

```powershell
ruff check app scripts tests
```

Expected: PASS or only pre-existing unrelated warnings.

- [ ] **Step 4: Live 51job smoke test with true immediate stop**

Run one guarded batch:

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/run_job51_guarded_batches.py --owners 和新红 宋峰峰 --batch-size 3 --live --confirm-live
```

Expected:

- Each item is processed via `run_job51_once.py --limit 1`.
- If a candidate fails identity verification, the script stops before touching the next candidate.
- If a resume PDF belongs to another candidate, the script reports `resume_identity_mismatch`, does not write artifact, and stops.
- No `#IMResumePrint` or `.annex-resume` blocker remains before the next candidate.

---

## Acceptance Criteria

- `王欣睿`-style left labels are parsed into expected `name`.
- Right-side candidate verification succeeds when right header name matches expected name and position is absent.
- Unclosed resume preview/export overlays stop processing instead of allowing the next candidate to continue.
- 51job downloaded PDFs are saved only when PDF text matches current candidate name or current applied position.
- 51job final business filenames are based on current candidate context, not stale platform filename.
- The two wrong pending artifacts from 2026-07-07 are quarantined or marked failed before any further sync.
- Guarded 51job batch runner truly stops after the first bad candidate because it runs `limit=1` per candidate.

## Self-Review

- Spec coverage: identity mismatch, stale preview, wrong resume artifact, batch immediate stop, and data cleanup are covered.
- Placeholder scan: no TBD/TODO/later placeholders remain.
- Type consistency: all new helper names are defined in their producing tasks before later tasks use them.
