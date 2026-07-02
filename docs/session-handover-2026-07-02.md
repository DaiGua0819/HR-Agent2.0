# HR-Agent2.0 会话交接文档

> 用途：新开 Codex 会话后，先让新会话阅读本文件，然后继续当前项目。
> 更新时间：2026-07-02 14:35（Asia/Shanghai）

## 1. 当前项目路径

- 本地项目路径：
  `C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent`
- 当前主要工作区：
  `hr-agent/`
- 不要修改旧版仓库，旧版 HR-Agent 只能只读参考。

## 2. GitHub 与当前提交

- GitHub 仓库：
  `https://github.com/DaiGua0819/HR-Agent2.0.git`
- 当前分支：
  `main`
- 当前已推送最新提交：
  `749ae8b Polish resume preview layout`
- 当前远端 `origin/main` 已确认指向：
  `749ae8b6368d106e87ba207465088db9cf5fb227`

继续工作前必须先运行：

```powershell
git status
git log -3 --oneline
```

注意：当前本地工作区仍有一批未提交的招聘自动化/规则相关改动，最近一次前端提交没有把它们带进去。不要随便回滚这些文件，先确认它们是不是用户此前工作的残留。

当前未提交文件包括但不限于：

- `app/agent/policy.py`
- `app/agent/rules.py`
- `app/agent/runner.py`
- `app/agent/skills/51job-recruiter-automation/SKILL.md`
- `app/agent/skills/boss-recruiter-automation/SKILL.md`
- `app/agent/skills/zhilian-recruiter-automation/SKILL.md`
- `config/chat_rules/boss_chat_rules.json`
- `scripts/platform_once_common.py`
- `tests/agent/test_boss_phase2.py`
- `tests/agent/test_job51_phase3.py`
- `tests/agent/test_phase7b_browser.py`
- `tests/agent/test_zhilian_phase1.py`

## 3. 服务器信息

敏感信息不要明文写入仓库。本文只记录地址、账号和连接方式；密码/密钥内容由本地密钥管理。

- 服务器地址：
  `218.244.142.84`
- Windows 用户：
  `Administrator`
- Windows 管理员密码：
  本地密钥管理，不入库；新会话如果无法取得，需要向用户确认。
- SSH 连接方式：

```powershell
ssh -i $HOME\.ssh\codex_backup_20260624 Administrator@218.244.142.84
```

- 服务器新服务项目路径：
  `C:\RecruitAgent2Preview\hr-agent`
- 服务器 Python 虚拟环境：
  `C:\RecruitAgent2Preview\.venv`
- 当前 18080 服务进程命令形态：

```text
cmd.exe /c "cd /d C:\RecruitAgent2Preview\hr-agent && C:\RecruitAgent2Preview\.venv\Scripts\python.exe run_control_plane.py >> C:\RecruitAgent2Preview\hr-agent\data\logs\control_plane_stdout.log 2>> C:\RecruitAgent2Preview\hr-agent\data\logs\control_plane_stderr.log"
```

## 4. 服务地址与红线

- 旧服务地址，不要修改：
  `http://218.244.142.84:8080/index.html`
- 新预览/新版服务地址，只改这里：
  `http://218.244.142.84:18080/index.html`
- 本地开发服务：
  `http://127.0.0.1:18181/index.html`

用户多次强调：

- `8080` 是改版前旧服务，不能动。
- 新 UI、新权限、新简历库预览都只部署到 `18080`。
- 服务器上当前 `git` 不在 PATH，最近一次同步是用 `scp` 把本地文件复制到服务器目录。

## 5. 最近一次前端状态

最近完成并已部署的功能：

- 简历库登录后页面使用新版 `Carh HR` UI。
- 摘要面板支持左右拖动宽度。
- 摘要面板支持收纳；收纳后右侧操作按钮悬浮到简历右上方。
- 收纳状态下简历图片按宽度铺满背后的预览框，长页在预览框内部纵向滚动。
- 管理员按钮为竖排；member 仍保持合适/不合适横排。
- 简历列表卡片、筛选器、入库日期、自动筛选、预加载后 10 份简历预览图等前端逻辑已经在本地和服务器生效。

当前线上 18080 验证过：

```powershell
curl.exe -s --max-time 10 http://218.244.142.84:18080/index.html
```

返回的静态资源版本包含：

```html
/assets/styles.css?v=20260702-resume-fill-frame
/assets/app.js?v=20260702-resume-fill-frame
```

最近一次服务器前端备份路径：

```text
C:\RecruitAgent2Preview\hr-agent\data\backups\frontend_before_resume_fill_20260702_143038
```

## 6. 最近一次验证命令

前端提交前已在本地通过：

```powershell
.venv312\Scripts\python.exe -m pytest tests\domain\test_frontend_resume_member_view.py
node --check frontend\app.js
git diff --check -- frontend\app.js frontend\index.html frontend\styles.css tests\domain\test_frontend_resume_member_view.py
```

结果：

- `tests/domain/test_frontend_resume_member_view.py`：50 passed
- `node --check frontend/app.js`：通过
- `git diff --check`：无空白错误，仅有 Windows 换行提示

用本机 Chrome 也测过折叠摘要后的真实尺寸：

- 简历图片宽度约等于下载链接/预览框宽度。
- 下载链接完整包住整张简历图。
- 预览框可纵向滚动。

## 7. 服务器同步方式

最近一次没有在服务器上 `git pull`，因为远端默认环境找不到 `git`。使用的是：

```powershell
scp -i $HOME\.ssh\codex_backup_20260624 frontend\index.html frontend\app.js frontend\styles.css Administrator@218.244.142.84:C:/RecruitAgent2Preview/hr-agent/frontend/
scp -i $HOME\.ssh\codex_backup_20260624 tests\domain\test_frontend_resume_member_view.py Administrator@218.244.142.84:C:/RecruitAgent2Preview/hr-agent/tests/domain/
```

静态前端文件由 18080 服务直接读磁盘，复制后通常不需要重启服务。同步后至少验证：

```powershell
curl.exe -s --max-time 10 http://218.244.142.84:18080/index.html | Select-String "20260702-resume-fill-frame"
curl.exe -s -o NUL -w "%{http_code} %{content_type}`n" --max-time 10 http://218.244.142.84:18080/index.html
```

## 8. 招聘平台自动化原则

- 所有招聘平台自动化只使用 CloakBrowser。
- 不要恢复普通 Chrome 自动化。
- 宋锋峰常用 CDP：
  `http://127.0.0.1:9333`
- 本地 profile 可能在：
  `profiles/songfengfeng`
  `profiles/hexinhong`
- 不要清理 `profiles/` 目录，不要运行会删除 profile 的命令。

三平台运行原则：

- 一个负责人启动一个 CloakBrowser。
- 一个浏览器里打开 BOSS、51job、智联三个页面。
- 页面动作后要等待并做可见状态校验。
- BOSS 处理前先进入“未读”，不要在“全部”里直接处理。
- 51job 要避免重复打开 `https://app.51job.com/51job/`；已登录沟通页可直接使用 `https://ehire.51job.com/Revision/chat/...`。
- 智联请求附件简历无需确认弹窗。

## 9. 当前招聘规则记忆

重构版本当前核心逻辑位置：

- `ConversationRunner`
- `app/agent/rules.py`
- `app/agent/screening.py`
- `app/agent/policy.py`
- `config/chat_rules/boss_chat_rules.json`

规则原则：

- 知识库没有答案时不要编造回复，标记为未知/待补充。
- 对方满足筛选条件后再求简历。
- `resume_requested=True` 只代表已请求简历，不代表已收到或已下载。
- 只有真实收到/下载简历并写入 artifact 后，才算简历完成。
- dry-run 下不能把求简历/下载写成真实完成态。

用户已确认的一些岗位处理：

- 运营类岗位、AI 智能体解决方案负责人、外部财务产品顾问、投资交易策略研究员：直接求简历。
- AI 应用开发实习生/工程师：先发送基础条件；明确接受后求简历。
- HRBP/人力资源相关：按需求问题推进。
- “没有，你们招实习生吗”：不要回复。
- “面试是否线上”：回复“面试都是线上”。
- “工作时间和薪资构成”：工作时间 8-11，1-5；培训期间一天 150。
- “带薪培训吗”：回复带薪培训。

## 10. Web 登录与角色

当前登录方式以飞书 OAuth 为准。

管理员：

- 王鑫力
- 和新红

普通成员与可见范围：

- 张怀滨：AI 智能体解决方案负责人、外部财务产品顾问、投资交易策略研究员等授权岗位。
- 其他成员按 `resumeScope` 限制查看。

本地开发仍有 loopback dev-login 供本机验证使用，服务器正式入口不要依赖它。

本地测试进入开发用户的示例：

```text
http://127.0.0.1:18181/api/auth/dev-login?username=admin
http://127.0.0.1:18181/api/auth/dev-login?username=zhanghuaibin
```

## 11. 继续开发时的注意事项

1. 每次动代码前先 `git status`，确认有哪些脏文件。
2. 不要回滚用户或前序会话留下的未提交改动，除非用户明确要求。
3. 前端 UI 改动优先更新：
   - `frontend/index.html`
   - `frontend/styles.css`
   - `frontend/app.js`
   - `tests/domain/test_frontend_resume_member_view.py`
4. 前端测试至少跑：

```powershell
.venv312\Scripts\python.exe -m pytest tests\domain\test_frontend_resume_member_view.py
node --check frontend\app.js
```

5. 上传 GitHub 前只暂存本轮明确相关文件，不要把招聘自动化规则脏文件混进前端提交。
6. 部署服务器前先备份服务器当前前端文件。
7. 部署后用 `curl` 验证 18080 读到新版本号。

## 12. 给新 Codex 会话的启动提示词

可以直接把下面这段发给新会话：

```text
请先详细阅读 `docs/session-handover-2026-07-02.md`。当前项目在 `C:\Users\24471\Documents\Codex\2026-06-25\codex-patchwork-recruit-gpt-agent-core\hr-agent`，GitHub 仓库是 `https://github.com/DaiGua0819/HR-Agent2.0.git`，当前 main 最新提交是 `749ae8b Polish resume preview layout`。服务器是 `218.244.142.84`，用户 `Administrator`，通过 `$HOME\.ssh\codex_backup_20260624` 连接；密码/密钥明文不入库。服务器新版项目路径是 `C:\RecruitAgent2Preview\hr-agent`，只部署和修改 `http://218.244.142.84:18080/index.html`，旧服务 `8080` 绝对不要动。继续前先 `git status`，不要清理或回滚未确认的脏文件，尤其不要删除 `profiles/`。所有招聘平台自动化只使用 CloakBrowser，不要恢复普通 Chrome。
```
