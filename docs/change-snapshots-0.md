# HR Agent 重构修改快照 0

> 本文档用于记录 `hr-agent` 重构版的每次重要改动。单个快照文件最多 600 行；超过后在同一路径新建下一个文件，例如 `change-snapshots-1.md`、`change-snapshots-2.md`，序号从 0 开始。

## 记录规则

- 每次代码或配置改动后追加一条快照。
- 每条快照必须包含：修改时间、修改原因、修改文件、修改结果。
- 修改文件尽量写相对路径，便于后续审查。
- 如果一次改动包含测试或验证，也记录验证结果。
- 如果存在风险、待确认点或未执行测试，需要明确写出来。

## 快照模板

```text
### 快照 NNNN：标题

- 修改时间：YYYY-MM-DD HH:mm:ss +08:00
- 修改原因：
  - ...
- 修改文件：
  - ...
- 修改结果：
  - ...
- 验证结果：
  - ...
- 风险 / 待确认：
  - ...
```

---

### 快照 0001：建立修改快照文档

- 修改时间：2026-06-26 14:58:48 +08:00
- 修改原因：
  - 需要在重构版项目内固定记录每次改动，避免后续功能边界、修改原因和验证结果丢失。
  - 需要控制单个 Markdown 文档长度，超过 600 行后按序号拆分，保持记录可读。
- 修改文件：
  - `docs/change-snapshots-0.md`
- 修改结果：
  - 新增第 0 份修改快照文档。
  - 明确每条快照必须记录修改时间、修改原因、修改文件、修改结果。
  - 明确文件超过 600 行后，按 `change-snapshots-1.md`、`change-snapshots-2.md` 继续新建。
- 验证结果：
  - 本次仅新增文档，未运行自动化测试。
- 风险 / 待确认：
  - 后续每次代码改动需要同步追加快照，否则文档会失去追踪价值。

---

### 快照 0002：补全 51job / 智联未读处理逻辑

- 修改时间：2026-06-26 15:01:00 +08:00
- 修改原因：
  - BOSS 消息处理规则已补齐后，需要让 51job 和智联复用同一套 `ConversationRunner + rules + screening + policy`，避免三平台复制岗位业务逻辑。
  - 51job 需要补齐未读扫描、候选人打开校验、消息读取、发送校验、真实附件优先下载、预览文字拒绝入库、求简历后确认。
  - 智联需要补齐未读扫描、会话读取、发送校验、已收附件/已求过判断、要附件简历后确认。
  - 当前没有登录真实 51job / 智联页面，因此本阶段以 FakePage、mock 和静态检查完成离线验证。
- 修改文件：
  - `app/agent/screening.py`
  - `app/browser/fake_page.py`
  - `app/platforms/job51/actions_chat.py`
  - `app/platforms/job51/actions_resume.py`
  - `app/platforms/job51/selectors.py`
  - `app/platforms/zhilian/actions.py`
  - `app/platforms/zhilian/selectors.py`
  - `scripts/dom_inspection_common.py`
  - `scripts/inspect_job51_dom.py`
  - `scripts/inspect_zhilian_dom.py`
  - `scripts/platform_once_common.py`
  - `scripts/run_job51_once.py`
  - `scripts/run_zhilian_once.py`
  - `tests/agent/test_job51_phase3.py`
  - `tests/agent/test_zhilian_phase1.py`
- 修改结果：
  - 三平台仍然共用同一个招聘决策入口，岗位匹配、知识库答疑、直求简历、AI 基础条件、筛选问题判断没有复制到平台层。
  - 51job 平台层补齐未读行跳过规则、虚拟列表打开候选人校验、聊天上下文读取、关闭遮挡层、输入框发送、最近己方消息校验。
  - 51job 求简历逻辑改为优先真实附件 href / 字节，校验 PDF/doc/docx 文件头；聊天中的在线简历预览文字不会入库，会回退为求简历并点击确认。
  - 智联平台层补齐未读候选会话查找、聊天上下文读取、发送校验、要附件简历动作；已收到附件或已求过附件时跳过重复请求。
  - 新增 51job / 智联 DOM 采样脚本和单次处理脚本，默认 `DRY_RUN=true`；真实副作用需要显式 live 确认。
  - 修正筛选判断中否定表达优先级，避免“不能出差”被误判为接受。
- 验证结果：
  - `python -m pytest tests`：49 passed，1 个 StarletteDeprecationWarning。
  - `python -m ruff check .`：All checks passed。
  - `python -m compileall app scripts run_control_plane.py run_worker.py`：通过。
- 风险 / 待确认：
  - 51job / 智联真实页面尚未登录验证，后续需要先跑 DOM 采样脚本，再根据真实页面修选择器漂移。
  - 本阶段没有执行真实发送、真实求简历、真实附件下载或真实打招呼。
