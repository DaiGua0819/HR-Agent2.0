# Resume Chat History Local Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地 `18080/18081` 简历库中实现仅管理员可用的右键聊天记录弹窗、丝滑进入/退出动画，并为候选人卡片增加上下对齐的评分胶囊。

**Architecture:** 后端新增聚焦的 `ResumeConversationService`，只读取已明确关联的 `conversation_sessions` 与 `conversation_messages`；API 先校验管理员身份和简历可见权限，再返回最多 200 条只读消息。前端使用一个 `body` 顶层弹窗，通过 `contextmenu`、AbortController、request sequence 和 opening/open/closing 状态控制请求与动画；评分使用固定网格列，不因姓名长度发生位移。

**Tech Stack:** Python 3.12、FastAPI、SQLite、原生 JavaScript、CSS transition、pytest、ruff、Node syntax check、当前本地 PDF.js 预览。

## Global Constraints

- 只修改当前 `hr-agent` 工作树，不修改或重启旧 `8080` 服务。
- 仅管理员可查看聊天；member 不显示入口，直接调用接口返回 `403 admin_conversation_forbidden`。
- 只展示明确 `linked_session_id` 关联的会话；姓名/岗位候选仅用于诊断，不自动返回消息。
- 弹窗完全只读，不提供输入框、发送按钮或招聘平台操作。
- 不新增 Motion、Headless UI、AutoAnimate 等运行时依赖；动画使用原生 CSS/JavaScript。
- 打开动画约 `240ms`，关闭动画约 `160ms`，支持 `prefers-reduced-motion`。
- 快速切候选人、重复右键或关闭弹窗时，旧请求和旧响应不得污染当前候选人。
- 候选人评分胶囊位于姓名右侧，姓名列、评分列、状态列使用稳定宽度并纵向对齐。
- 本计划不执行服务器会话同步；同步和旧 `8080` JSON 迁移在本地功能验收后单独计划。
- 所有手工代码编辑使用 `apply_patch`，不覆盖用户现有未提交数据、日志或部署包。

---

## File Structure

- Create `app/domain/conversation/service.py`: 简历到明确会话的定位、消息规范化和只读响应组装。
- Modify `app/domain/conversation/repository.py`: 增加消息总数查询，支持最多 200 条历史消息读取。
- Modify `app/api/routes/resumes.py`: 新增管理员聊天接口和服务获取函数。
- Modify `app/control_plane/main.py`: 复用同一个 `ConversationRepository` 并注入 `ResumeConversationService`。
- Create `tests/domain/test_resume_conversation_history.py`: 服务、接口、权限、断链和截断测试。
- Modify `frontend/index.html`: 增加顶层弹窗 DOM，更新前端 cache-bust。
- Modify `frontend/app.js`: 增加右键入口、请求防串、消息渲染、关闭生命周期和评分胶囊 markup。
- Modify `frontend/styles.css`: 增加方案 A 弹窗动画、消息样式和候选卡片固定列布局。
- Modify `tests/domain/test_frontend_resume_member_view.py`: 增加静态交互、动画、权限和评分对齐契约测试。

---

### Task 1: Conversation Repository And Read-only Service

**Files:**
- Create: `app/domain/conversation/service.py`
- Modify: `app/domain/conversation/repository.py:244-262`
- Create: `tests/domain/test_resume_conversation_history.py`

**Interfaces:**
- Consumes: `Resume`, `ConversationSession`, `ConversationMessageRecord`, `ConversationRepository.get_session()`, `ConversationRepository.search_by_candidate_name()`.
- Produces: `ConversationRepository.count_messages(session_id: str) -> int`, `ConversationRepository.list_messages(session_id: str, *, limit: int = 200) -> list[ConversationMessageRecord]`, `ResumeConversationService.get_for_resume(resume: Resume, *, limit: int = 200) -> dict[str, object]`.

- [ ] **Step 1: Write failing service tests**

Add fixtures and tests to `tests/domain/test_resume_conversation_history.py`:

```python
from pathlib import Path

from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.conversation.service import MAX_CONVERSATION_MESSAGES, ResumeConversationService
from app.domain.resume.models import Resume
from app.platforms.types import ChatMessage, MessageSender


def _session(session_id: str = "session-1") -> ConversationSession:
    return ConversationSession(
        id=session_id,
        platform="boss",
        owner="宋锋峰",
        candidate_name="李乐",
        position="AI应用开发实习生",
        updated_at="2026-07-13T12:43:26+00:00",
    )


def _linked_resume(session_id: str = "session-1") -> Resume:
    return Resume(
        id="resume-1",
        name="李乐",
        parsed_name="李乐",
        job_type="AI应用开发实习生",
        linked_session_id=session_id,
        linked_platform="boss",
        linked_owner="宋锋峰",
    )


def test_linked_resume_returns_chronological_read_only_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session())
    repository.save_messages(
        "session-1",
        [
            ChatMessage(sender=MessageSender.CANDIDATE, text="想了解工作时间", time="20:31"),
            ChatMessage(sender=MessageSender.ME, text="工作时间为 9:00-18:00", time="20:32"),
            ChatMessage(sender=MessageSender.SYSTEM, text="对方向你发送了简历", time="20:35"),
        ],
    )

    payload = ResumeConversationService(repository).get_for_resume(_linked_resume())

    assert payload["matched"] is True
    assert payload["matchMode"] == "linked_session_id"
    assert payload["conversation"]["platform"] == "boss"
    assert payload["conversation"]["owner"] == "宋锋峰"
    assert [item["sender"] for item in payload["messages"]] == ["other", "me", "system"]
    assert [item["text"] for item in payload["messages"]] == [
        "想了解工作时间",
        "工作时间为 9:00-18:00",
        "对方向你发送了简历",
    ]


def test_broken_or_ambiguous_resume_link_never_returns_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session("candidate-a"))
    repository.save_session(_session("candidate-b"))
    service = ResumeConversationService(repository)

    broken = service.get_for_resume(_linked_resume("missing-session"))
    unlinked = service.get_for_resume(
        Resume(id="resume-2", name="李乐", parsed_name="李乐", job_type="AI应用开发实习生")
    )

    assert broken["matched"] is False
    assert broken["reason"] == "conversation_not_linked"
    assert broken["messages"] == []
    assert unlinked["matched"] is False
    assert unlinked["reason"] == "conversation_ambiguous"
    assert unlinked["messages"] == []


def test_conversation_history_is_limited_to_latest_200_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session())
    repository.save_messages(
        "session-1",
        [
            ChatMessage(sender=MessageSender.CANDIDATE, text=f"message-{index:03d}")
            for index in range(MAX_CONVERSATION_MESSAGES + 5)
        ],
    )

    payload = ResumeConversationService(repository).get_for_resume(_linked_resume())

    assert payload["conversation"]["messageCount"] == 205
    assert payload["conversation"]["truncated"] is True
    assert len(payload["messages"]) == MAX_CONVERSATION_MESSAGES
    assert payload["messages"][0]["text"] == "message-005"
    assert payload["messages"][-1]["text"] == "message-204"
```

- [ ] **Step 2: Run the tests and confirm the missing service failure**

Run:

```powershell
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' -m pytest tests/domain/test_resume_conversation_history.py -q
```

Expected: collection fails with `ModuleNotFoundError: app.domain.conversation.service`.

- [ ] **Step 3: Add repository count and bounded history reads**

Update `ConversationRepository`:

```python
    def count_messages(self, session_id: str) -> int:
        """Return the number of persisted messages for one session."""

        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM conversation_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["total"] if row else 0)

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int = 200,
    ) -> list[ConversationMessageRecord]:
        """Read the latest bounded message window in chronological order."""

        bounded_limit = max(1, min(int(limit), 200))
        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                  SELECT rowid AS message_rowid, *
                  FROM conversation_messages
                  WHERE session_id = ?
                  ORDER BY created_at DESC, rowid DESC
                  LIMIT ?
                )
                ORDER BY created_at ASC, message_rowid ASC
                """,
                (session_id, bounded_limit),
            ).fetchall()
        return [_message_from_row(row) for row in rows]
```

- [ ] **Step 4: Implement the focused conversation service**

Create `app/domain/conversation/service.py`:

```python
"""Read-only resume conversation lookup for the resume library."""

from __future__ import annotations

from typing import Any

from app.domain.conversation.models import ConversationMessageRecord, ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.models import Resume

MAX_CONVERSATION_MESSAGES = 200
_VALID_SENDERS = {"me", "other", "system"}


class ResumeConversationService:
    """Resolve only high-confidence resume links and expose safe message fields."""

    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    def get_for_resume(self, resume: Resume, *, limit: int = MAX_CONVERSATION_MESSAGES) -> dict[str, object]:
        session = self._linked_session(resume)
        if session is None:
            reason = self._unmatched_reason(resume)
            return _empty_payload(resume, reason)

        total = self.repository.count_messages(session.id)
        bounded_limit = max(1, min(int(limit), MAX_CONVERSATION_MESSAGES))
        messages = self.repository.list_messages(session.id, limit=bounded_limit)
        return {
            "resumeId": resume.id,
            "matched": True,
            "matchMode": "linked_session_id",
            "reason": "",
            "candidate": _candidate_payload(resume),
            "conversation": _session_payload(session, total=total, limit=bounded_limit),
            "messages": [_message_payload(message) for message in messages],
        }

    def _linked_session(self, resume: Resume) -> ConversationSession | None:
        if not resume.linked_session_id:
            return None
        return self.repository.get_session(resume.linked_session_id)

    def _unmatched_reason(self, resume: Resume) -> str:
        if resume.linked_session_id:
            return "conversation_not_linked"
        name = (resume.parsed_name or resume.name or "").strip()
        position = (resume.job_type or resume.applied_position or "").strip()
        candidates = self.repository.search_by_candidate_name(
            candidate_name=name,
            position=position,
        )
        return "conversation_ambiguous" if len(candidates) > 1 else "conversation_not_linked"


def _empty_payload(resume: Resume, reason: str) -> dict[str, object]:
    return {
        "resumeId": resume.id,
        "matched": False,
        "matchMode": "none",
        "reason": reason,
        "candidate": _candidate_payload(resume),
        "conversation": None,
        "messages": [],
    }


def _candidate_payload(resume: Resume) -> dict[str, str]:
    return {
        "name": (resume.parsed_name or resume.name or "").strip(),
        "jobType": (resume.job_type or resume.applied_position or "").strip(),
    }


def _session_payload(session: ConversationSession, *, total: int, limit: int) -> dict[str, Any]:
    return {
        "sessionId": session.id,
        "platform": session.platform,
        "owner": session.owner,
        "updatedAt": session.updated_at or session.last_seen_at,
        "messageCount": total,
        "truncated": total > limit,
    }


def _message_payload(message: ConversationMessageRecord) -> dict[str, str]:
    sender = message.sender if message.sender in _VALID_SENDERS else "other"
    return {
        "id": message.id,
        "sender": sender,
        "text": message.text,
        "sentAt": message.sent_at or message.created_at,
    }
```

- [ ] **Step 5: Run focused tests and lint**

Run:

```powershell
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' -m pytest tests/domain/test_resume_conversation_history.py -q
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' -m ruff check app/domain/conversation tests/domain/test_resume_conversation_history.py
```

Expected: `3 passed`; Ruff prints `All checks passed!`.

- [ ] **Step 6: Commit Task 1**

```powershell
git add app/domain/conversation/service.py app/domain/conversation/repository.py tests/domain/test_resume_conversation_history.py
git commit -m "新增简历聊天记录只读服务"
```

---

### Task 2: Admin-only Conversation API

**Files:**
- Modify: `app/api/routes/resumes.py:17-53, 129-230`
- Modify: `app/control_plane/main.py:24-68`
- Modify: `tests/domain/test_resume_conversation_history.py`

**Interfaces:**
- Consumes: `ResumeConversationService.get_for_resume(resume)` from Task 1 and existing `_assert_resume_visible()`.
- Produces: `GET /api/resumes/{resume_id}/conversation` returning the Task 1 payload.

- [ ] **Step 1: Add failing API and permission tests**

Append:

```python
from fastapi.testclient import TestClient

from app.control_plane.main import create_app
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService


def _conversation_app(tmp_path: Path):
    conversation_repository = ConversationRepository(tmp_path / "conversation.sqlite")
    conversation_repository.save_session(_session())
    conversation_repository.save_messages(
        "session-1",
        [ChatMessage(sender=MessageSender.CANDIDATE, text="hello", time="20:31")],
    )
    resume_repository = ResumeRepository.in_memory([_linked_resume().to_record()])
    app = create_app()
    app.state.auth_session_store_path = tmp_path / "auth.sqlite"
    app.state.resume_repository = resume_repository
    app.state.resume_service = ResumeService(resume_repository)
    app.state.resume_conversation_service = ResumeConversationService(conversation_repository)
    return app


def test_admin_can_read_linked_resume_conversation(tmp_path: Path) -> None:
    app = _conversation_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.get("/api/resumes/resume-1/conversation")

    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["messages"][0]["text"] == "hello"


def test_member_cannot_read_resume_conversation(tmp_path: Path) -> None:
    app = _conversation_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "member", "password": "member"})
        response = client.get("/api/resumes/resume-1/conversation")

    assert response.status_code == 403
    assert response.json()["detail"] == "admin_conversation_forbidden"


def test_missing_resume_returns_not_found_after_admin_check(tmp_path: Path) -> None:
    app = _conversation_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.get("/api/resumes/missing/conversation")

    assert response.status_code == 404
    assert response.json()["detail"] == "resume_not_found"
```

- [ ] **Step 2: Run the new API tests and confirm 404 route failures**

Run the three tests by name. Expected: the first two fail because the route does not exist.

- [ ] **Step 3: Inject a shared conversation repository and service**

In `app/control_plane/main.py`, add imports and initialization:

```python
from app.domain.conversation.repository import ConversationRepository
from app.domain.conversation.service import ResumeConversationService

# inside create_app()
conversation_repository = ConversationRepository(settings.resolved_database_path)
app.state.conversation_repository = conversation_repository
app.state.resume_conversation_service = ResumeConversationService(conversation_repository)
app.state.interview_center_service = InterviewCenterService(
    repository=repository,
    conversation_repository=conversation_repository,
)
```

Replace the existing `InterviewCenterService(repository=repository)` assignment so both features use the same SQLite repository instance.

- [ ] **Step 4: Add the admin-only route**

In `app/api/routes/resumes.py`:

```python
from app.domain.conversation.service import ResumeConversationService


def _conversation_service(request: Request) -> ResumeConversationService:
    service = getattr(request.app.state, "resume_conversation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="conversation_service_unavailable")
    return service


def _assert_admin_conversation_access(request: Request) -> None:
    payload = require_session_payload(request)
    roles = payload.get("roles")
    allowed = isinstance(roles, list) and any(role in {"admin", "super_admin"} for role in roles)
    if not allowed:
        raise HTTPException(status_code=403, detail="admin_conversation_forbidden")


@router.get("/{resume_id}/conversation")
async def get_resume_conversation(resume_id: str, request: Request) -> dict[str, object]:
    """Return one resume's persisted platform conversation to administrators."""

    _assert_admin_conversation_access(request)
    resume = _service(request).get_resume(resume_id)
    _assert_resume_visible(request, resume)
    return _conversation_service(request).get_for_resume(resume)
```

Place the route before the generic patch/update routes; FastAPI supports the static suffix without changing public list/detail URLs.

- [ ] **Step 5: Run API, permission, and interview-center regressions**

```powershell
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' -m pytest tests/domain/test_resume_conversation_history.py tests/domain/test_resume_scope_permissions.py tests/features/test_phase6_interview_center.py -q
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' -m ruff check app/api/routes/resumes.py app/control_plane/main.py tests/domain/test_resume_conversation_history.py
```

Expected: all selected tests pass and Ruff passes.

- [ ] **Step 6: Commit Task 2**

```powershell
git add app/api/routes/resumes.py app/control_plane/main.py tests/domain/test_resume_conversation_history.py
git commit -m "增加管理员简历聊天记录接口"
```

---

### Task 3: Modal DOM, Right-click Entry, And Request Guards

**Files:**
- Modify: `frontend/index.html:221-359`
- Modify: `frontend/app.js:1-69, 1446-1459, 3150-3218`
- Modify: `tests/domain/test_frontend_resume_member_view.py`

**Interfaces:**
- Consumes: `GET /api/resumes/{resume_id}/conversation`, existing `api()`, `isAdminUser()`, `selectedResume()`, `escapeHtml()`.
- Produces: `openResumeConversation()`, `closeResumeConversation()`, `handleResumePreviewContextMenu(event)`, and top-level modal element IDs.

- [ ] **Step 1: Add failing frontend contract tests**

Add:

```python
def test_admin_resume_preview_has_right_click_conversation_modal_contract() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="resumeConversationModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert "function handleResumePreviewContextMenu(event)" in script
    assert 'if (!isAdminUser() || !state.selectedId) return' in script
    assert 'event.preventDefault()' in script
    assert 'api(`/api/resumes/${resumeId}/conversation`' in script
    assert "resumeConversationAbortController" in script
    assert "resumeConversationRequestSequence" in script
    assert "resume-conversation-date" in script
    assert "if (requestSequence !== state.resumeConversationRequestSequence) return" in script
    assert "if (state.selectedId !== resumeId) return" in script


def test_member_right_click_keeps_browser_default_menu() -> None:
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    block = script.split("function handleResumePreviewContextMenu(event)", 1)[1].split(
        "async function openResumeConversation", 1
    )[0]

    assert block.index('if (!isAdminUser() || !state.selectedId) return') < block.index(
        "event.preventDefault()"
    )
```

- [ ] **Step 2: Run the contract tests and confirm failure**

Expected: failures for missing modal DOM and functions.

- [ ] **Step 3: Add the static modal shell**

Before the reviewer popover root in `frontend/index.html`, add:

```html
<div id="resumeConversationModal" class="resume-conversation-root" data-state="closed" hidden>
  <div id="resumeConversationBackdrop" class="resume-conversation-backdrop"></div>
  <section
    class="resume-conversation-dialog"
    role="dialog"
    aria-modal="true"
    aria-labelledby="resumeConversationTitle"
  >
    <header class="resume-conversation-head">
      <span id="resumeConversationAvatar" class="resume-conversation-avatar"></span>
      <div class="resume-conversation-identity">
        <strong id="resumeConversationTitle">聊天记录</strong>
        <span id="resumeConversationSubtitle"></span>
      </div>
      <button id="resumeConversationCloseBtn" class="resume-conversation-close" type="button" title="关闭聊天记录" aria-label="关闭聊天记录">×</button>
    </header>
    <div id="resumeConversationMeta" class="resume-conversation-meta"></div>
    <div id="resumeConversationMessages" class="resume-conversation-messages" aria-live="polite"></div>
    <footer class="resume-conversation-readonly">只读历史记录 · 不会向招聘平台发送消息</footer>
  </section>
</div>
```

Update CSS and JS cache-bust values to `20260714-resume-conversation`.

- [ ] **Step 4: Add request and modal state**

Extend `state`:

```javascript
  resumeConversationAbortController: null,
  resumeConversationRequestSequence: 0,
  resumeConversationResumeId: "",
  resumeConversationCloseTimer: null,
  resumeConversationPreviousFocus: null,
```

Add the core renderer and loader:

```javascript
function conversationDateLabel(value) {
  const match = String(value || "").match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : "";
}

function renderResumeConversationPayload(payload) {
  const resume = selectedResume() || {};
  const candidate = payload?.candidate || {};
  const conversation = payload?.conversation || {};
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  $("resumeConversationAvatar").textContent = (candidate.name || resumeName(resume) || "候").slice(0, 2);
  $("resumeConversationTitle").textContent = `${candidate.name || resumeName(resume)} · ${candidate.jobType || resumeJob(resume)}`;
  $("resumeConversationSubtitle").textContent = payload?.matched
    ? `${platformName(conversation.platform)} · ${conversation.owner || "未知账号"} · 最近更新 ${conversation.updatedAt || "待同步"}`
    : "暂未找到明确关联的聊天记录";
  $("resumeConversationMeta").innerHTML = payload?.matched
    ? `<span class="resume-conversation-chip resume-conversation-chip--success">身份已关联</span><span class="resume-conversation-chip">历史消息 ${Number(conversation.messageCount || 0)} 条</span><span class="resume-conversation-chip">只读</span>`
    : `<span class="resume-conversation-chip">未关联</span>`;
  $("resumeConversationMessages").innerHTML = renderResumeConversationMessages(messages, payload);
}

function renderResumeConversationMessages(messages, payload) {
  if (!payload?.matched) return '<div class="resume-conversation-empty">暂未找到明确关联的聊天记录。</div>';
  if (!messages.length) return '<div class="resume-conversation-empty">当前会话还没有已保存消息。</div>';
  let previousDate = "";
  return messages.map((message) => {
    const sender = ["me", "other", "system"].includes(message.sender) ? message.sender : "other";
    const date = conversationDateLabel(message.sentAt);
    const separator = date && date !== previousDate
      ? `<div class="resume-conversation-date">${escapeHtml(date)}</div>`
      : "";
    if (date) previousDate = date;
    if (sender === "system") {
      return `${separator}<div class="resume-conversation-system">${escapeHtml(message.text || "")}</div>`;
    }
    return `${separator}
      <article class="resume-conversation-message resume-conversation-message--${sender}">
        <div class="resume-conversation-bubble">
          <span>${escapeHtml(message.text || "")}</span>
          <time>${escapeHtml(message.sentAt || "")}</time>
        </div>
      </article>`;
  }).join("");
}

function handleResumePreviewContextMenu(event) {
  if (!isAdminUser() || !state.selectedId) return;
  if (!event.target.closest("#resumePreview")) return;
  event.preventDefault();
  openResumeConversation();
}

async function openResumeConversation() {
  if (!isAdminUser() || !state.selectedId) return;
  const resumeId = state.selectedId;
  const requestSequence = (state.resumeConversationRequestSequence += 1);
  if (state.resumeConversationAbortController) state.resumeConversationAbortController.abort();
  const controller = new AbortController();
  state.resumeConversationAbortController = controller;
  showResumeConversationModalLoading(resumeId);
  try {
    const payload = await api(`/api/resumes/${resumeId}/conversation`, { signal: controller.signal });
    if (requestSequence !== state.resumeConversationRequestSequence) return;
    if (state.selectedId !== resumeId) return;
    renderResumeConversationPayload(payload);
  } catch (error) {
    if (error?.name === "AbortError") return;
    if (requestSequence !== state.resumeConversationRequestSequence) return;
    $("resumeConversationMessages").innerHTML = '<div class="resume-conversation-empty">聊天记录读取失败，请关闭后重试。</div>';
  } finally {
    if (state.resumeConversationAbortController === controller) state.resumeConversationAbortController = null;
  }
}
```

`showResumeConversationModalLoading()` and closing lifecycle are completed in Task 4 so this task remains focused on request identity and payload rendering.

- [ ] **Step 5: Bind the right-click and close controls**

In `bindPageActions()`:

```javascript
  $("resumePreview").addEventListener("contextmenu", handleResumePreviewContextMenu);
  $("resumeConversationCloseBtn").onclick = closeResumeConversation;
  $("resumeConversationBackdrop").onclick = closeResumeConversation;
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("resumeConversationModal").hidden) closeResumeConversation();
  });
```

In `openResume(id)`, call `closeResumeConversation({ immediate: true })` before changing `state.selectedId`, ensuring a visible modal never remains attached to the previous candidate.

- [ ] **Step 6: Run frontend contract tests and syntax check**

```powershell
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' -m pytest tests/domain/test_frontend_resume_member_view.py -q
& 'C:\Users\24471\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check frontend/app.js
```

Expected: frontend tests pass and Node exits `0`.

- [ ] **Step 7: Commit Task 3**

```powershell
git add frontend/index.html frontend/app.js tests/domain/test_frontend_resume_member_view.py
git commit -m "增加管理员右键聊天记录弹窗"
```

---

### Task 4: Smooth Modal Animation And Accessible Close Lifecycle

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Modify: `tests/domain/test_frontend_resume_member_view.py`

**Interfaces:**
- Consumes: modal element IDs and request state from Task 3.
- Produces: `showResumeConversationModalLoading(resumeId)`, `closeResumeConversation({ immediate = false } = {})`, opening/open/closing animation states.

- [ ] **Step 1: Add failing animation contract tests**

```python
def test_resume_conversation_modal_has_smooth_open_close_states() -> None:
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'modal.dataset.state = "opening"' in script
    assert 'modal.dataset.state = "open"' in script
    assert 'modal.dataset.state = "closing"' in script
    assert "requestAnimationFrame" in script
    assert "transitionend" in script
    assert "resumeConversationCloseTimer" in script
    assert '.resume-conversation-root[data-state="open"] .resume-conversation-dialog' in styles
    assert 'translateY(12px) scale(0.985)' in styles
    assert '240ms cubic-bezier(0.22, 1, 0.36, 1)' in styles
    assert '160ms cubic-bezier(0.4, 0, 1, 1)' in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles
```

- [ ] **Step 2: Run the animation contract test and confirm failure**

Expected: missing CSS selectors and lifecycle strings.

- [ ] **Step 3: Implement the modal lifecycle**

```javascript
function finishResumeConversationClose() {
  const modal = $("resumeConversationModal");
  if (state.resumeConversationCloseTimer) clearTimeout(state.resumeConversationCloseTimer);
  state.resumeConversationCloseTimer = null;
  modal.hidden = true;
  modal.dataset.state = "closed";
  $("resumeConversationMessages").innerHTML = "";
  const previousFocus = state.resumeConversationPreviousFocus;
  state.resumeConversationPreviousFocus = null;
  if (previousFocus?.focus) previousFocus.focus({ preventScroll: true });
}

function showResumeConversationModalLoading(resumeId) {
  const modal = $("resumeConversationModal");
  const resume = selectedResume() || {};
  if (state.resumeConversationCloseTimer) clearTimeout(state.resumeConversationCloseTimer);
  state.resumeConversationCloseTimer = null;
  state.resumeConversationResumeId = resumeId;
  if (modal.hidden) state.resumeConversationPreviousFocus = document.activeElement;
  modal.hidden = false;
  modal.dataset.state = "opening";
  $("resumeConversationAvatar").textContent = (resumeName(resume) || "候").slice(0, 2);
  $("resumeConversationTitle").textContent = `${resumeName(resume)} · ${resumeJob(resume)}`;
  $("resumeConversationSubtitle").textContent = "正在读取平台聊天记录";
  $("resumeConversationMeta").innerHTML = '<span class="resume-conversation-chip">读取中</span>';
  $("resumeConversationMessages").innerHTML = '<div class="resume-conversation-loading">正在读取聊天记录...</div>';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (!modal.hidden && state.resumeConversationResumeId === resumeId) {
      modal.dataset.state = "open";
      $("resumeConversationCloseBtn").focus({ preventScroll: true });
    }
  }));
}

function closeResumeConversation({ immediate = false } = {}) {
  const modal = $("resumeConversationModal");
  if (!modal || modal.hidden) return;
  state.resumeConversationRequestSequence += 1;
  state.resumeConversationResumeId = "";
  if (state.resumeConversationAbortController) {
    state.resumeConversationAbortController.abort();
    state.resumeConversationAbortController = null;
  }
  if (immediate) {
    finishResumeConversationClose();
    return;
  }
  modal.dataset.state = "closing";
  const dialog = modal.querySelector(".resume-conversation-dialog");
  const finish = () => finishResumeConversationClose();
  dialog.addEventListener("transitionend", finish, { once: true });
  state.resumeConversationCloseTimer = setTimeout(finish, 240);
}
```

- [ ] **Step 4: Add scheme A styles and motion reduction**

Add CSS using the exact approved values:

```css
.resume-conversation-root {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: grid;
  place-items: center;
  padding: 24px;
}
.resume-conversation-root[hidden] { display: none; }
.resume-conversation-backdrop {
  position: absolute;
  inset: 0;
  opacity: 0;
  background: rgba(15, 23, 42, 0.42);
  transition: opacity 180ms ease-out;
}
.resume-conversation-dialog {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  width: min(820px, calc(100vw - 48px));
  height: min(720px, calc(100vh - 48px));
  overflow: hidden;
  opacity: 0;
  transform: translateY(12px) scale(0.985);
  border: 1px solid rgba(203, 213, 225, 0.9);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 30px 80px rgba(15, 23, 42, 0.28);
  transition: opacity 240ms cubic-bezier(0.22, 1, 0.36, 1), transform 240ms cubic-bezier(0.22, 1, 0.36, 1);
}
.resume-conversation-root[data-state="open"] .resume-conversation-backdrop { opacity: 1; }
.resume-conversation-root[data-state="open"] .resume-conversation-dialog { opacity: 1; transform: translateY(0) scale(1); }
.resume-conversation-root[data-state="closing"] .resume-conversation-backdrop { opacity: 0; transition-duration: 140ms; transition-timing-function: ease-in; }
.resume-conversation-root[data-state="closing"] .resume-conversation-dialog {
  opacity: 0;
  transform: translateY(6px) scale(0.99);
  transition: opacity 160ms cubic-bezier(0.4, 0, 1, 1), transform 160ms cubic-bezier(0.4, 0, 1, 1);
}
@media (prefers-reduced-motion: reduce) {
  .resume-conversation-backdrop,
  .resume-conversation-dialog {
    transition-duration: 1ms !important;
    transform: none !important;
  }
}
```

Add focused styles for `.resume-conversation-head`, avatar, chips, messages, bubbles, date separators, loading/empty states and responsive `max-width: 760px`. Use white candidate bubbles, pale blue `me` bubbles and centered gray system messages; do not add a composer.

- [ ] **Step 5: Run frontend tests and syntax check**

Run the same commands from Task 3. Expected: pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add frontend/app.js frontend/styles.css tests/domain/test_frontend_resume_member_view.py
git commit -m "优化聊天弹窗丝滑过渡动画"
```

---

### Task 5: Aligned Candidate Score Capsule

**Files:**
- Modify: `frontend/app.js:1206-1244`
- Modify: `frontend/styles.css:836-848`
- Modify: `tests/domain/test_frontend_resume_member_view.py:1301-1412`

**Interfaces:**
- Consumes: slim list fields `match_score` / `matchScore`, existing decision and member badge markup.
- Produces: `resumeScoreLabel(resume)`, `.candidate-card__score`, `.candidate-card__heading-status`, fixed heading grid columns.

- [ ] **Step 1: Add failing score alignment contract test**

```python
def test_candidate_score_capsule_is_aligned_in_fixed_heading_column() -> None:
    script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function resumeScoreLabel(resume)" in script
    assert 'class="candidate-card__score"' in script
    assert 'class="candidate-card__heading-status"' in script
    assert 'title="简历评分"' in script
    heading_block = styles.split(".candidate-card__heading {", 1)[1].split("}", 1)[0]
    score_block = styles.split(".candidate-card__score {", 1)[1].split("}", 1)[0]
    assert "display: grid" in heading_block
    assert "grid-template-columns: minmax(0, 1fr) 46px 112px" in heading_block
    assert "min-width: 36px" in score_block
    assert "justify-self: center" in score_block
```

- [ ] **Step 2: Run the single test and confirm failure**

Expected: missing helper and classes.

- [ ] **Step 3: Add score label helper and stable markup**

```javascript
function resumeScoreLabel(resume) {
  const value = Number(resume?.match_score ?? resume?.matchScore);
  return Number.isFinite(value) ? String(Math.round(value)) : "--";
}
```

Change the card heading:

```html
<span class="candidate-card__heading">
  <strong>${escapeHtml(resumeName(resume))}</strong>
  <span class="candidate-card__score ${resumeScoreLabel(resume) === "--" ? "candidate-card__score--empty" : ""}" title="简历评分">${escapeHtml(resumeScoreLabel(resume))}</span>
  <span class="candidate-card__heading-status">
    <span class="${tsTagClass(review.decision)}">${escapeHtml(decision)}</span>
    ${memberDecisionBadge}
  </span>
</span>
```

- [ ] **Step 4: Convert the heading to fixed columns**

```css
.candidate-card__heading {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 46px 112px;
  align-items: center;
  gap: 8px;
}
.candidate-card__score {
  justify-self: center;
  min-width: 36px;
  padding: 3px 7px;
  border: 1px solid rgba(96, 165, 250, 0.34);
  border-radius: 999px;
  color: #1d4ed8;
  background: rgba(219, 234, 254, 0.78);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
  text-align: center;
}
.candidate-card__score--empty { color: #7b8798; background: #eef2f7; border-color: #dce4ee; }
.candidate-card__heading-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  width: 112px;
  min-width: 0;
}
```

At the existing mobile breakpoint, use `grid-template-columns: minmax(0, 1fr) 42px 92px` and set the status width to `92px`; all cards within the same viewport still align.

- [ ] **Step 5: Run candidate-card and full frontend tests**

```powershell
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' -m pytest tests/domain/test_frontend_resume_member_view.py -q
& 'C:\Users\24471\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check frontend/app.js
```

Expected: all pass.

- [ ] **Step 6: Commit Task 5**

```powershell
git add frontend/app.js frontend/styles.css tests/domain/test_frontend_resume_member_view.py
git commit -m "增加候选人评分胶囊并统一对齐"
```

---

### Task 6: Full Regression And Local Real-data Browser Verification

**Files:**
- Verify only; modify implementation files only if a reproduced failure requires a focused fix and new regression test.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified local feature, measured response timings and a concise real-data coverage report. No server deployment.

- [ ] **Step 1: Run complete focused regression**

```powershell
$python='C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe'
& $python -m pytest tests/domain/test_resume_conversation_history.py tests/domain/test_frontend_resume_member_view.py tests/domain/test_resume_scope_permissions.py tests/domain/test_auth_login_access.py tests/features/test_phase6_interview_center.py -q
& $python -m ruff check app tests
& 'C:\Users\24471\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check frontend/app.js
```

Expected: all selected pytest tests pass, Ruff prints `All checks passed!`, Node exits `0`.

- [ ] **Step 2: Start a local service on port 18081**

First check the port. If free:

```powershell
$env:CONTROL_PLANE_PORT='18081'
& 'C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe' run_control_plane.py
```

Keep the process running in its exec session. Do not use or stop `8080`.

- [ ] **Step 3: Open the local admin session and test real conversations**

Open:

```text
http://127.0.0.1:18081/api/auth/dev-login?username=admin
```

Then verify at least 15 linked real resumes, covering BOSS, 智联 and 51job when present:

- Right-click PDF.js canvas opens the modal.
- Right-click fallback image opens the same modal.
- Candidate name, job, platform and owner match the selected card.
- Message direction and order match SQLite.
- Empty stored message sessions show the empty state.
- Closing via X, backdrop and Escape runs the exit animation.
- Rapidly switch 10 candidates; no old title or message appears.
- Right-click repeatedly during loading; only one current modal remains.
- Score capsules remain vertically aligned for short names, long names, missing scores and member-decision badges.

- [ ] **Step 4: Verify member protection**

Visit:

```text
http://127.0.0.1:18081/api/auth/dev-login?username=member
```

Confirm right-click keeps the browser default menu. Directly request one known conversation endpoint and verify HTTP `403` with `admin_conversation_forbidden`.

- [ ] **Step 5: Measure local endpoint latency**

Use an authenticated admin cookie and at least 10 linked resume IDs. Record each `/conversation` request time with `curl.exe -w "%{time_total}"`; acceptance target is median below `0.2s`. In the browser, right-click to first visible loading state should be immediate and loaded messages should normally appear below `0.5s`.

- [ ] **Step 6: Inspect browser errors and responsive layout**

Check console errors, failed network requests, and viewport widths `1280px`, `900px`, and `390px`. Confirm the modal fits the viewport, only its message region scrolls, text does not overlap, and the close button remains visible.

- [ ] **Step 7: Fix only reproduced issues with regression tests**

For every issue, first add a failing test to the relevant test file, reproduce the failure, apply the smallest fix, then rerun Steps 1, 3 and 4. Do not broaden scope into data synchronization.

- [ ] **Step 8: Commit verification fixes if any**

If no fixes were necessary, do not create an empty commit. If fixes were necessary:

```powershell
git add app frontend tests
git commit -m "修复聊天记录本地真实数据验证问题"
```

- [ ] **Step 9: Stop only the local 18081 process and report results**

Stop the exec session started in Step 2. Report:

- Automated test counts.
- Real resumes tested by platform.
- Median and slowest endpoint times.
- Any unmatched or ambiguous local resumes observed.
- Confirmation that `8080` and server `18080` were untouched.

---

## Follow-up Plan Boundary

After this plan passes, write a separate `conversation-history-sync` implementation plan covering:

- Local `1660` sessions / `7301` messages incremental export.
- Server merge without replacing its `2867` resumes.
- Old `8080` JSON import and high-confidence resume linking.
- Dry-run manifests, backups, conflict handling and deployment to server `18080`.

Do not start that work until the local viewer has passed Task 6.
