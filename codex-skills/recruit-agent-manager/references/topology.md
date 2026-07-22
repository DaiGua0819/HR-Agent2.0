# Runtime Topology

## Authoritative Runtime

- Worktree: `interview-center-migration`
- Control plane: `127.0.0.1:18081`
- Database: the worktree `data/resumes.sqlite`
- Browser backend: `cloak`
- Live mode: `DRY_RUN=false`

Do not use the repository `main` checkout, its database, or server port `18080` for local message processing.

## Owners

| Owner | Profile | CDP | Worker |
|---|---|---:|---:|
| 和新红 | `profiles/hexinhong` | 9222 | 8801 |
| 宋峰峰 | `profiles/songfengfeng` | 9333 | 8802 |

Each owner has one CloakBrowser containing BOSS, 51job, and Zhilian tabs. Do not create one browser per platform.

## Login State

Chromium persists platform sessions inside each configured profile directory. The manager stores only the profile path and starts CloakBrowser with `--user-data-dir=<profile>`. The Skill must not inspect profile credential databases, cookies, tokens, Local Storage, IndexedDB, or password files.

When a platform logs out, keep the profile and browser open for manual login. When security verification appears, stop that owner/platform and wait for the user; do not automate around it.

## Runtime State

Mutable manager state belongs under `<projectRoot>/data/agent_manager/`:

- `managed_processes.json`: adopted or started process metadata.
- `current_run.json`: current/last guarded run.
- `stop.requested`: graceful stop request.
- `runs/*.jsonl`: sanitized per-contact evidence.
- `logs/`: manager-started process output.

Do not place cookies, access tokens, resume bodies, or complete chat histories in these files.

