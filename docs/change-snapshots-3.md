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
