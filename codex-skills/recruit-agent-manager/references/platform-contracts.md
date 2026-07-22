# Platform Contracts

Use these completion rules when classifying a contact, reporting progress, or deciding whether a guarded batch should stop.

## BOSS

- BOSS is a request-and-handoff workflow. A verified `求简历` action is the completion point for the local agent and counts as a successfully acquired/downloaded resume in business metrics.
- Report a verified request as `boss_request_verified_server_imap`, even when `downloaded=false` and no local file exists.
- The production server receives candidate-approved resumes through its validated IMAP pipeline. Local message-processing machines intentionally do not run that IMAP importer.
- `boss_attachment_present_no_local_download`, `request_confirmed`, `resume_consent_accepted`, and a verified successful request are non-anomalies.
- Do not attempt a local BOSS attachment download, inspect a local mailbox, require a local artifact, or diagnose the absence of a local BOSS PDF as a failure.
- A failed click, failed request confirmation, login/security blocker, wrong conversation, or unknown business question remains an anomaly.
- If a candidate is frozen or cannot be contacted, skip it without clicking destructive controls and cache the row identity for the current Worker lifetime.
- If the unread badge indicates work but the unread list is stale or unexpectedly empty, reset the list once with `全部 -> 未读`, reread it, and return `processed=0` only after the refreshed traversal is genuinely empty.

## 51job

- When an exportable online or attachment resume is available, success requires a valid local file and hash.
- Keep the original candidate identity snapshot through preview open, export, close, and any fallback send.
- If an online resume cannot be exported, a verified request for an attachment is an expected waiting state, not a completed local download.
- If the platform queues an export and shows `导出成功` without producing an immediate file, record `online_resume_export_queued_no_file`, dismiss the notification, and request an attachment. Never navigate to export records as part of guarded message processing.
- A delayed export notification may belong to the preceding candidate. It must be closed before the next identity-sensitive click, and it is never proof that the current candidate's resume was acquired.
- Identity changes, stale previews, ambiguous contacts, export failures, and unverified sends stop the guarded batch.

## Zhilian

- If an attachment exists, success requires capture of the actual local file and hash.
- Prefer `.session-new-action a.km-button`, then `.im-resume-detail .newest-attach-resume`; do not click an inert text layer with the same `查看附件简历` wording.
- If no attachment exists, a verified resume request is `resume_requested_waiting`.
- `download_not_captured`, `download_file_not_found`, failed sends, or an unexpected early unread-list end require diagnosis.

## Data Lifecycle

The common flow is:

```text
profile/browser -> unread contact -> identity verification -> chat context
-> policy decision -> verified send/request -> platform completion contract
```

After the platform contract diverges:

```text
BOSS -> verified request -> production server IMAP handoff

51job/Zhilian -> local file + hash -> resume_artifacts
-> parse into resumes -> local-to-18080 automatic sync
```

Pending `resume_artifacts` are relevant to 51job/Zhilian ingestion health. They are not evidence of a BOSS failure.

Run all manager and child Python processes with `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`. Do not pass Chinese owner/job literals through an encoding-ambiguous PowerShell-to-Python pipe.

## Reporting Vocabulary

Keep these counters separate:

| Counter | Meaning |
|---|---|
| processed contacts | Contacts for which a decision was produced |
| BOSS handoffs | Verified BOSS resume requests, completed locally |
| resume requests waiting | 51job/Zhilian candidates asked to send an attachment |
| local downloads | Unique 51job/Zhilian files captured by hash |
| parsed resumes | Local downloads converted into `resumes` rows |
| server-synced resumes | Parsed rows accepted by the 18080 sync endpoint |

Never compare processed contacts directly with local downloads without first separating BOSS handoffs, waiting requests, prior downloads, screening/basic-condition stages, and duplicate hashes.

When the user asks how many resumes were acquired or downloaded without explicitly saying “local PDF/file”, include verified BOSS handoffs. When the user asks for physical local files, count only unique 51job/Zhilian file hashes and label the narrower metric clearly.

Use `scripts/agent_manager.py data-health` to obtain local pipeline counts. It is the preferred source for artifact status and sync diagnostics; do not infer ingestion health from folder file counts alone.
