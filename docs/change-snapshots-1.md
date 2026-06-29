# 修改快照记录 1

> 继续记录重构版 HR Agent 的代码修改。单文件控制在 600 行以内。

---

### 快照 0026：三平台真实处理缺陷修复
- 修改时间：2026-06-29 10:15:00 +08:00
- 修改原因：
  - 真实页面验证暴露出三类缺陷：已求简历被误当成已完成、智联确认/未读/发送验证不可靠、51job 弹窗残留导致重复处理。
  - BOSS 已检测到候选人发送 PDF 时只等待，没有尝试下载和写入 resume artifact。
  - live 脚本输出缺少 session、artifact、candidate_status 和失败根因，不利于复盘。
- 修改文件：
  - `app/agent/persistence.py`
  - `app/agent/runner.py`
  - `app/platforms/types.py`
  - `app/platforms/zhilian/actions.py`
  - `app/platforms/boss/actions_resume.py`
  - `app/platforms/job51/actions_resume.py`
  - `app/platforms/job51/actions_resume_close.py`
  - `app/browser/fake_page.py`
  - `scripts/platform_once_common.py`
  - `scripts/run_boss_once.py`
  - `scripts/boss_once_support.py`
  - `tests/domain/test_conversation_state_bridge.py`
  - `tests/agent/test_boss_phase2.py`
  - `tests/agent/test_zhilian_phase1.py`
  - `tests/agent/test_job51_phase3.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - `resume_requested` 不再是完成态；只有 `resume_downloaded=True` 才跳过后续下载。
  - Runner 在看到页面当前已有附件/在线简历入口时，会优先调用平台动作下载或同意接收，不被历史已求简历状态阻断。
  - 直求简历岗位遇到未知岗位细节类问题时先进入 `unknown_question`，不绕过知识库直接求简历。
  - 智联未读行过滤排除 `[已读]` / `[送达]` 和系统类 label；求附件确认只匹配当前可见弹窗按钮；发送结果带 fill/trigger/verify 链，发送验证失败不写已问问题。
  - 51job 增加统一 `cleanup_resume_overlays()`，每个候选人处理前后关闭在线简历、附件预览、导出弹窗并 Escape 兜底。
  - BOSS 已有附件简历会尝试抓取真实 bytes/href，保存到 `data/downloads/boss/`，成功后可写 `resume_artifacts`；拿不到真实字节时返回 blocked reason，不伪造文件。
  - live summary 增加 `sessionId / artifactWritten / candidateStatusWritten / processed/skipped/failed`，BOSS live limit 放宽到 1-10。
- 验证结果：
  - 新增回归测试 8 个，针对状态语义、BOSS 附件下载、智联未读/确认/发送、51job 去重/清理，已全部通过。
- 风险 / 待确认：
  - BOSS 真实附件下载依赖页面暴露真实链接或可 fetch 的 blob；若真实页面只允许预览但不暴露字节，会返回 `boss_attachment_download_unavailable`。
  - 智联仍未实现真实附件 PDF 落盘，只修复“要附件简历”确认和状态语义。
  - 51job 的导出弹窗清理已接入，但真实页面如新增遮挡层，还需要根据采样继续补 selector。

### 快照 0019：51job 未读筛选改为状态感知刷新

- 修改时间：2026-06-27 14:55:58 +08:00
- 修改原因：
  - 真实 51job 页面中“未读”是复选框；如果已经勾选，处理前再次点击会取消未读筛选，导致后续在全部消息里处理。
  - 用户要求：处理 51job 前先检查未读状态；已勾选时先取消、等待 1 秒、再勾选刷新；未勾选时直接勾选一次。每次点击动作结束后至少等待 1 秒。
- 修改文件：
  - `app/platforms/job51/actions_navigation.py`
  - `app/platforms/job51/actions_unread.py`
  - `app/platforms/job51/actions_chat.py`
  - `app/platforms/job51/selectors.py`
  - `app/browser/fake_page.py`
  - `scripts/platform_once_common.py`
  - `tests/agent/test_job51_phase3.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - 新增 `actions_unread.py`，专门承载 51job 未读筛选状态读取、取消刷新、重新勾选与点击后等待。
  - 新增 `actions_navigation.py`，进入“人才沟通”失败时回 51 工作台重试，不再跳到 `about:blank`。
  - `open_chat_page()` 点击人才沟通后会等待会话列表、输入框或未读筛选出现，避免页面还没加载完就做选择器预检。
  - `actions_chat.py` 只导出/复用未读动作，不再混入未读复选框细节，避免文件继续膨胀。
  - FakePage 支持 51job 未读复选框 toggle，测试能覆盖已勾选刷新场景。
  - 新增测试：未读未勾选时勾选一次；未读已勾选时先取消再勾选，最终仍保持未读筛选开启。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_job51_phase3.py`：11 passed。
  - `.venv312\Scripts\python.exe -m pytest tests`：64 passed，1 个 FastAPI/TestClient deprecation warning。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\job51\actions_navigation.py app\platforms\job51\actions_unread.py app\platforms\job51\actions_chat.py app\platforms\job51\selectors.py app\browser\fake_page.py tests\agent\test_job51_phase3.py`：All checks passed。
  - `.venv312\Scripts\python.exe -m compileall app\platforms\job51 app\browser\fake_page.py`：通过。
- 风险 / 待确认：
  - 真实 51job 页面刷新后列表重新排序，后续处理应始终重新读取未读行，不能复用刷新前的行引用。

---

### 快照 0020：51job 在线简历保存弹窗下载补全
- 修改时间：2026-06-27 15:37:00 +08:00
- 修改原因：
  - 真实 51job 页面中，符合条件候选人的在线简历不能只判断“在线简历”文本，也不能伪造 PDF。
  - 用户确认在线简历预览层右上角有存储卡按钮；点击后还会弹出“保存到本地”二次确认框，需要选择 Pdf 并点击“确定”才会触发真实浏览器下载。
  - 刚刚六人处理中，栾洪鹏已通过膨润土销售筛选，但之前下载失败，原因是只找下载链接，没有处理保存按钮和确认弹窗。
- 修改文件：
  - `app/platforms/job51/dom_scripts.py`
  - `app/platforms/job51/actions_resume.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - 在线简历下载脚本优先点击真实稳定按钮 `#sensor_imresume_download`。
  - 点击保存后等待 1 秒，再在“保存到本地”弹窗中保留/选择 `Pdf 文件`，点击“确定”触发真实下载。
  - `actions_resume.py` 在打开在线简历后增加 1 秒等待，避免预览层尚未生成时提前判断缺失。
  - 已对栾洪鹏执行真实补下载，保存路径：`data/downloads/job51/51job_栾洪鹏_膨润土销售人员_上海(806034283).pdf`。
- 验证结果：
  - 真实 CB 浏览器下载事件触发成功，下载文件大小 367894 bytes，保存校验通过，文件哈希 `def9510326a804997fc9bd8a2a7c8a1208c9f9c23c9580192a69c743584f9877`。
- 风险 / 待确认：
  - 51job 的保存弹窗当前默认走 PDF；如果后续账号或页面默认值变化，需要继续以 PDF 为强制选项。
  - 下载目录 `data/downloads/` 为本地资产，保持不入 Git。

---

### 快照 0021：51job live 处理 6 人与在线简历可信点击尝试
- 修改时间：2026-06-27 15:47:11 +08:00
- 修改原因：
  - 用户要求继续处理宋峰峰 51job 未读 6 人，并要求真实处理，不只点开。
  - 程翔飞的在线简历下载暴露出新问题：51job 保存按钮对 DOM `.click()` 不稳定，需要真实可信点击。
- 修改文件：
  - `app/browser/playwright_cdp.py`
  - `app/platforms/job51/actions_resume.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - `PlaywrightCDPPage.click_and_download()` 对 51job 在线简历保存按钮增加可信点击路径，点击 `#sensor_imresume_download` 后等待 1 秒，并尝试在“保存到本地”弹窗中点击 `确定`。
  - 51job 在线简历下载等待时间调整为 30 秒。
  - live 处理 6 人结果：
    - 邹广 / AI应用开发实习生：发送基础条件。
    - 陈罡 / 外部财务产品顾问：下载附件简历成功。
    - 张荣华 / AI应用开发实习生：问题未命中知识库，转待人工/待补充。
    - 陈先生 / 企业内容运营负责人：最后消息非候选人，等待。
    - 程翔飞 / 外部财务产品顾问：进入求简历/下载分支，但在线简历下载仍未完成。
    - 莫佳书 / 膨润土销售人员：发送第二个筛选问题。
- 验证结果：
  - 已确认 51job 页面恢复，无可见在线简历预览层或保存弹窗残留。
- 风险 / 待确认：
  - 程翔飞在线简历保存弹窗在真实页面中可见，但 CDP/Playwright 下载事件未稳定触发；下一轮需要专项修复“保存到本地”的真实下载捕获。
  - 本次 6 人处理完成，但程翔飞简历未落盘，不能算下载完成。

---

### 快照 0022：51job 在线简历下载后关闭预览层
- 修改时间：2026-06-27 16:11:27 +08:00
- 修改原因：
  - 用户观察到处理 51job 时疑似一直重复下载孔德威的简历。
  - 原因是在线简历下载完成后没有可靠关闭右上角 X，页面仍停留在简历预览层，后续循环可能继续围绕同一份简历判断。
- 修改文件：
  - `app/platforms/job51/actions_resume_close.py`
  - `app/platforms/job51/actions_resume.py`
  - `app/platforms/job51/resume_files.py`
  - `app/browser/fake_page.py`
  - `tests/agent/test_job51_phase3.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - 新增 `actions_resume_close.py`，统一关闭 51job 附件简历预览层和在线简历预览层。
  - 附件简历下载结束后仍优先关闭 `.annex-resume .container-close`。
  - 在线简历下载结束后增加右上角 X 关闭逻辑，优先匹配语义关闭按钮，找不到时按在线简历页右上角区域兜底。
  - 下载成功、下载失败、缺少下载链接三种结果都会进入 `finally` 关闭流程，关闭动作后至少等待 1 秒。
  - `resume_files.py` 增加磁盘级内容哈希去重；脚本重启后如果同一份简历已经落盘，不再写出新的重复 PDF。
  - `platform_once_common.py` 从“首屏只扫一次”改为“处理后重读列表；无进展时滚动会话列表续扫”，最多滚动 8 次，避免处理人数少于 `--limit`。
  - FakePage 增加 `resume_preview_closes` 计数，测试可验证在线简历下载后确实触发关闭。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_job51_phase3.py -q`：12 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\job51\actions_resume.py app\platforms\job51\actions_resume_close.py app\platforms\job51\resume_files.py app\browser\fake_page.py tests\agent\test_job51_phase3.py`：All checks passed。
  - 随后执行 51job live 处理，实际处理到 4 个 eligible 会话后结束：1 个附件简历下载成功并关闭预览，2 个发送消息，1 个进入在线简历分支但未拿到真实下载链接。
  - `.venv312\Scripts\python.exe -m ruff check scripts\platform_once_common.py app\platforms\job51\resume_files.py app\platforms\job51\actions_resume_close.py app\platforms\job51\actions_resume.py`：All checks passed。
  - 滚动续扫补齐后再次执行 live，处理结果为 0；只读摘要确认当前未读筛选开启，但可见未读行均为 `[已读]` / `[送达]` / `[平台推荐]`，按规则跳过。
- 风险 / 待确认：
  - live 输出在 PowerShell 中出现中文编码乱码，后续如果需要人工复盘候选人姓名和话术，应改用 `PYTHONIOENCODING=utf-8` 或写 JSON 报告文件。
  - 当前脚本仍坚持“只处理未读候选人消息”，不会处理 51job 的 `[平台推荐]` 或“已读未回”列表；如果后续要处理这些，需要单独做主动联系/跟进流程。

---

### 快照 0023：智联真实未读会话打开与 Enter 发送修复
- 修改时间：2026-06-27 17:15:35 +08:00
- 修改原因：
  - 真实智联页面中，通用 locator 点击 `.im-session-item__box` 不稳定，可能只保持在旧会话，导致候选人/岗位上下文误读。
  - 智联右侧详情没有稳定左侧 active 行，候选人和岗位必须从 `#im-session-detail` 的“沟通职位”区域读取，不能从左侧列表或全页 header 猜。
  - 真实发送按钮点击后未触发发送，原因是 `fill()` 后直接点按钮不能稳定触发智联内部输入状态；经验证聚焦输入框后按 Enter 可以真实发送。
- 修改文件：
  - `app/platforms/zhilian/dom_scripts.py`
  - `app/platforms/zhilian/actions.py`
  - `scripts/platform_once_common.py`
  - `app/browser/base.py`
  - `app/browser/playwright_cdp.py`
  - `app/browser/fake_page.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - 新增智联真实 DOM 会话行内部点击脚本，按行内实际坐标派发点击，并在动作层用右侧候选人/岗位做身份校验。
  - 智联未读行解析改为只认真实未读红点；有红点但无数字时按 1 条未读处理，不再因“未读筛选已打开”把所有行兜底成未读。
  - 智联上下文读取优先从 `#im-session-detail` 抽取候选人、岗位和消息，修复左侧第一行误当当前会话的问题。
  - 智联消息方向修正为只识别 `--me` / `mine` / `myself`，避免把 `resume` 字符串误判成己方消息。
  - 浏览器页面接口新增 `press()`；Playwright CDP 用真实键盘按键，FakePage 用当前输入模拟发送。
  - 智联发送动作改为填入后优先按 Enter 并校验最新己方消息，失败时再回退点击发送按钮。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_zhilian_phase1.py -q`：7 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\browser\base.py app\browser\fake_page.py app\browser\playwright_cdp.py app\platforms\zhilian\actions.py app\platforms\zhilian\dom_scripts.py scripts\platform_once_common.py`：All checks passed。
  - 真实智联 live 处理宋峰峰账号 3 人：郑潮洋发送外贸销售经历筛选问题；王振中发送 AI 应用开发基础条件；frank 命中已收到附件简历分支，未重复发送。
- 风险 / 待确认：
  - 智联附件简历目前仍只识别“已收到/可查看附件简历”，未实现像 51job 一样的真实 PDF 落盘下载。
  - PowerShell 直接输出中文仍可能乱码；真实复盘建议继续用 `PYTHONIOENCODING=utf-8` 或输出 JSON 文件。
---

### 快照 0024：收紧智联附件简历检测
- 修改时间：2026-06-29 08:34:39 +08:00
- 修改原因：
  - 智联页面里“要附件简历”只是可点击请求入口，不代表候选人已经发送附件简历。
  - 之前 fallback 文本检测把“附件简历”宽泛命中为已收到，可能导致符合条件候选人被误判为已有简历，从而不再请求附件。
- 修改文件：
  - `app/platforms/zhilian/dom_scripts.py`
  - `app/platforms/zhilian/actions.py`
  - `tests/agent/test_zhilian_phase1.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - 新增 `ZHILIAN_RESUME_STATE_JS`，只在当前聊天详情区内判断简历状态，避免扫描全页按钮文字。
  - 只有真实文件名后缀（`.pdf/.doc/.docx/.wps/.rtf`）、“查看附件简历”或附件卡片证据才算 `hasResumeAttachment=True`。
  - “要附件简历”仅作为 `canRequestResume` 证据，不再算已收到附件。
  - “已要附件简历 / 已向对方要附件简历 / 已请求附件简历”单独归为 `alreadyRequested=True`。
  - 新增回归测试覆盖：请求按钮不算已收到、查看附件算已收到、文件名算已收到、已请求不算已收到但标记已请求。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_zhilian_phase1.py -q`：8 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\zhilian\actions.py app\platforms\zhilian\dom_scripts.py tests\agent\test_zhilian_phase1.py`：All checks passed。
- 风险 / 待确认：
  - 这次只修“是否已有附件简历”的判定，不新增智联真实 PDF 下载落盘能力。
  - 如果智联真实页面的附件卡片不是文本/文件名形式，后续需要根据登录页面采样继续补充更精准的附件卡片选择器。

---

### 快照 0025：候选人会话状态持久化与简历 artifact 桥接
- 修改时间：2026-06-29 09:25:51 +08:00
- 修改原因：
  - 用户要求把“处理消息状态”和“简历入库解析”拆开：处理消息时只定位平台会话并快写下载 artifact，简历姓名先允许为空，后续解析入库时再回填 `parsed_name`。
  - 主关联依据必须是下载发生时的 `session_id`，不能依赖简历解析姓名；姓名只用于展示、检索和历史数据兜底匹配。
- 修改文件：
  - `app/db/schema.sql`
  - `app/db/engine.py`
  - `app/domain/conversation/__init__.py`
  - `app/domain/conversation/models.py`
  - `app/domain/conversation/dedup.py`
  - `app/domain/conversation/identity.py`
  - `app/domain/conversation/repository.py`
  - `app/domain/resume/models.py`
  - `app/domain/resume/repository.py`
  - `app/domain/resume/name_parser.py`
  - `app/domain/resume/artifacts.py`
  - `app/agent/persistence.py`
  - `app/agent/message_utils.py`
  - `app/agent/runner.py`
  - `app/worker/runtime.py`
  - `app/browser/read_once.py`
  - `app/platforms/job51/actions_resume.py`
  - `app/features/interview_center/service.py`
  - `app/api/routes/interview.py`
  - `app/api/routes/resumes.py`
  - `app/domain/resume/service.py`
  - `scripts/run_boss_once.py`
  - `scripts/boss_targeting.py`
  - `scripts/platform_once_common.py`
  - `tests/domain/test_conversation_state_bridge.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - 新增 `conversation_sessions`、`conversation_messages`、`candidate_status`、`resume_artifacts` 四张表；`resumes` 增加 nullable 桥接字段 `parsed_name / linked_session_id / linked_platform / linked_owner / linked_platform_conversation_id / source_artifact_id`。
  - `run_migrations()` 增加旧表预补列逻辑，避免旧库已有 `resumes` 表时，新索引先于补列执行导致启动失败。
  - 新增会话身份定位：优先 `platform + owner + platform_conversation_id + position`，没有平台 ID 时用 `candidate_name + position + recent_messages_fingerprint` 兜底；岗位纳入身份键，避免同人不同岗位串档。
  - 新增会话消息去重与候选人状态持久化；Runner 读取会话后先写 session/messages，处理完成后写阶段、下一动作和状态。
  - dry-run 只写观察状态和决策，不会把 `resume_requested / resume_downloaded / linked_*` 置为真实完成。
  - 新增 `resume_artifacts` 桥接层：51job 下载成功后写 `session_id / platform / owner / platform_conversation_id / candidate_name_from_platform / position / file_path / file_hash / parse_status=pending`，`parsed_name` 初始为空。
  - 新增 `parse_pending_artifacts()`：后续解析 artifact 文件，生成/更新 Resume，并回填 `parsed_name / linked_session_id / source_artifact_id`；简历姓名与平台显示名不一致时仍保持硬关联。
  - 51job 下载结果补充 `sourceKind`，区分 `attachment` 与 `online_resume`。
  - worker、BOSS/51/智联一次性脚本和 dry-run read 路径均显式注入同一套持久化仓储。
  - 简历 API 响应保留 snake_case 字段，同时补充 `parsedName / linkedSessionId / linkedPlatform / linkedOwner / linkedPlatformConversationId / sourceArtifactId`。
  - 面试入口新增会话定位：有 `linked_session_id` 时直接返回唯一 session；只有姓名+岗位匹配时返回候选列表并标记 `requiresConfirmation=True`。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\domain\test_conversation_state_bridge.py -q`：7 passed。
- 风险 / 待确认：
  - BOSS/智联真实 PDF 下载能力尚未新增；后续实现时必须复用 `ResumeArtifactStore.record_download()`。
  - artifact 解析目前是轻量文本/PDF 文本提取，复杂简历解析与字段清洗仍应由后续简历入库解析流程承接。

---

### 快照 0027：BOSS 已有附件简历预览下载补全
- 修改时间：2026-06-29 10:31:02 +08:00
- 修改原因：
  - 重新处理 BOSS 王岩时，系统已识别到“点击预览附件简历”，但直接 DOM 中没有可抓取的下载 href/bytes，导致 `boss_attachment_download_unavailable`。
  - BOSS 真实页面可能需要先点击附件预览，再从预览层触发下载或读取 blob/href，不能只扫描聊天消息里的 `a[href]`。
- 修改文件：
  - `app/platforms/boss/actions_resume.py`
  - `tests/agent/test_boss_phase2.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - BOSS 附件下载流程改为三段：先取直接 payload；失败则点击附件预览并等待 1 秒；再从预览层抓取 href/blob 或触发浏览器下载。
  - 新增真实 href fetch 兜底，使用页面登录态 `credentials: include` 拉取同源/可访问文件字节。
  - 下载成功后仍走统一校验与保存，不伪造 PDF，不拿到真实字节就不标记 `resume_downloaded`。
  - 新增回归测试覆盖“直接 payload 不存在，但预览下载能捕获真实 PDF 字节”的场景。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py::test_boss_existing_attachment_downloads_after_preview_click -q`：1 passed。
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py -q`：16 passed。
- 风险 / 待确认：
  - BOSS 预览层若使用非浏览器下载事件、且不暴露 href/blob，脚本仍会返回 blocked reason，不会假装已下载。
  - 仍需用真实 CB 浏览器重新处理王岩这类已发附件候选人，确认页面是否能触发下载事件。

---

### 快照 0028：BOSS 简历处理改为只求简历不本地下载
- 修改时间：2026-06-29 10:41:31 +08:00
- 修改原因：
  - 用户确认：BOSS 平台只需要执行“求简历/同意接收简历”，不需要把附件简历下载到本地。
  - 王岩会话已经出现“王岩的简历.pdf / 点击预览附件简历”，此时应视为 BOSS 已收到简历，而不是下载失败。
- 修改文件：
  - `app/platforms/boss/actions_resume.py`
  - `app/agent/persistence.py`
  - `tests/agent/test_boss_phase2.py`
  - `tests/domain/test_conversation_state_bridge.py`
  - `docs/change-snapshots-1.md`
- 修改结果：
  - BOSS `request_resume()` 遇到 `has_resume_attachment=True` 时直接返回 `resumeReceived=True / downloaded=False / reason=boss_attachment_present_no_local_download`。
  - 删除 BOSS 本地下载 helper 和预览下载 JS，避免后续误触发本地下载。
  - 持久化层改为：真实处理结果里只要 `resumeReceived=True` 就记录 `candidate_status.resume_received=True`；只有真实文件落盘并带 `filePath/fileHash` 才记录 `resume_downloaded=True` 和 artifact。
  - 重新处理王岩：阶段变为 `resume_attachment_received`，不再是 `resume_attachment_download_blocked`，没有写本地 artifact。
- 验证结果：
  - `.venv312\Scripts\python.exe -m pytest tests\agent\test_boss_phase2.py tests\domain\test_conversation_state_bridge.py -q`：25 passed。
  - `.venv312\Scripts\python.exe -m ruff check app\platforms\boss\actions_resume.py app\agent\persistence.py tests\agent\test_boss_phase2.py tests\domain\test_conversation_state_bridge.py`：All checks passed。
  - 真实 CB / BOSS targeted live：`scripts\run_boss_once.py --conversation-id 84959880-0 --limit 1 --live --confirm-live` 返回 `resume_attachment_received`。
- 风险 / 待确认：
  - BOSS 简历文件不会进入本地 `resume_artifacts`；如果后续要做 BOSS 简历入库，需要另接邮箱或 BOSS 平台导出来源。
  - 51job 仍保持“符合条件后下载到本地”；智联目前只识别附件/求附件，平台规则不受本次 BOSS 调整影响。
