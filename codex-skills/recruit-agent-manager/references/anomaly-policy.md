# Anomaly Policy

## Stop Immediately

- `security_verification_required` or a CAPTCHA/verification page.
- `boss_security_warning` returned as a structured blocker during Worker preparation. Do not accept a generic HTTP 500 as sufficient diagnostics when the page supplied this exact reason.
- `login_required`.
- Candidate identity mismatch, ambiguous row selection, or conversation changed before send.
- `candidate_identity_changed_before_send`, including a 51job preview close that returns to a different new-greeting card.
- Send/request confirmation failure.
- Resume download/export failure when the platform policy requires a local file.
- Stale modal or preview overlay that cannot be closed.
- Unknown candidate question requiring business knowledge.
- HTTP failure, Worker/control-plane loss, wrong database, wrong branch, fake backend, or `dryRun=true` during a live request.

## Skip The Contact And Continue

- A BOSS candidate is frozen or cannot be contacted: do not click the row's destructive actions, cache its identity for the Worker lifetime, and continue.
- Zhilian reports that the candidate closed job search: click only `知道了`, cache the row identity for the Worker lifetime, and continue.
- A row is a system notification, read-only update, or has no candidate reply.
- The user explicitly configured the contact or target to be skipped.

Do not delete conversations as part of skip handling.

## Expected Non-Anomalies

- `processed=0` after a complete unread-list traversal.
- `screening_question_sent`, `basic_phrase_sent`, `knowledge_hit`, or a confirmed resume request.
- `resume_attachment_downloaded` with a valid file path/hash.
- Any verified BOSS `求简历` action is a successful resume acquisition and should report `boss_request_verified_server_imap`. Include it in business “resumes acquired/downloaded” totals. `downloaded=false`, no local PDF, and no local IMAP process are expected; the validated production server IMAP pipeline owns delivery and import.
- 51job `online_resume_not_exportable_attachment_message_sent` is expected only when the original candidate identity remained stable and either the normal chat message or an exclusively selected single-candidate common phrase was verified.
- 51job `online_resume_export_queued_no_file` is an expected intermediate export result only when the delayed dialog is closed and a same-candidate attachment request is subsequently verified. Without that verified fallback, it remains an anomaly.

## Counting

`max-anomalies` means anomalies tolerated. With `0`, the first anomaly stops. With `3`, the fourth anomaly stops. Every anomaly must remain in the run JSONL with its low-level reason.

## Missing Knowledge

Do not invent factual answers. Capture candidate name, owner, platform, position, question, and existing matched topics. Ask the user for the expected answer, then add the smallest position-scoped knowledge entry and a regression test.
