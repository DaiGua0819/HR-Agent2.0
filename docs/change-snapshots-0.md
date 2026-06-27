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

---

### 快照 0003：新增稳定交互节奏层建设方案

- 修改时间：2026-06-26 16:57:42 +08:00
- 修改原因：
  - 需要把旧系统“拟人化操作”的观察结论整理成可审核的重构方案。
  - 需要明确为什么不原样复用旧 `BrowserTerminal`，以及重构版如何在不污染业务边界的前提下保留真实浏览器操作稳定性。
- 修改文件：
  - `docs/interaction-pacing-plan.md`
  - `docs/change-snapshots-0.md`
- 修改结果：
  - 新增稳定交互节奏层建设方案文档。
  - 文档说明了旧系统实现、弃用旧结构的原因、新模块设计、三平台接入计划、dry-run 边界、测试计划和风险控制。
  - 追加本次文档修改快照。
- 验证结果：
  - 本次仅新增文档，未运行自动化测试。
- 风险 / 待确认：
  - 该方案待审核，审核通过后再进入代码实现。

---

### 快照 0004：实现可靠点击层（去拟人化版）

- 修改时间：2026-06-27 09:15:53 +08:00
- 修改原因：
  - 需要把真实浏览器操作稳定性从“拟人化操作”改为轻量可靠动作层，去掉鼠标轨迹、真人阅读停顿、错字/误点模拟和随机长休息。
  - 需要让 BOSS / 51job / 智联平台动作统一使用等待、校验、有限重试、退避和分段滚动，减少真实页面元素未就绪导致的误判。
  - 需要保证 dry-run 安全边界仍在 adapter / runner 层，不下沉到浏览器动作层。
- 修改文件：
  - `app/browser/interaction_profile.py`
  - `app/browser/reliable_actions.py`
  - `app/browser/reliable_support.py`
  - `app/browser/base.py`
  - `app/browser/fake_page.py`
  - `app/browser/playwright_cdp.py`
  - `app/browser/selector_validation.py`
  - `app/platforms/boss/actions.py`
  - `app/platforms/boss/actions_resume.py`
  - `app/platforms/boss/actions_recommend.py`
  - `app/platforms/boss/dom_scripts.py`
  - `app/platforms/job51/actions_chat.py`
  - `app/platforms/job51/actions_mode.py`
  - `app/platforms/job51/actions_recommend.py`
  - `app/platforms/job51/actions_resume.py`
  - `app/platforms/zhilian/actions.py`
  - `scripts/boss_once_support.py`
  - `scripts/boss_targeting.py`
  - `scripts/platform_once_common.py`
  - `scripts/run_boss_once.py`
  - `tests/platforms/test_reliable_actions.py`
  - `docs/reliable-actions-plan.md`
  - `docs/interaction-pacing-plan.md`
  - `.env.example`
  - `app/settings.py`
- 修改结果：
  - 新增 `reliable_click` / `reliable_click_element` / `reliable_fill` / `reliable_confirm` / `reliable_scroll`，统一返回结构化动作结果并记录到页面。
  - 平台动作层的发送、求简历、确认、候选人打开、推荐打招呼、51job 推荐滚动等改为可靠动作调用。
  - BOSS 单次脚本和指定会话补处理脚本改为可靠点击候选人，并在小结中输出本轮可靠动作。
  - BOSS 未读筛选 DOM 脚本改为只读探测，遮挡层关闭改为 Escape + 可靠点击关闭按钮。
  - BOSS 动作层按职责拆分为聊天主动作、求简历动作、推荐牛人动作，避免单文件继续膨胀。
  - 新增去拟人化版方案文档，旧 `interaction-pacing-plan.md` 改为历史说明并指向新文档。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests`：53 passed，1 个 StarletteDeprecationWarning。
  - `.venv312\Scripts\python.exe -m ruff check .`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`：通过。
- 风险 / 待确认：
  - 真实页面仍需在登录后的 BOSS / 51job / 智联环境跑一次 dry-run，观察可靠动作记录与选择器漂移。
  - 可靠动作层不负责 dry-run 判断；后续新增平台副作用动作时仍必须在 adapter / runner 层接入安全守卫。

---

### 快照 0005：修复 BOSS 求简历确认弹层

- 修改时间：2026-06-27 09:40:37 +08:00
- 修改原因：
  - 真实 BOSS 页面点击“求简历”后会出现“确定向牛人索取简历吗？”确认弹层，按钮文本为“取消 / 确定”。
  - 旧确认选择器没有覆盖真实弹层按钮结构，导致脚本停在确认弹层，未自动点击“确定”。
  - 真实页面动作需要在每次点击、填入、确认后至少等待 1 秒再检测。
- 修改文件：
  - `app/browser/interaction_profile.py`
  - `app/browser/reliable_actions.py`
  - `app/platforms/boss/selectors.py`
  - `app/platforms/boss/actions_resume.py`
  - `tests/agent/test_boss_phase2.py`
  - `tests/platforms/test_reliable_actions.py`
  - `docs/change-snapshots-0.md`
- 修改结果：
  - 可靠动作层新增 `post_action_wait_ms=1000`，真实页面每个动作后至少等待 1 秒再校验。
  - `reliable_confirm()` 改为优先点击文本完全等于“确定/确认”等候选词的最小按钮元素，避免点到弹层容器。
  - BOSS 求简历确认选择器扩展到真实弹层常见结构，覆盖 `[class*='dialog']`、`[class*='modal']`、`.btn-primary`、`.confirm-btn` 等按钮。
  - BOSS 求简历点击后的成功条件同时支持确认弹层出现、系统消息“简历请求已发送”、按钮禁用等真实页面状态。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests`：54 passed，1 个 StarletteDeprecationWarning。
  - `.venv312\Scripts\python.exe -m ruff check .`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`：通过。
- 风险 / 待确认：
  - 该修复基于 BOSS 当前真实弹层形态；后续如果弹层类名再变，仍以“按钮文本精确匹配”为首选兜底。

---

### 快照 0006：修复 BOSS 真实未读识别与 exchange-tooltip 确认层

- 修改时间：2026-06-27 10:06:16 +08:00
- 修改原因：
  - 真实 BOSS 未读列表中，已读会话也可能留在“未读”筛选后的列表里；只有带数字徽标的 `badge-count` / `badge` 才是真实未读。
  - 旧逻辑把没有 `unread` 属性的真实行默认当作未读，导致已处理候选人占用处理名额。
  - BOSS “确定向牛人索取简历吗？”确认层实际使用 `.exchange-tooltip` + `.boss-btn-primary.boss-btn`，旧选择器仍无法稳定点到“确定”。
- 修改文件：
  - `app/platforms/boss/dom_scripts.py`
  - `app/platforms/boss/actions.py`
  - `app/platforms/boss/actions_resume.py`
  - `app/platforms/boss/selectors.py`
  - `app/browser/fake_page.py`
  - `scripts/run_boss_once.py`
  - `tests/agent/test_boss_phase2.py`
  - `docs/change-snapshots-0.md`
- 修改结果：
  - 新增 BOSS 只读未读行抽取脚本，按真实数字徽标输出 `id / label / unread_count`。
  - BOSS 平台层 `read_unread_conversations()` / `find_next_unread_thread()` 改为只处理带数字未读徽标的行；真实页面缺少 `unread` 属性时不再默认视为未读。
  - `run_boss_once.py` 启动健康检查不再预先点开候选人，避免检查阶段把未读状态消费掉；处理循环改为按未读快照逐条点击。
  - BOSS 求简历确认选择器新增 `.exchange-tooltip .boss-btn-primary` / `.exchange-tooltip .boss-btn`。
  - 求简历确认增加确认文案可见时的兜底确认路径，并把兜底坐标校准到真实弹层按钮区域。
  - FakePage 增加 `boss.read_unread_rows` 返回，测试覆盖“未读数为 0 的行不能进入处理队列”。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py tests\agent\test_phase7b_browser.py`：14 passed。
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py`：10 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\boss\actions.py app\platforms\boss\dom_scripts.py app\browser\fake_page.py scripts\run_boss_once.py tests\agent\test_boss_phase2.py`：All checks passed。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\boss\actions_resume.py app\platforms\boss\selectors.py`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app\platforms\boss app\browser\fake_page.py scripts\run_boss_once.py`：通过。
  - 真实 CB 浏览器 LIVE 运行：识别真实未读 20 条，按数字未读处理 3 条；李俊辉、黄宝泉已发送 AI 实习生基础条件。
- 风险 / 待确认：
  - 韦女士会话判断为已接受基础条件，应求简历；但指定会话补处理受 BOSS 虚拟列表定位影响，没有稳定补到该会话，需要后续补“指定会话滚动定位”后再处理。
  - BOSS 确认层兜底目前基于当前 `.exchange-tooltip` 结构和按钮相对位置，后续仍建议优先使用真实按钮选择器。

---

### 快照 0007：BOSS 处理前强制点击顶部未读

- 修改时间：2026-06-27 10:22:25 +08:00
- 修改原因：
  - 处理 BOSS 消息前需要显式点击聊天列表上方的“未读”，确保进入未读消息页面后再扫描候选人。
  - 旧逻辑虽然会读数字未读徽标，但未读筛选动作对真实 BOSS 顶部筛选区的定位不够明确。
- 修改文件：
  - `app/platforms/boss/dom_scripts.py`
  - `app/platforms/boss/actions.py`
  - `docs/change-snapshots-0.md`
- 修改结果：
  - `CLICK_UNREAD_FILTER_JS` 改为在真实聊天列表顶部区域按“未读 / 全部 未读”文本定位筛选入口，并派发鼠标事件点击。
  - `select_unread_filter()` 在点击未读后固定等待 1 秒，再继续读取真实未读行，保证筛选切换完成。
  - 后续 `run_boss_once.py`、worker 和 function call 入口都会复用这个平台层动作。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py tests\agent\test_phase7b_browser.py`：14 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\boss\actions.py app\platforms\boss\dom_scripts.py`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app\platforms\boss\actions.py app\platforms\boss\dom_scripts.py`：通过。
  - 真实 CB 浏览器 LIVE 运行：先点击顶部未读后识别真实未读 19 条，并处理 3 条。
- 风险 / 待确认：
  - 韦女士已发附件简历，但 AI 实习生分支仍显示 `basic_unclear`，后续应把附件简历消息优先识别为“已收简历/等待”，避免误归入基础条件不明确。

---

### 快照 0008：AI 应用开发首轮优先发送基础条件

- 修改时间：2026-06-27 10:27:38 +08:00
- 修改原因：
  - AI应用开发实习生 / AI应用开发工程师在首次处理某个联系人时，必须先发送基础条件确认话术。
  - 旧共享 runner 会先做知识库答疑或未知问题升级，导致候选人问“方便看看我的简历吗”时没有先发基础条件。
  - 基础条件已发送后，如果候选人回复附件简历，应识别为已收到简历并等待，不能判成 `basic_unclear`。
- 修改文件：
  - `app/agent/runner.py`
  - `tests/agent/test_boss_phase2.py`
  - `docs/change-snapshots-0.md`
- 修改结果：
  - `ConversationRunner` 在读取最后一条候选人消息后，优先判断 AI 基础条件规则；只要历史里没有发过基础条件，立即发送基础条件。
  - 基础条件已发送后，AI 分支会先检查附件简历、已求简历、待同意附件简历，再判断候选人是否接受/拒绝基础条件。
  - 新增测试覆盖“候选人先提问也先发基础条件”和“基础条件后收到附件简历直接等待”。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py tests\agent\test_zhilian_phase1.py tests\agent\test_job51_phase3.py`：25 passed。
  - `.venv312\Scripts\python.exe -m pytest tests`：57 passed，1 个 StarletteDeprecationWarning。
  - `.venv312\Scripts\python.exe -m ruff check .`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`：通过。
- 风险 / 待确认：
  - 该规则应用在共享 runner，因此 BOSS / 51job / 智联都会一致生效。

---

### 快照 0009：修正 BOSS 未读页签真实点击位置

- 修改时间：2026-06-27 10:32:51 +08:00
- 修改原因：
  - 真实 BOSS 页面左侧列表筛选区的“未读”是 `.chat-message-filter-left span`，位置在职位筛选下方。
  - 上一次未读点击脚本搜索范围偏到了会话列表区域，导致处理前仍停留在“全部”页签。
  - 需要在处理消息前明确切换到截图中的“未读”页签，并校验 active 状态。
- 修改文件：
  - `app/platforms/boss/dom_scripts.py`
  - `app/platforms/boss/actions.py`
  - `docs/change-snapshots-0.md`
- 修改结果：
  - `CLICK_UNREAD_FILTER_JS` 改为精确查找 `.chat-message-filter-left span` 中文本等于“未读”的页签。
  - 点击后 `select_unread_filter()` 会等待 1 秒，并读取 `.chat-message-filter-left span.active`；只有 active 文本为“未读”才返回 selected。
  - 已在真实 CB 浏览器上验证：点击前 active 是“全部”，点击后 active 变为“未读”。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests`：57 passed，1 个 StarletteDeprecationWarning。
  - `.venv312\Scripts\python.exe -m ruff check .`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`：通过。
- 风险 / 待确认：
  - 该修复针对当前 BOSS 左侧筛选区 DOM；如果 BOSS 后续改名或改结构，需要重新跑 DOM 采样。

---

### 快照 0010：直求简历岗位优先于未知问题升级

- 修改时间：2026-06-27 10:44:53 +08:00
- 修改原因：
  - 投资交易策略研究员、AI智能体解决方案负责人、财务等直求简历岗位已经配置 `directResume: true`。
  - 候选人消息中包含“可否进一步沟通 / 可以聊聊吗”等问句时，旧 runner 会先进入 `unknown_question`，导致直求简历岗位没有执行求简历流程。
  - 正确顺序应为：AI 基础条件首轮优先；知识库命中则先答疑再继续；直求简历岗位优先于未知问题升级。
- 修改文件：
  - `app/agent/runner.py`
  - `tests/agent/test_boss_phase2.py`
  - `docs/change-snapshots-0.md`
- 修改结果：
  - `ConversationRunner` 在知识库未命中后，先判断 `is_direct_resume_rule(rule)`，再判断 `looks_like_question()`。
  - 投资交易策略研究员这类直求简历岗位即使候选人说“可否进一步沟通呢？”，也会发送求简历话术并点击求简历。
  - 新增 BOSS 测试覆盖“直求简历岗位带问句也不升级未知问题”。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py tests\agent\test_zhilian_phase1.py tests\agent\test_job51_phase3.py`：26 passed。
  - `.venv312\Scripts\python.exe -m pytest tests`：58 passed，1 个 StarletteDeprecationWarning。
  - `.venv312\Scripts\python.exe -m ruff check .`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`：通过。
- 风险 / 待确认：
  - 对直求简历岗位，未知问题不会阻断求简历；若后续希望某些具体问题必须先人工确认，需要在知识库或策略里显式配置拦截。
