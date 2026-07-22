# Operations Runbook

## 1. Inventory

1. Read `topology.json`.
2. Run `inventory`.
3. Confirm the branch, commit, worktree, database size/path, profile existence, CDP pages, Worker ports, control-plane port, backend, and dry-run state.
4. Ignore unrelated dirty worktree files; never revert user changes.

Run `preflight --quick-check` before the first live operation of a session. Later checks may omit `--quick-check` unless database integrity is in doubt.

Run `data-health` before an end-to-end report. It is read-only and does not require browsers or Workers to be active.

Run `daily-report --date YYYY-MM-DD` for repeatable Beijing-time totals. Use `byJobPlatform` for the breakdown and retain the `coverage` block in any report. Do not silently combine manager contacts, legacy direct-script decisions, and file artifacts under one unlabeled number.

## 2. Start Or Adopt

Run `start --adopt-running`.

The manager starts missing CloakBrowser sessions with the configured profile, then starts missing Workers and the `18081` control plane. It adopts healthy existing instances. After startup, run `preflight` again.

## 3. Guarded Live Run

After a code change, run one owner/platform with `--max-contacts 1 --max-anomalies 0`. Expand to three contacts only after the targeted result is correct.

Poll the unified command session every 30 seconds. Do not infer completion from browser movement alone. Use Worker `agentBusy`, the contact JSON line, the run JSONL, and database/file evidence.

Apply `platform-contracts.md` before evaluating resume completion. In particular, a verified BOSS request is complete without a local file, while 51job/Zhilian local-download success requires a file/hash.

## 4. Investigate A Slow Contact

1. Check which Worker has `agentBusy=true`.
2. Read current CDP page URL/title and visible dialogs without clicking.
3. Read the platform's current candidate/header/message context.
4. Inspect service logs and the control-plane timeout boundary.
5. If a harmless blocking dialog is fully understood, issue a graceful stop before dismissing it.

Do not start a second request against the same Worker.

## 5. Repair

Use a failing test that reproduces the real wording or DOM state. Examples validated in live operation:

- `单休接受不了` must be `reject`, not `accept`.
- Zhilian `对方已关闭求职，无法继续进行沟通` must dismiss with `知道了`, never `删除对话`, and must not wait 600 seconds.
- `住房是自行解决吗` must match the AI intern accommodation answer.
- Specific `薪资构成` answers suppress redundant generic salary answers.
- BOSS frozen contacts are skipped without clicking; do not use a destructive action to clear the row.
- BOSS stale unread state gets one `全部 -> 未读` reset before an empty queue is accepted.
- A BOSS security-warning or login/verification state found during adapter preparation must return a structured blocker such as `boss_security_warning`; it must not be flattened into an opaque HTTP 500. The guarded run still stops and the operator must resolve the platform prompt manually.
- For AI basic-condition replies, `好的，我是已经毕业的应届生` is an affirmative acknowledgement and may continue to the resume request. `好的，我考虑一下` contains hesitation and must remain `basic_unclear`; do not treat every leading `好的` as acceptance.
- Zhilian attachment download uses the actionable toolbar/button before any text fallback.
- Manager-started Python processes must force UTF-8 output so Chinese owners, roles, and reasons remain machine-readable.

Run platform tests plus shared runtime tests after a shared-rule change.

### 51job Online Resume Fallback

- Snapshot candidate name, position, conversation label, and latest message before opening an online resume.
- Element UI can keep hidden mounted dialogs before the visible dialog. Overlay detection must inspect all matching nodes and accept only nodes that are actually visible; never use the first `querySelector()` match as proof that no overlay exists.
- A successful file download can be followed later by a `导出成功` notification that mentions `导出记录`. Treat it as a delayed status dialog from the preceding export, not as evidence about the newly selected candidate.
- Close that status dialog only with the exact `我知道了` action or its header close control. Never click `去看看`, never navigate to export records, and never count an asynchronous export task as a local resume without a captured file and hash.
- If 51 confirms the export task but no immediate browser file exists, preserve `online_resume_export_queued_no_file`, close the dialog, and request an attachment from the same verified candidate.
- Wait briefly for the close transition to settle before attempting another blocker action. Broad selectors such as `[class*='popover']` include normal popovers and navigation references and must not be treated as modal blockers.
- After closing a preview, verify the current candidate against that snapshot before any native request, fill, common-phrase selection, or send.
- Explicit close controls come first. If overlay state is already empty, stop cleanup; do not press Escape, because Escape can leave the target and open a default new-greeting candidate.
- A new-greeting fallback may use a configured resume-request common phrase only when exactly one candidate is selected, the detail card matches the original snapshot, the phrase is exact, and the send is verified by card removal, updated text, or a success signal.
- Treat `candidate_identity_changed_before_send` as a hard stop. Preserve expected/actual diagnostics and never retry against the newly visible candidate.

## 6. Reload

Restart Workers after changing agent, platform, rule-loading, or adapter code. Keep CloakBrowser profiles running. Restart the control plane only when control-plane code changes.

Verify listener PIDs and command lines before stopping any process.

## 7. Targeted Live Verification

Compare before and after evidence:

- elapsed time;
- candidate identity;
- stage and next action;
- message text actually visible in the chat;
- expected and actual candidate identity immediately before send;
- resume file path/hash when locally downloaded on 51job or Zhilian;
- BOSS `resumeHandling=boss_request_verified_server_imap` instead of a local file path or local IMAP check;
- anomaly count;
- whether the next contact can be processed.

Only then resume broader guarded batches.

## 8. Closeout

Report processed contacts by owner/platform/job, downloaded resume count, skipped/blocked contacts, unanswered questions, fixes made, test commands, current runtime status, and remaining business decisions.

Use the `data-health` output to distinguish:

- BOSS business acquisitions through verified server-IMAP handoffs;
- unique local 51job/Zhilian files;
- artifacts waiting for local parsing;
- parsed `resumes` rows eligible for synchronization;
- auto-sync errors or queued batches.

Use `daily-report` to distinguish business resume acquisitions from physical local files. Verified BOSS requests count as acquisitions; 51job/Zhilian acquisitions are unique hashes. If `coverage` notes legacy/direct-script gaps, say so explicitly before comparing the result with historical decision-log totals.

Do not call auto-sync unhealthy merely because `lastSuccessAt` is old when there are no changed rows. Treat `lastError`, `consecutiveFailures`, queued pending batches, and cursor movement after new parsed rows as the stronger evidence.
