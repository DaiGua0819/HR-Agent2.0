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
