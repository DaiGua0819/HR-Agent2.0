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
---

### 快照 0068：自动日历同步复用完整面试中心编排

- 修改时间：2026-07-03 02:07:15 +08:00
- 修改原因：
  - 旧 Node 的自动日历 tick 调用完整 `syncCalendarSessions(source="auto")`，因此自动同步也会执行候选人匹配、Bitable 简历图同步、过早回灌保护以及 `lastResult` 统计刷新。
  - 当前 FastAPI 版 `run_auto_calendar_sync_tick()` 直接调用底层 `CalendarSyncService.sync()`，绕过了 `InterviewCenterService.sync_calendar()` 中已迁移的简历图回写和保护逻辑，导致自动 tick 的 `lastResult` 缺少 `bitableResumeSynced / Skipped / Errors`，也不会触发 `asset_sync.ensure_resume_image()`。
  - 自动 tick 仍需保持旧行为中的 `autoPrepare=false`，不能因为复用 service 编排而自动创建面试题文档。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_auto_calendar_tick_runs_full_service_sync_when_connected()`，模拟飞书已授权、日历匹配到候选人且简历有本地 PDF 路径时，自动 tick 应触发一次 `resume_image` 同步并把 Bitable 简历图统计写入 `calendar_sync.lastResult`。
  - `InterviewCenterService.sync_calendar()` 新增内部可选参数 `source` 和 `skip_if_running`，默认仍为手动同步；当底层同步返回 skipped 时直接返回，避免继续做 service 层后处理。
  - `run_auto_calendar_sync_tick()` 改为调用 `self.sync_calendar(source="auto", auto_prepare=False, auto_prepare_limit=0, skip_if_running=True)`，让自动链路复用手动链路已迁移的 Bitable 简历图同步、过早回灌保护和统计刷新。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，原因为 `status["lastResult"]["bitableResumeSynced"]` 缺失，证明自动 tick 绕过了完整 service 编排。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k full_service_sync_when_connected`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：48 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：61 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check`：无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：295 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮关闭了自动日历 tick 绕过 service 编排的问题，但真实飞书 OAuth、日历事件、Bitable 上传和本地 PDF 路径仍需在有授权环境下继续端到端联调。
  - `sync_calendar()` 的 `source/skip_if_running` 目前作为 service 内部参数使用；若后续 API 需要暴露自动来源，应继续保持默认手动行为，避免影响现有 `/sync` 调用方。
---

### 快照 0069：Bitable 面试阶段优先生成 InterviewFlow

- 修改时间：2026-07-03 02:16:33 +08:00
- 修改原因：
  - 旧 Node 面试中心在返回 sessions 前会读取飞书 Bitable 面试表记录，按 `bitableRecordId`、候选人电话或姓名匹配 session，并优先使用真实 `面试阶段` 字段生成 `interviewFlow`。
  - 当前 FastAPI 版只在 `InterviewSession.to_dict()` 中做 calendar fallback 推导，旧页面即使 Bitable 已有“二面通过/复试/已淘汰”等真实阶段，也只能看到 `source=calendar` 和空 `stageText`。
  - Bitable 读取是异步 HTTP 能力，而当前 `list_sessions()` 是同步方法；需要在不破坏现有同步调用方的前提下，让旧 API 和同步结果使用异步 enrichment。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_sessions_api_prefers_bitable_interview_flow_stage()`，覆盖 `/api/interview-center/sessions` 在 session 已有 `bitableTableId/bitableRecordId` 且 Bitable 记录含 `面试阶段=二面通过` 时，返回 `interviewFlow.source=bitable`、`stageText=二面通过`、`groupKey=completed`、`roundKey=second`。
  - `InterviewCenterService` 新增 `list_sessions_enriched()`，保留原同步 `list_sessions()` 行为，同时为旧 API 和日历同步结果提供异步 Bitable flow enrichment。
  - 新增 Bitable 记录匹配与字段解析 helper：按记录 ID 优先匹配，随后兼容候选人联系电话和姓名/候选人姓名；支持文本、数组、对象字段形态。
  - Bitable flow 生成按旧逻辑优先使用 `面试阶段`，并结合 `面试记录`、`HR面试评价`、`复试结果评价`、结束时间等信息推导等待/已面试分组和初面/二面/其他轮次。
  - `/api/interview-center/sessions` 改为 await `list_sessions_enriched()`；`sync_calendar()` 刷新的 sessions 也使用 enrichment，保持旧页面在手动/自动同步后立即看到 Bitable 阶段。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，原因为 `flow["source"]` 仍是 `calendar`，证明旧 API 未读取 Bitable 阶段。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k prefers_bitable_interview_flow_stage`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：49 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：62 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check`：无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：296 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮实现了读取 Bitable 阶段的旧 API 路径；真实飞书表字段如果存在更多阶段字段别名，仍需在端到端联调后继续扩展字段映射。
  - 当前 enrichment 会在有可解析 tableId 时读取 Bitable 记录；真实环境的分页读取、字段权限和接口限流已经由 Bitable client 负责，但仍需要带真实 OAuth/tenant 配置做联调确认。
---

### 快照 0070：兼容旧式提前回灌一次性授权

- 修改时间：2026-07-03 02:25:18 +08:00
- 修改原因：
  - 旧 Node 面试中心支持 `earlyBackfillOverride.allowed/token/expiresAt/usedAt/failedAt` 一次性授权；在面试结束后 10 分钟保护期内，只有携带正确 token 且授权未过期、未使用、未失败时才允许强制回灌。
  - 当前 FastAPI 版只接受 `earlyOverrideToken == session.id`，无法兼容旧数据里已经生成的一次性 override token，也不会在成功提前回灌后标记 `usedAt`。
  - 旧前端会根据 `earlyBackfillOverride.usedAt + availableAt` 判断保护是否解除，因此成功提前回灌后必须回写该状态，避免后续列表保护把刚回灌的结果当作过早脏数据清掉。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/backfill.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_backfill_allows_old_one_off_early_override_token()`，覆盖 session payload 中已有 `earlyBackfillOverride.allowed=true`、正确 token、未来 `expiresAt` 时，未到 `endTime + 10 分钟` 仍可强制回灌。
  - `BackfillService._enforce_ten_minute_guard()` 改为返回是否使用了提前授权；普通未到时间仍抛 `backfill_not_available`，保留原有阻止逻辑。
  - 新增旧式授权校验：校验 `allowed`、`token`、`expiresAt`、`usedAt`、`failedAt`，并保留兼容 `earlyOverrideToken == session.id` 的旧 Python 临时行为。
  - 提前授权成功回灌后，session payload 会写回 `earlyBackfillOverride.usedAt`、`availableAt` 和原有 `reason`，供列表保护和旧前端继续识别。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，原因为 `_enforce_ten_minute_guard()` 抛出 `backfill_not_available`，证明当前实现不兼容旧式 token。
  - 新增切片验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k old_one_off_early_override_token`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：50 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：63 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check`：无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：297 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮补齐的是已有一次性授权 token 的消费与 usedAt 回写；旧系统中生成 override token 的入口如果后续仍需要开放，还需继续补对应 API/权限流程。
  - 失败时的 `failedAt` 标记仍需要结合真实失败路径继续审计，避免没有授权却被误标记。
---

### 快照 0071：隔离回灌资产同步失败

- 修改时间：2026-07-03 02:34:50 +08:00
- 修改原因：
  - 旧 Node 面试中心在成功生成并保存 `interviewEvaluation` 后，会分别尝试把面试记录截图和技能评估文档同步到 Bitable；这些资产同步失败只记录 warn，不会让已经成功的回灌整体失败。
  - 当前 FastAPI 版本在 `BackfillService.backfill()` 保存面试评价后直接 await `_sync_assets()`，如果 Bitable/截图/文档同步链路抛错，会把已保存的回灌结果表现成接口失败，和旧逻辑不一致。
  - 该行为需要保证候选人面试评价、简历库回写、`lastBackfillError` 清空这些核心结果优先生效，资产同步失败只进入 session warn 日志，便于后续重试或排查。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/features/interview_center/backfill.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_backfill_keeps_evaluation_when_asset_sync_fails()`，模拟 `asset_sync.ensure_interview_record_image()` 抛出 `asset_sync_failed`，覆盖回灌接口仍返回 `needs_review`、保留 `interviewEvaluation`、清空 `lastBackfillError`、写回简历库并记录 warn 日志。
  - 新增 `FailingAssetSync` 测试替身，复用现有 `FakeAssetSync` 的其他行为，只让面试记录图片同步阶段失败，避免测试同时覆盖多个异常来源。
  - `BackfillService.backfill()` 在保存 session 后对 `_sync_assets()` 加 try/except，失败时追加 warn 日志并重新读取 session，继续返回已保存的回灌结果。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，原因为 `RuntimeError("asset_sync_failed")` 从 `_sync_assets()` 冒泡，证明当前实现会把资产同步失败当成回灌失败。
  - 修正测试断言：聚焦用例通过，命令 `C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k asset_sync_fails`，结果 `1 passed, 50 deselected`，仅有既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`，结果 `51 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`，结果 `64 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`，结果 `All checks passed!`。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`，通过。
  - 空白检查：`git diff --check` 无空白错误，仅有 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`，结果 `298 passed`，仅有既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本次只隔离回灌成功后的资产同步异常；如果未来要支持后台自动补偿失败的面试记录截图或评估文档，需要继续补充重试队列或人工重试入口。
  - warn 日志目前记录异常字符串；真实 Bitable/Docx 错误若需要更细的错误码、recordId、fileToken 等诊断字段，可在联调后继续扩展日志 payload。
---

### 快照 0072：恢复旧面试中心列表默认时间窗

- 修改时间：2026-07-03 02:44:09 +08:00
- 修改原因：
  - 旧 Node 面试中心的 `GET /api/interview-center/sessions` 在未传 `startTime/endTime` 时默认只返回“当前时间前 1 天到未来 14 天”的面试类日程，避免旧前端列表加载历史或过远未来的日程。
  - 当前 FastAPI 路由把 `startTime/endTime` 默认值设为 `0`，等价于默认不过滤时间范围，导致旧日程和 15 天后的日程也会进入旧前端列表。
  - 需要保留显式传 `startTime=0&endTime=0` 的调试/兼容入口，因此只改变“参数缺省”时的默认窗口，不改变 service 层的显式 0 语义。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_sessions_api_uses_old_default_time_window()`，覆盖默认列表只返回窗口内面试类日程、排除过旧/过远日程，并确认显式 `startTime=0&endTime=0` 仍可请求不按时间过滤的全量面试类日程。
  - `/api/interview-center/sessions` 的 `startTime/endTime` 改为可空查询参数；缺省时使用 `service.now()` 计算 `now - 86400` 到 `now + 14 * 86400` 的旧默认窗口。
  - 原有 Bitable 面试阶段 enrichment 测试显式传 `startTime=0&endTime=0`，让它继续专注验证 Bitable 阶段字段，不依赖默认时间窗。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，默认列表返回了过旧和过远未来会话，证明当前路由未应用旧默认时间窗。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k default_time_window`，结果 `1 passed, 51 deselected`，仅有既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`，结果 `52 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`，结果 `65 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`，结果 `All checks passed!`。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`，通过。
  - 空白检查：`git diff --check` 无空白错误，仅有 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`，结果 `299 passed`，仅有既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 默认列表现在更贴近旧前端日程视图；如果后续新增管理后台需要默认看全量历史，应显式传 `startTime=0&endTime=0` 或单独提供管理视图参数。
  - 本次只恢复时间窗默认值；旧前端若还有更多列表筛选维度或分页行为，仍需继续按旧 Node 入口逐项审计。
---

### 快照 0073：恢复同步接口默认自动准备

- 修改时间：2026-07-03 02:50:30 +08:00
- 修改原因：
  - 旧 Node 面试中心 `POST /api/interview-center/sync` 会把请求体解析失败当作空对象，并使用 `autoPrepare: body.autoPrepare !== false`，因此无请求体或未传 `autoPrepare` 时默认会自动为已匹配日程生成面试问题文档。
  - 当前 FastAPI 路由要求请求体必须存在，无 body 时返回 422；同时 `InterviewCenterSyncRequest.autoPrepare` 默认值是 `False`，和旧前端默认同步按钮行为不一致。
  - 需要保留显式传 `autoPrepare:false` 的能力，避免自动日历 tick 或人工调试在不需要时创建文档。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_interview_center_sync_api_defaults_to_auto_prepare_without_body()`，覆盖旧兼容行为：无 body 调用 `/api/interview-center/sync` 应返回 200，完成日历同步并自动生成题集/飞书文档。
  - `InterviewCenterSyncRequest.auto_prepare` 默认值改为 `True`，显式 `autoPrepare:false` 仍会传入 service 并跳过自动准备。
  - `sync_calendar()` 路由 payload 改为可选，缺省时使用默认请求对象，兼容旧 Node 的 `readJsonBody(...).catch(() => ({}))`。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，接口在无 body 时返回 `422 Unprocessable Entity`，证明当前实现不兼容旧同步入口默认行为。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "sync_api"`，结果 `2 passed, 51 deselected`，仅有既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`，结果 `53 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`，结果 `66 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`，结果 `All checks passed!`。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`，通过。
  - 空白检查：`git diff --check` 无空白错误，仅有 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`，结果 `300 passed`，仅有既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 旧同步按钮默认会创建文档；本次恢复该行为后，如果某些内部调用不想自动准备，必须继续显式传 `autoPrepare:false`。
  - 本次仅兼容无 body 和默认值；如果旧前端存在非 JSON body 的调用路径，FastAPI 请求解析行为还需结合真实浏览器 smoke 再确认。
---

### 快照 0074：兼容回灌接口空请求体

- 修改时间：2026-07-03 02:56:53 +08:00
- 修改原因：
  - 旧 Node 面试中心 `POST /api/interview-center/sessions/{id}/backfill` 会把请求体解析失败当作空对象，并用默认 `force=false / earlyOverride=false / earlyOverrideToken=""` 执行回灌。
  - 当前 FastAPI 路由要求 `InterviewBackfillRequest` 请求体必须存在，旧前端或手动按钮如果不带 JSON body 会直接返回 422，不能进入正常回灌逻辑。
  - 需要保持显式 body 的行为不变，同时兼容空 body 的旧入口调用。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_backfill_api_accepts_empty_body_like_old_node()`，覆盖无 body 调用 `/backfill` 也会执行默认回灌并返回 `needs_review` 和面试评价摘要。
  - `backfill_session()` 路由 payload 改为可选，缺省时构造 `InterviewBackfillRequest()`，复用原有 service/backfill 逻辑。
  - 原有显式 `{"force": true}` 回灌 API 测试保持不变，继续验证已有兼容入口。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，接口在无 body 时返回 `422 Unprocessable Entity`，证明当前实现不兼容旧 backfill 入口。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "backfill_api"`，结果 `2 passed, 52 deselected`，仅有既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`，结果 `54 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`，结果 `67 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`，结果 `All checks passed!`。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`，通过。
  - 空白检查：`git diff --check` 无空白错误，仅有 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`，结果 `301 passed`，仅有既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本次只兼容 backfill 空 body；旧 Node 的 review/confirm 也采用空对象默认解析，后续仍需继续逐项审计这些交互入口。
  - 空 body 会按默认非强制回灌执行，因此仍受 10 分钟保护和数据源校验约束，不会绕过原有业务保护。
---

### 快照 0075：兼容复核确认接口空请求体

- 修改时间：2026-07-03 03:04:45 +08:00
- 修改原因：
  - 旧 Node 面试中心 `POST /api/interview-center/sessions/{id}/review` 和 `/confirm` 会把请求体解析失败当作空对象，并通过 `normalizeReviewDecision(body.decision)` 默认把空 decision 视为 `passed`。
  - 当前 FastAPI 路由要求 `InterviewReviewRequest` 请求体必须存在，旧前端或手动确认按钮如果不带 JSON body 会直接返回 422。
  - 需要保持显式 decision/note 行为不变，同时兼容空 body 的旧复核/确认入口。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_review_and_confirm_api_accept_empty_body_like_old_node()`，覆盖无 body 调用 `/review` 和 `/confirm` 都会默认按 `passed` 完成人工复核，note 为空字符串。
  - `review_session()` 路由 payload 改为可选，缺省时构造 `InterviewReviewRequest()` 并复用已有 service review 逻辑。
  - `confirm_session()` 同样允许 payload 缺省，并按新签名正确复用 `review_session()`。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，`/review` 无 body 返回 `422 Unprocessable Entity`，证明当前实现不兼容旧 review/confirm 入口。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "review_confirm or empty_body_like_old_node"`，结果 `3 passed, 52 deselected`，仅有既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`，结果 `55 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`，结果 `68 passed`，仅有既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`，结果 `All checks passed!`。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`，通过。
  - 空白检查：`git diff --check` 无空白错误，仅有 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`，结果 `302 passed`，仅有既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 空 body 复核会默认通过，这是旧 Node 行为；如果后续需要强制人工填写决策，应新增受控入口，而不是改变旧兼容 API。
  - 本次仍未替代真实浏览器 smoke，后续需要继续在 18080 本地服务里验证旧前端点击复核/确认按钮的请求形态。
---

### 快照 0076：本地 18080 面试中心冒烟验证

- 修改时间：2026-07-03 03:16:16 +08:00
- 修改原因：
  - 迁移计划要求在测试通过后启动本地 18080 服务，验证旧面试中心页面、静态资源和核心旧 API 在真实 FastAPI/SQLite 运行态下可用。
  - 需要确认近期补齐的默认时间窗、空 body 同步/回灌/复核兼容不只在 TestClient 中成立，也能通过本地 HTTP 服务正常响应。
  - 本次验证必须使用临时 SQLite，避免影响真实 `data/` 运行库、浏览器 profile 或日志。
- 修改文件：
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 使用 `%TEMP%\hr-agent-interview-center-smoke-18080.sqlite` 作为 `DATABASE_PATH`，预置 1 条 smoke 简历和 2 条已结束超过 10 分钟、可人工复核的面试会话。
  - 使用 `CONTROL_PLANE_PORT=18080`、`DRY_RUN=true` 启动 `run_control_plane.py`，验证完成后停止 uvicorn 进程并删除临时 SQLite 文件。
  - 首次 smoke 使用未来面试时间，触发既有“过早回灌保护”，`backfill-source` 返回空 source；复核后确认这是 smoke 数据不符合旧保护窗口导致，随后把临时会话改成已结束超过 10 分钟并重新验证通过。
- 验证结果：
  - 本地服务启动：`Uvicorn running on http://127.0.0.1:18080`。
  - HTTP smoke 共 15 项通过：`/health`、`/interview-center.html`、`/assets/interview-center/app.js`、`/api/interview-center/sessions`、`items` alias、`/sessions/{id}`、`/backfill-source`、`/logs`、无 body `/review`、无 body `/confirm`、`/sync/status`、`/backfill/status`、`/feishu/status`、`/feishu/auth-url`、`/feishu/disconnect`。
  - 服务清理：已停止本轮 uvicorn 进程，18080 端口无监听项；临时 SQLite 文件已删除。
- 风险 / 待确认：
  - 本轮 smoke 验证的是 dry-run/临时库下的本地 HTTP 运行态，未连接真实飞书 OAuth、真实日历事件、真实 Docx 写入和真实 Bitable 上传。
  - 后续还需要在有授权的环境中完成真实飞书 OAuth、calendar event、Docx、VC/妙记和 Bitable 写入的端到端联调，才能把总迁移目标标记完成。

---

### 快照 0077：兼容旧面试中心错误响应与回灌来源字段

- 修改时间：2026-07-03 03:33:29 +08:00
- 修改原因：
  - 旧前端 `requestJson()` 在请求失败时只读取响应体里的 `error` 或 `message` 字段；当前 FastAPI 路由抛出的 `HTTPException` 默认返回 `detail`，会导致旧页面只能显示泛化的 HTTP 状态错误，和旧 Node 的 `{ ok:false, error:"..." }` 协议不一致。
  - 旧 Node 的 `publicBackfillSource()` 会给回灌来源补齐 `types/rawTextLength/linkedDocIds/minuteTokens/sources/errors` 等稳定字段；当前服务在来源客户端只返回最小 source 时会把不完整对象直接暴露给旧页面。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `app/features/interview_center/store.py`
  - `app/features/interview_center/service.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_old_interview_center_errors_use_error_payload_for_frontend()`，覆盖旧面试中心 404/409 失败响应必须返回 `ok:false` 和 `error` 字段。
  - `/api/interview-center/*` 旧路由的显式 `KeyError/ValueError` 捕获分支改为返回旧协议 JSON 错误响应；`KeyError` 会去掉 Python 字符串引号，避免前端显示 Python 异常形态。
  - 新增 `test_backfill_source_payload_is_normalized_like_old_node()`，覆盖 backfill 结果和 `/backfill-source` 接口都补齐旧前端需要的来源字段。
  - 新增 `public_backfill_source()` 并复用到 `InterviewSession.to_dict()` 与 `InterviewCenterService.backfill_source()`；空 source 仍保持 `{}`，避免过早回灌保护清理后的会话被误显示为有来源。
- 验证结果：
  - 红灯确认：新增旧错误响应测试首次失败，实际返回 `{"detail": ...}`，证明缺少旧协议 `error` 字段。
  - 红灯确认：新增回灌来源规范化测试首次失败，实际 `backfillSource` 缺少 `types` 等字段。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k old_interview_center_errors_use_error_payload_for_frontend`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k backfill_source_payload_is_normalized_like_old_node`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 边界回归：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "premature_backfill or backfill_source_payload"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：57 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：70 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check` 无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：304 passed，1 个既有 `StarletteDeprecationWarning`。
  - 本地 18080 smoke：使用 `%TEMP%\hr-agent-interview-center-smoke-18080.sqlite` 和 `DRY_RUN=true` 启动 `run_control_plane.py`，真实 HTTP 检查 10 项通过：`/health`、`/interview-center.html`、`/assets/interview-center/app.js`、`/api/interview-center/sessions`、缺失 session 的 `/sessions/{id}` 404、缺失 session 的 `/prepare` 404、缺失 session 的 `/backfill-source` 404、`/feishu/status`、`/feishu/auth-url`、`/feishu/disconnect`；3 个 404 均确认包含 `ok:false` 和 `error`。服务已停止，临时 SQLite 已删除。
- 风险 / 待确认：
  - 本轮修复的是旧前端可见的本地协议兼容，不替代真实飞书 OAuth、真实日历、真实 Docx、真实 VC/妙记和真实 Bitable 写入联调。
  - 错误内容目前沿用当前 service 层错误码，没有完整恢复旧 Node 的中文错误文案；如果产品侧需要逐字一致，还需要继续建立错误码到旧中文文案的映射表。

---

### 快照 0078：兼容旧 OAuth 回调缺省参数与断开授权文案

- 修改时间：2026-07-03 03:43:12 +08:00
- 修改原因：
  - 旧 Node 面试中心 OAuth callback 只读取 `code`，`state` 缺失时仍会继续交换飞书授权码；当前 FastAPI 路由把 `state` 声明为必填，导致缺省 `state` 的旧入口请求在路由层返回 422。
  - 旧 Node 在缺少 `code` 时返回旧式 HTML 授权失败页；当前 FastAPI 因 `code` 必填同样会在路由层返回 422，绕过了旧页面可读的失败页。
  - 旧 Node `feishu/disconnect` 返回 `已断开飞书日历授权`，当前实现返回 `feishu_disconnected`，属于旧 API 响应面不一致。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `app/features/interview_center/feishu/oauth.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_feishu_oauth_callback_accepts_missing_state_like_old_node()`，覆盖 `/api/interview-center/feishu/oauth/callback?code=...` 在无 `state` 时仍返回旧式 HTML redirect，并保存 token 中的空 `state`。
  - 新增 `test_feishu_oauth_callback_missing_code_uses_old_html_error()`，覆盖无 `code/state` 时返回 400 HTML 授权失败页，而不是 FastAPI 422。
  - 旧 Feishu OAuth callback 路由的 `code/state` 改为可缺省查询参数，继续复用现有 `handle_callback()` 的缺 code 校验和 HTML/JSON 分支。
  - `FeishuOAuthService.disconnect()` 的 `message` 恢复为旧 Node 中文文案 `已断开飞书日历授权`，并在状态/断开测试中固定。
- 验证结果：
  - 红灯确认：新增 OAuth callback 缺省参数测试首次运行 2 failed，两个场景均实际返回 422，证明被 FastAPI 路由参数校验拦截。
  - 红灯确认：断开授权文案断言首次失败，实际返回 `feishu_disconnected`。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "missing_state_like_old_node or missing_code_uses_old_html_error"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k feishu_status_and_disconnect_use_stored_token`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：59 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：72 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check` 无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：306 passed，1 个既有 `StarletteDeprecationWarning`。
  - 本地 18080 smoke：使用 `%TEMP%\hr-agent-interview-center-oauth-smoke-18080.sqlite` 和 `DRY_RUN=true` 启动 `run_control_plane.py`，真实 HTTP 检查 4 项通过：`/health`、`/interview-center.html`、无 `code` 的 `/api/interview-center/feishu/oauth/callback` 返回 400 HTML 且包含 `missing_feishu_oauth_code`、`/api/interview-center/feishu/disconnect` 返回中文 message。服务已停止，临时 SQLite 已删除。
- 风险 / 待确认：
  - 本轮只恢复 OAuth callback 参数兼容和断开授权响应文案；真实飞书 OAuth 授权码交换仍需在有飞书应用配置和授权用户的环境里端到端联调。
  - 缺 `code` 的 HTML 失败页目前显示当前 service 错误码 `missing_feishu_oauth_code`，不是旧 Node 的完整中文缺 code 文案；如需逐字一致，可以继续补错误文案映射。

---

### 快照 0079：兼容绑定空请求体与未知面试中心接口

- 修改时间：2026-07-03 03:53:39 +08:00
- 修改原因：
  - 旧 Node 面试中心 `POST /api/interview-center/sessions/{id}/bind` 会把请求体解析失败当作 `{}`，再进入正常绑定逻辑；当前 FastAPI 路由要求 `InterviewBindRequest` 必填，空 body 会在路由层返回 422，和旧入口行为不一致。
  - 旧 Node 对未知 `/api/interview-center/*` 路径统一返回 `{ ok:false, error:"未知面试中心接口" }`；当前 FastAPI 默认 404 返回 `{"detail":"Not Found"}`，旧前端的 `requestJson()` 只能得到泛化错误。
- 修改文件：
  - `tests/features/test_interview_center_migration.py`
  - `app/api/routes/interview.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `test_bind_api_accepts_empty_body_like_old_node()`，覆盖 bind 空 body 不再 422，而是进入旧逻辑并返回旧协议 JSON 错误。
  - 新增 `test_unknown_interview_center_route_uses_old_error_payload()`，覆盖未知 `/api/interview-center/unknown` 和未知 session action 均返回旧协议 404。
  - `bind_session()` 路由 payload 改为可选，缺省时构造 `InterviewBindRequest()`，保持显式 `resumeId/prepare` 行为不变。
  - 在所有已知 `/api/interview-center/*` 路由之后新增 catch-all，只处理未匹配的旧面试中心 API 路径，返回 `{ ok:false, error:"未知面试中心接口" }`。
- 验证结果：
  - 红灯确认：新增 bind 空 body 测试首次失败，实际返回 422，证明路由层仍要求 body。
  - 红灯确认：新增未知路由测试首次失败，实际返回 `{"detail":"Not Found"}`。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "bind_api_accepts_empty_body_like_old_node or unknown_interview_center_route_uses_old_error_payload"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：61 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：74 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 空白检查：`git diff --check` 无空白错误，仅 Windows 换行提示。
  - 全量回归：同一 Python 运行 `-m pytest -q`：308 passed，1 个既有 `StarletteDeprecationWarning`。
  - 本地 18080 smoke：使用 `%TEMP%\hr-agent-interview-center-route-smoke-18080.sqlite` 和 `DRY_RUN=true` 启动 `run_control_plane.py`，真实 HTTP 检查 4 项通过：`/health`、未知 `/api/interview-center/unknown` 404、未知 `/api/interview-center/sessions/session-1/unknown` 404、空 body `/api/interview-center/sessions/session-1/bind` 404；未知接口均确认旧协议 payload。服务已停止，临时 SQLite 已删除。
- 风险 / 待确认：
  - catch-all 仅放在本路由文件已有 `/api/interview-center/*` 路由之后；如果后续新增新的旧面试中心接口，需要继续确保新增路由定义位于 catch-all 之前。
  - bind 空 body 的错误内容仍沿用当前 service 错误码 `resume_not_found`，不是旧 Node 的中文 `候选人简历不存在`；如需前端逐字文案一致，还需继续补错误码到中文文案的映射。

---

### 快照 0080：恢复面试中心旧中文错误文案

- 修改时间：2026-07-03 04:08:37 +08:00
- 修改原因：
  - 旧 Node 面试中心对旧前端暴露的是中文错误文案，例如缺少候选人简历时返回 `候选人简历不存在`，而上一轮 FastAPI 兼容层只把旧协议 payload 恢复为 `{ ok:false, error }`，内容仍可能是内部错误码。
  - 旧前端会直接展示 `error/message` 字段；如果继续暴露 `resume_not_found`、`interview_session_not_found` 等内部码，页面提示会退化为工程错误码，不符合旧入口体验。
  - 需要先覆盖当前已知 service 层错误码，后续如新增旧入口错误再继续补映射。
- 修改文件：
  - `app/api/routes/interview.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `_legacy_error_message()` 新增旧文案映射表，把 `resume_not_found`、`interview_session_not_found`、`interview_session_resume_required`、`bound_resume_not_found`、`backfill_not_available`、`no_valid_interview_record` 转为旧前端可读中文。
  - 保留未知错误的原样透传，避免把尚未识别的新错误吞成泛化文案。
  - 更新 bind 空 body 与旧错误 payload 测试期望，固定缺简历、缺面试日程、未绑定候选人的中文错误内容。
- 验证结果：
  - 红灯确认：中文文案测试期望切换后，旧实现仍返回内部错误码，聚焦用例首次失败，证明缺少错误码到旧中文文案的映射。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "bind_api_accepts_empty_body_like_old_node or old_interview_center_errors_use_error_payload_for_frontend"`：2 passed，59 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：61 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：74 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：308 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只覆盖当前 FastAPI service 已知会暴露到旧面试中心前端的错误码；真实联调中如果出现旧 Node 其它中文错误分支，还需要继续补充映射。
  - 当前映射集中在路由兼容层，业务层仍保留内部错误码，便于测试和后端逻辑继续用稳定 code 判断。

---

### 快照 0081：恢复旧提前回灌授权保护

- 修改时间：2026-07-03 04:19:01 +08:00
- 修改原因：
  - 旧 Node 面试中心在面试结束后 10 分钟保护期内，只允许 `force=true`、`earlyOverride=true` 且一次性授权 token 有效时提前回灌；授权无效时返回 403，避免误读尚未完成的会议纪要。
  - 当前 FastAPI backfill 服务忽略了 `force` 参数，导致只要 `earlyOverride=true` 且 token 正确，即使没有 `force=true` 也会绕过 10 分钟保护并执行回灌。
  - 当前旧 API 错误响应层只固定调用处传入的状态码，无法带出 backfill 领域错误自己的 403 状态和旧 Node 的 `availableAt/endTime` 错误 payload。
- 修改文件：
  - `app/features/interview_center/backfill.py`
  - `app/api/routes/interview.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `BackfillError(ValueError)`，在保留内部错误码的同时携带旧 API 所需的 `status_code` 和 `payload`。
  - `_enforce_ten_minute_guard()` 恢复旧条件：提前回灌必须同时满足 `early_override` 和 `force`，且 token 未过期、未使用、未失败；无效授权返回 `early_backfill_override_forbidden` 和 403。
  - 普通 10 分钟保护失败继续返回 `backfill_not_available`，并补齐旧 Node payload：`availableAt` 和 `endTime`。
  - `_legacy_error_response()` 现在会读取异常上的 `status_code/payload`，旧前端可以拿到旧协议中的 403 与保护窗口信息。
  - 修正一个已有日志断言抖动：资产同步失败用例改为查找本 session 日志中存在 `asset_sync_failed` warn，而不是依赖最新一条日志排序。
- 验证结果：
  - 红灯确认：新增提前回灌测试首次运行 2 failed；错误 token 场景实际返回 409，缺少 `force` 场景实际返回 200，证明当前实现偏离旧 Node 保护逻辑。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k "invalid_old_early_override or requires_force_for_old_early_override"`：2 passed，61 deselected，1 个既有 `StarletteDeprecationWarning`。
  - Backfill 边界验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "backfill_api or backfill_blocks_until_ten_minutes or old_one_off_early_override"`：6 passed，57 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：63 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：76 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：310 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮恢复的是提前回灌授权保护和错误响应形状，不替代真实飞书会议/妙记来源读取的端到端联调。
  - 普通 10 分钟保护的 `error` 文案仍使用当前映射中的稳定中文短句；旧 Node 会追加本地化预计可回灌时间，当前通过 `availableAt/endTime` 提供机器可读时间信息。

---

### 快照 0082：保存旧提前回灌原因

- 修改时间：2026-07-03 04:26:01 +08:00
- 修改原因：
  - 旧 Node 面试中心 `POST /api/interview-center/sessions/{id}/backfill` 会读取请求体中的 `earlyOverrideReason`，并在一次性提前回灌成功后写入 `earlyBackfillOverride.reason`。
  - 当前 FastAPI 请求模型、service 方法和 backfill 编排都没有传递该字段，导致即使旧前端提交了人工提前回灌原因，最终仍保留 session 中已有的旧 reason。
  - 提前回灌原因是人工越过 10 分钟保护的重要审计信息，迁移后需要保留旧行为。
- 修改文件：
  - `app/api/routes/interview.py`
  - `app/features/interview_center/service.py`
  - `app/features/interview_center/backfill.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `InterviewBackfillRequest` 新增 `earlyOverrideReason` alias，并在旧 backfill API 中传给 service。
  - `InterviewCenterService.backfill_session()` 和 `BackfillService.backfill()` 新增 `early_override_reason` 参数，保持默认空字符串以兼容已有调用。
  - `_used_early_override_payload()` 现在优先使用请求传入的 reason，其次使用 session 中已有 reason，最后回退 `one_off_manual_override`，并继续按旧 Node 行为截断到 300 字。
  - 新增 `test_backfill_api_persists_old_early_override_reason_from_body()`，覆盖请求体 reason 覆盖已存 reason 并在成功提前回灌后持久化。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，实际 `earlyBackfillOverride.reason` 为 `stored reason`，证明请求体 `earlyOverrideReason` 未被读取和传递。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k old_early_override_reason_from_body`：1 passed，63 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 提前回灌边界验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "old_one_off_early_override_token or invalid_old_early_override or requires_force_for_old_early_override or old_early_override_reason"`：4 passed，60 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：64 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：77 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：311 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复提前回灌审计原因的传递和保存；真实飞书会议/妙记文本读取仍需端到端授权环境验证。
  - 当前 reason 仍只保存在 session payload 的 `earlyBackfillOverride` 中，和旧 Node 数据结构一致；如果后续需要单独审计表，应作为新需求另行设计。

---

### 快照 0083：避免无 force 重复覆盖已有面评

- 修改时间：2026-07-03 04:34:49 +08:00
- 修改原因：
  - 旧 Node 面试中心在 `session.interviewEvaluation && !force` 时不会重新读取会议纪要和重算面评，只会尝试补同步缺失的评价文档后返回已有 session。
  - 当前 FastAPI `BackfillService.backfill()` 即使 session 已有 `interview_evaluation`，只要再次调用且 `force=false`，仍会采集会议记录、调用评价生成器并覆盖已有面评。
  - 重复覆盖已有面评会影响人工复核后的结果稳定性，也可能误读后续变更的会议/妙记内容，和旧服务安全边界不一致。
- 修改文件：
  - `app/features/interview_center/backfill.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 在 backfill 已通过 session、简历绑定和候选人简历存在校验后，新增 `session.interview_evaluation and not force` 的早返回分支，直接返回当前 session。
  - 新增 `test_backfill_returns_existing_evaluation_without_force_like_old_node()`，覆盖已有面评、`force=false` 时不采集会议源、不调用评价生成器、不触发资产同步，也不覆盖简历库中的面评。
  - 为 `FakeMeetingClient` 和 `FakeEvaluationGenerator` 增加调用计数，便于测试确认早返回未触发采集和生成。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，返回的 `interviewEvaluation.summary` 被覆盖为新生成摘要，证明当前实现会重复回灌已有面评。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k existing_evaluation_without_force`：1 passed，64 deselected，1 个既有 `StarletteDeprecationWarning`。
  - Backfill 切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "backfill_persists_evaluation or backfill_keeps_evaluation or existing_evaluation_without_force or backfill_api"`：8 passed，57 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：65 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：78 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：312 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮恢复的是旧 Node 的“不 force 不覆盖已有面评”保护；旧 Node 同时会尝试补同步缺失的 Bitable 评价文档，当前 FastAPI 仍需后续继续审计补同步链路是否完全等价。
  - 如果业务方需要在已有面评情况下强制重读会议纪要，仍可通过 `force=true` 走完整回灌链路。

---

### 快照 0084：补同步已有面评的评价文档

- 修改时间：2026-07-03 04:43:17 +08:00
- 修改原因：
  - 旧 Node 面试中心在 `session.interviewEvaluation && !force` 时不会重算面评，但如果当前轮次对应的 Bitable 评价文档字段缺失，会调用 `syncSessionSkillEvaluationDocumentToBitable()` 补同步评价文档后再返回 session。
  - 上一轮 FastAPI 只恢复了“不 force 不覆盖已有面评”的早返回，导致缺失的 `bitableSkillEvaluationDocument` / `bitableSecondInterviewEvaluationDocument` 不会被补同步。
  - 该行为会影响旧页面和飞书表格查看已有面评文档链接，属于面试中心迁移的旧行为缺口。
- 修改文件：
  - `app/features/interview_center/backfill.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `BackfillService.backfill()` 在已有面评且 `force=false` 时改为调用 `_sync_existing_evaluation_document()`，再返回保存后的 session。
  - 新增 `_sync_existing_evaluation_document()`：只补同步评价文档，不读取会议源、不调用评价生成器、不生成面试记录图；如果对应文档已存在则直接返回。
  - 补同步失败时沿用旧 Node 容错思路，只写 warn 日志并返回现有 session，避免因为飞书/Bitable 写入失败影响已有面评展示。
  - 更新回归测试为 `test_backfill_syncs_missing_evaluation_document_without_force_like_old_node()`，覆盖已有面评、缺评价文档、`force=false` 时只触发 `evaluation_document` 同步并保留原面评。
  - 测试用 `FakeAssetSync.ensure_evaluation_document()` 现在模拟真实实现写回 session 的评价文档字段，便于断言 API 返回 payload。
- 验证结果：
  - 红灯确认：新增/调整测试首次运行失败，`asset_sync.calls` 为空，证明当前早返回没有补同步评价文档。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k syncs_missing_evaluation_document_without_force`：1 passed，64 deselected，1 个既有 `StarletteDeprecationWarning`。
  - Backfill 切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "backfill_persists_evaluation or backfill_keeps_evaluation or syncs_missing_evaluation_document or backfill_api or second_interview_evaluation_field"`：9 passed，56 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：65 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：78 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：312 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 当前轮次判断沿用评价 payload 中的 `round == "second"` 来选择复试评价字段；旧 Node 使用 `deriveInterviewRound({ session })`，后续仍可继续扩展为完全复用 session 阶段推导。
  - 本轮验证使用 fake asset sync 和本地单测证明编排行为，真实 Bitable 字段权限和文档链接写入仍需在授权环境里端到端联调。

---

### 快照 0085：已有面评补同步按 session 推导二面字段

- 修改时间：2026-07-03 04:53:44 +08:00
- 修改原因：
  - 旧 Node `deriveInterviewRound({ session })` 会从 session 标题、描述和阶段文本中识别 `二面/复试/second/2面` 等关键词，再决定评价文档写入初试字段还是复试字段。
  - 上一轮 FastAPI 补同步已有面评评价文档时只看 `interviewEvaluation.round == "second"`；如果历史面评 payload 没有 round，但 session 标题或描述已经标明二面，就会错误写入 `bitableSkillEvaluationDocument`。
  - 该偏差会导致复试评价文档链接落到初试字段，影响旧页面和 Bitable 中二面结果的查看。
- 修改文件：
  - `app/features/interview_center/backfill.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `_is_second_interview_round(session, evaluation)`，优先兼容既有 `evaluation.round == "second"`，再从 `stageText/interviewStage/stage/面试阶段/title/description/job_type` 中按旧关键词推导二面/复试。
  - 新生成评价文档和已有面评补同步评价文档两条链路都改为复用该判断，避免 round 缺失时写错 Bitable 字段。
  - 新增 `test_backfill_existing_evaluation_uses_session_round_for_second_document()`，覆盖已有面评、`force=false`、session 标题/描述标明二面但评价 payload 无 round 时，应写入 `bitableSecondInterviewEvaluationDocument`。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，实际写入 `bitableSkillEvaluationDocument`，证明当前实现只看评价 payload 的 round。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k session_round_for_second_document`：1 passed，65 deselected，1 个既有 `StarletteDeprecationWarning`。
  - Backfill 切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "syncs_missing_evaluation_document or session_round_for_second_document or second_interview_evaluation_field or backfill_persists_evaluation"`：4 passed，62 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：66 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：79 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：313 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 当前只补齐旧 Node 二面关键词推导中的关键字段来源；真实 Bitable 写入、飞书文档权限和线上历史 session 仍需在授权环境做端到端联调确认。
  - 轮次关键词仍集中在 backfill 兼容层；后续如果面试中心其他链路也需要完全一致的轮次判断，可以再抽到共享 helper。

---

### 快照 0086：回灌生成异常保存失败态

- 修改时间：2026-07-03 05:00:51 +08:00
- 修改原因：
  - 旧 Node 面试中心在进入 `backfillSession()` 的真实回灌流程后，如果会议来源读取、面评生成或后续处理抛错，会捕获异常、保存 `backfill_failed`、写入 `lastBackfillError` 和 error 日志，然后返回失败 session。
  - 当前 FastAPI `BackfillService.backfill()` 在面评生成器抛出 `ValueError/KeyError` 时会直接把异常抛给 API，绕过失败态持久化；例如 LLM JSON 解析失败会让旧页面看到请求失败，而不是可审计的回灌失败 session。
  - 该行为会影响自动回灌调度的错误归档和页面查看失败原因，和旧服务不一致。
- 修改文件：
  - `app/features/interview_center/backfill.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `BackfillService.backfill()` 在加入运行中集合后初始化本轮 `source`，进入回灌流程后的异常统一保存为 `backfill_failed` 并返回 session，不再直接抛出。
  - `_save_failed()` 新增可选 `log_level/log_message`，空来源失败继续走 warn；生成/处理异常走旧 Node 风格 error 日志，日志消息保留原异常内容。
  - 新增 `test_backfill_marks_session_failed_when_evaluation_generation_errors_like_old_node()`，覆盖有效会议文本存在但评价生成器抛 `ValueError` 时，服务返回失败 session、记录 `lastBackfillError/backfillAttempts`，且不污染简历库中的 `interviewEvaluation`。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，`ValueError: llm_json_parse_failed` 从 `FailingEvaluationGenerator.generate()` 直接冒泡，证明当前实现没有保存失败态。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k evaluation_generation_errors`：1 passed，66 deselected，1 个既有 `StarletteDeprecationWarning`。
  - Backfill 切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "backfill_fails_when_sources_are_empty or evaluation_generation_errors or backfill_persists_evaluation or backfill_keeps_evaluation or syncs_missing_evaluation_document or session_round_for_second_document or backfill_api"`：11 passed，56 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：67 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：80 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：314 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复“已进入回灌流程后的异常落失败态”行为；会话不存在、未绑定简历、10 分钟保护等前置校验仍按旧 API 错误响应抛出。
  - 如果后续要完全复刻旧 Node 提前回灌失败时写入 `earlyBackfillOverride.failedAt`，需要增加单独测试后继续补齐。

---

### 快照 0087：保存提前回灌失败审计时间

- 修改时间：2026-07-03 05:10:31 +08:00
- 修改原因：
  - 旧 Node 面试中心在一次性提前回灌授权通过后，会先写入 `earlyBackfillOverride.requestedAt/requestedBeforeAvailableAt`；如果后续回灌流程抛错，则保存 `earlyBackfillOverride.failedAt`，保留人工提前读取会议纪要但失败的审计轨迹。
  - 当前 FastAPI 上一轮只把生成异常落成 `backfill_failed`，但提前回灌失败时没有写 `failedAt`；旧页面和后续人工排查无法区分“授权未使用”和“授权已用但回灌失败”。
  - 该审计字段是提前绕过 10 分钟保护时的重要安全边界，需要和旧服务保持一致。
- 修改文件：
  - `app/features/interview_center/backfill.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 进入真实回灌流程且 `allow_early_backfill=true` 时，先写入 `_requested_early_override_payload()`，保留 `requestedAt/requestedBeforeAvailableAt/availableAt/reason`。
  - 回灌流程异常失败时写入 `_failed_early_override_payload()`，保留旧 payload 并补充 `failedAt/availableAt/reason`；成功路径仍使用既有 `usedAt` 逻辑。
  - 新增 `test_backfill_old_early_override_failure_records_failed_at()`，覆盖授权提前回灌、面评生成异常、返回失败 session 且审计 payload 写入 `failedAt`，同时不写 `usedAt`。
- 验证结果：
  - 红灯确认：新增测试首次运行失败，`earlyBackfillOverride` 缺少 `failedAt`，证明当前实现没有保存提前回灌失败审计时间。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k old_early_override_failure_records_failed_at`：1 passed，67 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 提前回灌切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "old_one_off_early_override_token or old_early_override_failure or invalid_old_early_override or requires_force_for_old_early_override or old_early_override_reason or evaluation_generation_errors or backfill_fails_when_sources_are_empty"`：7 passed，61 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：68 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：81 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：315 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮恢复的是提前回灌失败审计字段；真实飞书会议/妙记来源读取失败时的端到端审计仍需在授权环境中联调确认。
  - 旧 Node 空会议来源失败只保留 requested payload、不写 failedAt；当前实现保持这一点，未把空来源失败扩大为异常失败审计。

---

### 快照 0088：恢复准备接口旧响应包裹

- 修改时间：2026-07-03 05:17:20 +08:00
- 修改原因：
  - 旧 Node `POST /api/interview-center/sessions/{id}/prepare` 返回 `{ ok:true, session, logs }`，旧前端的请求层会按 `ok` 和 `logs` 展示操作结果。
  - 当前 FastAPI prepare 路由直接返回 service payload，只有 `session`，缺少旧协议中的 `ok` 和 `logs`；这会让旧页面和其它旧调用方无法用统一方式判断准备动作成功。
  - bind/backfill/review 等相邻旧接口已经恢复了 `ok/logs` 包裹，prepare 需要保持同一协议形态。
- 修改文件：
  - `app/api/routes/interview.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `prepare_session()` 路由改为先调用 service，再返回 `{ ok:true, ...result, logs: store.list_logs("", 50) }`。
  - 扩展 `test_prepare_session_api_route_is_compatible()`，断言 prepare API 响应包含 `ok:true` 和 `logs` 数组，同时继续校验 `session.status` 与 `feishuDoc`。
- 验证结果：
  - 红灯确认：扩展测试首次运行失败，`response.json()["ok"]` 抛出 `KeyError`，证明当前 prepare API 缺少旧协议字段。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k prepare_session_api_route_is_compatible`：1 passed，67 deselected，1 个既有 `StarletteDeprecationWarning`。
  - API 切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "prepare_session or bind_and_sessions_api_routes_are_compatible or backfill_api_routes_are_compatible or review_confirm_and_logs_api_routes_are_compatible"`：7 passed，61 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：68 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：81 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：315 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复 prepare API 的旧 JSON 包裹，不改变 `InterviewCenterService.prepare_session()` 的内部返回结构。
  - 旧前端仍可能依赖其它细小字段顺序或文案；后续继续按旧 Node 路由逐项对照。

---

### 快照 0089：对齐绑定接口旧校验顺序

- 修改时间：2026-07-03 05:30:02 +08:00
- 修改原因：
  - 旧 Node `POST /api/interview-center/sessions/{id}/bind` 会先用请求体里的 `resumeId` 查候选人简历，找不到简历时立即返回 `候选人简历不存在`，之后才检查面试日程是否存在。
  - 当前 FastAPI `InterviewCenterService.bind_session()` 先检查 session，再检查 resume；当旧前端空 body 或缺 resumeId 且 session id 不存在时，会返回 `面试日程不存在`，和旧入口错误优先级不一致。
  - 旧前端会直接展示 `error` 文案，错误优先级变化会影响用户排查绑定失败原因。
- 修改文件：
  - `app/features/interview_center/service.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `bind_session()` 调整为先 `_load_resume(resume_id)`，简历不存在时抛 `resume_not_found`，再 `_require_session(session_id)`。
  - 扩展 `test_bind_api_accepts_empty_body_like_old_node()`，覆盖空 body 且 session 存在、空 body 且 session 不存在两个场景都返回旧文案 `候选人简历不存在`。
- 验证结果：
  - 红灯确认：扩展测试首次运行失败，未知 session + 空 body 实际返回 `面试日程不存在`，证明当前校验顺序和旧 Node 不一致。
  - 聚焦验证：`C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent\.venv312\Scripts\python.exe -m pytest tests/features/test_interview_center_migration.py -q -k bind_api_accepts_empty_body_like_old_node`：1 passed，67 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 绑定/准备切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "bind_session or bind_and_sessions_api_routes_are_compatible or bind_api_accepts_empty_body_like_old_node or prepare_session_api_route_is_compatible or list_sessions"`：6 passed，62 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 目标验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：68 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：81 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：315 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只调整 bind 旧入口的校验优先级；service 直接调用方如果传入无效 resume 和无效 session，现在也会按旧入口先报 resume 缺失。
  - 其它旧入口仍需继续按路由逐项对照错误优先级和响应文案。

---

### 快照 0090：恢复回灌来源旧回退

- 修改时间：2026-07-03 05:45:14 +08:00
- 修改原因：
  - 旧 Node 面试中心 `GET /api/interview-center/sessions/{id}/backfill-source` 会按 `session.backfillSource || session.interviewEvaluation?.source || {}` 返回来源，并同时返回 `lastBackfillError`。
  - 当前 FastAPI 迁移实现只读取 `session.backfill_source`，当历史 session 只有 `interviewEvaluation.source` 时，旧前端无法看到已回灌来源；同时接口缺少旧协议中的 `lastBackfillError` 字段。
  - 该差异会影响旧页面展示回灌来源和排查最近一次回灌失败原因，需要与旧服务响应保持一致。
- 修改文件：
  - `app/features/interview_center/service.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `InterviewCenterService.backfill_source()` 现在优先返回 `session.backfill_source`，为空时回退到 `session.interview_evaluation.source`，最后才返回空来源，并继续通过 `public_backfill_source()` 归一化旧前端需要的字段。
  - `/backfill-source` 服务 payload 新增 `lastBackfillError`，由路由继续包裹 `ok:true` 后返回，贴齐旧 Node 协议。
  - 新增 `test_backfill_source_falls_back_to_evaluation_source_like_old_node()`，覆盖 `backfillSource` 为空、历史 `interviewEvaluation.source` 存在时的 fallback、字段归一化和 `lastBackfillError` 返回。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k backfill_source_falls_back` 首次失败，`payload["source"]["source"]` 抛 `KeyError`，证明当前实现没有旧来源回退。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k backfill_source_falls_back`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "backfill_source_falls_back or backfill_source_payload_is_normalized_like_old_node or backfill_api_routes_are_compatible"`：3 passed，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：69 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：82 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：316 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复旧 `backfill-source` 读取优先级和错误字段，不改变真实回灌、面评生成、Bitable 或飞书会议来源读取链路。
  - 真实 Feishu/妙记/Bitable 授权环境下的端到端回灌来源展示仍需后续联调确认。

---

### 快照 0091：恢复飞书回调缺 code 旧文案

- 修改时间：2026-07-03 05:54:52 +08:00
- 修改原因：
  - 旧 Node 面试中心 `GET /api/interview-center/feishu/oauth/callback` 在缺少 `code` 参数时返回 400 HTML，页面文案为 `飞书授权失败：缺少 code`。
  - 当前 FastAPI HTML 失败页直接展示 service 抛出的内部错误码 `missing_feishu_oauth_code`，旧前端/用户看到的是工程码而不是旧系统文案。
  - OAuth callback 是用户授权后的浏览器可见入口，错误页需要保持旧体验并避免暴露内部码。
- 修改文件：
  - `app/api/routes/interview.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `missing_feishu_oauth_code` 新增旧错误文案映射为 `缺少 code`。
  - `feishu_oauth_callback()` 的 HTML 错误分支改为使用 `_legacy_error_message(exc)`，和 JSON 旧错误响应共享同一映射。
  - `test_feishu_oauth_callback_missing_code_uses_old_html_error()` 改为断言 HTML 包含 `飞书授权失败：缺少 code`，并确认不再暴露 `missing_feishu_oauth_code`。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k missing_code_uses_old_html_error` 首次失败，实际 HTML 仍包含 `missing_feishu_oauth_code`。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k missing_code_uses_old_html_error`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - OAuth 切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "feishu_oauth_callback or feishu_auth_url or feishu_status or disconnect"`：6 passed，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：69 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：82 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：316 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复 OAuth callback 缺 `code` 的旧 HTML 文案，不改变授权码交换、token 保存或真实飞书 OAuth 联调路径。
  - 真实飞书 OAuth 授权码交换仍需在有飞书应用配置和授权用户的环境里端到端验证。

---

### 快照 0092：兼容旧入口畸形 JSON 请求体

- 修改时间：2026-07-03 06:03:29 +08:00
- 修改原因：
  - 旧 Node 面试中心在 `sync`、`prepare`、`backfill`、`review/confirm` 入口使用 `readJsonBody(request).catch(() => ({}))`，请求体 JSON 解析失败时会按空对象继续处理。
  - 当前 FastAPI 这些入口直接声明 Pydantic body 参数，畸形 JSON 会在路由层返回 422，旧前端无法得到 `{ ok:true/false, ... }` 的旧协议响应。
  - 这些入口都属于旧页面按钮动作，解析失败时默认空 body 的兼容行为需要保留；`bind` 旧实现没有 catch，本轮不改变。
- 修改文件：
  - `app/api/routes/interview.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `_legacy_optional_body()`，在旧 action 路由内部读取 JSON；解析失败、非对象 body 或校验失败时回退到对应请求模型默认值。
  - `sync_calendar()`、`prepare_session()`、`backfill_session()`、`review_session()`、`confirm_session()` 改为内部调用该 helper，避免 FastAPI 在进入路由前返回 422。
  - 新增 `test_old_action_routes_treat_malformed_json_body_as_empty_like_old_node()`，覆盖畸形 JSON 下 `sync` 默认自动准备、`prepare` 默认非 force、`backfill` 默认非 force、`review` 默认 passed。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k malformed_json_body_as_empty` 首次失败，`/api/interview-center/sync` 实际返回 422。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k malformed_json_body_as_empty`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - Action 路由切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "malformed_json_body_as_empty or sync_api or prepare_session_api_route_is_compatible or backfill_api_routes_are_compatible or review_confirm_and_logs_api_routes_are_compatible or review_and_confirm_api_accept_empty_body"`：7 passed，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：70 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：83 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：317 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只改变旧 Node 明确容错的 action 路由；`bind` 保持原有严格解析路径，避免扩大行为差异。
  - 对字段类型非法但 JSON 有效的请求，本轮按模型默认值容错；如旧前端存在特殊类型转换依赖，后续可继续按旧 Node 的 `Boolean()`/默认值规则补充用例。

---

### 快照 0093：恢复同步入口旧 JS 参数语义

- 修改时间：2026-07-03 06:12:04 +08:00
- 修改原因：
  - 旧 Node `POST /api/interview-center/sync` 使用 `body.calendarId || "primary"`、`body.autoPrepare !== false`、`body.autoPrepareLimit || context.autoPrepareLimit || 12`。
  - 当前 FastAPI 通过 Pydantic 解析请求体，`autoPrepare: "false"` 会被解析成 `False`，空 `calendarId` 会保留为空字符串，`autoPrepareLimit: 0` 会保留为 0，和旧 JavaScript 真值/默认值规则不一致。
  - 旧入口可能被历史页面或脚本以字符串/假值形式调用，同步和自动准备行为需要贴齐旧服务。
- 修改文件：
  - `app/api/routes/interview.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `_legacy_json_object()` 复用旧入口“JSON 解析失败则空对象”的读取逻辑。
  - 新增 `_legacy_sync_request()`：空 `calendarId` 回退 `primary`；只有 JSON 布尔 `false` 才关闭 `autoPrepare`；`autoPrepareLimit` 假值或非法值回退 12。
  - `sync_calendar()` 改为使用 `_legacy_sync_request()`，其它旧 action 继续使用通用 `_legacy_optional_body()`。
  - 新增 `test_interview_center_sync_uses_old_js_body_defaults()`，覆盖 `calendarId:""`、`autoPrepare:"false"`、`autoPrepareLimit:0` 时仍按旧 Node 自动准备并使用 `primary` 日历。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k sync_uses_old_js_body_defaults` 首次失败，实际 `prepared` 为 0，证明 `autoPrepare:"false"` 被当成了关闭自动准备。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k sync_uses_old_js_body_defaults`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - Sync/action 切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "sync_api or sync_uses_old_js_body_defaults or malformed_json_body_as_empty"`：4 passed，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：71 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：84 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：318 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复 sync 入口的旧 JavaScript 参数语义；prepare/backfill 的 `Boolean(body.force)` 等字符串真值行为仍可继续按旧 Node 逐项补齐。
  - `autoPrepareLimit` 对非法真值字符串当前回退 12，避免把不可比较值传入 Python 服务；如果旧脚本依赖更怪异的 JS 比较行为，需要另行加用例。

---

### 快照 0094：恢复准备和回灌旧布尔参数语义

- 修改时间：2026-07-03 06:23:57 +08:00
- 修改原因：
  - 旧 Node `prepare` 和 `backfill` 入口使用 `Boolean(body.force)`，`backfill` 还使用 `Boolean(body.earlyOverride)`；因此字符串 `"false"` 在旧服务中属于真值，会触发强制准备/强制回灌。
  - 当前 FastAPI 通过 Pydantic 解析请求体，`"false"`、`"0"` 等字符串会被解析为 `False`，导致旧脚本或旧页面传入字符串时行为和旧 Node 不一致。
  - 该差异会让本该强制重建问题文档或重新回灌面评的操作被静默当成非 force，尤其会保留旧文档或旧面评。
- 修改文件：
  - `app/api/routes/interview.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `_legacy_js_boolean()`，按 JavaScript `Boolean()` 语义处理 JSON 值：`None/false/0/""` 为 false，其它值为 true。
  - 新增 `_legacy_prepare_request()` 和 `_legacy_backfill_request()`，使 prepare/backfill 旧入口按 Node 的 `Boolean(body.force)` / `Boolean(body.earlyOverride)` 解析。
  - `prepare_session()` 和 `backfill_session()` 路由改用旧布尔解析；review/confirm 继续使用通用旧 body helper。
  - 新增 `test_prepare_api_uses_old_js_boolean_force_semantics()`，覆盖 `force:"false"` 会强制重建飞书文档。
  - 新增 `test_backfill_api_uses_old_js_boolean_force_semantics()`，覆盖 `force:"false"` 会重新采集会议来源并生成新面评，而不是早返回旧面评。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "old_js_boolean_force_semantics"` 首次 2 failed；prepare 返回旧 `old-doc`，backfill 状态保持 `created`，证明字符串 `"false"` 被当成了 false。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "old_js_boolean_force_semantics"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - Action 切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "old_js_boolean_force_semantics or malformed_json_body_as_empty or prepare_session_api_route_is_compatible or backfill_api_routes_are_compatible or backfill_api_requires_force_for_old_early_override_token"`：6 passed，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：73 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：86 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：320 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复 prepare/backfill 的旧布尔解析；如果旧入口其它字段还存在 JavaScript 类型转换依赖，后续继续按旧 Node 逐项补齐。
  - 对 JSON 对象/数组作为布尔字段的极端输入，当前按 JS 真值处理；这是为了贴齐旧入口，不代表新 API 推荐这样调用。

---

### 快照 0095：恢复复核入口旧备注解析与裁剪

- 修改时间：2026-07-03 06:35:12 +08:00
- 修改原因：
  - 旧 Node `review/confirm` 入口对 `decision` 使用 `String(body.decision || "").trim()` 独立归一化，对 `note` 使用 `clipText(body.note || "", 1000)`。
  - 当前 FastAPI 复核入口仍通过 Pydantic 对整个 body 做统一校验；当 `note` 是数字等旧 Node 可接受值时，会触发校验失败并把有效 `decision` 一起丢成默认 `passed`。
  - 当前服务层保存备注只做 `[:1000]`，没有恢复旧 `clipText` 的 trim 和超长追加 `...` 行为。
- 修改文件：
  - `app/api/routes/interview.py`
  - `app/features/interview_center/service.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `_legacy_review_request()`，让 `review` 和 `confirm` 按旧 Node 逐字段解析请求体，不再因为 `note` 类型导致 `decision` 回退。
  - 新增 `_legacy_js_string()`，覆盖旧入口常见 JSON 值到 JavaScript `String()` 的兼容转换。
  - `InterviewCenterService.review_session()` 保存备注时改用 `_legacy_clip_text(note, 1000)`，恢复 trim、空值归空、超长追加 `...` 的旧行为。
  - 新增 `test_review_api_preserves_decision_when_note_uses_old_js_string_semantics()`，覆盖 `note:123` 时仍保留 `decision:"need_followup"` 并保存备注 `"123"`。
  - 新增 `test_review_api_clips_note_like_old_node_clip_text()`，覆盖带空格的 1001 字符备注会 trim 后保存为前 1000 字符加 `...`。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "review_api_preserves_decision_when_note_uses_old_js_string_semantics or review_api_clips_note_like_old_node_clip_text"` 首次 2 failed；第一条状态从 `needs_review` 误变 `completed`，第二条备注保留前导空格且没有追加 `...`。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "review_api_preserves_decision_when_note_uses_old_js_string_semantics or review_api_clips_note_like_old_node_clip_text"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - Review 切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "review"`：5 passed，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：75 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：88 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：322 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复 review/confirm 的旧备注解析与裁剪；backfill 的 `earlyOverrideReason`/`earlyOverrideToken` 仍可继续按旧 Node 的更多类型转换细节逐项补齐。
  - `_legacy_js_string()` 已覆盖常见 JSON 值；极端对象/数组输入按旧 JavaScript 字符串化近似处理，用于兼容旧入口，不代表新 API 推荐传入复杂类型。

---

### 快照 0096：恢复提前回灌理由旧字符串与裁剪

- 修改时间：2026-07-03 06:43:25 +08:00
- 修改原因：
  - 旧 Node `backfill` 入口对 `earlyOverrideReason` / `earlyOverrideToken` 使用 `body.xxx || ""`，后续理由保存通过 `clipText(..., 300)` 做 JavaScript 字符串化、trim 和超长追加 `...`。
  - 当前 FastAPI backfill 入口直接 `str(raw_body.get(...) or "")`，对象会保存成 Python 字典字符串；服务层理由保存也只是 `[:300]`，没有旧 `clipText` 的 trim 和省略号语义。
  - 该差异会让旧页面或脚本传入非字符串理由时，审计记录与旧服务不一致，也会让超长理由裁剪格式不同。
- 修改文件：
  - `app/api/routes/interview.py`
  - `app/features/interview_center/backfill.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `_legacy_backfill_request()` 的 `earlyOverrideReason` 和 `earlyOverrideToken` 改用 `_legacy_js_string()`，贴齐旧 Node 的常见 JSON 值字符串化。
  - backfill 提前回灌的 requested / used / failed reason 保存改用本地 `_legacy_clip_text(..., 300)`，恢复 trim、空值归空、超长追加 `...`。
  - 新增 `test_backfill_api_uses_old_js_string_semantics_for_early_override_reason()`，覆盖对象理由保存为旧 JavaScript 的 `[object Object]`。
  - 新增 `test_backfill_api_clips_early_override_reason_like_old_node_clip_text()`，覆盖带空格的 301 字符理由保存为前 300 字符加 `...`。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "early_override_reason_like_old_node or old_js_string_semantics_for_early_override_reason"` 首次 2 failed；对象理由实际保存为 `{'source': 'manual'}`，长理由保留前导空格且没有追加 `...`。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "early_override_reason_like_old_node or old_js_string_semantics_for_early_override_reason"`：2 passed，1 个既有 `StarletteDeprecationWarning`。
  - Backfill 切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "backfill"`：21 passed，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：77 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：90 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：324 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只恢复提前回灌理由和 token 的入口字符串化，以及 reason 保存裁剪；其它旧 Node 小型类型转换差异仍继续按路由逐项对照。
  - `_legacy_clip_text()` 在 backfill 模块内保持局部实现，后续若多个模块继续需要旧 `clipText`，可以再在有测试覆盖后提取共享 helper。

---

### 快照 0097：恢复会话列表只返回面试日程

- 修改时间：2026-07-03 06:50:34 +08:00
- 修改原因：
  - 旧 Node `GET /api/interview-center/sessions` 在返回前执行 `.filter((item) => item.isInterviewLike)`，只有明确识别为面试的日程会进入旧面试中心列表。
  - 当前 FastAPI 服务层只排除 `isInterviewLike is False`，缺失 `isInterviewLike` 字段的未识别日程仍会被返回。
  - 该差异会让旧面试中心页面混入未识别日程或普通日程，影响后续绑定、准备和回灌判断。
- 修改文件：
  - `app/features/interview_center/service.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `InterviewCenterService.list_sessions()` 改为要求 `session.payload["isInterviewLike"]` 为真才返回，贴齐旧 Node 真值过滤。
  - `create_session_from_resume()` 和 `create_session_from_payload()` 创建的本地面试中心会话显式写入 `isInterviewLike:true`，避免旧列表过滤误伤现有本地创建流程。
  - 扩展 `test_sessions_api_uses_old_default_time_window()`，加入时间窗口内但缺失 `isInterviewLike` 的会话，并断言旧 sessions 接口不会返回它。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "sessions_api_uses_old_default_time_window"` 首次 1 failed；默认 sessions 列表多返回了缺失 `isInterviewLike` 的会话。
  - 聚焦验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "sessions_api_uses_old_default_time_window"`：1 passed，1 个既有 `StarletteDeprecationWarning`。
  - Sessions/List 切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "sessions_api or list_sessions or bind_and_sessions_api_routes_are_compatible"`：5 passed，1 个既有 `StarletteDeprecationWarning`。
  - 兼容回归发现：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q` 首次 1 failed；`test_interview_center_api_routes_are_wired` 中本地创建会话后旧列表为空，证明需要给本地创建会话补 `isInterviewLike:true`。
  - 本地创建回归验证：同一 Python 运行 `-m pytest tests/features/test_phase6_interview_center.py -q -k "interview_center_api_routes_are_wired"`：1 passed，5 deselected，1 个既有 `StarletteDeprecationWarning`。
  - 迁移测试：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q`：77 passed，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_phase7a_persistence.py -q`：90 passed，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 全量回归：同一 Python 运行 `-m pytest -q`：324 passed，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 该行为只影响旧 `/api/interview-center/sessions` 列表语义；如果后续有新入口需要展示所有手工创建会话，应另走新接口或显式标记 `isInterviewLike`。
  - 本轮没有触碰 calendar sync 的识别规则，后续仍需通过本地服务烟测确认真实日历同步后的旧列表展示。

---

### 快照 0098：忽略面试中心本地运行产物

- 修改时间：2026-07-03 07:18:36 +08:00
- 修改原因：
  - 本地迁移服务烟测创建面试会话时会生成 `data/interview_center/*_summary.png`，该目录属于运行时产物，不应进入 Git。
  - 当前分支也缺少 `data/sync_packages/` 和 `data/backups/` 的忽略规则，简历同步包与数据库备份同样属于本地/部署运行数据。
  - 需要降低后续提交时误提交候选人资料、面试图片和数据库备份的风险。
- 修改文件：
  - `.gitignore`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `.gitignore` 新增 `data/interview_center/`、`data/sync_packages/`、`data/backups/`。
  - 本地烟测生成的 summary PNG 已被忽略，工作区不再暴露该运行时文件。
- 验证结果：
  - `git check-ignore -v data/interview_center/466aab36-88af-4f45-9300-47c7539c7f22_summary.png`：命中 `.gitignore:16:data/interview_center/`。
  - `git check-ignore -v data/sync_packages/example.zip`：命中 `.gitignore:17:data/sync_packages/`。
  - `git check-ignore -v data/backups/example.json`：命中 `.gitignore:18:data/backups/`。
  - `git status --short --branch --untracked-files=all`：只剩 `.gitignore` 和本快照文档修改。
- 风险 / 待确认：
  - 本轮只调整 Git 忽略规则，不删除本地已有运行时文件，不改变面试中心业务逻辑。

---

### 快照 0099：消除面试中心独立页 favicon 404

- 修改时间：2026-07-03 07:24:00 +08:00
- 修改原因：
  - 本地 Playwright 打开 `/interview-center.html` 时，页面业务资源均为 200，但 Chrome 控制台出现一个 404。
  - 进一步捕捉 response 列表确认页面脚本、样式和 API 均无 4xx；根因是独立页没有 favicon 声明，浏览器自动请求缺失图标。
  - 需要让面试中心独立页浏览器烟测达到无 4xx、无控制台错误，避免把无关资源缺失误判为业务问题。
- 修改文件：
  - `frontend/interview-center.html`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `/interview-center.html` 的 `<head>` 新增 `<link rel="icon" href="data:," />`，避免浏览器自动请求 `/favicon.ico`。
  - 面试中心前端静态资源测试新增 favicon 声明断言。
- 验证结果：
  - 红灯确认：`python -m pytest tests/features/test_interview_center_migration.py -q -k frontend_page_and_assets_are_served` 首次失败，断言缺少 `<link rel="icon" href="data:," />`。
  - 绿灯验证：同一命令再次运行：1 passed，76 deselected，1 个既有 `StarletteDeprecationWarning`。
  - `node --check frontend\interview-center\app.js`：通过。
  - 本地服务 `http://127.0.0.1:18182/interview-center.html` 复查：favicon 声明和 `/assets/interview-center/*` 引用均可读。
  - Playwright + 系统 Chrome 烟测：标题为“面试中心”，飞书状态为“飞书未授权”，会话数为 `1`，`bad_responses=[]`，`console_errors=[]`，截图写入 `data/diagnostics/interview-center-smoke.png`。
- 风险 / 待确认：
  - 本轮只影响独立面试中心 HTML 的浏览器资源加载，不改变业务 API 或面试中心状态流。

---

### 快照 0100：修正飞书 OAuth 缺回调地址时的配置状态

- 修改时间：2026-07-03 07:53:23 +08:00
- 修改原因：
  - 本地运行态烟测发现 `/api/interview-center/feishu/auth-url` 返回 `configured:true`，但 `redirectUri` 为空。
  - 旧面试中心的飞书授权链路需要 app id、app secret 和 redirect URI 三项同时可用；只凭 app id/secret 就提示已配置，会让旧页面展示一个实际不可用的授权入口。
  - 需要让 `/feishu/auth-url` 和 `/feishu/status` 对“OAuth 是否配置完整”使用同一口径。
- 修改文件：
  - `app/features/interview_center/feishu/oauth.py`
  - `tests/features/test_interview_center_migration.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 新增 `_is_oauth_configured()`，要求 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_REDIRECT_URI` 都存在时才返回 `configured:true`。
  - `/api/interview-center/feishu/auth-url` 和 `/api/interview-center/feishu/status` 共用该判断。
  - 新增 `test_feishu_oauth_reports_unconfigured_without_redirect_uri()`，覆盖 app id/secret 存在但 redirect URI 缺失时两个旧接口都返回 `configured:false`。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "oauth_reports_unconfigured_without_redirect_uri"` 首次失败，实际 `auth_url.json()["configured"]` 为 `True`。
  - 绿灯验证：同一命令再次运行：`1 passed, 77 deselected`，1 个既有 `StarletteDeprecationWarning`。
  - OAuth 切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py -q -k "feishu_oauth or feishu_auth_url or feishu_status or disconnect or oauth_reports"`：`8 passed, 70 deselected`，1 个既有 `StarletteDeprecationWarning`。
  - 面试中心切片验证：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py -q`：`84 passed`，1 个既有 `StarletteDeprecationWarning`。
  - 全量回归：同一 Python 运行 `-m pytest -q`：`325 passed`，1 个既有 `StarletteDeprecationWarning`。
  - 静态检查：同一 Python 运行 `-m ruff check app tests`：All checks passed。
  - 编译检查：同一 Python 运行 `-m compileall app scripts run_control_plane.py run_worker.py`：通过。
  - 前端语法检查：`node --check frontend/app.js`、`node --check frontend/interview-center/app.js`、`node --check frontend/interview-center/api.js`、`node --check frontend/interview-center/state.js` 均通过。
  - 本地 HTTP smoke：用 `CONTROL_PLANE_PORT=18182` 和临时 `DATABASE_PATH=%TEMP%\hr-agent-interview-center-smoke-18182.sqlite` 启动服务，真实 HTTP 覆盖 `/health`、`/interview-center.html`、`/assets/interview-center/*`、`/api/interview-center/sessions`、`/sync/status`、`POST /sync`、`/backfill/status`、`/feishu/auth-url`、`/feishu/status`、`POST /feishu/disconnect`、未知旧路径 404；全部符合预期，其中空 `redirectUri` 时 `configured=False`。
  - Playwright + 系统 Chrome 烟测：打开 `http://127.0.0.1:18182/interview-center.html`，`.interview-shell` 存在，`bad_responses=[]`，`console_errors=[]`，`page_errors=[]`。服务已关闭。
- 风险 / 待确认：
  - 本轮只修正 OAuth 配置完整性展示，不改变授权码交换、token 保存、日历读取、Docx 写入或 Bitable 写入逻辑。
  - 真实飞书 OAuth 端到端仍需要在设置了有效 `FEISHU_REDIRECT_URI` 且飞书应用后台已登记同一回调地址的环境中联调确认。

---

### 快照 0101：闭环面试中心迁移计划勾选状态

- 修改时间：2026-07-03 07:58:27 +08:00
- 修改原因：
  - 完成度审计发现 `docs/superpowers/plans/2026-07-02-interview-center-migration.md` 仍保留 34 个 `- [ ]` 未完成项。
  - 当前代码、测试、快照和本地烟测已经覆盖 Task 1-8 的本地迁移验收范围；计划文件继续显示未完成会让后续审计误判迁移状态。
  - 需要在计划文件中显式补充最新验证证据和真实 Feishu 环境仍需联调的边界，避免把本地 mock/dry-run 证据扩大解释成真实外部系统已联通。
- 修改文件：
  - `docs/superpowers/plans/2026-07-02-interview-center-migration.md`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - 将 Task 1-8 的执行复选项从 `- [ ]` 更新为 `- [x]`。
  - 在计划末尾新增 `Completion Evidence`，记录当前分支、已验证提交、快照范围、核心旧路由、前端入口和 2026-07-03 的测试/静态/HTTP/Playwright 证据。
  - 新增 `Remaining External Verification`，明确真实 Feishu OAuth、日历、Docx、妙记/会议纪要和 Bitable 写入仍依赖授权环境联调。
- 验证结果：
  - `rg -n "^- \[ \]" docs/superpowers/plans/2026-07-02-interview-center-migration.md`：无输出，计划中不再有未勾选执行项。
  - `rg -n "Completion Evidence|Remaining External Verification|^- \[x\]" docs/superpowers/plans/2026-07-02-interview-center-migration.md`：能定位完成证据、剩余外部验证段落和已勾选任务。
  - `git diff --check`：通过，无空白错误。
- 风险 / 待确认：
  - 本轮仅同步计划/快照文档状态，不改变 Python、前端或数据库逻辑。
  - 计划勾选代表本地迁移与兼容测试范围已闭环；真实 Feishu 外部系统联调仍按新增 `Remaining External Verification` 保留为环境依赖项。

---

### 快照 0102：补齐面试中心飞书联调样例环境项

- 修改时间：2026-07-03 08:21:45 +08:00
- 修改原因：
  - 18080 已切换到迁移 worktree 后，飞书 OAuth 配置已能读到 `FEISHU_REDIRECT_URI`，但真实 Bitable 写入仍缺 `FEISHU_BITABLE_APP_TOKEN`。
  - 进一步审计发现主 `.env` 和 `.env.example` 都没有 Bitable app token 相关变量；其中 `.env.example` 也缺少 `FEISHU_REDIRECT_URI`、候选人表和面试表配置项。
  - `.env.example` 是本地部署和真实联调的入口说明，缺少这些键会让后续环境准备继续误判为代码问题。
- 修改文件：
  - `.env.example`
  - `tests/domain/test_settings_env_file.py`
  - `docs/change-snapshots-3.md`
- 修改结果：
  - `.env.example` 的飞书配置块新增 `FEISHU_REDIRECT_URI`、`FEISHU_BITABLE_APP_TOKEN`、`FEISHU_CANDIDATE_TABLE_ID`、`FEISHU_INTERVIEW_TABLE_ID`。
  - 新增 `test_env_example_documents_interview_center_feishu_keys()`，防止样例配置再次漏掉面试中心真实联调所需飞书键。
- 验证结果：
  - 红灯确认：同一 Python 运行 `-m pytest tests/domain/test_settings_env_file.py -q` 首次失败，实际缺少 `FEISHU_REDIRECT_URI=`。
  - 绿灯验证：同一命令再次运行：`2 passed`。
  - 面试中心兼容切片：同一 Python 运行 `-m pytest tests/features/test_interview_center_migration.py tests/features/test_phase6_interview_center.py tests/domain/test_settings_env_file.py -q`：`86 passed`，1 个既有 `StarletteDeprecationWarning`。
- 风险 / 待确认：
  - 本轮只补 `.env.example` 和对应测试，不写入真实密钥，不改变 18080 当前运行环境。
  - 真实 Bitable 写入仍需要在本机 `.env` 中配置有效 `FEISHU_BITABLE_APP_TOKEN`，并确认飞书应用拥有对应 Base/Bitable 权限。
