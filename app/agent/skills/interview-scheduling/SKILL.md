---
name: interview-scheduling
description: Use when inviting a resume-library candidate to interview through the candidate source platform account.
---

# 约面试自动化

## 目标

从简历库对候选人发起约面试沟通。系统必须回到候选人简历来源的平台账号，按当时聊天联系人使用的平台显示名搜索，再用岗位和少量聊天证据确认是同一个联系人，然后点击平台内置的“换微信”动作；如平台出现确认弹窗，需要点击确认。换微信校验成功后，再在当前聊天输入框发送固定消息“加我微信沟通”。

## 强制规则

- 必须使用 `platformContact.displayName` 搜索候选人，不能使用简历姓名、手机号、文件名、URL 或平台候选人 ID 兜底。
- 搜索完成后必须结合 `platformContact.chatEvidence`、`platformContact.appliedPosition`、来源平台和账号核对当前联系人。
- 搜索不到、同名多人无法用证据确认、缺少平台联系人名、账号未登录、人机验证、页面异常时立即停止并返回原因。
- 点击“换微信”前必须确认已经打开目标候选人的单聊页面，并定位到对应平台的换微信动作入口。
- 点击后必须校验页面出现交换微信请求、已交换微信、微信号可查看/复制等状态；校验不到则返回失败。
- 如果页面出现“确定与对方交换微信吗？”等确认弹窗，必须点击确认按钮；弹窗仍存在时不能判定换微信成功，也不能继续发送后续消息。
- 换微信校验成功后必须发送“加我微信沟通”；该消息发送失败时，本次约面试动作按失败记录，并返回 `interview_followup_send_failed`。
- 同一候选人已经发起过约面试/换微信时默认不重复执行。

## Function Call 设计

- 前端入口：简历库候选人行的“约面试”按钮。
- 后端入口：`POST /api/resumes/:id/interview-invite`。
- Agent 入口：`POST /api/interview-invite`，支持 `dryRun`。

请求核心字段：

- `platform`: `boss` / `51job` / `zhilian`
- `sourceKey`: `boss_a` / `boss_b` / `job51_a` / `job51_b` / `zhilian_a` / `zhilian_b`
- `platformContact.displayName`: 平台联系人当前使用的显示名
- `platformContact.label`: 当时联系人列表整行文本
- `platformContact.appliedPosition`: 当时沟通岗位
- `platformContact.chatEvidence`: 最近 3 条有效聊天片段
- `action`: `exchange_wechat`
- `dryRun`: 只搜索、核对、点开联系人并定位换微信按钮，不点击换微信

## 三平台流程

1. 打开对应账号当前招聘平台会话页。
2. 在联系人/人才搜索栏输入 `platformContact.displayName`。
3. 等待搜索结果出现。
4. 若存在多个同名联系人，必须用岗位或聊天证据确认；不能确认则停止。
5. 点开确认后的联系人。
6. 再次确认当前会话是目标候选人。
7. 定位平台内置“换微信”动作。
8. 点击“换微信”，如出现确认弹窗则点击“确定/确认/发送/发起交换”。
9. 校验页面出现交换微信请求、已交换微信、微信号可查看/复制等状态。
10. 在当前聊天输入框发送“加我微信沟通”，并校验最近己方消息中出现该文本。

## 换微信入口定位

- BOSS：聊天底部右侧 `.conversation-operate .operate-exchange-left`，按钮通常是 `.operate-icon-item` / `.operate-btn`，文字可能为“换微信”“交换微信”；已交换时显示“查看微信”。
- 51job：人才沟通页右侧候选人操作区 `.custom-operate` 内的 `.exchange-wx-btn` / `.exchange-wx-wrap`，文字为“换微信”。
- 智联：聊天底部 `.im-session-detail-footer .session-new-action` 内的 `.im-ask-for-wx`，按钮文字为“换微信”；已交换时可能显示“微信号”或“复制微信号”。

## 失败原因

- `missing_platform_display_name`: 简历缺少平台联系人显示名。
- `search_input_not_found`: 当前平台页没有找到可用搜索栏。
- `search_result_not_found`: 搜索后未找到可确认的目标联系人。
- `multiple_candidates_unverified`: 同名候选人过多，无法用岗位或聊天证据确认。
- `chat_evidence_not_matched`: 未能匹配岗位或聊天证据。
- `wechat_exchange_button_not_found`: 已确认联系人，但没有找到可点击的换微信按钮。
- `wechat_exchange_button_disabled`: 换微信按钮不可用。
- `wechat_exchange_confirm_failed`: 换微信确认弹窗点击失败。
- `wechat_exchange_confirm_required`: 换微信确认弹窗仍存在，未完成确认发送。
- `wechat_exchange_verification_failed`: 点击后没有校验到交换微信请求或微信状态。
- `interview_followup_send_failed`: 换微信成功，但“加我微信沟通”发送或校验失败。
- `captcha_or_login_required`: 页面要求登录、人机验证或账号异常。

## 安全演示边界

- `dryRun=true` 只能用于验证打开平台、搜索联系人、核对联系人和定位换微信按钮，不点击换微信。
- 非 `dryRun` 分支会点击平台内置“换微信”，不能用于“点到按钮前停止”的演示。
- 如需演示到换微信按钮前停止，必须使用 `dryRun=true`。
- 演示前必须确认目标平台账号处于 agent ready 状态：浏览器 ready、CDP ready、agent ready 三项都需要通过。
