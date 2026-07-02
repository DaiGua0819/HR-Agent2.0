---
name: boss-recruiter-automation
description: Use when operating BOSS recruiter automation for unread message handling, position screening, candidate Q&A, resume requests, and recruiter workflow status decisions.
---

# BOSS 招聘自动化

## 目标

处理招聘端 BOSS 会话：识别候选人岗位、处理未读消息、推进岗位筛选问题、知识库答疑、求简历、跳过不合适候选人，并输出处理统计。

## Function Call 选择

- 处理所有岗位的未读/新消息/未处理消息，直到没有未读：`recruiter_process_unread_all_positions`
- 处理当前已打开候选人，按其岗位规则推进：`recruiter_process_current_position`
- 只回答候选人最近 1-3 条未回复问题：`recruiter_answer_candidate_questions`
- 发送 AI 实习生公司基本情况/基础条件/常用语：`recruiter_send_company_info`
- 发送指定常用语：`recruiter_send_common_phrase`
- 求简历、同意候选人主动发来的附件简历，都必须调用 `recruiter_request_resume`；BOSS 运营 A/B、外部财务产品顾问、AI智能体解决方案负责人等直求简历岗位由工作流先发固定话术再求简历
- 最近 N 个联系人处理并观察后续回复：`recruiter_screen_recent_with_followup`
- 推荐牛人/主动打招呼/主动联系候选人：`recruiter_proactive_contact_recommended_candidates`
- 需要标记不合适且用户明确允许时：`recruiter_mark_unsuitable`

## 智能体工作流结构

1. Planner：识别用户目标，优先选择业务 functioncall，不让大模型临场猜按钮。
2. State：每个候选人必须保存 `agentWorkflow`、`stage`、`agentNextAction`、`conversationReview`。
3. Memory：候选人记忆以姓名、岗位、聊天 key 和页面 label 多重匹配，防止重名混淆。
4. Skill：岗位横向拓展只改 `boss_chat_rules.json` 的岗位 section，不复制 AI 实习生逻辑。
5. Tools：页面动作必须走后端工具，例如答疑、发话术、问筛选题、求简历、跳过。
6. Evaluation：每次状态变更写入 `recruiter_decision_log.json`，用于复盘“为什么这样处理”。
7. Monitor：Web 明细页可查看原始聊天、已读/求简历状态、智能体决策和筛选依据。

## 工作流

1. 未读任务先切到“未读”，从最上方候选人开始处理，不能继续读取当前聊天框替代未读会话。
2. 打开候选人后读取岗位、最近 1-3 条对方未回复消息、历史状态和是否已经求过简历。
3. 如果岗位是 AI 应用开发实习生：未发送基础情况就发常用语；对方接受关键条件就求简历；不接受线下、单休、六个月、薪资等硬条件就跳过；“考虑下”直接跳过等待后续回复。
4. 如果岗位是 BOSS 运营 A/B（`运营A`、`运营B`、企业内容运营负责人（B2B/短视频方向）、B端社交媒体运营）：不发送筛选问题，不主动回答岗位细节/是否还招等泛问题；未收到简历且未求过简历时，先在聊天界面发送 `你好可以看看简历吗` 或 `你好，方便发一份简历过来吗`，再执行“求简历”；已收到或已求过则不重复发送话术、不重复求简历。
5. 如果岗位是财务 AI 团队新增直求简历岗位（外部财务产品顾问/业财智能化顾问/AI财务场景顾问、AI智能体解决方案负责人/AI Solution Architect/AI FDE/AI Workflow Engineer）：不发送筛选问题；先按岗位配置发送 `resumeRequestPrompt`，再执行“求简历”；简历入库分别归类为 `外部财务产品顾问`、`AI智能体解决方案负责人`。
6. 如果岗位有 `companyKnowledgeBase.sections[岗位].screening`：按岗位配置的问题推进；必须项不满足就跳过；满足规则后求简历。
7. 需要发送筛选问题的岗位，先判断候选人当前是否有可回答的问题：知识库能答则先回复答案，再继续发送配置好的筛选问题；知识库不能答或规则外问题，不回复“暂时还不清楚”、不标记停在 `unknown_question`，直接跳过答疑并发送下一条配置筛选问题。
8. 不能因为候选人主动发了简历附件就直接求简历；必须结合最近几轮对话判断是否仍然合适。
9. 每个候选人的处理结果、未知问题、岗位、状态和时间都要记录，方便复查和后续补知识库。

## BOSS 简历 Function Call 契约

- 业务流程走到求简历、同意候选人主动发来的附件简历、或处理“对方想发送附件简历给您，您是否同意”卡片时，只调用 `recruiter_request_resume`。
- `recruiter_request_resume` 内部固定先执行 `boss_resume_consent_click`：在聊天消息卡片中定位可见的“同意”按钮，优先点击 `span.card-btn`，其次点击 `a.btn`。
- 如果没有待同意的附件简历卡片，`recruiter_request_resume` 再执行 `boss_request_resume_button_click`：在聊天工具栏 `.conversation-operate` / `.toolbar-box-right` 里点击可见的“求简历”按钮。
- 点击“求简历”后必须用 `boss_confirm_prompt_visible` 检测“确定向牛人索取简历吗？”确认层；确认层出现时执行 `boss_request_resume_confirm_click` 点击“确定/确认/发送请求/发起请求/继续”。
- 不要让模型/agent 临场猜 selector 或手工点按钮；所有真实点击都由 `recruiter_request_resume` 这条后端 function call 完成。

## 主动联系推荐牛人

1. 这套筛选条件只适用于“推荐牛人 / 主动打招呼 / 主动联系”流程，不复用到未读消息处理、聊天答疑、求简历或已沟通过候选人的判断。
2. 进入 BOSS 推荐牛人后，先确认 `.job-selecter-wrap .ui-dropmenu-label` 当前岗位等于目标岗位；不一致就切换岗位并二次确认。
3. 对每个正常 `.candidate-card-wrap`，先点击候选人卡片内容区，打开 `.dialog-wrap.active` 在线简历弹层。
4. 提取在线简历弹层里的简历/经历概览文本，并与卡片文本合并作为判断依据。
5. 使用合并后的简历文本执行主动联系门槛判断；不满足就关闭在线简历弹层并跳过。
6. 满足条件后，只点击在线简历弹层里的 `button.btn-greet` “打招呼”按钮，不额外点确认、继续沟通或其他按钮。
7. 打招呼后关闭在线简历弹层，再继续处理下一张正常候选人卡片。
8. 如果页面插入“更多牛人推荐 / 相似牛人 / 为你推荐 与某某相似的牛人”等区域，忽略它，小幅下滑后重新观察下一张正常候选人卡。
9. 已主动联系过的人必须按候选人状态和身份 key 去重跳过。
10. HRBP、人力资源、人力资源管培生都走同一套 HR 主动联系门槛：本科及以上、30 岁以下，专业为人力资源/相关专业或理工科。

## 大模型解析

- 基础条件和岗位筛选都使用结构化模型判定；模型只能输出 `not_asked`、`waiting`、`accept`、`reject`、`unclear`。
- 模型必须围绕岗位 `screening.questions`、`passRule`、`failRule` 判断，不能新增条件或改变岗位询问逻辑。
- 对方一次回复多个点时，要把回复拆到各个条件上；只回复其中一个条件时，不能误判为全部接受。
- 模型失败或结果不合法时，回退到规则判断。

## 回复与安全

- 回复尽量简短，不要编造知识库没有的信息。
- 不要绕过登录、验证码、权限限制或平台风控。
- 有业务 function call 时不要临场猜按钮 selector。
- 点击、滚动、输入的拟人化轨迹由后端执行层负责。
