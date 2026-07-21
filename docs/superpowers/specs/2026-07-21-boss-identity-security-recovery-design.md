# BOSS Identity And Security Recovery Design

## Incident

The guarded server run `20260721_144659_825884` stopped after 58 processed contacts and 7 anomalies. Five successful BOSS contacts were incorrectly classified as `recent_messages_not_matched`. The final concurrent BOSS request returned HTTP 500 after the page entered `security_verification_required`.

The preserved incident evidence is stored on the server under:

`C:\ProgramData\OpenAI\Codex\incident-backups\boss-message-match-20260721-145352`

## Root Causes

Conversation identity fingerprints currently prefer `ChatMessage.raw_text`. On BOSS, raw text includes volatile UI metadata such as relative dates (`昨天`), absolute dates, timestamps, and read-state labels. The same message therefore produces a different fingerprint when read on another day even though `ChatMessage.text` is unchanged.

When a platform changes to a login, security-verification, or account-abnormal page during contact processing, the resulting DOM exception escapes the Worker route as HTTP 500. The runtime status detector can identify the external blocker after the exception, but the contact response loses that precise reason.

## Selected Design

1. Compute recent-message identity fingerprints from stable message text, falling back to raw text only when normalized text is empty.
2. For an existing session found by stable platform conversation ID and position, suppress a historical fingerprint mismatch only when both stored and current candidate names are non-empty and equal after whitespace/case normalization. A candidate-name conflict keeps `recent_messages_not_matched` as an anomaly.
3. When contact processing raises an exception, inspect the current platform runtime status without changing the page. Convert only confirmed `needsLogin`, `securityVerification`, or `accountAbnormal` states into the existing structured blocked payload. Re-raise all other exceptions.
4. Keep manager anomaly classification unchanged. Any remaining `recent_messages_not_matched` warning remains anomalous.
5. Do not migrate historical fingerprints or bulk-update the database. Sessions naturally adopt the stable fingerprint when they are next read.

## Alternatives Rejected

- Ignoring `recent_messages_not_matched` in the manager was rejected because it would weaken identity protection for genuine candidate changes.
- Bulk migration of historical fingerprints was rejected because the old raw text is already contaminated by volatile relative dates and read-state labels.
- Catching every Worker exception as a blocker was rejected because it would hide programming defects and unrelated platform failures.

## Verification

- A fingerprint remains identical when only raw timestamps, relative dates, or read-state prefixes change.
- Same platform ID, position, and candidate name with evolved messages does not emit a mismatch warning.
- Same platform ID and position with a changed candidate name still emits `recent_messages_not_matched`.
- A confirmed security-verification page returns a structured blocked result rather than HTTP 500.
- An unrelated exception is still raised.
- Focused identity, Worker, manager, cross-platform, and full test suites pass.
- A server canary must not touch the blocked BOSS account until manual verification is complete. Job51/Zhilian resume canaries must prove file, hash, parsed artifact, resume ID, score, and exact session linkage.
