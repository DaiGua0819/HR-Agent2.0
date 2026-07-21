# BOSS Identity And Security Recovery Design

## Incident

The guarded server run `20260721_144659_825884` stopped after 58 processed contacts and 7 anomalies. Five successful BOSS contacts were incorrectly classified as `recent_messages_not_matched`. The final concurrent BOSS request returned HTTP 500. Its traceback was not captured, so its root cause remains unproven.

The preserved incident evidence is stored on the server under:

`C:\ProgramData\OpenAI\Codex\incident-backups\boss-message-match-20260721-145352`

## Root Causes

Conversation identity fingerprints currently prefer `ChatMessage.raw_text`. On BOSS, raw text includes volatile UI metadata such as relative dates (`昨天`), absolute dates, timestamps, and read-state labels. The same message therefore produces a different fingerprint when read on another day even though `ChatMessage.text` is unchanged.

The Worker runtime-status detector searched the full BOSS URL and title for the generic marker `security`. A normal chat URL containing the stale query parameter `_security_check=...` therefore became `security_verification_required`, even though the title was `BOSS直聘` and the manager reported `blockers=[]`.

The HTTP 500 cannot be attributed to security verification. Worker launch currently does not preserve stdout/stderr in a durable incident log, so a future reproduction needs explicit traceback capture before any code repair is selected.

## Selected Design

1. Compute recent-message identity fingerprints from stable message text, falling back to raw text only when normalized text is empty.
2. For an existing session found by stable platform conversation ID and position, suppress a historical fingerprint mismatch only when both stored and current candidate names are non-empty and equal after whitespace/case normalization. A candidate-name conflict keeps `recent_messages_not_matched` as an anomaly.
3. Keep trusted candidate name, label, and fingerprint unchanged when stable platform identity conflicts with a different candidate name. Production persistence must not overwrite them after the resolver emits `recent_messages_not_matched`.
4. Treat normalized-empty `text` as absent and fall back to normalized `raw_text`. Preserve read compatibility with historical raw-first fingerprints.
5. Align Worker BOSS security detection with the manager: explicit `verify.html`, BOSS passport/security titles, or other explicit verification evidence block; `_security_check` on `/web/chat/index` does not.
6. Keep manager anomaly classification unchanged. Any remaining `recent_messages_not_matched` warning remains anomalous.
7. Do not migrate historical fingerprints or bulk-update the database. Sessions naturally adopt the stable fingerprint when they are next read.

## Alternatives Rejected

- Ignoring `recent_messages_not_matched` in the manager was rejected because it would weaken identity protection for genuine candidate changes.
- Bulk migration of historical fingerprints was rejected because the old raw text is already contaminated by volatile relative dates and read-state labels.
- Converting the unexplained HTTP 500 into a security blocker was rejected because the only security signal was itself a confirmed false positive.

## Verification

- A fingerprint remains identical when only raw timestamps, relative dates, or read-state prefixes change.
- Same platform ID, position, and candidate name with evolved messages does not emit a mismatch warning.
- Same platform ID and position with a changed candidate name still emits `recent_messages_not_matched`.
- A BOSS chat URL with `_security_check` remains authenticated and ready.
- A real `verify.html` or security-verification title remains blocked.
- Repeated conflicting observations cannot replace the trusted candidate name, label, or fingerprint through the production persistence path.
- Empty historical fingerprints and whitespace-only normalized text retain identity protection.
- Focused identity, Worker, manager, cross-platform, and full test suites pass.
- A server canary may use the BOSS account only after manager preflight confirms the real page has no blocker. Job51/Zhilian resume canaries must prove file, hash, parsed artifact, resume ID, score, and exact session linkage.
