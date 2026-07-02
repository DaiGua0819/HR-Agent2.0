---
name: 51job-recruiter-automation
description: Use when operating 51job recruiter automation for unread message handling, current-candidate screening, candidate Q&A, and resume requests using the same business rules as the BOSS recruiter automation.
---

# 51job 招聘自动化

## Function Call 选择

- 处理 51job 已配置岗位的未读消息：`job51_process_unread_all_positions`
- 处理当前已打开候选人：`job51_process_current_position`
- 只回答当前候选人的最近问题：`job51_answer_candidate_questions`
- 当前候选人满足筛选后求简历：`job51_request_resume`
- 人才望远镜主动联系/立即Hi聊：`job51_proactive_contact_recommended_candidates`；主动联系只能点击“人才望远镜”入口进入，不能直接打开推荐页 URL。

## 平台边界

- 真实浏览器只使用 owner 对应的 CloakBrowser：一个招聘号一个 CB 浏览器，BOSS / 51job / 智联在同一个浏览器的三个标签页中运行；不要恢复每平台独立 CDP。
- 51job 当前处理这些已配置岗位：`膨润土销售人员`、`国际业务管培生`、`电气工程师`、`应用技术经理（工业涂料领域）`、`外贸销售经理（流变助剂）`、`销售工程师（石油钻井泥浆膨润土）`、`销售管培生`、`AI应用开发实习生`、`AI应用开发工程师`、`HRBP`、`人力资源`、`人力资源管培生`、`外部财务产品顾问`、`AI智能体解决方案负责人`、`投资交易策略研究员（量化与市场情绪方向）`、`企业内容运营负责人（B2B/短视频方向）`、`B端社交媒体运营`。
- `机电工程师（嵌入式开发方向）` 当前没有业务规则；即使聊天列表可见也按未配置岗位跳过，不发送消息。
- 业务判断复用 `boss_chat_rules.json`：岗位知识库、筛选问题、候选人问题答疑、基础条件判断和决策日志风格都沿用现有 BOSS 规则。
- DOM/按钮定位只放在 `job51_` 前缀适配层里，不把 51job selector 混进 BOSS function call。

## 51job 聊天页定位

- 进入人才沟通：`#sensor_talentcommunicate`
- 岗位标签：`.position-menu .menu-item`、`.menu-item_content_short`、`.menu-item-all`
- 未读筛选：`label.el-checkbox.btn.unread-checkbox`
- 会话列表：`#conversation-list .list-item`
- 会话行岗位：`.jobname`
- 当前候选人名：`div.im_userName span.username-text`、`div.im_userName`
- 消息项：`div.im-message-item`、`div.message-item.others`、`div.message-item.mine`
- 输入框：`#drop-area.input-textarea_self`
- 发送按钮：`button.el-button.new-send-button.el-button--primary`
- AI 辅助引导弹窗取消按钮：`button.ai-guide-btn-no`
- 微信提醒关闭：`.wechat-notify .close`、`.wechat-notify .el-icon-close`
- 人才望远镜入口：`#sensor_recommand_menu`；主动联系必须从这个入口点击进入。
- 人才望远镜候选人卡片：`div.item.resume-card`、`.resume-card`
- 人才望远镜打招呼按钮：`button.el-button.tm_button.el-button--primary`，文本通常是 `立即Hi聊`
- 通用广告/引导关闭：优先点击 `不感兴趣`、`跳过`、`稍后再说`、`知道了/我知道了`、关闭 X；包括推荐 AI 回复、微信通知、driver guide 等遮挡层。
- 底部操作按钮：`div.operate-item`
- 聊天简历卡片里的附件简历按钮：`.resume-element .info-content-item.file-item`
- 附件 PDF 预览层：`.annex-resume`
- 附件 PDF 预览层下载链接：`.annex-resume #sensor_Bchatinfo_xiazai a`、`.annex-resume .item-download a`
- 附件 PDF 预览层关闭按钮：`.annex-resume .container-close`
- 批量面板：`section.batch-chat-panel`、`.wrap-item`、`.batch-chat-item`

## 处理流程

1. 进入 51job 人才沟通页后，按已配置岗位逐个切换岗位标签；页面不存在的岗位记录为跳过。
2. 每个岗位先打开未读筛选，再从列表顶部逐个打开未读候选人。
3. 读取候选人姓名、岗位、最近消息和历史消息，匹配 `boss_chat_rules.json` 里的岗位 section。
4. 岗位未配置时只记录并跳过，不发送消息、不求简历。
5. AI 应用开发实习生走基础条件流程：未发送则发送基础条件；候选人明确接受后再求简历；拒绝或不明确则跳过等待后续。
6. 销售、国际业务、应用技术、电气、HRBP/人力资源类岗位走岗位专属筛选问题：未问则发送配置里的问题；明确通过后求简历；明确不满足则跳过；有问题先用知识库答疑。
7. 运营 A/B（企业内容运营负责人（B2B/短视频方向）、B端社交媒体运营）在 51job 不回答岗位问题、不发送筛选问题；未收到简历且未求过简历时，先发送 `你好可以看看简历吗` 或 `你好，方便发一份简历过来吗`，再执行 51job 求简历/下载简历函数。
8. 财务 AI 团队新增直求简历岗位（外部财务产品顾问/业财智能化顾问/AI财务场景顾问、AI智能体解决方案负责人/AI Solution Architect/AI FDE/AI Workflow Engineer）不发送筛选问题；先用 51job 专用发送函数发送岗位配置的 `resumeRequestPrompt`，再执行 51job 求简历/下载简历函数。
9. 51job 只有在岗位逻辑已经走到“需要简历”时才执行 `job51_request_resume`；不能因为页面看见“附件简历/在线简历”就提前下载。
10. 候选人提问时只使用岗位知识库回答；知识库没有答案时不回复，只记录为待补充问题。
11. 发送前先关闭 51job AI 辅助引导和微信提醒等遮挡层；发送按钮用 51job 专用点击路径触发，发送后必须用 `div.message-item.mine` 最近消息校验，不使用 BOSS 通用消息解析器。
12. 会话列表中出现 `[送达]`、`[已读]` 的行视为已经回复过，本轮未读扫描跳过，避免重复处理刚发送过的候选人。
13. 未读扫描只处理真实会话行，跳过 `[平台推荐]` 和“以下是为你推荐的人才”等推荐区块。
14. 只有最后一条消息来自候选人时才做模型辅助判断/会话复盘；最后一条是我方消息时直接进入等待状态，避免无意义慢调用。
15. 所有点击和发送串行执行，并保留稳定等待和动作校验，避免过快操作。
16. 每个候选人的处理结果写入批量报告和决策日志，`type` 使用 `job51_process_unread_all_positions`。

## 51job 简历下载 / 求简历流程

- `job51_request_resume` 只能由“直求简历 / AI 基础条件接受 / 岗位筛选通过”等需要简历的业务分支调用；不要在读取会话阶段提前调用。
- 如果当前聊天消息里有简历卡片，并且卡片里有“附件简历”，优先点击 `.resume-element .info-content-item.file-item`。
- 点击“附件简历”后，51job 会打开 `.annex-resume` PDF 预览层；这一步不是最终下载成功。
- PDF 预览层底部的“下载”按钮是 `.annex-resume #sensor_Bchatinfo_xiazai a` / `.annex-resume .item-download a`，其 `href` 通常是 `blob:https://ehire.51job.com/...#toolbar=0`，`download` 属性带真实文件名。
- 下载动作必须抓取该 blob 的真实字节，并通过文件头校验：PDF 必须以 `%PDF-` 开头，docx 必须是 `PK`，doc 必须是 OLE 头。
- 如果聊天里没有“附件简历”，但右上角候选人信息区有“在线简历”，在候选人已符合条件后点击该入口并下载真实导出文件。
- 下载成功后保存到项目相对目录 `data/downloads/job51/`，并返回 `downloaded=True`、`resumeReceived=True`、`fileHash`、`filePath`。
- 下载完成或失败后都要关闭 `.annex-resume .container-close`，避免 PDF canvas 遮挡后续会话点击。
- 只有“在线简历/附件简历”的可见文字、没有真实附件卡片或 blob 下载链接时，不允许伪造 PDF、不允许入库；应回退为正常 in-chat 求简历。
- 如果当前会话没有可下载附件，也没有可下载在线简历，才寻找“求简历”按钮并处理确认弹层。

## 主动联系推荐候选人

1. 使用 `job51_proactive_contact_recommended_candidates`，必须先点击左侧/导航里的“人才望远镜”入口进入推荐候选人页；如果找不到该入口，任务直接阻断，不通过 URL 直跳推荐页。
2. 进入 51job 人才望远镜后先切换到目标岗位。
3. 只处理当前 51job 岗位中已配置主动联系门槛的岗位；未配置门槛的岗位跳过，不直接打招呼。
4. 候选人卡片文本作为第一版筛选证据，复用 BOSS 主动联系的学历、年龄、关键词/专业门槛。
5. 膨润土销售人员要求大专及以上、35 岁以下，并且有涂料/膨润土/流变助剂任一证据。
6. 销售管培生要求大专及以上、25 岁以下。
7. 石油钻井泥浆膨润土销售要求大专及以上、45 岁以下，并且有石油/钻井/泥浆/膨润土/油服任一证据。
8. 应用技术经理要求本科及以上、45 岁以下，并有流变助剂/膨润土/工业涂料/涂料研发/涂料工程师任一证据。
9. 国际业务管培生要求本科及以上、25 岁以下，并且专业为国际贸易/英语/俄语/翻译，或理工科且英语六级。
10. 电气工程师要求本科及以上、35 岁以下，专业为电气工程或自动化，并且简历体现 PLC。
11. HRBP/人力资源/人力资源管培生要求本科及以上、30 岁以下，并且专业为人力资源、人力资源相关专业或理工科。
12. 外贸销售经理要求有外贸/国际贸易/英语/出口/海外/化工等证据；AI 应用开发实习生主动联系门槛未配置前不批量打招呼。
13. 默认支持 `dryRun` 预览符合条件候选人；非 dryRun 时才点击 `立即Hi聊`。
14. 每次采集、点击前后都先执行广告/引导清理，避免推荐 AI 回复等遮挡任务流程。

## 2026-06-04 Job51 Proactive Flow Note

- Enter the recommended-candidate page only by clicking `#sensor_recommand_menu` / Talent Telescope. Do not direct-open the recommend URL.
- Select the exact target job tab before reading candidates. Do not map a non-equivalent job tab just because it is text-similar.
- For each candidate, click the candidate card body first. 51job usually opens a new resume detail page.
- Read the detail page text as the primary screening evidence: intent, work history, education, age, and job-specific keywords.
- After reading, close the new detail page or go back to the Talent Telescope list.
- If the candidate passes the configured rules and the original card still has `Hi` / greet button, click the original card button.
- The detail page itself may show `Hi` buttons for similar candidates lower on the page; do not treat those as the current candidate action.
- Record the detail URL in proactive contact state and reports so later audits can explain why a candidate was greeted or skipped.

## 2026-06-04 Job51 AI Gold / Traditional Mode Note

- The same left-nav entry `#sensor_recommand_menu` may display either Talent Telescope or `AI淘金`.
- Proactive contact must run in the traditional Talent Telescope list, because that mode has stable job tabs and `div.item.resume-card` candidate cards.
- After entering the recommend page, first check whether the page is already traditional: candidate cards exist, job tabs exist, and `.ai-mode-switch` is not active.
- If the nav text is `AI淘金`, or `.ai-mode-switch` has `ai-mode-switch-active`, switch back by targeting the outer `.ai-mode-switch`, not the inner SVG/icon. Move the visible cursor to the switch first, then use the stable outer switch click and verify the mode.
- After switching, verify the nav text returns to Talent Telescope and candidate cards are visible before selecting jobs or greeting candidates.
- If the mode cannot be verified as traditional, block the proactive task instead of processing candidates in AI Gold mode.

## 2026-06-04 Job51 Humanized Review Note

- Proactive contact on 51job must use visible mouse movement and trail for nav entry, mode switch, job tab selection, candidate card open, scroll, and `Hi` click.
- For the AI Gold / traditional mode switch, coordinate clicks on `.ai-mode-switch-inner` can miss even when the cursor is visually on the icon. Use the outer `.ai-mode-switch` after a visible cursor move, then verify the traditional list before continuing.
- Do not use instant DOM clicks for the visible workflow unless every humanized/stable mouse click attempt fails and the task is being safely blocked.
- After opening a candidate card, stay on the resume detail page long enough to read basic information, work history, education, age, and job-specific evidence.
- While reading detail, perform a small humanized scroll and optional adjustment scroll before making the screening decision.
- If the card click does not open a resume detail page, retry once with a slower card-body click. If it still stays on the list page, skip the candidate as `detail_page_not_opened_after_card_click`.
- Never treat the recommendation list page as the candidate detail page; a valid detail must be a resume detail page or an actually opened detail view.
- 51job recommendation cards open most reliably from the candidate name/avatar area, not the middle work-history area. Use a visible mouse move to the name area first, then retry once near the upper-left information area.
- Detail-page open waits and reading waits should use real browser waits, not the globally accelerated operation-speed wait, so the user can see that the resume was actually opened, read, scrolled, and judged.
- 51job proactive job-specific thresholds should mirror the BOSS proactive thresholds for jobs that need proactive outreach. AI application intern must not be proactively contacted; skip it as `ai_intern_proactive_contact_disabled`, and only process AI interns after they message first through the normal basic-condition chat flow.
- 51job platform common gates are platform-specific: confirm a real `/Revision/talent/resume/detail` page, dedupe against `proactive|`, `job51_proactive|`, and `zhilian_proactive|` states, and skip candidates whose detail text shows prior communication records such as communication date, communication job, already communicated, or continue communication.
- In the 51job Talent Telescope list, skip candidate cards that show a visible `已看` badge in the top-left corner of the list card. These people have already been reviewed and should not be opened, screened, or greeted again.

## 2026-06-24 Job51 Real Resume Download Note

- For all 51job accounts, use the same real attachment flow; do not keep account-specific names such as hexinhong in the function logic.
- Real chat attachments may appear as a resume card with two actions: `在线简历` and `附件简历`. Do not download them merely because they are visible; download only after the shared business flow decides the candidate is qualified and needs a resume.
- When resume is needed, prefer `附件简历 -> .annex-resume preview -> bottom 下载 link`. If no chat attachment is available, use the top-right `在线简历` entry before falling back to in-chat 求简历.
- The bottom download link is usually a blob URL. Fetch the blob bytes in page context, verify the file signature, save it under `data/downloads/job51/`, and return the saved file path.
- Only real files can be counted as downloaded resumes: PDF `%PDF-`, docx `PK`, or doc OLE header.
- Visible online-resume preview text in the chat is not a real resume. Do not convert it to PDF, do not add it to the resume library, and do not mark the candidate as downloaded.
- If no real attachment card, no top-right online resume export, no blob link, and no valid bytes are available, fall back to the normal in-chat resume request and record the result as requested, not downloaded.
