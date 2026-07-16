# B2B AI Product Manager Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic AI product manager scoring profile with the approved B2B sales and enterprise-product profile, rescore the two newest server records, and produce a deduplicated top-20 recommendation report from all server AI product manager resumes.

**Architecture:** Extend the existing JD profile model with grouped hard gates, evaluate those gates in the shared scoring engine, and keep all other job profiles behaviorally unchanged. Add one focused operational script that backs up SQLite, scores all AI product manager records in memory, optionally persists only the newest N scores, and emits an auditable JSON report.

**Tech Stack:** Python 3.12, dataclasses, SQLite, pytest, Ruff, existing `ResumeRepository` and JD scoring engine.

## Global Constraints

- The authoritative rule source is `https://pirategang.feishu.cn/docx/FCcQdsYgOoXuLIxxFjfc1pR5n9e`.
- Missing one hard gate caps the score at 74; missing both caps it at 54.
- Do not modify message processing, resume acquisition, or any non-AI-product-manager profile.
- Do not overwrite unrelated dirty-worktree changes.
- Back up the server database before any score update.
- Persist only the two newest AI product manager scores; score the remaining records in memory.
- Deploy only to `C:\RecruitAgent2Preview\hr-agent` and restart only port 18080. Do not modify the old 8080 service.

---

### Task 1: Add grouped hard-gate scoring

**Files:**
- Modify: `app/domain/scoring/jd_profiles.py`
- Modify: `app/domain/scoring/jd_match.py`
- Modify: `app/domain/scoring/engine.py`
- Test: `tests/domain/test_phase5_scoring.py`

**Interfaces:**
- Produces: `JdHardGate(label, keyword_groups, minimum_groups=0)`.
- Produces: `match_jd_hard_gates(text, gates) -> dict[str, Any]`.
- Extends: `calculate_jd_match()` result with `hardGates`, `missingHardGates`, and `hardGateCap`.

- [ ] **Step 1: Write failing hard-gate tests**

Add tests proving that two evidence groups are required, one missing gate caps at 74, two missing gates cap at 54, and an unrelated electrical profile has no hard-gate cap.

```python
def test_ai_product_manager_requires_b2b_sales_and_enterprise_product_gates() -> None:
    result = calculate_jd_match(FULL_B2B_AI_PM_TEXT, "AI产品经理")
    assert result["missingHardGates"] == []
    assert result["hardGateCap"] is None
    assert result["score"] >= 75


def test_ai_product_manager_missing_one_gate_is_capped_at_b() -> None:
    result = calculate_jd_match(B2B_WITHOUT_ENTERPRISE_COMPLEXITY, "AI产品经理")
    assert len(result["missingHardGates"]) == 1
    assert result["hardGateCap"] == 74
    assert result["score"] <= 74


def test_ai_product_manager_missing_both_gates_is_capped_at_c() -> None:
    result = calculate_jd_match("AI产品经理 Agent Prompt PRD", "AI产品经理")
    assert len(result["missingHardGates"]) == 2
    assert result["hardGateCap"] == 54
    assert result["score"] <= 54
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
pytest tests/domain/test_phase5_scoring.py -q
```

Expected: failures because the result has no hard-gate fields and the generic profile still applies.

- [ ] **Step 3: Add the profile data structure**

Add to `jd_profiles.py`:

```python
@dataclass(frozen=True)
class JdHardGate:
    label: str
    keyword_groups: tuple[tuple[str, ...], ...]
    minimum_groups: int = 0


@dataclass(frozen=True)
class JdProfile:
    name: str
    aliases: tuple[str, ...]
    must_have: tuple[JdRule, ...]
    bonus: tuple[JdRule, ...]
    risks: tuple[JdRule, ...]
    hard_gates: tuple[JdHardGate, ...] = ()
```

- [ ] **Step 4: Implement grouped matching and score caps**

Implement `match_jd_hard_gates()` so every keyword group reports matched and missing evidence. In `calculate_jd_match()`, apply:

```python
missing_count = len(hard_gates["missing"])
hard_gate_cap = 54 if missing_count >= 2 else 74 if missing_count == 1 else None
if hard_gate_cap is not None:
    raw_score = min(raw_score, hard_gate_cap)
```

Return the complete gate diagnostics and update `POSITION_SCORING_VERSION` to `v6-b2b-ai-product-manager-gates`.

- [ ] **Step 5: Replace the AI product manager profile**

Define two hard gates and the approved core, bonus, and risk rules from the design specification. Do not include bare `B2B`, `CRM`, or `SaaS` as enough evidence by themselves; each gate must match both of its evidence groups.

- [ ] **Step 6: Run focused scoring tests and verify GREEN**

Run:

```powershell
pytest tests/domain/test_phase5_scoring.py -q
```

Expected: all scoring tests pass.

### Task 2: Add the auditable rescore and recommendation tool

**Files:**
- Create: `scripts/rescore_b2b_ai_product_manager.py`
- Create: `tests/scripts/test_rescore_b2b_ai_product_manager.py`

**Interfaces:**
- Produces: `build_b2b_ai_pm_report(database_path, latest_count=2) -> dict[str, Any]`.
- Produces: `apply_latest_scores(database_path, report, backup_dir) -> Path`.
- CLI: `python scripts/rescore_b2b_ai_product_manager.py --database <path> --report <path> [--apply-latest 2]`.

- [ ] **Step 1: Write failing report tests**

Create a temporary SQLite database containing AI product manager and unrelated resumes. Assert that:

- only AI product manager records are scored;
- newest records are selected before writes;
- recommendation identities are unique by phone, hash, then normalized candidate identity;
- sorting prefers both hard gates, then score, must count, fewer risks, and recency;
- dry-run does not alter scores;
- apply updates only the requested newest records and creates a SQLite backup.

- [ ] **Step 2: Run tool tests and verify RED**

Run:

```powershell
pytest tests/scripts/test_rescore_b2b_ai_product_manager.py -q
```

Expected: import failure because the script does not exist.

- [ ] **Step 3: Implement report generation**

Use `ResumeRepository.iter_resumes()` and `ScoringService.score_resume()`. Build each recommendation row with:

```python
{
    "resumeId": record.id,
    "candidateName": candidate_name,
    "jobType": canonical_job,
    "platform": platform,
    "owner": owner,
    "oldScore": record.match_score,
    "newScore": result["score"],
    "level": result["level"],
    "hardGates": result["raw"]["hardGates"],
    "missingHardGates": result["raw"]["missingHardGates"],
    "must": result["evidence"]["must"],
    "bonus": result["evidence"]["bonus"],
    "risks": result["evidence"]["risks"],
    "updatedAt": record.updated_at,
}
```

Generate concise recommendation reasons from matched gate and must-have labels; do not include full resume text in the report.

- [ ] **Step 4: Implement safe apply mode**

Use SQLite's online backup API before updates. Freeze the newest IDs before writing, then call `repository.update_score()` for exactly those IDs. Write `backupPath`, `updatedLatest`, and `recommendations` into the final report.

- [ ] **Step 5: Run tool tests and verify GREEN**

Run:

```powershell
pytest tests/scripts/test_rescore_b2b_ai_product_manager.py -q
```

Expected: all tests pass.

### Task 3: Regression verification and server deployment

**Files:**
- Deploy: `app/domain/scoring/jd_profiles.py`
- Deploy: `app/domain/scoring/jd_match.py`
- Deploy: `app/domain/scoring/engine.py`
- Deploy: `scripts/rescore_b2b_ai_product_manager.py`
- Deploy tests used for server verification.

**Interfaces:**
- Server Python: `C:\RecruitAgent2Preview\.venv\Scripts\python.exe`.
- Server project: `C:\RecruitAgent2Preview\hr-agent`.
- Server database: `C:\RecruitAgent2Preview\hr-agent\data\resumes.sqlite`.

- [ ] **Step 1: Run local regression tests**

```powershell
pytest tests/domain/test_phase5_scoring.py tests/scripts/test_rescore_b2b_ai_product_manager.py tests/domain/test_phase7a_persistence.py -q
ruff check app/domain/scoring scripts/rescore_b2b_ai_product_manager.py tests/domain/test_phase5_scoring.py tests/scripts/test_rescore_b2b_ai_product_manager.py
```

- [ ] **Step 2: Back up server code files**

Create a timestamped directory under `C:\RecruitAgent2Preview\backups\b2b-ai-pm-scoring-<timestamp>` and copy only the files being replaced.

- [ ] **Step 3: Deploy the tested files**

Upload only the listed scoring files, script, and focused tests. Do not synchronize the whole dirty worktree.

- [ ] **Step 4: Run server tests**

```powershell
C:\RecruitAgent2Preview\.venv\Scripts\python.exe -m pytest tests/domain/test_phase5_scoring.py tests/scripts/test_rescore_b2b_ai_product_manager.py -q
```

Expected: all tests pass on the deployed server runtime.

- [ ] **Step 5: Generate a server dry-run report**

```powershell
C:\RecruitAgent2Preview\.venv\Scripts\python.exe scripts/rescore_b2b_ai_product_manager.py `
  --database data/resumes.sqlite `
  --report data/reports/b2b_ai_product_manager_rescore_20260716.json
```

Verify the report contains 121 source records, two frozen latest IDs, and no database score changes.

- [ ] **Step 6: Apply exactly two server score updates**

```powershell
C:\RecruitAgent2Preview\.venv\Scripts\python.exe scripts/rescore_b2b_ai_product_manager.py `
  --database data/resumes.sqlite `
  --report data/reports/b2b_ai_product_manager_rescore_20260716.json `
  --apply-latest 2
```

Verify the backup path exists and only the two frozen IDs changed score.

- [ ] **Step 7: Review recommendation quality**

Inspect the top 30 report rows against their resume evidence, remove identity duplicates or false-positive keyword matches, and finalize 20 candidates. If fewer than 20 pass both hard gates, label the remainder as B-tier follow-up rather than claiming they fully satisfy the JD.

- [ ] **Step 8: Restart only 18080 and verify health**

Restart the preview control plane using the existing server task/process workflow. Confirm port 18080 has a new process and `http://127.0.0.1:18080/health` returns 200. Confirm port 8080 remains listening.

- [ ] **Step 9: Verify future automatic scoring**

Run a repository-level smoke test against a temporary record with no preexisting score and confirm it receives version `v6-b2b-ai-product-manager-gates` behavior without writing a production test record.
