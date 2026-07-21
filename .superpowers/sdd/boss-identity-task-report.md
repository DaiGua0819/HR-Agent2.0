# BOSS Identity Tasks 1-2 Report

Date: 2026-07-21

## Scope

Implemented Tasks 1 and 2 from
`docs/superpowers/plans/2026-07-21-boss-identity-security-recovery.md`.

- Conversation fingerprints now use normalized `text` first and `raw_text` only as fallback.
- Stable platform conversation ID plus position suppresses
  `recent_messages_not_matched` only when both candidate names are non-empty and
  equal after whitespace removal and `casefold()`.
- Candidate name conflicts continue to emit `recent_messages_not_matched`.
- `message_hash` and manager anomaly classification were not changed.

## TDD Evidence

### Task 1: Stable conversation fingerprints

RED command:

```text
C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/domain/test_conversation_state_bridge.py -k fingerprint_ignores_volatile_raw_metadata -q
```

Observed expected failure before production code:

```text
FAILED test_fingerprint_ignores_volatile_raw_metadata
AssertionError: fingerprints differed when only raw timestamp/read metadata changed
1 failed, 35 deselected
```

GREEN after changing `_fingerprint_window` to `item.text or item.raw_text`:

```text
1 passed, 35 deselected in 0.61s
```

### Task 2: Stable platform identity

Same-candidate RED command:

```text
C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/domain/test_conversation_state_bridge.py -k stable_platform_identity_accepts_same_candidate_with_evolved_messages -q
```

Observed expected failure before identity production code:

```text
FAILED test_stable_platform_identity_accepts_same_candidate_with_evolved_messages
AssertionError: ['recent_messages_not_matched'] != []
1 failed, 36 deselected
```

Changed-candidate safety regression before implementation:

```text
1 passed, 37 deselected in 0.98s
```

Combined GREEN command:

```text
C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/domain/test_conversation_state_bridge.py -k "stable_platform_identity or fingerprint_ignores_volatile_raw_metadata" -q
```

Result:

```text
3 passed, 35 deselected in 1.33s
```

## Verification

Conversation state bridge suite:

```text
38 passed in 49.90s
```

Ruff check for the owned Python files:

```text
All checks passed!
```

`git diff --check` reported no whitespace errors. The LF-to-CRLF messages were
Git working-copy conversion warnings only.

Environment note: the bare `pytest` command was not on PowerShell `PATH`, and
the system Python lacked `python-dotenv`. All authoritative test evidence above
uses the repository's existing `.venv312` interpreter.

## Changed Files

- `app/domain/conversation/dedup.py`
- `app/domain/conversation/identity.py`
- `tests/domain/test_conversation_state_bridge.py`
- `.superpowers/sdd/boss-identity-task-report.md`

## Commit

- Message: `fix: stabilize conversation identity checks`
- Scope: only the four owned files listed above
- Hash: reported in the task result; a commit cannot embed its own final hash
  without changing that hash

## Concerns

None.
