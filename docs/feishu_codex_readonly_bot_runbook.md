# 飞书 Codex 查询与受控运行机器人手册

## 运行边界

机器人仍以独立进程运行 `scripts/run_feishu_bot.py`。内置 Codex 只负责生成只读查询计划，Shell、浏览器、MCP、Memory 和文件修改能力继续关闭。只有在 `config/feishu_bot_access.yaml` 中显式设置 `runtimeControl: true` 的 admin，才能通过固定命令调用受控招聘运行管理器。

机器人仅处理授权用户的飞书单聊。群聊、未知账号、候选人聊天原文、简历正文和运行控制命令都不会进入 Codex。运行控制由确定性代码直接分流。

## 运行控制命令

只接受以下三条完整文本，不接受参数或自由命令：

- `启动处理程序`
- `暂停处理程序`
- `查看处理状态`

`启动处理程序` 使用权威 `agent_manager.py` 执行 `start --adopt-running`，随后按 topology 中的固定顺序处理消息。运行参数由本地环境固定，不能通过飞书修改。

当前 `scripts/manage_feishu_bot.ps1` 通过 `FEISHU_BOT_RUNTIME_CONTROL_SKIP_TARGETS` 固定跳过 `宋峰峰:job51`，沿用该账号暂不处理 51job 的业务约束。跳过目标会出现在结束汇报中；飞书消息不能增加、删除或覆盖跳过项。

`暂停处理程序` 写入 `feishu_admin_pause` 优雅停止请求。当前联系人允许处理完成，随后停止下一联系人；不会强杀 Worker、关闭 CloakBrowser 或清除登录状态。

运行遇到 HTTP 500、临时连接失败、Worker/CDP 短暂不可用等基础设施异常时，默认最多自动恢复并重试 2 次。身份不匹配、登录验证、发送失败、未知问题、简历下载失败和残留遮罩等保护类异常不会自动重试。

每次批次结束后，机器人自动回复处理人数、业务简历获取、待简历回复、异常数和各平台汇总。BOSS 已验证的“求简历”动作按业务口径计为已获取简历，不要求本地 PDF。

## 登录与密钥

- 飞书应用登录状态保存在 lark-cli 专用 Profile `hr-agent-readonly-bot` 中，由当前 Windows 用户的 lark-cli 凭据存储管理。
- 仓库、`.env`、命令行和日志中不得保存飞书 App Secret 或访问令牌。
- `.env` 只保存 Codex 模型、网关地址和密钥环境变量名。
- Codex API Key 保存在当前 Windows 用户环境变量中。启动脚本只把配置指定的那一个密钥转交给隔离的 Codex 子进程。
- 用户权限只按 `config/feishu_bot_access.yaml` 中的专用应用 `openId` 精确匹配。当前不配置菜花账号。
- `role: admin` 本身不会自动获得控制权，必须同时配置 `runtimeControl: true`。

## 运维命令

在项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\manage_feishu_bot.ps1 -Action preflight

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\manage_feishu_bot.ps1 -Action start

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\manage_feishu_bot.ps1 -Action status

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\manage_feishu_bot.ps1 -Action stop
```

`preflight` 和 `start` 只在当前机器人子进程中设置启用状态和固定跳过目标，不会修改 `.env` 或系统环境。`start` 使用 Windows detached process 启动，并等待状态文件确认真实服务 PID 后才返回。

## 状态与审计

- 状态文件：`data/feishu_bot/state.json`
- 停止请求：`data/feishu_bot/stop.request.json`
- 运行锁：`data/feishu_bot/feishu-bot.lock`
- 标准输出：`data/feishu_bot/bot.out.log`
- 错误日志：`data/feishu_bot/bot.err.log`
- 独立审计库：`data/feishu_bot/feishu-bot.sqlite`

审计库只记录事件幂等状态、受限长度的问题和确定性回复。手机号、邮箱、Authorization、Cookie、access token 和 app secret 形态文本会在入库前脱敏。

## 安全重载

1. 执行 `preflight`，确认数据库、访问名单、飞书 Profile 和 Codex 凭据全部正常。
2. 执行 `stop`，等待 `status.running=false` 和 `status=stopped`。
3. 执行 `start`，确认返回 `started=true`，并记录新的真实服务 PID。
4. 再执行一次 `preflight`，确认长连接和只读查询依赖正常。
5. 检查控制面、Worker、自动同步和浏览器进程 PID 未变化。

禁止使用 `Stop-Process` 强杀机器人。正常回退只需停止该独立进程、切换代码版本并重新启动，其他服务无需重启。

## 权限验收

管理员应能查询：

- 岗位处理日报
- 简历数量和最近简历
- 审阅统计
- Worker 状态
- 最近异常

显式授权的运行管理员还应能：

- 启动固定招聘处理批次
- 请求优雅暂停
- 查询处理状态
- 在处理结束后收到自动汇报

以下行为必须被拒绝：

- member、未授权 admin 或群聊启动/暂停招聘处理程序
- 带参数、路径、Shell 片段或附加文字的运行控制命令
- 向候选人发送消息
- 下载、请求或修改简历
- 查询候选人聊天原文或简历正文
- 由内置 Codex 调用命令、文件、MCP、Web Search 或其他工具
- 通过飞书修改账号、平台顺序、异常阈值、规则、代码或部署配置

member 真实账号验收暂缓；在取得专用应用事件中的正确 `sender_id` 前，不得凭姓名或旧应用 `open_id` 添加权限。
