# 管理者驾驶舱、简历审阅与面试中心整合 UI 设计

## 背景

当前重构版 `hr-agent` 已经具备三平台自动化、控制面、worker、真实 CloakBrowser 接入、会话状态、简历 artifact、简历审阅工作台、飞书登录权限设计和面试中心后端模块。旧服务器版本已经在线运行，提供了丰富的运营功能：六账号浏览器状态、三平台处理消息、主动联系、暂停、24 小时轮转、每日统计、自动化明细、简历库、批量导入、规则学习和面试中心。

旧版的问题是功能都堆在一个长页面里：简历审阅、平台控制、统计、批量、规则、面试入口混在一起。管理者想看今日处理数据时要在页面里找统计；普通筛选人员看简历时也会看到过多高风险控制按钮。新版需要把这些能力重新组织成清晰的信息架构。

本设计目标是把旧版可用能力与重构版干净架构结合起来，形成一个更舒服、更安全、更适合日常使用的招聘管理后台。

## 只读调研结论

已只读查看旧服务器，没有修改服务器文件或服务。旧版服务结构如下：

- 入口：`http://218.244.142.84:8080/index.html`，外层 Basic Auth。
- Web 代理：`recruit_web_proxy.js` 转发到内部 `127.0.0.1:8765`。
- 旧后端：`patchwork-recruit-gpt/server.js` 通过 `server/runtime/legacyServerLoader.js` 加载 `server/legacy-parts/server.part*.js`。
- 旧控制维度：两个人、三平台、六个自动化目标。
- 旧接口已提供：
  - `/api/boss-automation/summary`
  - `/api/platform-automation/summary`
  - `/api/boss-automation/details`
  - `/api/51job-automation/details`
  - `/api/zhilian-automation/details`
  - `/api/automation-browser/status`
  - `/api/automation-24h/status`
  - `/api/automation-24h/settings`
  - `/api/resumes`
  - `/api/rule-suggestions`
  - `/api/interview-center/*`

旧版今日 summary 已能返回管理者关心的指标：处理人数、询问问题、求简历、候选人提问、获取简历、已答疑、主动联系点开人数、主动打招呼人数、主动回复人数、主动符合人数。details 已能返回候选人、平台、账号、岗位、动作、状态、简历文件、聊天摘要和命中记录。

## 参考项目

本次 UI 不照搬单个项目，而是借鉴多个开源项目的成熟模式：

- [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin)：后台 AppShell、左侧导航、响应式布局、主题结构。
- [openstatusHQ/openstatus-template](https://github.com/openstatusHQ/openstatus-template)：指标卡、服务状态卡、空状态、事件流。
- [twentyhq/twenty](https://github.com/twentyhq/twenty)：CRM 对象详情体验，适合候选人、简历、会话和任务。
- [sadmann7/tablecn](https://github.com/sadmann7/tablecn)：高级表格、筛选、排序、列显隐、批量操作。
- [calcom/cal.diy](https://github.com/calcom/cal.diy)：日程、预约、面试状态流。
- HR dashboard / ATS 类项目：用于参考候选人阶段、岗位维度和招聘漏斗，但不直接复制其页面。

视觉方向是企业内部运营工具：安静、密集、稳定、可快速扫视。避免营销式 hero、大面积渐变、装饰卡片堆叠和功能混放。

## 目标

- 管理者登录后第一眼看到今日处理数据、服务状态、异常和可操作入口。
- 普通筛选人员登录后只看到自己有权限的简历库和待处理队列。
- 简历审阅保持固定三栏，不需要整页上下滚动。
- 面试中心作为一级菜单存在，同时从简历详情和待处理队列提供快捷入口。
- 自动化控制从简历库中拆出去，集中在高风险操作页面，并保留 dry-run/live 安全提示。
- 旧版按钮背后的可用逻辑尽量复用，不重写三平台业务规则或面试中心编排。
- 所有页面和 API 都按角色和数据范围做权限控制。

## 非目标

- 不在本阶段重新设计三平台岗位处理规则。
- 不把旧版长页面原样迁移到新版。
- 不把自动化控制按钮放进普通简历审阅列表。
- 不在第一版做复杂流程审批。
- 不在前端硬编码权限，后端必须强制校验。
- 不重写面试中心核心后端逻辑，优先复用现有 `features/interview_center`。

## 信息架构

推荐登录后 AppShell：

```text
HR Agent
├─ 经理驾驶舱
├─ 简历库
├─ 待我处理
├─ 面试中心
├─ 自动化控制
├─ 规则与知识库
└─ 系统设置
```

路由建议：

```text
/login
/app/dashboard
/app/resumes
/app/resumes/:id
/app/review-queue
/app/interviews
/app/interviews/:sessionId
/app/automation
/app/rules
/app/settings
```

默认入口：

- `super_admin`：进入 `/app/dashboard`。
- `owner_admin`：进入 `/app/dashboard`，但只显示授权 owner 范围。
- `resume_viewer`：进入 `/app/resumes`。
- `interviewer`：进入 `/app/interviews` 或 `/app/review-queue`。
- `readonly`：进入只读简历库。

## 整体布局

使用固定 AppShell：

```text
左侧导航：
  HR Agent 标识
  一级菜单
  当前环境 / dry-run 状态

顶部栏：
  当前页面标题
  全局搜索
  日期范围
  平台 / 账号 / 岗位全局筛选
  当前登录人、角色、退出

主内容：
  根据路由展示驾驶舱、简历库、面试中心或控制页
```

页面宽度按工作台处理：

- 1440px 以上：左侧导航 + 主要内容完整展示。
- 1024-1439px：保持导航，表格和右侧详情可折叠。
- 小屏：导航收进抽屉，宽表横向滚动或卡片化。

## 视觉规范

采用浅色主界面：

```text
背景：#F6F7F9 / #F8FAFC
主内容面：#FFFFFF
正文：#111827 / #0F172A
弱文本：#64748B
边框：#E5E7EB
主按钮：#2563EB
成功：#16A34A
等待：#D97706
异常：#DC2626
信息：#0891B2
```

组件风格：

- 卡片圆角不超过 8px。
- 表格密度中等偏紧，适合运营快速扫视。
- 状态用 badge + 文本，不只靠颜色。
- 图标统一用 lucide 或 shadcn 体系，不使用 emoji 作为结构图标。
- 控制按钮明确区分主操作、次操作、危险操作。
- 危险操作必须有二次确认或显式 live 确认。

## 经理驾驶舱

经理驾驶舱是管理者首页，目标是回答四个问题：

1. 今天系统处理了多少人？
2. 哪个平台、哪个账号、哪个岗位贡献了结果？
3. 哪些服务在线、哪些异常？
4. 我现在可以安全地点哪些控制按钮？

页面结构：

```text
第一行：今日 KPI
  今日处理人数 / 求简历 / 获取简历 / 已解析 / 合适 / 待我处理 / 异常

第二行：服务状态
  六个目标卡片：BOSS 宋峰峰、BOSS 和新红、51 宋峰峰、51 和新红、智联 宋峰峰、智联 和新红

第三行：趋势与分布
  平台处理分布
  岗位处理排行
  获取简历趋势
  异常原因分布

第四行：每日明细表
  时间 / 平台 / 账号 / 候选人 / 岗位 / 动作 / 结果 / 简历状态 / 详情
```

KPI 卡片示例：

```text
今日处理人数  215   较昨日 +18
求简历        19    BOSS 13 / 51 5 / 智联 1
获取简历      103   51job 91 / BOSS 12
待我处理      12    合适待复核 8 / 异常 4
```

服务卡片示例：

```text
BOSS 宋峰峰
浏览器：在线
Worker：ready
状态：空闲
今日：处理 35 / 求简历 13 / 获取 12
[处理消息] [主动联系] [暂停]
```

按钮规则：

- `处理全部`：只在 manager 权限可见，默认按配置串行执行。
- `处理某平台`：需要选择 owner 或默认当前授权 owner。
- `暂停`：只影响对应 owner/platform。
- `启动浏览器`：只启动 CloakBrowser，不启动普通 Chrome。
- `LIVE` 操作必须显示二次确认；`DRY_RUN` 只记录意图。

## 简历库

简历库目标是筛选和批量处理，不负责服务控制。

结构：

```text
顶部状态分组：
  全部 / 未看 / 已看 / 合适 / 不合适 / 待补充 / 待我处理

筛选区：
  常用筛选常驻，高级筛选放抽屉

表格：
  候选人 / 岗位 / 平台 / 账号 / 评分 / 学历 / 学校 / 专业 / 状态 / 更新时间 / 操作

批量操作栏：
  批量已看 / 批量不合适 / 批量分配 / 批量导出
```

筛选条件：

```text
关键词：姓名 / 手机 / 学校 / 专业 / 技能
平台：BOSS / 51job / 智联
账号：宋峰峰 / 和新红
岗位：按岗位规则分组
评分：A/B/C/D、分数区间
学历：大专 / 本科 / 硕士 / 博士
学校层次：985 / 211 / 双一流 / 普通本科 / 专科
毕业年份：2025 / 2026 / 2027 / 2028
简历状态：待解析 / 已解析 / 解析失败
附件状态：有附件 / 无附件 / 已下载
审阅状态：未看 / 已看 / 合适 / 不合适 / 待补充
来源时间：今日 / 近 3 天 / 近 7 天 / 自定义
```

默认排序：

1. 待我处理优先。
2. 未看优先。
3. 高分优先。
4. 最近入库优先。

## 简历审阅工作台

审阅工作台使用固定三栏：

```text
左侧：当前筛选结果候选列表
中间：简历预览
右侧：候选人摘要与操作
```

中间预览：

- PDF 固定高度滚动，不滚动整页。
- 支持上一页、下一页、缩放、适应宽度。
- 没有 PDF 时显示解析文本。
- 解析文本按基本信息、教育经历、工作经历、项目经历、技能分块。

右侧摘要：

- 候选人基础信息。
- 岗位与平台来源。
- 评分等级和证据。
- 最近聊天摘要。
- 简历下载和解析状态。
- 历史审阅记录。
- 固定操作区。

固定操作：

```text
已看
合适
不合适
待补充
约面试
查看聊天记录
下一份
```

`约面试` 按钮只做入口，不重写面试逻辑：

```text
点击约面试
-> 调用面试中心现有 API 创建或查找 session
-> 复用 question_generator / feishu / store / service
-> 跳转 /app/interviews/:sessionId
```

## 待我处理

待我处理是管理者收口页面，不是另一个简历库。

分组：

```text
合适待复核
未知问题待补充
简历解析失败
下载失败
面试待确认
需人工确认关联
```

每条任务展示：

```text
候选人
岗位
来源平台和账号
触发原因
提交人或系统来源
最近聊天摘要
推荐动作
```

操作：

- 查看简历。
- 进入面试中心。
- 标记已处理。
- 打回。
- 分配给其他人。

## 面试中心

面试中心应作为一级菜单，而不是藏在简历详情里。原因是它承担完整业务流程：候选人匹配、面试题生成、飞书同步、出图、反馈回填。

页面结构：

```text
左侧：面试 session 列表
中间：候选人详情、简历摘要、岗位匹配
右侧：面试题、飞书同步、出图、反馈回填
```

状态分组：

```text
待约面
已约面
待出题
待同步飞书
待反馈回填
已完成
异常
```

列表字段：

```text
候选人 / 岗位 / 负责人 / 来源平台 / 面试状态 / 飞书状态 / 更新时间
```

详情区：

- 候选人简历摘要。
- 原始简历入口。
- 关联会话和聊天摘要。
- 岗位匹配结果。
- AI 生成面试题。
- 面试官备注。
- 飞书多维表同步状态。
- 简历图和面试小结图。

复用现有代码：

```text
app/api/routes/interview.py
app/features/interview_center/service.py
app/features/interview_center/store.py
app/features/interview_center/question_generator.py
app/features/interview_center/candidate_matcher.py
app/features/interview_center/feishu/*
app/features/interview_center/render_resume_image.py
app/features/interview_center/render_summary_image.py
```

需要新增的只是 UI 入口、权限判断、状态展示和与简历审阅页的跳转关系。

## 自动化控制

自动化控制独立成页，避免普通简历审阅人员误触。

页面结构：

```text
顶部安全状态：
  DRY_RUN / LIVE
  当前数据库
  当前浏览器后端
  当前 worker 状态

控制区：
  处理全部
  按平台处理
  按账号处理
  主动联系
  暂停
  启动/检查 CloakBrowser

任务日志：
  当前任务
  最近任务
  失败原因
```

高风险动作规则：

- `DRY_RUN=true` 时按钮文字明确写“模拟处理”。
- `LIVE` 时必须二次确认，并显示影响平台、账号、预计处理上限。
- 页面不提供关闭 dry-run 的快捷开关；切换由环境配置控制。
- 所有操作写入决策日志或操作日志。

## 规则与知识库

规则与知识库放在独立菜单，不放在驾驶舱首页。

包含：

- 岗位规则查看。
- 知识库问答条目。
- 规则建议。
- 反馈采纳/拒绝。
- 评分规则版本。

管理员可编辑；普通用户只读或不可见。

## 权限与数据范围

复用飞书登录 RBAC 设计：

```text
super_admin
owner_admin
resume_viewer
interviewer
readonly
```

权限建议：

```text
dashboard:read
resumes:read
resumes:review
resumes:assign
automation:run
automation:pause
monitoring:read
rules:read
rules:write
interview:read
interview:write
settings:manage
```

数据范围：

```text
resumeScope:
  owners: ["宋峰峰"]
  platforms: ["boss", "job51", "zhilian"]
  includeUnlinked: false
```

后端必须按 scope 过滤：

- 简历列表。
- 简历详情。
- 审阅上下文。
- 面试 session。
- 自动化统计。
- 自动化控制目标。

## API 整合建议

新增或扩展管理者驾驶舱 API：

```text
GET /api/dashboard/overview
GET /api/dashboard/daily-details
GET /api/dashboard/service-status
GET /api/dashboard/job-breakdown
GET /api/dashboard/platform-breakdown
```

返回结构建议：

```json
{
  "date": "2026-06-29",
  "kpis": [
    {"key": "processed", "label": "今日处理", "value": 215},
    {"key": "requestedResume", "label": "求简历", "value": 19},
    {"key": "savedResumes", "label": "获取简历", "value": 103},
    {"key": "pendingReview", "label": "待我处理", "value": 12},
    {"key": "errors", "label": "异常", "value": 3}
  ],
  "services": [],
  "recentRecords": []
}
```

可由现有数据源聚合：

```text
decision_logs
conversation_sessions
candidate_status
resume_artifacts
resume_review_states
resume_assignments
worker / browser status
```

短期也可以兼容旧 summary/details 格式，但新系统内部建议统一转换成 dashboard DTO，避免前端依赖旧字段名。

## 前端组件拆分

建议未来从单文件静态页演进到模块化结构：

```text
frontend/src/app/
  AppShell.tsx
  routes.tsx

frontend/src/features/dashboard/
  DashboardPage.tsx
  KpiStrip.tsx
  ServiceGrid.tsx
  ServiceCard.tsx
  DailyDetailsTable.tsx
  DashboardFilters.tsx

frontend/src/features/resumes/
  ResumeLibraryPage.tsx
  ResumeReviewWorkbench.tsx
  ResumeFilterBar.tsx
  ResumeTable.tsx
  ResumePreviewPane.tsx
  CandidateSummaryPanel.tsx
  ReviewActionBar.tsx

frontend/src/features/review-queue/
  ReviewQueuePage.tsx
  ReviewTaskList.tsx

frontend/src/features/interviews/
  InterviewCenterPage.tsx
  InterviewSessionList.tsx
  InterviewSessionDetail.tsx
  InterviewQuestionPanel.tsx
  FeishuSyncPanel.tsx

frontend/src/features/automation/
  AutomationControlPage.tsx
  AutomationSafetyBanner.tsx
  AutomationTargetCard.tsx
  AutomationRunLog.tsx

frontend/src/features/rules/
  RulesPage.tsx
```

拆分原则：

- Dashboard 只负责统计和控制入口，不承载简历审阅。
- Resume Review 只负责看简历和做审阅判断，不承载平台启动/暂停。
- Interview Center 只负责面试流程，不承载普通简历筛选。
- Automation Control 只负责服务操作和任务日志，不承载规则编辑。
- Rules 独立承载岗位规则、知识库和规则建议。

## 状态与数据流

管理者查看今日数据：

```text
打开 /app/dashboard
-> GET /api/auth/me
-> GET /api/dashboard/overview?date=today&scope=current
-> GET /api/dashboard/service-status
-> 渲染 KPI、服务卡片、明细表
```

处理某个平台消息：

```text
点击 BOSS 宋峰峰 / 处理消息
-> 检查权限 automation:run
-> 若 live，弹出二次确认
-> POST /automation/boss/process-messages?owner=宋峰峰
-> 控制面派发 worker
-> UI 显示任务进行中
-> 轮询 service status 和 daily details
```

审阅简历并进入面试：

```text
打开简历
-> GET /api/resumes/{id}/review-context
-> 点击合适
-> POST /api/resumes/{id}/review-decision
-> 创建 assignment 到管理者
-> 点击约面试
-> POST /api/resumes/{id}/interview-invite 或面试中心 session API
-> 跳转 /app/interviews/{sessionId}
```

面试中心处理：

```text
进入 /app/interviews
-> 读取 session 列表
-> 选择候选人
-> 复用 service 生成题目
-> 同步飞书 mock/真实接口
-> 生成图片
-> 回填反馈
```

## 分阶段实施

### Phase 1: 设计壳与导航

- 重做 AppShell。
- 增加一级菜单：经理驾驶舱、简历库、待我处理、面试中心、自动化控制、规则与知识库、系统设置。
- 接入 `/api/auth/me` 控制菜单可见性。
- 保持现有后端逻辑不变。

### Phase 2: 经理驾驶舱

- 新增 dashboard 聚合 service 和 API。
- 聚合今日 KPI、服务状态、每日明细。
- 加入六账号服务卡片。
- 控制按钮先接现有 automation API。

### Phase 3: 简历库增强

- 把现有本地工作台升级成三栏审阅体验。
- 增强筛选条件。
- 完善已看、未看、合适、不合适、待补充。
- 合适进入待我处理。

### Phase 4: 面试中心 UI

- 新增面试中心一级页面。
- 复用现有 interview API 和 service。
- 从简历审阅页提供约面试入口。
- 展示飞书同步状态、题目、出图、回填。

### Phase 5: 自动化控制与安全提示

- 把 process-all、按平台处理、暂停、主动联系集中到自动化控制页。
- 增加 dry-run/live 安全提示。
- 操作按钮加入权限和二次确认。

### Phase 6: 规则与知识库

- 迁移规则建议、评分规则、知识库查看与维护入口。
- 保持岗位处理规则唯一来源，不在前端复制业务规则。

## 测试计划

后端：

- dashboard API 按权限和 scope 聚合正确。
- 普通用户看不到未授权 owner 的统计和简历。
- 自动化控制接口需要 `automation:run` 或 `automation:pause`。
- 面试 session 必须关联到当前用户可见的简历。
- 合适简历能进入管理者待处理队列。

前端：

- 不同角色菜单不同。
- Dashboard KPI、服务状态、明细表加载态和错误态完整。
- 简历工作台不需要整页滚动即可完成审阅。
- 面试中心可从菜单进入，也可从简历页跳转。
- 自动化 live 操作必须二次确认。
- 小屏表格不撑破页面。

建议命令：

```text
pytest tests
ruff check .
python -m compileall app scripts run_control_plane.py run_worker.py
```

如果前端后续引入构建系统，再补：

```text
npm run lint
npm run build
```

## 风险与待确认

- 旧版统计字段丰富但来源分散，新系统应在后端统一成 dashboard DTO，避免前端绑定旧字段。
- 面试中心后端可复用，但 UI 需要补 session 状态、权限和简历关联展示。
- 自动化控制按钮必须和简历审阅分离，否则普通人员容易误触真实处理。
- 飞书登录接入后，旧 Basic Auth 网关需要调整，否则 OAuth start/callback 可能被拦截。
- 当前本地前端还是静态文件结构，若要做到更完整的交互体验，建议后续引入模块化前端工程。
- 管理者“待我处理”的分配规则需要确认：固定给一个 super_admin，还是按岗位/owner 路由。

## 成功标准

- 管理者能在首页看到今日处理人数、求简历、获取简历、待我处理、异常和六账号状态。
- 管理者能从驾驶舱安全触发处理任务，并看到任务进度和结果。
- 普通用户只看到自己有权限的简历库和待处理队列。
- 简历审阅不再依赖整页上下滚动。
- 面试中心成为一级功能，同时保留从简历详情一键进入。
- 自动化控制、简历审阅、面试中心、规则管理职责清楚，不再混在一个页面里。
