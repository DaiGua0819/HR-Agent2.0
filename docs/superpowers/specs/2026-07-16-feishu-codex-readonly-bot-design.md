# 飞书 Codex 只读招聘机器人设计

## 目标

版本 A 在不改变现有控制面、Worker、浏览器自动化、简历同步和面试中心行为的前提下，新增一个独立运行的飞书单聊机器人。机器人使用 Codex 理解自然语言，但只能规划并调用招聘系统提供的只读查询；所有事实由受权限约束的本地查询服务返回。

## 非目标

- 不启动、暂停或继续任何招聘程序。
- 不发送候选人消息、不求简历、不下载简历。
- 不修改规则、代码、数据库业务数据或飞书文档。
- 不在群聊展示招聘数据。
- 不让 Codex 访问招聘数据库、浏览器 Profile、Cookie、Token 或任意 Shell 能力。

## 架构

```text
飞书单聊消息
  -> lark-cli 独立机器人 Profile 长连接
  -> event_id/message_id 幂等仓储
  -> open_id 白名单与岗位范围解析
  -> Codex 只输出结构化查询计划
  -> 服务端再次校验意图和参数
  -> SQLite 只读查询 / Worker 只读状态
  -> 确定性中文结果渲染
  -> lark-cli 以 bot 身份回复原消息
```

机器人作为 `scripts/run_feishu_bot.py` 独立进程运行，不挂入 FastAPI lifespan，不共享现有 Dispatcher 实例，也不启动任何 Worker。

## 飞书应用隔离

现有 `day1` 应用已经存在一个未知来源的长连接实例。版本 A 不停止、不复用该连接，创建名为 `hr-agent-readonly-bot` 的独立飞书应用和 lark-cli Profile。

独立应用只申请以下最小权限：

- `im:message.p2p_msg:readonly`：接收机器人单聊消息。
- `im:message`：回复消息。

应用可用范围只包含明确授权的 admin/member。应用密钥保存在 lark-cli Profile 的凭据存储中，不写入仓库、`.env`、日志或命令行。

## 身份与权限

机器人身份只使用独立应用下的飞书 `open_id`，不使用姓名推断权限。配置文件 `config/feishu_bot_access.yaml` 明确记录：

- `openId`
- `displayName`
- `role`: `admin` 或 `member`
- `jobTypes`
- `reviewUserId`，用于关联现有简历审阅账号
- `enabled`

权限规则：

| 能力 | member | admin |
| --- | --- | --- |
| 单聊帮助 | 允许 | 允许 |
| 岗位处理日报 | 仅授权岗位 | 全部岗位 |
| 简历数量与最近简历 | 仅授权岗位 | 全部岗位 |
| 个人审阅统计 | 仅本人 | 全部及共享待处理 |
| Worker 状态 | 禁止 | 允许 |
| 最近异常摘要 | 禁止 | 允许 |
| 候选人聊天原文 | 禁止 | 版本 A 也不开放 |
| 任意写操作 | 禁止 | 版本 A 也禁止 |

未知、停用或未配置 `open_id` 只返回无权限提示，不向 Codex发送原始问题。

## Codex 隔离

Codex 只负责把用户问题转换成 `BotQueryPlan`：

```json
{
  "intent": "daily_summary",
  "date": "2026-07-16",
  "dateStart": "",
  "dateEnd": "",
  "jobTypes": ["AI产品经理"],
  "owner": "",
  "platform": "",
  "limit": 10,
  "clarification": ""
}
```

允许的 intent：

- `help`
- `daily_summary`
- `resume_counts`
- `recent_resumes`
- `review_summary`
- `worker_status`
- `recent_errors`
- `unsupported`

Codex 运行约束：

- `codex exec --ephemeral`
- 独立空工作目录
- `default_permissions=":read-only"`
- `approval_policy="never"`
- 禁用 web search、MCP、记忆和用户配置
- 模型生成命令的环境变量继承设为 `none`
- 使用 JSON Schema 约束最终输出
- JSONL 中一旦出现命令、文件修改、MCP 或网络工具事件，立即判定 `codex_policy_violation`，不执行计划

Codex 不接收数据库查询结果。回复由应用根据结构化结果确定性渲染，杜绝模型修改人数或泄漏未授权数据。

## 查询口径

### 每日处理

优先复用 agent-manager 的统计合同：

- 处理人数：当天 manager JSONL 中每个平台、账号、候选人、岗位的最后一条成功联系人结果。
- BOSS 简历获取：已验证的求简历动作计为业务简历获取。
- 51job/智联简历：当天 `resume_artifacts` 中不同 `file_hash` 的本地文件。
- 异常：manager JSONL 中 `classification.is_anomaly=true`。

返回值必须带 `coverage`，当 manager 日志不存在或联系人无法映射时明确说明覆盖缺口。

### 简历库

- 全量数量从 `resumes` 读取。
- 日期范围内新增文件优先从 `resume_artifacts.created_at` 读取。
- 结果按 canonical job type 聚合并在 SQL/查询层应用岗位权限。
- 最近简历只返回姓名、岗位、评分、平台、账号和时间，不返回手机号、邮箱、简历正文或文件路径。

### 审阅统计

- member 只读取 `reviewUserId` 对应的个人判断统计。
- admin 可读取共享管理员待处理池及全局判断聚合。

## 事件、审计与隐私

新增表：

- `feishu_bot_events`：事件和消息幂等、处理状态、错误和回复 ID。
- `feishu_bot_turns`：受限长度的用户问题、机器人回复、意图和时间。

约束：

- `event_id` 与 `message_id` 均唯一。
- 重复事件不重复查询、不重复回复。
- 单条问题最多保存 1000 字，回复最多保存 4000 字。
- 入库前遮蔽手机号、邮箱、access token、app secret 和 Cookie 形态文本。
- 日志不记录 Codex 完整 prompt、数据库原始 payload 或 lark-cli 凭据。

## 错误处理

- 群聊：只回复通用帮助，不执行查询。
- 未授权用户：返回无权限提示并记录拒绝原因。
- Codex 超时/不可用：使用安全关键词规划器处理常见查询；仍无法识别时返回示例帮助。
- 数据库不可读：返回“招聘数据暂不可用”，不创建或迁移业务库。
- 飞书回复失败：事件标记 `reply_failed`，保留幂等键，人工重试前可追溯。
- 长连接断开：指数退避重连；发现同应用已有远端连接时停止并报告，不主动结束其他实例。

## 运行与回退

- 默认 `FEISHU_BOT_ENABLED=false`。
- `preflight` 只检查，不消费事件。
- `serve` 使用独立单实例锁和状态文件。
- `stop` 通过停止请求文件优雅关闭，禁止强杀事件进程。
- 回退只需停止机器人进程；现有服务无需重启。

## 验收

- member 无法查询未授权岗位、Worker 或异常。
- admin 可以查询全局日报、Worker 和异常，但不能执行任何写操作。
- 重复飞书事件只产生一次回复。
- 群聊不返回招聘数据。
- Codex 发生工具调用时计划被拒绝。
- 现有自动化、简历库、面试中心、同步和平台测试全部通过。
- 使用 1 名 admin 与至少 1 名 member 完成真实单聊验证。
