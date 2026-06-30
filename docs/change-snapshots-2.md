# 修改快照记录 2

> 继续记录重构版 HR Agent 的代码修改。单文件控制在 600 行以内。

---

### 快照 0045：约面试按钮实现收尾与全量验证
- 修改时间：2026-06-30 09:23:32 +08:00
- 修改原因：
  - 约面试按钮平台动作链实现后，需要修正 Ruff 暴露的折行/import 问题，并让旧 Phase 6 面试中心路由测试适配新的独立 `interview_invite_service`。
  - 全仓库验证发现少量历史行长问题，本轮一并做机械折行，避免新功能合入后全量静态检查失败。
- 修改文件：
  - `app/features/interview_invite/platform_actions.py`
  - `app/platforms/boss/adapter.py`
  - `tests/features/test_interview_invite.py`
  - `app/platforms/boss/dom_scripts.py`
  - `app/platforms/job51/actions_resume_close.py`
  - `tests/agent/test_job51_phase3.py`
  - `tests/features/test_phase6_interview_center.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - `platform_actions.py` 保持原语义，折行处理联系人搜索、换微信定位/点击确认脚本，保留中文语义选择器。
  - 前端在 `missing_linked_session` 时展示候选会话按钮，管理员选择后会带 `selectedSessionId` 重新发起 dry-run 预检，再进入 live 确认。
  - `test_phase6_interview_center.py` 增加 `FakeInterviewInviteService`，使旧面试中心路由测试明确注入新的约面试入口服务，不再误触发真实派发链。
  - BOSS DOM 脚本、51job 简历关闭脚本和 51job 测试仅做行长/类型标注静态修正，不改变平台动作逻辑。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests/features/test_interview_invite.py tests/domain/test_frontend_resume_member_view.py tests/agent/test_phase4_runtime.py tests/domain/test_conversation_state_bridge.py -q`：31 passed，1 warning。
  - `node --check frontend/app.js`：通过。
  - `.venv312\Scripts\python.exe -m ruff check .`：All checks passed。
  - `.venv312\Scripts\python.exe -m pytest tests -q`：142 passed，1 warning。
  - `.venv312\Scripts\python.exe -m compileall app scripts run_control_plane.py run_worker.py`：通过。
- 风险 / 待确认：
  - 本轮未执行真实平台 live 动作；三平台“换微信”按钮定位仍需在 CloakBrowser 已登录真实页面上先跑 dry-run 预检，再由管理员确认 live。
  - live 模式仍受 `confirmLive=true` 和现有 dry-run/worker 配置共同约束，正式执行前需确认全局环境不是安全拦截态。

---

### 快照 0046：三平台换微信真实 DOM 定位收窄
- 修改时间：2026-06-30 09:36:26 +08:00
- 修改原因：
  - 用户提供 BOSS、51job、智联三平台“换微信”按钮截图后，连接当前 CloakBrowser `9333` 做只读 DOM 探测。
  - 初始探测确认三平台都能读到“换微信”，但旧逻辑会把父容器或 BOSS 顶部“已交换微信”筛选项排在真正按钮前面，存在误点风险。
- 修改文件：
  - `app/features/interview_invite/platform_actions.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - `locate_wechat_exchange` 和 `click_wechat_exchange` 改为候选打分：优先精确文本 `换微信`，优先小的可点击控件，降低父容器和 `已交换微信` 标签权重。
  - JS 内部使用 Unicode 转义保存中文关键词，避免 PowerShell/CDP 探测时中文正则被编码成 `???`。
  - 真实页面只读复测结果：智联命中 `A.km-button`，BOSS 命中 `DIV.operate-icon-item`，51job 命中 `SPAN.exchange-wx-wrap`，三者 `label/targetLabel` 均为 `换微信`。
- 验证结果：
  - `.venv312\Scripts\python.exe -m ruff check app/features/interview_invite/platform_actions.py`：All checks passed。
  - `.venv312\Scripts\python.exe -m pytest tests/features/test_interview_invite.py -q`：10 passed，1 warning。
  - `.venv312\Scripts\python.exe -m compileall app/features/interview_invite/platform_actions.py`：通过。
  - CloakBrowser `http://127.0.0.1:9333` 三平台当前标签页只读 `evaluate`：三平台均 `found=true`，未点击真实按钮。
- 风险 / 待确认：
  - 本轮只验证定位，没有点击“换微信”；live 点击和后续“加我微信沟通”仍需在管理员确认后小范围验证。

### 快照 0043：智联附件简历下载后关闭新页面
- 修改时间：2026-06-30 08:20:19 +08:00
- 修改原因：
  - 智联平台下载附件简历时会按官方设计打开新的 PDF / 下载页面。
  - 旧实现只在新页面中抓取 PDF 字节，下载完成后没有关闭该页面，连续处理候选人时会留下多余标签页。
- 修改文件：
  - `app/browser/playwright_cdp.py`
  - `tests/browser/test_playwright_cdp_download.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - `PlaywrightCDPPage._click_zhilian_attachment_resume_download()` 增加新页面清理逻辑。
  - 只有确认打开了新的 `Page` 时才在 `finally` 中关闭；如果没有新页、目标仍是原聊天页，则不会关闭原页面。
  - 新增回归测试覆盖“打开新页后必须关闭”和“没有新页时不能关闭原页”两个场景。
- 验证结果：
  - 先运行新增测试确认红灯：新页面未关闭时 `opened.closed is False`。
  - 修复后 `.venv312\Scripts\python.exe -m pytest tests\agent\test_zhilian_phase1.py tests\browser\test_playwright_cdp_download.py -q`：21 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\browser\playwright_cdp.py tests\browser\test_playwright_cdp_download.py`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app\browser\playwright_cdp.py tests\browser\test_playwright_cdp_download.py`：通过。
- 风险 / 待确认：
  - 本次只验证 fake Playwright 页面，不触发真实智联页面下载；下一次 live 下载时应观察新 PDF 标签页是否自动关闭。
---

### 快照 0044：约面试按钮绑定平台预检与换微信动作
- 修改时间：2026-06-30 09:12:48 +08:00
- 修改原因：
  - 简历库“约面试”按钮此前只调用面试中心定位接口，worker 仍是 stub，没有回到来源平台执行搜索联系人、换微信和发送后续消息。
  - 用户明确本次不复刻面试中心大模块，只绑定按钮背后的平台动作链。
- 修改文件：
  - `app/features/interview_invite/*`
  - `app/api/routes/interview.py`
  - `app/control_plane/{dispatcher.py,worker_client.py}`
  - `app/worker/runtime.py`
  - `app/platforms/{boss,job51,zhilian}/adapter.py`
  - `app/browser/fake_page.py`
  - `frontend/app.js`
  - `tests/features/test_interview_invite.py`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 新增独立 `interview_invite` 功能层，负责从简历硬关联会话生成平台联系人 payload，并派发到对应 owner worker。
  - `/api/interview/invite` 支持 `resumeId / dryRun / confirmLive / selectedSessionId`；非 dry-run 必须 `confirmLive=true`。
  - worker `/interview-invite` 不再返回旧 stub，改为打开对应平台 adapter 执行约面试动作。
  - 三平台 adapter 增加 `invite_to_interview()`：dry-run 只搜索、核对、定位换微信；live 点击换微信后发送“加我微信沟通”。
  - 前端“约面试”改为预检再确认：第一次点击只预检，预检通过后显示“确认发起约面试”。
- 验证结果：
  - 先补 `tests/features/test_interview_invite.py` 并确认红灯：缺少 `app.features.interview_invite`。
  - 实现后 `.venv312\Scripts\python.exe -m pytest tests\features\test_interview_invite.py -q`：10 passed。
  - 前端先补契约测试并确认红灯：缺少 `confirmInterviewInvite()`；实现后该测试通过。
- 风险 / 待确认：
  - 当前真实 DOM 搜索和换微信定位采用通用语义脚本，后续第一次 live 前建议先对三平台各跑 dry-run 预检，采样页面漂移。
---

### 快照 0040：拉高简历审阅工作台以完整显示十人列表
- 修改时间：2026-06-29 20:57:08 +08:00
- 修改原因：
  - 用户截图反馈左侧“当前结果”每页 10 人仍需要内部上下滑动，审阅时不够顺手。
  - 远端 `18080` 实测三页候选列表完整显示所需最大高度为 693px，当前工作台高度为 560px。
- 修改文件：
  - `frontend/styles.css`
  - `frontend/index.html`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - `.workbench` 最小高度从 560px 调整为 704px，覆盖“标题 + 10 个候选人条目”的实际高度并留少量边框余量。
  - 刷新 `styles.css` 版本号到 `20260629-member-tall-workbench`，避免浏览器使用旧缓存。
  - 增加前端契约测试，确保后续不会把工作台高度改回导致十人列表再次出现内部滚动。
- 验证结果：
  - 先补测试并确认红灯：工作台仍为 560px。
  - 修改后 `.venv312\Scripts\python.exe -m pytest tests\domain\test_frontend_resume_member_view.py -q`：6 passed。
  - `.venv312\Scripts\python.exe -m ruff check tests\domain\test_frontend_resume_member_view.py`：All checks passed。
  - `node --check frontend/app.js`：通过。
- 风险 / 待确认：
  - 页面整体会比之前更长，符合“左侧十人不内滚”的目标；简历正文和审阅摘要仍保留各自内部滚动，便于看长简历。

---

### 快照 0041：三平台 live 处理后修复可观测性与拒绝短路
- 修改时间：2026-06-29 21:28:19 +08:00
- 修改原因：
  - 宋峰峰三平台各处理 6 个联系人后，发现 51job 里候选人明确说“职位不太合适”仍进入直求简历流程。
  - 智联 Enter 发送成功时 summary 只显示 fill，缺少发送动作证明。
  - 智联附件简历下载成功后，summary 将 PDF bytes 原样打印，导致终端输出巨大。
- 修改文件：
  - `app/agent/runner.py`
  - `app/platforms/zhilian/actions.py`
  - `scripts/platform_once_common.py`
  - `tests/agent/test_job51_phase3.py`
  - `tests/agent/test_zhilian_phase1.py`
  - `tests/agent/test_platform_summary_output.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - `ConversationRunner` 在岗位规则命中后先识别候选人明确拒绝/结束沟通的短句，命中后直接 `skip/candidate_rejected`，不发消息、不求简历。
  - 智联 `send_message()` 在 Enter 发送且最近己方消息校验成功后，把 `press` 动作写入 `page.reliable_actions`，live summary 能看到发送完成证据。
  - live summary 的 `_jsonable()` 改为递归转换，遇到 `bytes` 只输出 `{type, length}` 摘要，不再打印整份 PDF。
- 验证结果：
  - 先补 3 个回归测试并确认红灯：拒绝短路、智联 Enter 动作日志、bytes 摘要输出。
  - 修复后 3 个回归测试通过。
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_job51_phase3.py tests\agent\test_zhilian_phase1.py tests\agent\test_boss_phase2.py tests\agent\test_platform_summary_output.py -q`：45 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\agent\runner.py app\platforms\zhilian\actions.py scripts\platform_once_common.py tests\agent\test_job51_phase3.py tests\agent\test_zhilian_phase1.py tests\agent\test_platform_summary_output.py`：All checks passed。
- 风险 / 待确认：
  - 智联“要附件简历”有一条真实页面返回 `confirm_button_not_visible`，本轮未能复现弹窗 DOM；已标记为真实页面待截图/DOM 采样项，后续需要针对可见弹窗结构继续增强确认按钮定位。

---

### 快照 0042：修正智联要附件简历无需确认弹窗
- 修改时间：2026-06-29 21:34:47 +08:00
- 修改原因：
  - 用户确认智联平台点击“要附件简历”后不需要二次确认，也不会出现确认弹窗。
  - 旧实现把“没有确认弹窗”误判为 `confirm_button_not_visible`，导致范文博这类会话被标记为请求未确认。
- 修改文件：
  - `app/platforms/zhilian/actions.py`
  - `tests/agent/test_zhilian_phase1.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 智联 `request_resume()` 点击“要附件简历”时不再等待确认弹窗。
  - 点击成功后先等待 1 秒并重新读取页面状态；如果出现附件则继续下载，没有附件则返回 `requested=True / confirmed=True / verifyReason=no_confirm_required`。
  - 保留“点击后出现附件继续下载”的原有分支。
- 验证结果：
  - 先改测试并确认红灯：旧代码仍返回 `confirmed=False`。
  - 修复后 `.venv312\Scripts\python.exe -m pytest tests\agent\test_zhilian_phase1.py -q`：13 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\zhilian\actions.py tests\agent\test_zhilian_phase1.py`：All checks passed。
- 风险 / 待确认：
  - 本次未重新 live 处理范文博，避免超出上一轮处理范围；下一轮智联 live 时该类结果应不再出现 `confirm_button_not_visible`。
