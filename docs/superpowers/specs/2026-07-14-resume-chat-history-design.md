# 18080 管理员简历聊天记录设计

## Summary

在 `18080` 简历库中增加只读聊天记录查看能力。仅管理员可以在简历 PDF/图片预览区域点击鼠标右键打开方案 A 的居中弹窗；member 保持浏览器默认右键菜单，不获得聊天接口权限。

本地先完成原生 SQLite 查询、前端弹窗和真实会话测试。服务器部署前再执行会话数据增量同步，不修改或重启旧 `8080` 服务，也不让 `18080` 在运行时依赖 `8080`。

## Confirmed UX

- 入口：管理员在当前简历预览内容上点击鼠标右键。
- 展示：居中只读弹窗，背景使用轻量遮罩，保持原简历页面状态不变。
- 头部：候选人姓名、岗位、平台、账号和最近更新时间。
- 内容：候选人消息靠左，我方消息靠右，系统消息居中，跨日期时显示日期分隔。
- 底部：固定显示“只读历史记录，不会向招聘平台发送消息”，不提供输入框、发送按钮或自动化操作。
- 关闭：右上角关闭按钮、点击遮罩或按 `Escape`；关闭后焦点回到简历预览。
- 状态：提供加载中、无明确关联、没有已保存消息、读取失败四种状态。
- 尺寸：桌面端宽度不超过 `820px`，高度不超过视口；窄屏使用接近全屏的安全边距，消息区单独滚动。

设计参考：

- [Rocket.Chat](https://github.com/RocketChat/Rocket.Chat)：弱化时间信息、保持消息流清晰。
- [Chatwoot](https://github.com/chatwoot/chatwoot)：候选人身份与渠道固定在会话头部。
- [Alibaba ChatUI](https://github.com/alibaba/ChatUI)：左右消息气泡和精简状态表达。

只借鉴信息层级和阅读方式，不引入这些项目的框架或组件依赖。

## Scope

本次包含：

- `18080` 管理员只读聊天接口。
- 右键打开方案 A 弹窗。
- 使用当前 `conversation_sessions`、`conversation_messages` 和简历桥接字段读取聊天。
- 本地真实数据验证、权限测试和前端交互测试。
- 为后续本地到服务器增量同步定义数据边界。

本次不包含：

- 不在弹窗中回复候选人。
- 不实时连接招聘平台读取页面聊天。
- 不修改旧 `8080`。
- 不用本地 `resumes.sqlite` 整库覆盖服务器数据库。
- 不在第一阶段自动采用姓名模糊匹配结果展示消息。

## Backend Architecture

### API

新增：

```http
GET /api/resumes/{resume_id}/conversation
```

处理顺序：

1. 从飞书 session 读取当前用户。
2. 非管理员返回 `403 admin_conversation_forbidden`。
3. 读取简历并执行现有 `_assert_resume_visible()`，避免绕过简历权限。
4. 使用专用会话服务定位会话并读取消息。
5. 返回只读展示字段，不返回 `raw_text`、内部状态 payload 或招聘平台凭据。

建议响应：

```json
{
  "resumeId": "resume-id",
  "matched": true,
  "matchMode": "linked_session_id",
  "reason": "",
  "candidate": {
    "name": "李乐",
    "jobType": "AI应用开发实习生"
  },
  "conversation": {
    "sessionId": "conv-id",
    "platform": "boss",
    "owner": "宋锋峰",
    "updatedAt": "2026-07-13T12:43:26Z",
    "messageCount": 12,
    "truncated": false
  },
  "messages": [
    {
      "id": "message-id",
      "sender": "other",
      "text": "您好，想了解一下工作时间？",
      "sentAt": "2026-07-13 20:31"
    }
  ]
}
```

没有明确会话时返回 `200`、`matched=false` 和稳定 `reason`，前端显示空状态，不把接口 404 当成页面故障。

### Conversation Resolution

新增聚焦的 `ResumeConversationService`，避免继续扩大已经较大的 `InterviewCenterService`。

定位规则：

1. 优先使用 `resume.linked_session_id`，且会话必须真实存在。
2. 没有有效桥接时，只查询“姓名完全一致 + 岗位完全一致”的候选会话用于诊断。
3. 若结果不是唯一明确会话，不返回任何消息，返回 `reason=conversation_not_linked` 或 `conversation_ambiguous`。
4. 不使用同姓、岗位相同、最新消息相似等弱证据自动展示历史消息。

这比旧 `8080` 的按分数扫描 JSON 更安全，可以避免同名候选人串档。历史迁移阶段会负责把高置信匹配写成明确 `linked_session_id`。

### Message Query

- 仓储增加消息总数查询，并允许一次读取最近最多 `200` 条消息。
- 返回顺序按聊天时间升序；缺少 `sent_at` 时使用 `created_at`。
- 超过 `200` 条时返回最新 `200` 条并设置 `truncated=true`。
- sender 只输出 `me`、`other`、`system` 三种规范值。
- SQL 查询按 `session_id` 使用现有索引，不扫描整张消息表。

### Service Injection

在 FastAPI app 初始化时复用当前 `ResumeRepository` 和同一数据库路径的 `ConversationRepository`，注入 `ResumeConversationService`。接口层只处理权限、HTTP 参数和错误映射。

## Frontend Architecture

### Right-click Entry

- 在 `#resumePreview` 上使用事件委托监听 `contextmenu`。
- 只有 `isAdminUser()`、存在 `state.selectedId` 且事件来自当前 PDF/图片预览内容时才 `preventDefault()` 并打开弹窗。
- member、空白预览区和非简历内容继续显示浏览器默认右键菜单。
- PDF.js canvas、单页 fallback 图片和普通图片预览都使用同一入口。

### Modal State

前端 state 新增：

- `resumeConversationAbortController`
- `resumeConversationRequestSequence`
- `resumeConversationResumeId`

每次打开都请求最新记录。快速切换简历或关闭弹窗时取消旧请求；旧响应必须同时通过 sequence 与 `selectedId` 校验，不能覆盖当前候选人。

### Modal DOM

在 `body` 末尾新增唯一顶层容器：

```html
<div id="resumeConversationModal" hidden></div>
```

弹窗结构保持简单：

- 遮罩层。
- 会话面板。
- 固定头部。
- 可滚动消息列表。
- 只读提示底栏。

消息文本一律使用转义后的文本节点，不把聊天内容作为 HTML 注入。

### Accessibility

- 面板使用 `role="dialog"`、`aria-modal="true"` 和明确标题。
- 打开后焦点移动到关闭按钮。
- `Escape` 关闭，关闭后恢复打开前焦点。
- 加载状态使用 `aria-live="polite"`。

## Data Synchronization Boundary

本地功能完成后，服务器部署前增加独立的增量同步流程：

1. 从本地导出 `conversation_sessions`、`conversation_messages` 和需要的 `candidate_status` 增量。
2. 服务器按 session `id` upsert，会话消息按 `session_id + message_hash` 去重。
3. 只更新匹配到同一业务简历的桥接字段，不覆盖服务器简历 payload、审核状态或权限数据。
4. 导入旧 `8080` JSON 时生成独立来源标记；只有唯一“姓名 + 岗位 + 平台/账号证据”匹配才写入 `linked_session_id`。
5. 所有同步先 dry-run，输出新增、更新、跳过、歧义和冲突数量；`--apply` 才写库。
6. 同步前备份服务器 SQLite，禁止整库替换。

第一阶段本地查看功能不依赖该同步脚本完成；同步作为上线 `18080` 前的必做步骤。

## Error Handling

- `403 admin_conversation_forbidden`：member 不显示功能入口，直接调用也被拒绝。
- `403 resume_forbidden`：管理员不在简历可见范围时拒绝。
- `matched=false`：弹窗正常打开并显示“暂未找到明确关联的聊天记录”。
- `conversation_ambiguous`：不展示任何候选会话消息。
- 数据库读取异常：前端显示读取失败，可关闭后重试，不影响简历预览。
- 401 继续复用现有登录失效处理。

## Files Expected To Change

- `app/domain/conversation/service.py`：新增简历会话定位与只读响应服务。
- `app/domain/conversation/repository.py`：增加消息总数和有上限的历史读取。
- `app/api/routes/resumes.py`：新增管理员聊天接口。
- `app/control_plane/main.py`：注入会话仓储与服务。
- `frontend/index.html`：增加顶层弹窗容器并更新 cache-bust。
- `frontend/app.js`：增加右键入口、请求取消、防串候选人和弹窗渲染。
- `frontend/styles.css`：增加方案 A 的弹窗、消息气泡和响应式样式。
- `tests/domain/test_resume_conversation_history.py`：后端服务与接口测试。
- `tests/domain/test_frontend_resume_member_view.py`：前端权限和交互契约测试。
- 后续同步阶段新增 `scripts/sync_conversation_history.py` 及对应测试。

## Test Plan

### Automated

- admin 对有明确关联的简历获得按时间排序的消息。
- member 调用接口返回 403。
- 简历权限检查先于消息返回，隐藏简历不能借接口读取。
- 无会话、断链和多候选会话均不泄露消息。
- 超过 200 条时只返回最新 200 条并标记截断。
- 前端仅 admin 右键拦截默认菜单。
- 快速切换候选人时旧响应不能覆盖新弹窗。
- 关闭、Escape、遮罩点击和 401 状态行为正确。
- `node --check frontend/app.js`、相关 pytest 和 `ruff check app tests` 通过。

### Local Real-data Verification

- 使用本地 `data/resumes.sqlite`，抽样 BOSS、智联、51job 至少各 5 个明确关联会话。
- 验证候选人姓名、岗位、平台和账号与消息内容一致。
- 验证消息左右方向、日期分隔、长文本换行和滚动。
- 连续切换至少 10 份简历，不串消息、不残留旧候选人标题。
- 本地接口目标响应时间小于 `200ms`，右键到弹窗首个可读状态目标小于 `500ms`。

## Deployment Gate

本地实现和真实数据测试通过后：

1. 提交并推送代码。
2. 备份服务器数据库。
3. 先执行会话同步 dry-run，再人工确认歧义报告。
4. 执行 apply，并验证会话/消息/关联数量。
5. 只部署 `18080` 相关代码和前端资源。
6. 重启实际监听 `18080` 的 Python 服务，保持 `8080` 不变。
7. 使用 admin 和 member 各验证一次权限与右键行为。

## Acceptance Criteria

- 只有 admin 在简历预览上右键时出现聊天弹窗。
- 弹窗符合方案 A，简约、只读、可滚动且不会遮挡后留下页面状态变化。
- member 看不到入口，也不能直接调用接口。
- 只展示明确关联会话，歧义匹配绝不自动放行。
- 本地 BOSS、智联、51job 真实会话均可正确展示。
- 服务器上线前完成增量同步，不覆盖服务器简历库。
- 旧 `8080` 完全不修改。
