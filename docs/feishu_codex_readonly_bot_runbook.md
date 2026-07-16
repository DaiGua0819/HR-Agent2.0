# 飞书 Codex 只读招聘机器人运行手册

## 运行边界

版本 A 是独立进程，只运行 `scripts/run_feishu_bot.py`。它不会启动或停止控制面、Worker、浏览器自动化、自动同步和面试中心，也不能向候选人发送消息或修改招聘业务数据。

机器人仅处理授权用户的飞书单聊。群聊、未知账号、候选人聊天原文、简历正文和任何写操作都不会进入 Codex。

## 登录与密钥

- 飞书应用登录状态保存在 lark-cli 专用 Profile `hr-agent-readonly-bot` 中，由当前 Windows 用户的 lark-cli 凭据存储管理。
- 仓库、`.env`、命令行和日志中不得保存飞书 App Secret 或访问令牌。
- `.env` 只保存 Codex 模型、网关地址和密钥环境变量名。
- Codex API Key 保存在当前 Windows 用户环境变量中。启动脚本只把配置指定的那一个密钥转交给隔离的 Codex 子进程。
- 用户权限只按 `config/feishu_bot_access.yaml` 中的专用应用 `openId` 精确匹配。当前不配置菜花账号。

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

`preflight` 和 `start` 只在当前机器人子进程中设置 `FEISHU_BOT_ENABLED=true`，不会修改 `.env` 或系统环境。`start` 使用 Windows detached process 启动，并等待状态文件确认真实服务 PID 后才返回。

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

## 只读验收

管理员应能查询：

- 岗位处理日报
- 简历数量和最近简历
- 审阅统计
- Worker 状态
- 最近异常

以下行为必须被拒绝：

- 启动或停止招聘处理程序
- 向候选人发送消息
- 下载、请求或修改简历
- 查询候选人聊天原文或简历正文
- 调用命令、文件、MCP、Web Search 或其他 Codex 工具

member 真实账号验收暂缓；在取得专用应用事件中的正确 `sender_id` 前，不得凭姓名或旧应用 `open_id` 添加权限。
