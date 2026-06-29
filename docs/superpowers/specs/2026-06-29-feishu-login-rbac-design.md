# 飞书登录与简历库权限设计

## 背景

当前控制面已经有 FastAPI 路由与简历库领域服务，核心 API 包括 `resumes`、`automation`、`monitoring`、`interview`、`batch` 和 `email_import`。简历模型中已经存在 `source_owner`、`linked_owner`、`linked_platform`、`linked_session_id` 等字段，适合作为简历库数据范围过滤依据。

线上入口 `http://218.244.142.84:8080/index.html` 只读访问返回 `401 Unauthorized`。后续接入飞书登录时，需要让登录页、飞书 OAuth 回调和静态资源能绕过旧的 401 拦截，否则用户无法进入授权流程。

本设计采用方案 A：shadcn 风格的企业内部控制台。视觉克制、信息密度适中，适合招聘自动化、简历库和面试中心这类内部运营工具。

## 目标

- 使用飞书授权登录作为唯一登录方式。
- 登录后根据用户身份展示不同菜单和页面。
- 后端强制执行权限，前端只负责按权限隐藏或展示界面。
- 支持“部分人只看到对应简历库”的数据范围控制。
- 保持现有三平台 worker、真实浏览器处理流程、简历解析流程不被登录系统污染。

## 非目标

- 不在本阶段接企业通讯录同步全量组织架构。
- 不做复杂审批流。
- 不把权限只做在前端。
- 不重做全部控制台页面，只设计登录与权限接入边界。
- 不在代码中保存飞书 app secret；所有密钥继续走 env。

## UI 设计方向

登录页使用 shadcn 风格内控台视觉：

- 页面整体为深石墨色或浅灰白背景，避免营销式大 hero。
- 主视觉是“招聘控制台登录”，不是宣传页面。
- 页面右侧放登录卡片，卡片包含系统名、飞书授权按钮、环境标识和安全说明。
- 页面左侧放轻量状态面板，展示“简历库 / BOSS / 51job / 智联 / 面试中心 / 权限受控”等模块状态。
- 登录按钮使用飞书图标或简洁图标加文字：“使用飞书授权登录”。
- 登录失败时在卡片内显示明确原因，例如“账号未授权访问 HR-Agent”。

登录后控制台：

- 顶部右侧显示飞书头像、姓名、角色。
- 左侧菜单根据 `permissions` 渲染。
- 简历库顶部显示当前数据范围，例如“当前可见：宋峰峰 · 全平台简历”。
- 普通用户看不到自动化、批量导入、邮箱导入、系统设置等入口。

## 角色与权限

建议保留少量角色，避免一开始做复杂。

| 角色 | 能力 |
| --- | --- |
| `super_admin` | 查看全部简历，管理用户权限，访问全部控制面功能 |
| `owner_admin` | 查看指定 owner 的简历和处理记录，可操作该 owner 的自动化 |
| `resume_viewer` | 只查看被授权范围内的简历库，不能触发自动化 |
| `interviewer` | 查看可约面试候选人和面试中心相关页面 |
| `readonly` | 只读访问被授权页面 |

权限建议用字符串表达：

```text
resumes:read
resumes:write
resumes:rescore
automation:run
automation:pause
monitoring:read
batch:write
email_import:write
interview:read
interview:write
auth:manage
```

## 数据范围

用户不仅有角色，还要有简历库可见范围。

```text
resume_scope:
  owners: ["宋峰峰"]
  platforms: ["boss", "job51", "zhilian"]
  include_unlinked: false
```

后端过滤规则：

- `super_admin` 可看全部。
- 普通用户只看 `linked_owner` 或 `source_owner` 命中授权 owner 的简历。
- 如配置了平台范围，则继续限制 `linked_platform` 或 `source_platform`。
- 历史简历没有 owner 归属时，默认只给 `super_admin` 看。
- 单条简历详情、编辑、重评、约面试入口都必须复用同一套过滤规则。

## 后端架构

新增认证领域：

```text
app/domain/auth/
  models.py
  repository.py
  service.py
  permissions.py
  sessions.py

app/integrations/feishu_auth/
  client.py
  oauth.py

app/api/dependencies/auth.py
app/api/routes/auth.py
```

职责：

- `domain/auth/models.py`：定义用户、角色、权限、数据范围。
- `domain/auth/repository.py`：读写本地用户、角色、会话和飞书绑定。
- `domain/auth/service.py`：处理登录、绑定、登出、权限判断。
- `domain/auth/permissions.py`：集中判断 `has_permission` 和简历范围。
- `domain/auth/sessions.py`：生成和校验服务端 session。
- `integrations/feishu_auth/oauth.py`：生成授权 URL、校验 state、用 code 换 token。
- `integrations/feishu_auth/client.py`：获取飞书用户信息。
- `api/dependencies/auth.py`：提供 `get_current_user`、`require_permission`、`get_resume_scope`。
- `api/routes/auth.py`：提供登录、回调、当前用户和登出 API。

## API 设计

新增：

```text
GET  /api/auth/feishu/start
GET  /api/auth/feishu/callback
GET  /api/auth/me
POST /api/auth/logout
```

`/api/auth/me` 返回：

```json
{
  "user": {
    "id": "local-user-id",
    "feishuOpenId": "ou_xxx",
    "name": "张三",
    "email": "zhangsan@example.com",
    "avatarUrl": ""
  },
  "roles": ["resume_viewer"],
  "permissions": ["resumes:read"],
  "resumeScope": {
    "owners": ["宋峰峰"],
    "platforms": ["boss", "job51", "zhilian"],
    "includeUnlinked": false
  }
}
```

需要保护的现有 API：

- `/api/resumes*`：至少需要 `resumes:read`；写和重评分别需要 `resumes:write`、`resumes:rescore`。
- `/automation*`：需要 `automation:run` 或 `automation:pause`，并校验 owner 范围。
- `/api/monitoring*`：需要 `monitoring:read`，并按 owner 范围聚合。
- `/api/batch*`：需要 `batch:write`。
- `/api/email-import*`：需要 `email_import:write`。
- `/api/interview*`：需要 `interview:read/write`，且关联简历必须在用户可见范围内。

## 会话与安全

- 登录成功后后端创建服务端 session，浏览器保存 `HttpOnly` Cookie。
- Cookie 设置：`HttpOnly`、`SameSite=Lax`，生产环境启用 `Secure`。
- OAuth `state` 存服务端短期表或签名 token，防止 CSRF。
- session 过期时间建议 8-12 小时，可做滑动续期。
- 所有未登录 API 返回 `401`，无权限返回 `403`。
- 不在前端保存飞书 token。
- 飞书 `app_id/app_secret/redirect_uri` 继续从 env 读取。

## 数据库设计

新增表：

```text
auth_users
auth_roles
auth_user_roles
auth_sessions
auth_feishu_bindings
auth_resume_scopes
auth_audit_logs
```

关键字段：

- `auth_users`: `id`, `name`, `email`, `avatar_url`, `status`
- `auth_feishu_bindings`: `user_id`, `open_id`, `union_id`, `employee_id`
- `auth_roles`: `id`, `name`, `permissions_json`
- `auth_resume_scopes`: `user_id`, `owners_json`, `platforms_json`, `include_unlinked`
- `auth_sessions`: `id`, `user_id`, `expires_at`, `created_at`, `last_seen_at`
- `auth_audit_logs`: 记录登录、登出、权限拒绝和敏感操作

默认种子数据：

- 一个 `super_admin`，通过 env 指定允许初始化的飞书 open_id 或 email。
- 宋峰峰、和新红可作为 owner scope 示例，不强制创建用户。

## 前端路由建议

```text
/login
/app/resumes
/app/automation
/app/monitoring
/app/interview
/app/settings/users
```

进入 `/app/*` 前先调用 `/api/auth/me`：

- 未登录：跳转 `/login`。
- 已登录但无权限：显示“无权限访问该模块”。
- 根据 `permissions` 渲染侧边栏。
- 根据 `resumeScope` 在简历库顶部展示当前数据范围。

## 与现有 401 的关系

服务器当前对 `/index.html` 返回 401。上线时需要调整网关或静态服务：

- 登录页、静态资源、OAuth start/callback 必须能公开访问。
- 其他 API 交给 FastAPI 的 auth dependency 判断。
- 如果保留 Nginx Basic Auth，会和飞书登录冲突，应在接入时替换或只作为临时外层保护。

## 测试计划

单元测试：

- 飞书 OAuth URL 生成包含 app_id、redirect_uri、state。
- callback 校验 state，mock 飞书用户信息。
- session 创建、过期、登出。
- `require_permission` 对无权限返回 403。
- 简历范围过滤：只返回授权 owner/platform。
- 未归属历史简历默认仅 admin 可见。

集成测试：

- 未登录访问 `/api/resumes` 返回 401。
- `resume_viewer` 只能访问 `/api/resumes`，不能访问 `/automation`。
- `owner_admin` 只能处理自己 owner。
- `super_admin` 可看全部。
- 前端 `/api/auth/me` 返回菜单所需权限结构。

## 风险与待确认

- 需要飞书后台配置真实 redirect URI，建议使用 HTTPS 域名。
- 如果当前 401 来自服务器外层 Basic Auth，需要在部署时调整白名单。
- 历史简历缺少 owner 归属，需要默认管理员可见，后续再做人工归属补齐。
- 若未来要做企业通讯录自动授权，需要新增同步任务；本设计先不做。
