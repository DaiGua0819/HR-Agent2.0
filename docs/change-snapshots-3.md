# 修改快照记录 3

> 继续记录重构版 HR Agent 的代码修改。单文件控制在 600 行以内。

---

### 快照 0047：面试中心迁移隔离工作树与实施计划

- 修改时间：2026-07-02 19:30:00 +08:00
- 修改原因：
  - 需要在不影响 `main` 当前运行数据和既有业务的前提下迁移面试中心。
  - 旧快照文件 `docs/change-snapshots-2.md` 已有 501 行，继续追加会接近 600 行上限，因此新建第 3 份快照记录。
  - 迁移范围较大，先记录执行计划、测试基线和后续每次修改的快照要求。
- 修改文件：
  - `docs/superpowers/plans/2026-07-02-interview-center-migration.md`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增面试中心迁移实施计划，拆分为存储/schema、多维表路由、日历同步、飞书文档、资产同步、回填、OAuth/status、最终验证 8 个任务。
  - 新增第 3 份修改快照文件，后续本次迁移的代码与配置修改都追加到该文件。
  - 已在隔离工作树 `interview-center-migration` 上开展迁移，避免直接污染主工作区。
- 验证结果：
  - 迁移前基线：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_phase6_interview_center.py -q`：6 passed，1 个既有 StarletteDeprecationWarning。
  - 迁移前全量基线：同一 Python 运行 `-m pytest -q`：247 passed，1 个既有 StarletteDeprecationWarning。
- 风险 / 待确认：
  - 当前可用技能列表中没有名为“快照”的独立 skill；本次沿用项目已有 `docs/change-snapshots-*.md` 快照规范记录。
  - 后续必须按 TDD 红绿循环推进，不能直接先写生产代码。

---

### 快照 0048：补齐面试中心 SQLite 会话、Token 与日志存储

- 修改时间：2026-07-02 22:26:05 +08:00
- 修改原因：
  - 旧面试中心依赖 `interview_sessions` 按 `feishu_event_id` 幂等同步飞书日历事件，当前 Python 版只有轻量会话字段，无法承接日历同步。
  - 旧面试中心把飞书 OAuth user token 存在 `interview_feishu_tokens`，并把同步、跳过、失败等动作写入 `interview_logs`；当前服务缺少这两个持久化边界。
  - 迁移需要先补齐存储层，并保持既有 Phase6/Phase7a API 不破坏。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/db/schema.sql`
  - `app/db/engine.py`
  - `app/features/interview_center/store.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增红灯测试覆盖日历事件按 `feishuEventId` upsert、飞书 token 保存/读取/清除、面试日志写入/倒序查询。
  - 扩展 `interview_sessions`，增加飞书日程、时间、问题包、飞书文档、多维表资产、评价、回填源、回填次数等旧逻辑需要的字段。
  - 新增 `interview_feishu_tokens` 和 `interview_logs` 表及索引。
  - `SQLiteInterviewStore` 与 `InMemoryInterviewStore` 同步支持 `upsert_from_calendar_event()`、`save_token()`、`get_token()`、`clear_token()`、`append_log()`、`list_logs()`。
  - 保留原有 `create/save/get/list/save_interview_session` 入口，旧轻量流程仍可用。
- 验证结果：
  - 红灯确认：新增测试初次运行 3 failed，均为 `SQLiteInterviewStore` 缺少 `upsert_from_calendar_event/save_token/append_log`。
  - 修复后：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`：3 passed。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：13 passed，1 个既有 StarletteDeprecationWarning。
- 风险 / 待确认：
  - 当前只完成存储层迁移，日历客户端、Bitable 路由、飞书文档、回填逻辑仍待后续任务接入。
  - 真实线上库迁移已使用幂等补列，但最终上线前仍需对服务器数据库副本跑一次只读/副本迁移验证。

---

### 快照 0049：迁移面试中心 Bitable 路由与幂等匹配 helper

- 修改时间：2026-07-02 22:36:55 +08:00
- 修改原因：
  - 旧面试中心会根据候选人岗位、日程标题、会话描述等文本选择不同飞书多维表；当前 Python 版只有固定 mock 表名，无法把 AI、HR、运营B 等岗位写到旧系统对应表。
  - 旧面试中心写入多维表前会先按手机号匹配已有记录，再按唯一姓名匹配，同名多条必须跳过，避免重复创建或误写候选人记录；当前 Python 版缺少该幂等匹配边界。
  - 旧面试中心真实写入飞书时会过滤不存在的字段，避免因为表结构差异导致整次写入失败；当前 Python 版缺少可复用字段过滤 helper。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/routes.py`
  - `app/features/interview_center/feishu/bitable.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `BitableRoute`、`BitableTarget`、`DEFAULT_BITABLE_TABLE_ROUTES`、`resolve_bitable_target()`，迁移旧系统默认表 ID 和关键词路由。
  - 新增 `ExistingBitableRecord`、`find_existing_bitable_record()`，实现手机号优先、唯一姓名命中、同名歧义跳过。
  - 新增 `pick_existing_bitable_fields()`，只保留目标表字段图中存在且非空的字段。
  - 新增测试覆盖 AI/HR/运营B 路由、手机号优先、唯一姓名、同名歧义、字段过滤。
- 验证结果：
  - 红灯确认：新增测试初次运行失败，原因是 `find_existing_bitable_record` 等 Task 2 接口尚不存在。
  - 修复后：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`：8 passed。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：21 passed，1 个既有 StarletteDeprecationWarning。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/feishu/routes.py app/features/interview_center/feishu/bitable.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/feishu/routes.py app/features/interview_center/feishu/bitable.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 当前完成的是路由、匹配、字段过滤的纯逻辑边界；后续 Task 5 需要把这些 helper 接入真实资产同步写入路径。
  - 旧系统支持环境变量覆盖 Bitable 路由，本轮暂按迁移计划落地默认路由；如线上仍依赖自定义路由，后续 OAuth/status 或配置兼容阶段需要补环境变量解析。

---

### 快照 0050：迁移面试中心日历同步与自动候选人匹配骨架

- 修改时间：2026-07-02 22:47:23 +08:00
- 修改原因：
  - 旧面试中心通过 `/api/interview-center/sync` 拉取飞书日历、标准化事件、按 `feishuEventId` 幂等写入 session，并只对面试类日程做候选人自动匹配；当前 Python 版缺少该同步入口。
  - 旧系统返回 `/sync/status`、同步结果、日志和面试类 session 列表，前端依赖这些旧接口形状。
  - 迁移需要先接入日历同步骨架，后续再继续接自动准备文档、资产同步和回填。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/calendar.py`
  - `app/features/interview_center/calendar_sync.py`
  - `app/features/interview_center/candidate_matcher.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `normalize_calendar_event()` 与面试类事件识别，保留旧字段：`calendarId`、`feishuEventId`、`title`、`description`、`location`、`attendees`、`meetingUrl`、`startTime`、`endTime`、`isInterviewLike`、`status`。
  - 新增 `CalendarSyncService`，支持拉取事件、幂等 upsert、面试类过滤、全局日志、同步状态和旧结果 payload。
  - 在 `candidate_matcher.py` 新增日历事件候选人评分与自动绑定决策，支持唯一姓名命中、高置信分数和歧义状态。
  - `InterviewCenterService` 新增 `sync_calendar()` 与 `calendar_sync_status()`；`app/api/routes/interview.py` 新增 `POST /api/interview-center/sync` 和 `GET /api/interview-center/sync/status`。
  - 新增测试覆盖事件标准化、同步 upsert、自动匹配、非面试日程不进入结果、旧 API 兼容返回。
- 验证结果：
  - 红灯确认：新增测试初次运行失败，原因是 `app.features.interview_center.feishu.calendar` 模块不存在；修正测试导入后继续由新增模块和接口补齐。
  - 修复后：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`：11 passed，1 个既有 StarletteDeprecationWarning。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：24 passed，1 个既有 StarletteDeprecationWarning。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/feishu/calendar.py app/features/interview_center/calendar_sync.py app/features/interview_center/candidate_matcher.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/feishu/calendar.py app/features/interview_center/calendar_sync.py app/features/interview_center/candidate_matcher.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 当前 `EmptyCalendarClient` 是安全默认空实现；真实 OAuth 用户 token 驱动的飞书日历 HTTP client 将在后续 OAuth/status 兼容阶段接入。
  - 本轮按计划先保留 `autoPrepare` 参数但不执行文档准备，Task 4 会实现真正的 prepare session 和飞书 docx 边界。
  - 本轮未触发 Bitable 简历图同步，Task 5 会把路由和幂等记录匹配接入资产同步。

---

### 快照 0051：迁移面试中心 Prepare Session 与飞书 Docx 边界

- 修改时间：2026-07-02 22:56:13 +08:00
- 修改原因：
  - 旧面试中心在准备面试时要求 session 已绑定候选人简历，然后生成问题包并写入飞书 Docx；当前 Python 版只有创建 session 时同步生成问题，缺少旧 `/prepare` 路径。
  - 旧系统在飞书文档创建失败时不会丢弃本地问题包，而是保留 `prepared_local` 状态和错误信息；当前服务缺少该降级状态。
  - 迁移需要先建立可 mock 的 Docx 边界，后续再替换成真实飞书文档读写。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/docx.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `InterviewDocClientProtocol`、`MockInterviewDocClient`、`build_interview_document_text()`，提供 dry-run 安全文档创建边界。
  - `InterviewCenterService` 新增 `doc_client` 注入和 `prepare_session()`，实现绑定校验、加载简历、生成/复用 `questionSet`、写入 `feishuDoc`、失败时保存 `prepared_local`。
  - `app/api/routes/interview.py` 新增 `POST /api/interview-center/sessions/{session_id}/prepare`，未绑定简历返回 409，session/简历不存在返回 404。
  - 新增测试覆盖未绑定拒绝、问题包生成、飞书文档保存、文档失败保留本地状态和旧 prepare API 路由。
- 验证结果：
  - 红灯确认：新增测试初次运行 4 failed，原因是 `InterviewCenterService.__init__()` 尚不支持 `doc_client`，prepare 入口未实现。
  - 修复后：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`：15 passed，1 个既有 StarletteDeprecationWarning。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：28 passed，1 个既有 StarletteDeprecationWarning。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/feishu/docx.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/feishu/docx.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 当前 `MockInterviewDocClient` 只提供 dry-run/mock 文档元数据；真实飞书 Docx 创建、正文块写入和失败补写会在后续 OAuth/status 与文档客户端完善阶段接入。
  - 当前 prepare 不自动更新 Bitable 记录；Task 5 会接入资产同步和目标表记录写入。

---

### 快照 0052：迁移面试中心 Bitable 资产同步服务

- 修改时间：2026-07-02 23:03:51 +08:00
- 修改原因：
  - 旧面试中心会把简历长截图、面试记录图、技能评价/复试评价文档写回路由后的飞书多维表，并在已有附件或文档链接时跳过重复写入；当前 Python 版缺少这条独立资产同步边界。
  - 旧系统会先按候选人手机号/姓名查找记录，并在岗位与目标表不匹配时跳过，避免写错表或重复创建记录。
  - 后续 backfill 需要复用统一资产同步服务，把面试评价产物回写到 Bitable。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/asset_sync.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `BitableAssetSync`，提供 `ensure_resume_image()`、`ensure_interview_record_image()`、`ensure_evaluation_document()`。
  - 资产同步复用 Task 2 的 `resolve_bitable_target()` 和 `find_existing_bitable_record()`，支持已有附件跳过、歧义姓名跳过、默认表岗位 guard、上传后创建/更新记录。
  - 支持字段：`简历`、`面试记录`、`技能评价`、`复试结果评价`；复试场景写入 `复试结果评价` 并保存到 `bitable_second_interview_evaluation_document`。
  - `InterviewCenterService` 组合 `BitableAssetSync`，供后续 backfill/prepare 流程复用。
  - 新增测试覆盖已有简历附件跳过、上传后创建记录、默认表岗位不匹配拦截、复试评价字段选择。
- 验证结果：
  - 红灯确认：新增测试初次运行失败，原因是 `app.features.interview_center.asset_sync` 模块不存在。
  - 修复后：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`：19 passed，1 个既有 StarletteDeprecationWarning。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：32 passed，1 个既有 StarletteDeprecationWarning。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/asset_sync.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/asset_sync.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 当前真实 Bitable 字段过滤仍以 Task 2 helper 为边界，`BitableAssetSync` 直接使用当前 client 写入；后续真实 HTTP client 接入字段列表后需要在写入路径统一调用字段过滤。
  - 当前资产同步服务已组合到主服务，但 backfill 尚未调用；Task 6 会把评价生成、source 收集、resume update 与 Bitable 资产同步串起来。

---

### 快照 0053：迁移面试中心 Backfill 来源收集与评价回填核心链路

- 修改时间：2026-07-02 23:14:48 +08:00
- 修改原因：
  - 旧面试中心在面试结束 10 分钟后读取飞书会议/妙记来源，生成面试评价，写回 session 和简历库，并进入人工复核状态；当前 Python 版只有简单 feedback-backfill。
  - 旧系统要求无有效来源时保存失败状态，不应生成空评价；有有效来源时需要调用 Bitable 资产同步。
  - 旧前端依赖 `/backfill`、`/backfill-source`、`/backfill/status` 这些旧接口。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/meeting.py`
  - `app/features/interview_center/backfill.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `MeetingSourceClientProtocol` 与 `EmptyMeetingSourceClient`，为后续真实飞书 VC/妙记来源读取提供可替换边界。
  - 新增 `BackfillService`，实现 10 分钟保护、空 source 失败、评价生成、session 持久化、简历库 `interviewEvaluation` 更新、资产同步调用、backfill 状态。
  - `InterviewCenterService` 新增 backfill 注入项和 `backfill_session()`、`backfill_status()`、`backfill_source()`。
  - `app/api/routes/interview.py` 新增 `POST /api/interview-center/sessions/{session_id}/backfill`、`GET /api/interview-center/sessions/{session_id}/backfill-source`、`GET /api/interview-center/backfill/status`。
  - 新增测试覆盖 10 分钟保护、空来源失败、评价持久化、简历库更新、资产同步调用和旧 API 兼容。
- 验证结果：
  - 红灯确认：新增测试初次运行 4 failed，原因是 `InterviewCenterService.__init__()` 尚不支持 `meeting_client` 等 backfill 依赖。
  - 修复后：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`：23 passed，1 个既有 StarletteDeprecationWarning。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：36 passed，1 个既有 StarletteDeprecationWarning。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/backfill.py app/features/interview_center/feishu/meeting.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/backfill.py app/features/interview_center/feishu/meeting.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 当前 `EmptyMeetingSourceClient` 是安全空实现；真实飞书会议/妙记 source 收集需要在 OAuth/status 兼容阶段接入用户 token HTTP client。
  - 当前评价生成器是保守本地 fallback；后续需要替换为旧 `feedbackBackfill.js` 同等 LLM 评价结构。
  - 本轮完成 backfill 核心链路，人工 review/confirm 旧路由仍需继续补齐。
---

### 快照 0054：迁移面试中心飞书 OAuth 与状态兼容接口

- 修改时间：2026-07-02 23:27:26 +08:00
- 修改原因：
  - 旧面试中心前端依赖 `/api/interview-center/feishu/auth-url`、`/api/interview-center/feishu/oauth/callback`、`/api/interview-center/feishu/status`、`/api/interview-center/feishu/disconnect` 四个飞书授权与连接状态接口。
  - 当前 Python 版 OAuth 服务此前只保留占位 URL/callback，未持久化用户 token，也未返回旧前端需要的授权 scope、连接状态和 Bitable 路由信息。
  - 后续真实日历、文档、会议/妙记读取都需要复用同一个用户 token 存储边界，因此本轮先补齐 store-backed OAuth 兼容层。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/oauth.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增旧 Node 版一致的默认飞书 OAuth scopes，授权 URL 返回 `authUrl`、`state`、`configured`、`redirectUri`。
  - 新增可注入的 `FeishuOAuthHttpClientProtocol` 与真实 `FeishuOAuthHttpClient`，支持 code 换 user access token、读取 user info，并通过 store 保存/读取/清理 token。
  - `InterviewCenterService` 组合 store-backed `FeishuOAuthService`，测试可注入 fake OAuth client，运行时默认使用真实飞书 HTTP client。
  - `app/api/routes/interview.py` 新增旧前端兼容的 `/api/interview-center/feishu/*` 授权、回调、状态和断开连接接口，同时保留原有 `/api/interview-center/oauth/*` 路径。
  - 新增测试覆盖授权 URL scope、OAuth callback 持久化 token、status/disconnect 使用已保存 token。
- 验证结果：
  - 红灯确认：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q` 初次运行 3 failed，原因是 `InterviewCenterService.__init__()` 尚不支持 `oauth_client`。
  - 修复后目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：26 passed，1 个既有 StarletteDeprecationWarning。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：39 passed，1 个既有 StarletteDeprecationWarning。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/feishu/oauth.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/feishu/oauth.py app/features/interview_center/service.py app/api/routes/interview.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 当前 OAuth token 已入库，但日历、Docx、VC/妙记等真实 HTTP client 仍需继续接入该 token。
  - 真实飞书接口错误码映射目前只做了基础异常抛出，后续联调时需要按旧前端提示文案细化。
---

### 快照 0055：迁移面试中心最终回归与 18080 运行验证

- 修改时间：2026-07-02 23:45:23 +08:00
- 修改原因：
  - Task 8 要求在迁移功能接入后运行全量回归、静态检查、编译检查，并启动本地 18080 服务验证旧面试中心接口。
  - 全仓 `ruff check app tests` 发现 `tests/domain/test_frontend_resume_member_view.py` 中 5 处既有超长行，需做纯格式换行，确保最终静态门禁可通过。
  - 本轮验证需使用临时 SQLite 数据库启动本地服务，避免污染已有 `data/` 运行数据。
- 修改文件：
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 将前端简历成员视图测试中的长链式表达式和长断言拆成多行，保持断言内容和测试语义不变。
  - 用 `CONTROL_PLANE_PORT=18080`、临时 `DATABASE_PATH=%TEMP%\hr-agent-interview-center-smoke.sqlite` 启动本地 FastAPI 服务，完成后关闭进程并删除临时数据库文件。
  - 通过本地 HTTP smoke test 验证 `/health`、`/api/interview-center/sessions`、`/api/interview-center/sync/status`、`POST /api/interview-center/sync`、`/api/interview-center/backfill/status`、`/api/interview-center/feishu/auth-url`、`/api/interview-center/feishu/status`、`POST /api/interview-center/feishu/disconnect` 均返回 200。
- 验证结果：
  - 迁移回归：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py -q`：32 passed，1 个既有 StarletteDeprecationWarning。
  - 全量回归：同一 Python 运行 `-m pytest -q`：273 passed，1 个既有 StarletteDeprecationWarning。
  - 格式修复后目标验证：同一 Python 运行 `-m pytest tests/domain/test_frontend_resume_member_view.py -q`：50 passed。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 本地运行：18080 端口启动成功，HTTP smoke test 覆盖旧面试中心核心状态/同步/飞书授权接口，完成后端口已释放。
- 风险 / 待确认：
  - 本轮 18080 smoke test 使用临时空库验证路由和默认安全空实现；真实飞书日历、Docx、VC/妙记联调仍需要有效 OAuth token 和飞书线上权限。
  - `/health` 中 worker 状态因本轮未启动 worker 进程而显示 unavailable，不影响面试中心 API smoke test。

---

### 快照 0056：接入面试中心飞书用户 Token 与真实客户端边界

- 修改时间：2026-07-03 00:03:23 +08:00
- 修改原因：
  - Task 8 后面试中心仍使用 `EmptyCalendarClient`、`MockInterviewDocClient` 等安全空/mock 边界，无法复用已入库的飞书 OAuth 用户 token 拉取日历或创建面试文档。
  - 旧 Node 面试中心会在用户 token 临近过期时刷新 token，并用该 token 调用 `/calendar/v4/calendars/{calendarId}/events` 分页读取日历事件；Python 版需要补齐同等边界。
  - 飞书 Docx 写入必须保留 dry-run 安全保护，测试和调用方需要能显式注入 dry-run，避免被全局 settings 缓存影响。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/client.py`
  - `app/features/interview_center/calendar_sync.py`
  - `app/features/interview_center/feishu/docx.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `FeishuStoredUserTokenProvider`，从面试中心 store 读取用户 token，临近过期时通过 `FeishuAuthClient.refresh_token()` 刷新并回写 store。
  - `FeishuAuthClient` 新增 app access token 与 OAuth refresh token 调用，作为用户 token 刷新的默认真实 HTTP client。
  - 新增 `FeishuCalendarClient`，使用 OAuth 用户 token 调用飞书日历事件接口，支持 `page_token` 分页、无 token 安全跳过和可注入 `httpx` transport。
  - 新增 `FeishuInterviewDocClient`，dry-run 时只记录意图并返回文档元数据；非 dry-run 时创建飞书 Docx 并写入文本块，保留内容写入失败信息。
  - `InterviewCenterService` 默认组合 store-backed 用户 token provider，并将默认日历/文档边界切到真实飞书客户端；测试或调用方传入的注入对象仍优先生效。
  - 新增测试覆盖用户 token 刷新持久化、飞书日历分页读取和 Docx dry-run 不触网。
- 验证结果：
  - 红灯确认：新增 Docx dry-run 测试曾复现 1 failed，原因是客户端只读全局 `is_dry_run()`，在 settings 已缓存后仍尝试访问飞书 Docx 网络接口。
  - 目标验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q`：29 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：42 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/feishu/client.py app/features/interview_center/calendar_sync.py app/features/interview_center/feishu/docx.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/feishu/client.py app/features/interview_center/calendar_sync.py app/features/interview_center/feishu/docx.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 当前已接入日历与 Docx 真实 HTTP 边界，但真实 VC/妙记来源读取、真实 Bitable 上传/字段过滤仍需后续继续迁移和联调。
  - 飞书真实接口的错误码映射目前只做基础异常抛出，后续联调时还需要按旧前端提示文案细化错误返回。

---

### 快照 0057：迁移面试中心飞书会议与妙记来源收集

- 修改时间：2026-07-03 00:14:09 +08:00
- 修改原因：
  - 旧 Node 面试中心 backfill 会从飞书面试文档、关联 Docx、日程关联会议、会议纪要 Doc、会议录制妙记和妙记转录中收集面试文本；当前 Python 版仍使用 `EmptyMeetingSourceClient`，真实回灌无法读取有效来源。
  - 既有 OAuth 用户 token 已入库，meeting/minutes/source 边界需要复用同一个 store-backed token provider，并在缺 token 时安全返回空来源，避免破坏现有 backfill 流程。
  - 回灌来源结构需要继续兼容旧前端需要的 `types`、`rawTextLength`、`linkedDocIds`、`minuteTokens`、`meetingNoteIds`、`sources` 和 `errors`。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/meeting.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `FeishuMeetingSourceClient`，使用 OAuth 用户 token 收集飞书面试来源，支持可注入 `httpx` transport 便于测试。
  - 支持读取主面试 Docx、描述/会议链接中的关联 Docx 与 Minutes token、飞书日程关联会议、会议详情 note_id、会议纪要 artifact Docx、会议录制里的 Minutes token，以及会议/妙记搜索兜底。
  - 新增 transcript payload 解析、Docx block 文本解析、source token 提取、来源去重和 RFC3339 搜索时间窗等 helper。
  - `InterviewCenterService` 默认将 backfill 的 meeting client 切换为 `FeishuMeetingSourceClient(token_provider=self.user_token_provider)`；测试传入的 fake meeting client 仍优先生效。
  - 新增测试覆盖真实来源收集聚合和缺用户 token 时不触网安全跳过。
- 验证结果：
  - 红灯确认：新增测试初次运行因 `FeishuMeetingSourceClient` 不存在而 collection error；随后校正测试中不符合旧正则的 Docx token 形状后，新测试稳定覆盖目标行为。
  - 新增切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "feishu_meeting_source_client"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：31 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：44 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/feishu/meeting.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/feishu/meeting.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 真实飞书 VC/Minutes 接口的字段形状可能存在租户差异，当前实现按旧 Node 兼容字段解析；线上联调时需根据实际响应继续补充字段映射。
  - Bitable 真实附件上传和字段列表过滤仍未完全替换 mock/pending 边界，是后续迁移的主要剩余缺口。

---

### 快照 0058：迁移面试中心 Bitable 真实字段过滤与附件上传

- 修改时间：2026-07-03 00:26:01 +08:00
- 修改原因：
  - 旧 Node 面试中心写入 Bitable 前会分页读取目标表字段，只保留真实存在且非空的字段，避免因为线上表结构差异导致整次写入失败；当前 Python `FeishuBitableClient` 直接提交原始字段。
  - 旧 Node 会通过 `drive/v1/medias/upload_all` 上传简历长图和面试总结图，并拿到真实 `file_token` 写入附件字段；当前 Python 仍返回 `pending-real-upload:*`。
  - 服务默认 Bitable 边界仍固定为 mock，导致配置齐全的本地/线上服务无法自动使用真实飞书 Bitable client。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/feishu/bitable.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `FeishuBitableClient` 新增可注入 `transport` 和显式 `dry_run`，便于测试和运行时安全控制。
  - 新增 `list_fields()`，按旧逻辑分页读取字段并缓存 `byName` 字段图；`create_record()` 和 `update_record()` 写入前统一调用 `pick_existing_bitable_fields()` 过滤字段。
  - `list_records()` 改为分页读取记录，并带上 `user_id_type=open_id`，兼容旧面试中心读取方式。
  - `upload_file()` 改为真实 multipart 上传到 `/drive/v1/medias/upload_all`，图片优先使用 `bitable_image`，失败后可回退 `bitable_file`，返回真实 `file_token`。
  - `InterviewCenterService` 默认 Bitable client 改为配置齐全时使用 `FeishuBitableClient`，未配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_BITABLE_APP_TOKEN` 时继续使用 `MockFeishuBitableClient`，避免影响本地未配置环境。
  - 新增测试覆盖字段分页过滤后创建记录、Drive media 附件上传、配置齐全时服务默认启用真实 Bitable client。
- 验证结果：
  - 红灯确认：新增 Bitable 测试初次运行 2 failed，原因是 `FeishuBitableClient` 不支持 `transport/dry_run` 且上传仍为 pending；服务默认注入测试初次运行 1 failed，原因是配置齐全时仍使用 mock。
  - 新增切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "feishu_bitable_client or real_bitable_client_when_configured"`：3 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：34 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：47 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app/features/interview_center/feishu/bitable.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/features/interview_center/feishu/bitable.py app/features/interview_center/service.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - multipart 上传已按旧 Node 参数实现，仍需用真实飞书租户做一次端到端联调，确认 `bitable_image` / `bitable_file` 在当前应用权限下均可用。
  - 默认真实 Bitable 仅在配置齐全时启用；若线上环境缺少任一飞书配置，服务会保守回落到 mock，需要部署前检查环境变量。

---

### 快照 0059：迁移面试中心人工复核与日志兼容路由

- 修改时间：2026-07-03 00:33:55 +08:00
- 修改原因：
  - 旧 Node 面试中心支持 `/api/interview-center/sessions/{id}/review`、`/confirm` 和 `/api/interview-center/logs`，旧前端会在回灌后通过这些接口完成人工复核、确认和查看操作日志；当前 FastAPI 版缺少这些入口。
  - 旧 `review/confirm` 会同步更新 session 状态、`interviewEvaluation.review`、`humanReview`，并把最新 `interviewEvaluation` 写回简历库；Python 版此前只停留在 `needs_review`。
  - 旧前端依赖 session 响应里的顶层 `humanReview` 字段，需要在不改 SQLite schema 的前提下兼容该响应形状。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/store.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `InterviewCenterService` 新增 `review_session()`，规范化 `passed/rejected/need_followup` 决策，按旧逻辑将 `need_followup` 保持为 `needs_review`，其他决策置为 `completed`。
  - review 会更新 session 的 `interview_evaluation.review`、`humanReviewRequired`、`reviewedAt`，并把同一份 `interviewEvaluation` 回写到绑定简历记录。
  - `InterviewSession.to_dict()` 新增旧前端兼容顶层 `humanReview`，数据存放在 `payload["humanReview"]`，避免新增数据库列。
  - `app/api/routes/interview.py` 新增 `POST /review`、`POST /confirm` 和 `GET /logs`，其中 confirm 复用 review 行为，logs 支持 `sessionId` 和 `limit`。
  - 新增测试覆盖 service review 持久化、resume 回写、API review/confirm/logs 兼容返回和日志记录。
- 验证结果：
  - 红灯确认：新增测试初次运行 2 failed，原因是 `InterviewCenterService.review_session` 不存在且 `/review` API 返回 404。
  - 新增切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "review_session or review_confirm"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：36 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：49 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app/api/routes/interview.py app/features/interview_center/service.py app/features/interview_center/store.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/api/routes/interview.py app/features/interview_center/service.py app/features/interview_center/store.py tests/features/test_interview_center_migration.py`：通过。
- 风险 / 待确认：
  - 本轮补齐的是人工复核和日志兼容入口；旧 Node 的自动 calendar/backfill scheduler 仍是后续端到端运行审计时需要确认的剩余差异。
  - 当前 `humanReview` 通过 payload 兼容输出，若后续前端需要按字段查询/筛选人工复核状态，再考虑新增持久化列。

---

### 快照 0060：补齐面试中心手动绑定与会话列表兼容

- 修改时间：2026-07-03 00:45:10 +08:00
- 修改原因：
  - 旧 Node 面试中心提供 `POST /api/interview-center/sessions/{id}/bind`，旧前端通过该入口把日历面试手动绑定到简历；当前 FastAPI 版缺少该路由，调用会返回 404。
  - 旧前端刷新会话列表时读取 `payload.sessions`，而当前 FastAPI `GET /api/interview-center/sessions` 只返回 `items`，会导致旧面试中心页面拿不到会话列表。
  - 旧 store 会把 session payload 展平到响应顶层，前端直接读取 `resume`、`matchedResume`、`matchMode`、`manualBoundAt`、`isInterviewLike` 等字段；当前响应只把这些放在 `payload` 里，手动绑定后旧页面仍可能显示未绑定。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/store.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `InterviewSession.to_dict()` 改为旧 store 兼容的 payload 展平输出，同时让数据库核心列字段覆盖 payload 中可能存在的旧值。
  - `InterviewCenterService` 新增 `bind_session()`，校验 session 与简历，写入 `resumeId`、`resume`、`matchedResume`、`matchMode=manual`、`manualBoundAt`，并记录“已人工绑定候选人”日志；传入 `prepare=true` 时继续复用 `prepare_session()`。
  - `list_sessions()` 支持 `start_time`、`end_time`、`status` 过滤，并默认跳过明确标记为 `isInterviewLike=false` 的非面试日程，避免旧页面混入普通会议。
  - `app/api/routes/interview.py` 新增 `POST /api/interview-center/sessions/{session_id}/bind`；`GET /api/interview-center/sessions` 改为返回 `ok`、`status`、`sessions`、`items` 和 `logs`，保留当前 `items` 兼容。
  - 新增测试覆盖 service 手动绑定持久化、旧 API bind 返回、旧 API sessions 返回和非面试日程过滤。
- 验证结果：
  - 红灯确认：新增切片测试首次运行 2 failed，原因是 `InterviewCenterService.bind_session` 不存在且 `/api/interview-center/sessions/{id}/bind` 返回 404。
  - 新增切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "bind_session or bind_and_sessions"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：38 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮补齐旧页面立即依赖的绑定和列表响应；自动 calendar/backfill scheduler 仍需继续审计并补齐状态与 tick 行为。
  - sessions 响应保留 `items`，同时新增旧前端使用的 `sessions`，若后续有新前端按 `items` 读取仍可兼容。

---

### 快照 0061：迁移面试中心自动同步与自动回灌 Scheduler

- 修改时间：2026-07-03 00:54:06 +08:00
- 修改原因：
  - 旧 Node 面试中心在服务启动后会自动启动飞书日历同步 scheduler 和面试回灌 scheduler，并通过 `/sync/status`、`/backfill/status` 暴露 `enabled`、`running`、`intervalMs`、`lastRunAt`、`lastError` 等状态；当前 FastAPI 版只有手动 sync/backfill 和简化状态。
  - 旧自动日历同步在飞书未授权时会安全跳过并记录 `lastError`，不能触发真实日历请求；当前 Python 版没有自动 tick 入口。
  - 旧自动回灌会筛选已绑定简历、已有飞书面试文档、已过 10 分钟保护期、未生成评价且未超过最大尝试次数的面试 session，并按结束时间排序、限制每轮处理数量；当前 Python 版没有这一自动候选筛选与限流行为。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/calendar_sync.py`
  - `app/features/interview_center/backfill.py`
  - `app/features/interview_center/service.py`
  - `app/control_plane/main.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `CalendarSyncService` 新增旧 scheduler 兼容的 `enabled`、`intervalMs` 状态字段，并读取 `INTERVIEW_CALENDAR_SYNC_ENABLED` / `INTERVIEW_CALENDAR_SYNC_INTERVAL_MS`。
  - `BackfillService` 新增自动回灌状态字段、`auto_candidates()` 和 `run_auto_tick()`，支持 `INTERVIEW_AUTO_BACKFILL_ENABLED`、`INTERVIEW_BACKFILL_INTERVAL_MS`、`INTERVIEW_BACKFILL_MAX_PER_TICK`、`INTERVIEW_BACKFILL_MAX_ATTEMPTS`，并返回 `lastProcessed`、`inFlightSessionIds`、`pendingCount`。
  - `InterviewCenterService` 新增 `run_auto_calendar_sync_tick()`、`run_auto_backfill_tick()`、`start_schedulers()`、`stop_schedulers()` 和 `scheduler_running`，自动日历同步在飞书未连接时只记录 `lastError` 并跳过。
  - `create_app()` 改用 FastAPI lifespan 在本地服务启动/关闭时启动并取消面试中心 scheduler，避免 `on_event` 弃用警告和后台任务泄漏。
  - 新增测试覆盖未授权自动日历同步跳过、自动回灌候选筛选/排序/maxPerTick 限制，以及后台 scheduler 能启动、自动 tick 并停止。
- 验证结果：
  - 红灯确认：新增 scheduler 切片测试首次运行 2 failed，原因是 `run_auto_calendar_sync_tick` / `run_auto_backfill_tick` 不存在；新增后台 scheduler 测试首次运行 1 failed，原因是 `start_schedulers` 不存在。
  - 新增切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "auto_calendar_tick or auto_backfill_tick or schedulers_start"`：3 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：41 passed，1 个既有 `StarletteDeprecationWarning`。
  - 警告修复验证：首次用 `@app.on_event` 接入时新增 FastAPI deprecation warnings；改为 lifespan 后重跑同一迁移测试，警告恢复为仅 1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：54 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app/api/routes/interview.py app/control_plane/main.py app/features/interview_center/calendar_sync.py app/features/interview_center/backfill.py app/features/interview_center/service.py app/features/interview_center/store.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/api/routes/interview.py app/control_plane/main.py app/features/interview_center/calendar_sync.py app/features/interview_center/backfill.py app/features/interview_center/service.py app/features/interview_center/store.py tests/features/test_interview_center_migration.py`：通过。
  - 空白检查：`git diff --check` 无空白错误，仅 Windows 换行提示。
- 风险 / 待确认：
  - 自动 scheduler 已在 FastAPI lifespan 中启停；真实环境仍需用有效飞书 OAuth token 观察自动日历同步和自动回灌的端到端效果。
  - 当前自动日历 tick 遵循旧逻辑，在未授权时只更新 `lastError` 并跳过，不会写入日志；如果运营侧需要可见日志，再单独补充。

---

### 快照 0062：修复面试中心飞书状态响应并完成 18080 Smoke

- 修改时间：2026-07-03 01:02:14 +08:00
- 修改原因：
  - 本地 18080 HTTP smoke 发现 `GET /api/interview-center/feishu/status` 虽返回 200，但响应只包含 OAuth status，缺少旧 Node 响应里的 `ok: true` 和 `calendarSync`，旧前端无法统一按 `ok` 判断状态，也拿不到日历同步状态。
  - 旧 Node `handleStatus()` 返回 `{ ok: true, ...feishu.getStatus(), calendarSync: calendarSyncStatusPayload() }`，FastAPI 版需要补齐同样形状。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 扩展 `test_feishu_status_and_disconnect_use_stored_token()`，要求 `/feishu/status` 响应包含 `ok` 和 `calendarSync.enabled`。
  - `GET /api/interview-center/feishu/status` 改为返回 `ok: true`、OAuth 状态和 `calendarSync` 状态。
  - 使用临时 SQLite 数据库启动本地 18080 服务完成旧面试中心核心 HTTP smoke；完成后关闭服务并删除临时数据库。
- 验证结果：
  - 红灯确认：扩展后的 Feishu status 测试首次运行 1 failed，原因是响应缺少 `ok`。
  - 新增切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "feishu_status_and_disconnect"`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：54 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app/api/routes/interview.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/api/routes/interview.py tests/features/test_interview_center_migration.py`：通过。
  - 本地运行：用 `CONTROL_PLANE_PORT=18080` 和临时 `DATABASE_PATH=%TEMP%\hr-agent-interview-center-smoke-18080.sqlite` 启动服务，HTTP smoke 覆盖 `/health`、`/api/interview-center/sessions`、`/api/interview-center/sync/status`、`POST /api/interview-center/sync`、`/api/interview-center/backfill/status`、`/api/interview-center/feishu/auth-url`、`/api/interview-center/feishu/status`、`POST /api/interview-center/feishu/disconnect`，全部返回 200；其中 `/feishu/status` 已返回 `ok,configured,connected,userInfo,expiresAt,bitableRoutes,calendarSync`。
  - 清理验证：18080 服务已关闭，临时 SQLite 数据库已删除。
- 风险 / 待确认：
  - 本轮 smoke 使用空临时库和当前本地飞书配置验证路由形状；真实 OAuth token、真实日历事件、Docx、VC/妙记、Bitable 写入仍需在有授权的环境里做端到端联调。
---

### 快照 0063：迁移面试中心前端入口与 OAuth HTML 回跳

- 修改时间：2026-07-03 01:16:04 +08:00
- 修改原因：
  - 旧 Node 面试中心前端依赖 `/interview-center.html` 作为可直接打开的页面入口，并通过 `/assets/interview-center/*` 加载拆分后的脚本与样式；当前 FastAPI 版本只有占位 HTML 且未暴露该页面入口。
  - 旧飞书 OAuth callback 面向浏览器默认返回 HTML，并在授权成功后跳回 `/interview-center.html?feishu=connected`；当前 FastAPI callback 默认返回 JSON，会导致旧页面授权完成后不能按原流程回到面试中心。
  - 仍需保留测试和 API 调用方使用 `Accept: application/json` 时的 JSON callback 行为，避免影响已有接口契约。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `app/control_plane/main.py`
  - `frontend/interview-center.html`
  - `frontend/interview-center/api.js`
  - `frontend/interview-center/state.js`
  - `frontend/interview-center/app.js`
  - `frontend/interview-center/styles.css`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 将旧面试中心前端结构迁入 `frontend/interview-center.html`，并将资源路径调整为 FastAPI 静态挂载下的 `/assets/interview-center/*`。
  - 从旧 Node 项目迁入 `api.js`、`state.js`、`app.js`、`styles.css`，保留旧页面的日历流、工作区、手动绑定、准备问题、回灌和复核交互入口。
  - `create_app()` 新增 `GET /interview-center.html`，返回迁移后的页面文件；现有 `/assets` 静态挂载继续负责脚本和样式。
  - `/api/interview-center/feishu/oauth/callback` 改为 `Accept: application/json` 时返回 JSON；浏览器默认请求时返回旧前端兼容 HTML，成功后执行 `location.replace('/interview-center.html?feishu=connected')`，失败时显示返回面试中心链接。
  - 路由显式设置 `response_model=None`，避免 FastAPI 将 `dict | HTMLResponse` 解析为 Pydantic response model。
- 验证结果：
  - 红灯确认：新增前端入口与旧 OAuth HTML callback 测试首次运行 2 failed，原因分别是 callback 返回 `application/json` 而非 HTML、`/interview-center.html` 返回 404。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "old_html_redirect or frontend_page"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：43 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：56 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app/api/routes/interview.py app/control_plane/main.py tests/features/test_interview_center_migration.py`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app/api/routes/interview.py app/control_plane/main.py tests/features/test_interview_center_migration.py`：通过。
  - 空白检查：`git diff --check`：无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：290 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮验证覆盖页面文件和静态资源可访问性，但尚未在真实浏览器中完成旧面试中心 UI 的端到端点击验收；后续需要结合真实飞书授权、真实日历事件、Docx、VC/妙记和 Bitable 写入做完整联调。
  - 前端资源为旧 Node 页面机械迁入，后续如继续收敛到 FastAPI 新前端体系，需要再检查全局样式冲突、缓存版本号策略和旧 API 字段使用情况。

---

### 快照 0064：补齐面试中心日历同步自动准备

- 修改时间：2026-07-03 01:22:15 +08:00
- 修改原因：
  - 旧 Node 面试中心在 `POST /api/interview-center/sync` 收到 `autoPrepare=true` 时，会对本次同步后已自动匹配候选人且尚未创建飞书文档的面试日程执行 `prepareSession`，并在响应中返回 `prepared` 和 `prepareErrors`。
  - 当前 FastAPI `InterviewCenterService.sync_calendar()` 虽然接收 `auto_prepare` 和 `auto_prepare_limit`，但底层 `CalendarSyncService` 实际忽略该参数，导致同步结果里 `prepared` 永远为 0，旧自动日历同步链路无法在拉取日程后自动生成面试问题文档。
  - 该编排需要同时访问日历同步结果、简历库、LLM 问题生成和 Docx 客户端，因此应放在 `InterviewCenterService` 层，而不是让 `CalendarSyncService` 反向依赖 prepare 逻辑。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_calendar_sync_auto_prepare_generates_docs_for_matched_sessions()`，覆盖日历同步自动匹配候选人后，`autoPrepare=true` 会生成问题、创建飞书文档、返回 `prepared=1`，并更新 `/sync/status` 的 `lastResult.prepared`。
  - `InterviewCenterService.sync_calendar()` 在底层日历同步完成后，按 `auto_prepare_limit` 选择已绑定简历且未创建 `feishuDoc.documentId` 的面试日程，逐个复用既有 `prepare_session()`。
  - 自动准备失败时记录 `prepareErrors` 和 session 日志；成功后刷新响应里的 `sessions`，确保旧前端拿到的 session 状态已是 `prepared`，并同步更新 `calendar_sync.last_result`。
- 验证结果：
  - 红灯确认：新增自动准备测试首次运行 1 failed，原因为 `result["prepared"]` 仍为 0。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k auto_prepare_generates_docs`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：44 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：57 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check`：无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：291 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮补齐的是旧 `autoPrepare` 编排；旧 Node 在日历同步中还会尝试把已绑定候选人的简历图同步到 Bitable 并返回 `bitableResumeResults`，当前 FastAPI 结果保留该字段但尚未在 sync 阶段触发真实简历图同步，后续还需要继续审计并补齐。
  - 自动准备复用现有 `prepare_session()`，真实飞书 Docx 写入仍受 dry-run 和 OAuth token 配置保护；端到端联调时需要用有效飞书授权验证真实文档创建。

---

### 快照 0065：补齐面试中心日历同步简历图回写

- 修改时间：2026-07-03 01:31:06 +08:00
- 修改原因：
  - 旧 Node 面试中心在日历同步中会对“面试类 + 已绑定简历”的 session 调用 `syncSessionResumeImageToBitable()`，把候选人简历长截图写入对应飞书面试表，并在响应中返回 `bitableResumeResults`。
  - 当前 FastAPI `CalendarSyncService.sync()` 仅保留了空的 `bitableResumeResults` 字段，实际没有触发 `BitableAssetSync.ensure_resume_image()`，也没有在 `/sync/status` 的 `lastResult` 中提供 `bitableResumeSynced / bitableResumeSkipped / bitableResumeErrors` 统计。
  - 该行为依赖简历库 payload 中的本地 PDF 路径和 `InterviewCenterService` 已组合的 `asset_sync`，因此继续在 service 编排层补齐，不让底层日历同步服务直接依赖渲染/飞书资产写入。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_calendar_sync_syncs_bound_resume_image_to_bitable()`，覆盖同步日历后已自动绑定简历的 session 会调用 `asset_sync.ensure_resume_image()`，返回 `bitableResumeResults`，并更新 `lastResult` 的 Bitable 简历图统计。
  - `InterviewCenterService.sync_calendar()` 在底层日历同步后、自动准备前执行 `_sync_bitable_resume_images()`，贴近旧 Node 的执行顺序。
  - 新增 `_resume_pdf_path()`，按 `resumePdfPath / resume_pdf_path / pdfPath / pdf_path / filePath / file_path / downloadPath / download_path` 从简历顶层或嵌套 `payload` 中解析本地 PDF 路径；缺失时返回 `missing_resume_pdf_path` 跳过结果，避免伪造文件或触发无意义渲染。
  - Bitable 简历图同步成功时写 session 日志；异常时返回 `{ok: false, error, payload}` 并记录 warn 日志，保持旧响应形状。
- 验证结果：
  - 红灯确认：新增 Bitable 简历图同步测试首次运行 1 failed，原因为 `result["bitableResumeResults"]` 仍为空数组。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k syncs_bound_resume_image`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：45 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：58 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check`：无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：292 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 当前同步阶段会在简历 payload 没有本地 PDF 路径时安全跳过；真实线上数据需要继续确认智联/51job 同步入库后的字段是否统一落在这些路径键中。
  - 真实 Bitable 写入仍依赖飞书配置、OAuth/tenant token、字段列表和 dry-run 设置；本轮用 FakeAssetSync 验证编排，真实 multipart 上传和字段过滤已由前置 Bitable client/asset sync 测试覆盖，仍需端到端联调。

---

### 快照 0066：补齐面试中心旧前端 InterviewFlow 字段

- 修改时间：2026-07-03 01:39:28 +08:00
- 修改原因：
  - 旧面试中心前端会读取 `session.interviewFlow.groupKey/groupLabel/roundKey/roundLabel/stageText/source/recordId/error` 来分组展示“等待面试/已经面试”、初面/二面和阶段标签。
  - 旧 Node 服务在返回 sessions 前会调用 `enrichSessionsWithInterviewFlow()`；当前 FastAPI session 响应没有 `interviewFlow` 字段，旧页面只能走前端 fallback，缺少后端兼容的 source/recordId/阶段判断形状。
  - 该字段属于 session API 的旧响应契约，最合适在 `InterviewSession.to_dict()` 序列化层统一补齐，避免每个路由单独拼装。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/store.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_list_sessions_includes_old_interview_flow_payload()`，覆盖 `list_sessions()` 返回旧前端需要的 `interviewFlow` 形状，并从标题“二面面试”和未来时间推导出“等待面试 / 二面”。
  - `InterviewSession.to_dict()` 新增 `interviewFlow` 输出；默认 `source=calendar`，`recordId` 使用当前 session 的 `bitable_record_id`，`error` 默认为空。
  - 新增 `_interview_flow()`、`_stage_text()`、`_interview_group()`、`_interview_round()`，按旧 Node 规则的核心关键词推导等待/已面试分组和初面/二面/其他轮次。
  - 已有 `interviewEvaluation`、`bitableInterviewRecordImage.fileToken`、`needs_review/completed/backfill_failed` 状态或已过结束时间的 session 会归到“已经面试”，否则归到“等待面试”。
- 验证结果：
  - 红灯确认：新增 `interviewFlow` 测试首次运行 1 failed，原因为响应缺少 `interviewFlow` key。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k old_interview_flow`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：46 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：59 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check`：无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：293 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮先补齐 calendar-source 的后端兼容推导；旧 Node 还会在飞书 Bitable 配置齐全时读取表记录字段并用真实“面试阶段”覆盖 `stageText/source=bitable`，后续仍需继续迁移 Bitable 阶段读取与缓存。
  - 当前关键词推导覆盖旧页面的核心展示需求；真实线上阶段字段如果包含更多自定义文案，需要在 Bitable 阶段读取落地时一起扩展。
---

### 快照 0067：保护面试中心过早回灌结果

- 修改时间：2026-07-03 01:56:46 +08:00
- 修改原因：
  - 旧 Node 面试中心在返回 sessions 或日历同步结果前，会检查已经存在 `interviewEvaluation` 但面试尚未到 `endTime + 10 分钟` 的 session，并清理这些过早写入的回灌结果，防止旧页面把未结束面试误展示为待复核/已回灌。
  - 当前 FastAPI 版只有 `backfill_session()` 前置十分钟保护，缺少列表/日历同步响应阶段的旧数据保护；如果历史数据或异常流程已经写入面评，前端仍会看到 `needs_review` 和活跃 `interviewEvaluation`。
  - 清理逻辑需要同时移动 session 上的面评、回灌来源、规则建议和错误信息，并把绑定简历库中的同一条 `interviewEvaluation` 移到 stale 记录，避免简历详情继续读取过早面评。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_list_sessions_clears_premature_backfill_from_session_and_resume()`，覆盖未来结束时间的面试若已有面评，`list_sessions()` 会恢复为 `prepared`、清空活跃回灌字段，并写入 `staleInterviewEvaluation` / `staleInterviewEvaluationHistory`。
  - `InterviewCenterService` 复用注入的 `now`，新增 premature guard、清理 session、清理绑定 resume payload 的编排逻辑；普通列表使用 `sessions_response` 来源，日历同步刷新结果使用 `calendar_sync_result` 来源。
  - 清理后会重置 `interviewEvaluation`、`backfillSource`、`ruleSuggestionIds`、`lastBackfillError`、`backfilledAt`，并按旧逻辑根据文档/题集/简历绑定恢复为 `prepared`、`prepared_local`、`questions_generated`、`matched` 或 `synced`。
  - 绑定简历库中属于同一 session 的 `interviewEvaluation` 会被移除，并保存在 `staleInterviewEvaluation.evaluation` 中；如果简历上已有其他 session 的面评则不会误删。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，原因为 `listed["status"]` 仍是 `needs_review`，证明当前实现缺少响应阶段清理。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k premature_backfill`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：47 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：60 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：294 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮补齐的是列表/手动日历同步结果刷新时的清理保护；自动日历调度当前仍有部分编排直接走底层 `CalendarSyncService.sync()`，后续迁移需要继续审计它是否也应复用 service 层完整同步链路。
  - 清理简历库时沿用当前 `ResumeRepository.save()` 写回规范化 payload；真实线上旧 payload 若有更多面评字段别名，后续端到端联调时还需要按实际数据形状扩展。
