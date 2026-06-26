# 招聘智能体重构项目（Phase 0）

`hr-agent/` 是与旧系统并列的新项目目录。旧的 `patchwork-recruit-gpt/`、
`agent_core/`、`agent_skills/` 只作为只读资产来源；新代码不修改旧项目。

## 目录职责

- `run_control_plane.py`：控制面入口，启动 FastAPI `:8080`，当前提供 `/health`。
- `run_worker.py`：worker 入口，按负责人启动独立 FastAPI，当前提供 `/status`。
- `config/`：账号、worker、LLM、知识库与 JD 配置。真实密钥只走 `.env`。
- `app/control_plane/`：任务派发和 worker HTTP 客户端。
- `app/worker/`：单负责人 worker 的运行时、HTTP 接口和后续浏览器装配。
- `app/api/`：控制面 Web API，保持薄路由。
- `app/agent/`：LangGraph 推理层、节点、工具 schema、迁移后的技能资产。
- `app/platforms/`：BOSS、51job、智联 DOM 选择器和动作适配层。
- `app/browser/`：独占浏览器、CDP、标签页和反检测接入。
- `app/domain/`：简历、评分、批量解析、邮箱导入等平台无关领域逻辑。
- `app/features/interview_center/`：面试中心与飞书多维表。
- `app/evaluation/`：决策日志、批次报告、候选人问题记录。
- `app/db/`：SQLite schema 与连接。
- `app/storage/`：真实简历文件存储和文件头校验。
- `frontend/`：后续承接旧前端 API 契约。
- `data/`：运行时 SQLite、上传文件和浏览器 profile，不进 git。

## 启动

建议使用 Python 3.11-3.13（本轮用 3.12 验证）。先安装依赖：

```powershell
python -m pip install -e ".[dev]"
```

启动控制面：

```powershell
python run_control_plane.py
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

启动 worker：

```powershell
python run_worker.py --owner 和新红 --port 8801
python run_worker.py --owner 宋峰峰 --port 8802
```

worker 状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8801/status
```

## 读取旧简历库

旧库路径通过 `.env` 的 `LEGACY_RESUME_DB_PATH` 或脚本参数传入：

```powershell
python scripts/smoke_read_resumes.py --db "旧项目/data/resumes.sqlite" --limit 5
```

该脚本只读打开 SQLite，验证 `resumes` 表的 payload + 索引列模式。

## Phase 路线

- P0：骨架、配置、DB schema、旧简历库只读 repository、LLM 客户端、入口空跑。
- P1：智联竖切，迁移 `zhilian_*` DOM 动作、工具 schema 与 LangGraph worker。
- P2：迁移 BOSS 与 51job，跑通两 worker、三平台、六个号。
- P3：补齐控制面、领域服务、面试中心、评估层和前端契约。
- P4：部署切换，灰度验证后退役旧巨型文件。
