# 修改快照记录 1

> 继续记录重构版 HR Agent 的代码修改。单文件控制在 600 行以内。

---

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
