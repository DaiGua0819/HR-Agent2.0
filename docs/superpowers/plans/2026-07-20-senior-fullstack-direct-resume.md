# 资深全栈工程师直求简历 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让三个招聘平台全面识别新发布的资深全栈岗位，不回答候选人问题，只执行求简历，并将简历统一标记为 `全栈工程师`。

**Architecture:** 继续以 `boss_chat_rules.json` 作为跨平台岗位规则唯一来源，通过现有 `select_position_rule()` 名称规范化和最长匹配选择规则。新增一条规则名称为 `资深全栈工程师`、`resumeJobType` 为 `全栈工程师` 的直求简历配置，并将该入库类型加入共享前置话术策略集合；三个 runner 不新增分支。

**Tech Stack:** Python 3.12、pytest、JSON 岗位规则、现有 ConversationRunner 平台适配器。

## Global Constraints

- 平台识别规则名称统一为 `资深全栈工程师`。
- 简历入库、统计和简历库标签统一为 `全栈工程师`。
- 当前不回复任何候选人问题，不发送筛选问题。
- 未收到简历且未求过简历时，沿用 AI 产品经理的两句前置话术池并执行原生求简历。
- 匹配 BOSS 短标题和 51job/智联长标题，同时兼容空格和标点差异。
- 不把任意普通 `全栈工程师` 岗位自动视为当前资深岗位。
- 不启动真实消息处理。

---

### Task 1: 岗位规则与名称映射契约

**Files:**
- Modify: `tests/agent/test_boss_phase2.py`
- Modify: `config/chat_rules/boss_chat_rules.json`

**Interfaces:**
- Consumes: `select_position_rule(position: str, rules: dict | None) -> dict | None`
- Produces: `资深全栈工程师` 直求简历规则，`resumeJobType == "全栈工程师"`

- [ ] **Step 1: Write the failing rule-resolution test**

```python
def test_senior_fullstack_platform_titles_share_resume_label() -> None:
    rules = load_chat_rules()
    titles = (
        "资深全栈工程师（AI 原生 B2B 平台 ）",
        "资深全栈工程师（AI 原生 B2B 平台 / 工程 Owner）",
        "资深全栈工程师(AI原生B2B平台/工程Owner)",
    )
    for title in titles:
        rule = select_position_rule(title, rules)
        assert rule is not None
        assert rule["directResume"] is True
        assert rule["positionRuleKey"] == "资深全栈工程师"
        assert rule["resumeJobType"] == "全栈工程师"

    assert select_position_rule("全栈工程师", rules) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agent/test_boss_phase2.py::test_senior_fullstack_platform_titles_share_resume_label -q`

Expected: FAIL because the new titles do not resolve to a direct-resume rule.

- [ ] **Step 3: Add the minimal shared rule**

Add a `positionReplies.资深全栈工程师` entry and matching `companyKnowledgeBase.sections.资深全栈工程师` entry with:

```json
{
  "category": "senior_fullstack_direct_resume",
  "directResume": true,
  "resumeJobType": "全栈工程师",
  "aliases": [
    "资深全栈工程师（AI 原生 B2B 平台 ）",
    "资深全栈工程师（AI 原生 B2B 平台 / 工程 Owner）",
    "资深全栈工程师(AI原生B2B平台/工程Owner)"
  ],
  "resumeRequestPrompt": "你好，方便发一份简历过来吗",
  "resumeRequestPrompts": [
    "你好，方便发一份简历过来吗",
    "你好，可以看看简历吗"
  ],
  "screeningQuestions": []
}
```

Do not add bare `全栈工程师` as a match alias.

- [ ] **Step 4: Run the rule-resolution test**

Run: `pytest tests/agent/test_boss_phase2.py::test_senior_fullstack_platform_titles_share_resume_label -q`

Expected: PASS.

### Task 2: 三个平台直求简历行为

**Files:**
- Modify: `app/agent/policy.py`
- Modify: `tests/agent/test_boss_phase2.py`
- Modify: `tests/agent/test_job51_phase3.py`
- Modify: `tests/agent/test_zhilian_phase1.py`

**Interfaces:**
- Consumes: resolved rule with `directResume=True` and `resumeJobType="全栈工程师"`
- Produces: all platforms send one configured prephrase and choose `next_action="request_resume"`

- [ ] **Step 1: Write failing platform behavior tests**

For each platform, run a conversation whose candidate asks a question and assert:

```python
assert state["next_action"] == "request_resume"
assert state["stage"] == "direct_resume"
assert page.sent_messages in (
    ["你好，方便发一份简历过来吗"],
    ["你好，可以看看简历吗"],
)
assert page.resume_requests == 1
assert state["decision"]["resume_job_type"] == "全栈工程师"
```

Use the BOSS short title and the 51job/智联 long title so both published forms are covered.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests/agent/test_boss_phase2.py::test_boss_senior_fullstack_question_requests_resume `
  tests/agent/test_job51_phase3.py::test_job51_senior_fullstack_question_requests_resume `
  tests/agent/test_zhilian_phase1.py::test_zhilian_senior_fullstack_question_requests_resume -q
```

Expected: FAIL because `全栈工程师` is not yet in the shared direct-resume prephrase policy.

- [ ] **Step 3: Add the resume label to the shared policy**

Add `全栈工程师` to `ALL_PLATFORM_DIRECT_RESUME_TYPES` and `ALL_PLATFORM_DIRECT_RESUME_ALIASES` in `app/agent/policy.py`. Do not introduce platform-specific branches.

- [ ] **Step 4: Run focused tests**

Run the three tests from Step 2 plus the rule-resolution test from Task 1.

Expected: PASS.

- [ ] **Step 5: Run cross-platform direct-resume regression tests**

Run:

```powershell
pytest tests/agent/test_boss_phase2.py -q
pytest tests/agent/test_job51_phase3.py -q
pytest tests/agent/test_zhilian_phase1.py -q
```

Expected: all tests pass with no warnings or errors.

- [ ] **Step 6: Validate JSON and inspect the diff**

Run:

```powershell
python -m json.tool config/chat_rules/boss_chat_rules.json > $null
git diff --check
git diff -- app/agent/policy.py config/chat_rules/boss_chat_rules.json tests/agent/test_boss_phase2.py tests/agent/test_job51_phase3.py tests/agent/test_zhilian_phase1.py
```

Expected: valid JSON, no whitespace errors, and only the intended role/policy/test changes.

- [ ] **Step 7: Commit**

```powershell
git add app/agent/policy.py config/chat_rules/boss_chat_rules.json tests/agent/test_boss_phase2.py tests/agent/test_job51_phase3.py tests/agent/test_zhilian_phase1.py docs/superpowers/plans/2026-07-20-senior-fullstack-direct-resume.md
git commit -m "支持资深全栈工程师直求简历"
```
