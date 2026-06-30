# 修改快照记录 2

> 继续记录重构版 HR Agent 的代码修改。单文件控制在 600 行以内。

---

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
