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
---

### 快照 0047：成员简历库岗位权限
- 修改时间：2026-06-30 09:59:08 +08:00
- 修改原因：
  - 普通成员登录简历库后不能看到全部简历，需要按公司成员与岗位范围限制可见数据。
  - 佘欣平、杨梅只允许看运营岗位 A/B；张怀滨只允许看 AI 智能体解决方案负责人、外部财务产品顾问、投资交易策略研究员相关简历。
  - 简历详情、文件预览、审阅、约面试等接口不能只靠前端隐藏，必须在后端统一做权限校验。
- 修改文件：
  - `config/resume_scopes.yaml`
  - `app/auth/resume_scope.py`
  - `app/auth/access.py`
  - `app/api/routes/auth.py`
  - `app/api/routes/resumes.py`
  - `app/api/routes/resume_review.py`
  - `app/api/routes/interview.py`
  - `app/domain/resume/service.py`
  - `frontend/auth.js`
  - `tests/domain/test_resume_scope_permissions.py`
  - 相关登录/简历/面试路由测试
- 修改结果：
  - 新增岗位权限配置文件，管理员仍可看全部岗位，未配置普通成员默认没有岗位可见范围。
  - `/api/auth/me` 返回 `resumeScope.jobTypes`，前端用户卡片展示当前可见岗位。
  - `/api/resumes`、简历详情、文件、预览图、编辑、重评、审阅、约面试入口均接入会话权限与岗位范围校验。
  - `/api/resume-review/queue` 也按同一岗位范围过滤，避免被分配的越权简历在待处理队列里露出。
  - 新增测试覆盖运营成员只能看到运营简历、张怀滨只能看到战略直求岗位简历。
- 风险 / 待确认：
  - 当前配置先按飞书姓名匹配，后续拿到三位同事的 `open_id/user_id/union_id` 后应补进 `resume_scopes.yaml`，避免同名风险。
  - 线上飞书登录需要在飞书开放平台配置应用可用范围/发布或测试用户；普通员工一般不应加为开发协作者。

---

### 快照 0048：成员岗位入口与权限兜底
- 修改时间：2026-06-30 10:57:30 +08:00
- 修改原因：
  - 成员登录后需要在状态按钮上方先看到可选岗位入口，按钮样式要更大、更接近岗位入口导航。
  - 普通成员不需要“待补充”和“待我处理”状态入口，也不需要右侧“待补充”操作按钮。
  - 佘新平登录后仍看到测试简历，需确认后端默认权限不是全量，并补齐姓名别名。
- 修改文件：
  - `config/resume_scopes.yaml`
  - `app/domain/resume/service.py`
  - `app/api/routes/resumes.py`
  - `frontend/index.html`
  - `frontend/app.js`
  - `frontend/styles.css`
  - `tests/domain/test_resume_scope_permissions.py`
  - `tests/domain/test_frontend_resume_member_view.py`
- 修改结果：
  - `/api/resumes` 增加 `jobFacets`，只在当前登录用户可见岗位范围内统计数量。
  - 前端新增“JOB TABLES / 岗位入口”大按钮区，点击岗位后按该岗位重新拉取简历。
  - member 模式隐藏“待补充 / 待我处理”状态入口和右侧“待补充”按钮。
  - `resume_scopes.yaml` 给佘欣平补充 `佘新平` 别名；未配置成员默认返回空简历列表。
- 风险 / 待确认：
  - 姓名别名仍只是临时兜底，等成员都登录成功后应把飞书 `open_id/user_id/union_id` 写入权限配置。
  - 服务器 `18080` 需要更新并重启新服务后，同事端才能看到新 UI 和权限修复；旧 `8080` 服务不动。

---

### 快照 0049：运营成员岗位显示归一为运营A/B
- 修改时间：2026-06-30 13:46:00 +08:00
- 修改原因：
  - 旧版简历库把“企业内容运营负责人（B2B/短视频方向）”显示为“运营A”，把“B端社交媒体运营”显示为“运营B”。
  - 新版成员岗位入口直接暴露了详细岗位名，佘欣平和杨梅的页面不符合旧服务展示口径。
- 修改文件：
  - `config/resume_scopes.yaml`
  - `app/domain/resume/job_types.py`
  - `app/auth/resume_scope.py`
  - `app/domain/resume/service.py`
  - `app/api/routes/resumes.py`
  - `frontend/app.js`
  - `frontend/auth.js`
  - `frontend/index.html`
  - `tests/domain/test_resume_scope_permissions.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 运营成员的可见岗位只暴露 `运营A` 和 `运营B`，不再把详细岗位名作为岗位入口展示。
  - 后端权限、列表筛选、岗位计数均按旧版别名规则归一匹配，长岗位名仍能被正确归入运营 A/B。
  - 简历接口新增 `displayJobType`，前端成员视图优先展示归一后的岗位名。
  - 已同步部署到新服务 `18080`，旧服务 `8080` 未修改。

---

### 快照 0050：成员简历库筛选区精简
- 修改时间：2026-06-30 14:08:00 +08:00
- 修改原因：
  - 成员端已经通过上方岗位入口选择 `运营A / 运营B`，筛选区里的“岗位”输入框重复且容易误解。
  - 学历筛选需要改为固定选项，避免成员手输导致筛选口径不一致。
  - 入库开始和入库结束日期需要相邻显示，减少横向查找成本。
- 修改文件：
  - `frontend/index.html`
  - `frontend/styles.css`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - member 模式隐藏筛选区里的岗位输入框，管理员页面仍保留岗位筛选。
  - 学历筛选改为下拉框，选项为 `大专 / 本科 / 硕士 / 博士`。
  - 入库开始和入库结束字段增加相邻布局标识。
  - 更新前端缓存版本为 `20260630-member-filter-polish`。

---

### 快照 0051：管理员简历库显示旧版全量岗位入口
- 修改时间：2026-06-30 14:18:00 +08:00
- 修改原因：
  - 管理员进入简历库时需要看到所有岗位入口，而不是只按成员权限显示或隐藏岗位按钮。
  - 岗位名称需要沿用旧版简历库显示口径，例如 `AI实习生 / 应用技术 / 人资管培 / 石油销售 / 财务顾问 / AI方案负责人`。
- 修改文件：
  - `frontend/app.js`
  - `frontend/index.html`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 前端新增旧版 `RESUME_LIBRARY_JOB_TYPES` 全量岗位列表。
  - 管理员 `resumeScope.jobTypes=["*"]` 时展示全部旧版岗位入口。
  - 岗位按钮和简历行展示复用旧版短名称映射，成员端仍只显示授权岗位。
  - 更新前端缓存版本为 `20260630-admin-job-tabs`。

---

### 快照 0052：投资岗位入口归一去重
- 修改时间：2026-06-30 14:35:23 +08:00
- 修改原因：
  - 张怀滨成员页同时显示 `投资交易策略研究员` 和 `投资交易策略研究员（量化与市场情绪方向）` 两个入口。
  - 旧版把这类岗位统一归到正式长名，并在简历库入口中用短标签展示，不能在成员页拆成两个岗位。
- 修改文件：
  - `config/resume_scopes.yaml`
  - `app/domain/resume/job_types.py`
  - `app/auth/resume_scope.py`
  - `app/domain/resume/service.py`
  - `frontend/app.js`
  - `frontend/index.html`
  - `tests/domain/test_resume_scope_permissions.py`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 张怀滨岗位权限只保留正式岗位 `投资交易策略研究员（量化与市场情绪方向）`。
  - 后端把投资短名、长名和旧版短标签 `投资策略研究` 统一归一，权限匹配和 facet 计数都合并。
  - 前端岗位入口按 canonical 去重，页面只显示一个 `投资策略研究` 按钮，避免旧 session 或重复 facet 再次造成重复入口。
  - 更新前端缓存版本为 `20260630-investment-job-dedupe`。

---

### 快照 0053：简历库岗位入口换行与筛选区防裁切
- 修改时间：2026-06-30 15:22:42 +08:00
- 修改原因：
  - 管理员简历库岗位入口按钮单行横向滚动，右侧岗位在常见屏宽下不可见。
  - 简历库上半块使用 `42vh` 限高，筛选条件第二行/底部字段会被 `overflow: hidden` 裁掉。
- 修改文件：
  - `frontend/styles.css`
  - `frontend/index.html`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 岗位入口改为桌面 8 列网格，15 个入口按 8 + 7 两行展示，取消横向滚动裁切。
  - 简历页上半块高度提升为 `minmax(540px, 58vh)`，筛选区改为宽屏 8 列，日期、排序、复核和按钮能完整显示。
  - 更新前端缓存版本为 `20260630-filter-layout-fix`。

---

### 快照 0054：候选人摘要补充学校与院校层级
- 修改时间：2026-06-30 15:36:22 +08:00
- 修改原因：
  - 右侧审阅摘要里的 `学历` 只显示学历等级，用户需要同时看到学校名称，并在学校后标注 `985 / 211 / 一本 / 二本` 等院校层级。
  - 部分旧数据没有结构化学校字段，需要前端从简历文本中做保守兜底提取。
- 修改文件：
  - `app/api/routes/resumes.py`
  - `frontend/app.js`
  - `frontend/index.html`
  - `tests/domain/test_phase5_resume.py`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 简历 API 增加 `school / schoolLevel / educationDisplay`，例如 `本科 · 重庆科技大学（一本）`。
  - 前端新增 `resumeSchool()`、`resumeSchoolLevel()`、`resumeEducationLine()`，优先用结构化字段，缺失时从简历文本提取常见学校名和院校层级。
  - 右侧候选人摘要显示 `学历：本科 · 学校（层级）`，并单独显示 `学校：学校名`。
  - 更新 `app.js` 缓存版本为 `20260630-education-summary`。
- 验证结果：
  - 先补前后端契约测试并确认红灯。
  - `.venv312\Scripts\python.exe -m pytest tests\domain\test_frontend_resume_member_view.py::test_resume_summary_uses_school_and_tier_display_line tests\domain\test_phase5_resume.py::test_resume_api_payload_exposes_school_tier_and_education_display -q`：2 passed。
  - `node --check frontend/app.js`：通过。

---

### 快照 0055：当前结果姓名旁增加学校层级标签
- 修改时间：2026-06-30 15:42:51 +08:00
- 修改原因：
  - 用户希望在左侧“当前结果”候选人姓名旁增加小标签，快速看到学校层次，例如 `985 / 211 / 一本 / 二本`。
  - 学校层级不应挤占岗位第二行，适合放成姓名同行的短 badge。
- 修改文件：
  - `frontend/app.js`
  - `frontend/styles.css`
  - `frontend/index.html`
  - `tests/domain/test_frontend_resume_member_view.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 新增 `resumeSchoolTierBadge()`，将组合层级压缩为短标签：`985 / 211 / 双一流` 优先显示 `985`，`211 / 双一流` 显示 `211`。
  - 左侧当前结果列表姓名行改为 `mini-heading`，姓名右侧显示 `school-tier-badge`；无层级时不显示标签。
  - `school-tier-badge` 使用小胶囊样式，避免长姓名溢出并保持列表紧凑。
  - 更新前端缓存版本为 `20260630-school-tier-badge`。
- 验证结果：
  - 先补前端契约测试并确认红灯。
  - `.venv312\Scripts\python.exe -m pytest tests\domain\test_frontend_resume_member_view.py -q`：14 passed。
  - `node --check frontend/app.js`：通过。
  - `.venv312\Scripts\python.exe -m ruff check tests\domain\test_frontend_resume_member_view.py`：All checks passed。

---

### 快照 0056：新增旧简历库一次性同步脚本
- 修改时间：2026-06-30 16:21:56 +08:00
- 修改原因：
  - 需要把旧 8080 服务的简历 SQLite 和 PDF 文件安全接入新 18080 预览服务。
  - 旧服务仍在运行，不能直接复制 live SQLite 文件，也不能让新旧服务共写同一个库。
  - 新系统需要先 dry-run 汇总，再 apply 前自动备份目标库，降低误覆盖风险。
- 修改文件：
  - `scripts/sync_legacy_resumes.py`
  - `tests/domain/test_legacy_resume_sync.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 新增 `SyncConfig/run_sync()` 和 CLI，默认 dry-run，只读取旧库一致快照并输出导入报告。
  - apply 必须显式传 `--apply --yes`；执行前自动备份目标库，并写入导入 manifest。
  - 导入保留旧 `id/payload/phone_key/job_type/match_score/updated_at`，补写 `parsed_name`，桥接字段保持空。
  - PDF 复制到新 `uploads/legacy/` 目录，并把 `payload.pdfPath` 改写为新路径，同时保留 `legacyPdfPath`。
  - 覆盖测试确认 dry-run 不写目标、replace 会复制 PDF 并改写 payload、merge 会跳过已有简历。

---

### 快照 0057：旧库同步到 18080 预览库完成
- 修改时间：2026-06-30 16:35:00 +08:00
- 修改原因：
  - 用户确认开始按旧库接入方案执行，需要把旧 8080 简历库一次性导入新 18080 预览库。
  - 服务器 Python 环境缺少项目依赖，迁移脚本需要改成标准库实现，避免依赖 `yaml/pydantic`。
- 修改文件：
  - `scripts/sync_legacy_resumes.py`
  - `docs/change-snapshots-2.md`
- 修改结果：
  - 迁移脚本移除对 `app.settings/app.db.engine` 的依赖，改为直接读取 `app/db/schema.sql` 并补齐目标字段。
  - 已在服务器 `C:\RecruitAgent2Preview\hr-agent` 执行旧库 dry-run：旧库 `quick_check=ok`，扫描 2207 条，PDF 存在 2207 个，缺失 0。
  - 已执行 apply 到新预览库：导入 2207 条，复制 2207 个 PDF，目标库 `quick_check=ok`。
  - 目标库备份：`C:\RecruitAgent2Preview\hr-agent\data\backups\resumes_before_legacy_sync_20260630_162903.sqlite`。
  - 导入 manifest：`C:\RecruitAgent2Preview\hr-agent\data\backups\legacy_sync_manifest_20260630_162903.json`。
  - 独立只读检查确认：新库 `resumes` 行数 2207，`data/uploads/legacy` PDF 数 2207，抽样 `payload.pdfPath` 文件存在且保留 `legacyPdfPath`。
