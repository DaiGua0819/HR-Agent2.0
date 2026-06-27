# 可靠点击层建设方案（去拟人化版）

## 1. 目标

在真实浏览器接入后，平台页面偶尔会出现元素未就绪、点击后页面未切换、浮层阻挡、
虚拟列表延迟渲染等问题。本方案只解决“动作可靠性”，不模拟真人行为。

可靠点击层只保留：

- 动作前等待元素可操作。
- 点击或填入后做结果校验。
- 失败时有限重试与短退避。
- 简单节流，避免连续动作贴得太紧。
- 分段滚动，触发懒加载。
- 结构化记录每次可靠动作，方便 dry-run 和真实页面排查。

明确不做：

- 鼠标轨迹模拟。
- 真人阅读停顿。
- 错字、误点、撤销、随机行为。
- 长时间休息或拟人化批处理节奏。
- 业务判断、dry-run 判断、平台规则判断。

## 2. 代码边界

可靠动作层放在 `app/browser/`：

- `interaction_profile.py`：保存 `fast / normal / slow` 三档参数。
- `reliable_actions.py`：提供平台无关的可靠动作函数。
- `reliable_support.py`：提供验证、节流、记录、滚动位置读取等内部工具。
- `base.py`：页面抽象支持 `timeout_ms`，让真实 Playwright 和 FakePage 接口一致。
- `playwright_cdp.py`：真实 CDP 页面实现负责执行底层 locator 动作。
- `fake_page.py`：测试页面记录可靠动作，不休眠、不依赖真实浏览器。

平台适配层继续放在 `app/platforms/*/actions*.py`：

- 读取页面、打开会话、发送消息、求简历、打招呼等动作仍由平台层表达。
- 平台层调用可靠动作层完成点击、填入、确认、滚动。
- dry-run 守卫仍在 adapter / runner 调用链中，不下沉到可靠动作层。

业务规则继续放在 `app/agent/`：

- 岗位匹配、知识库答疑、筛选问题、直求简历、AI 岗位特殊流程不进入浏览器层。
- 三个平台复用同一套 `ConversationRunner + rules + screening + policy`。

## 3. 对外函数

`app/browser/reliable_actions.py` 提供：

- `reliable_click(page, selector, label="", verify=None, profile=None)`
- `reliable_click_element(page, element, label="", verify=None, profile=None)`
- `reliable_fill(page, selector, text, label="", verify_value=True, profile=None)`
- `reliable_confirm(page, selector, expected_texts, label="", verify=None, profile=None)`
- `reliable_scroll(page, amount=600, container_selector="", max_segments=20, profile=None)`

每个函数返回结构化 dict，至少包含：

- `ok`：动作是否成功。
- `action`：动作类型。
- `label`：调用方提供的人类可读标签。
- `method`：可靠动作方法名。
- `attempts` / `reason` / `verified`：用于定位失败。

如果页面对象有 `reliable_actions` 列表，动作结果会自动追加进去。

## 4. 重试规则

可靠点击的重试原则：

1. 第一次点击前等待元素出现。
2. 点击后执行调用方提供的 `verify`。
3. 如果验证失败，进入下一轮前先再次执行 `verify`。
4. 如果上一轮点击其实已经生效，只是验证延迟，则直接返回成功，不重复点击。
5. 达到最大次数仍未验证成功，返回失败和最后原因。

这条规则是为了避免“发送按钮 / 求简历按钮 / 打招呼按钮”被重复点击。可靠层不判断
这些动作是否允许执行，只负责不因为重试机制扩大副作用。

## 5. 当前接入点

BOSS：

- 未读筛选、职位筛选、候选人会话打开。
- 输入框填入、发送按钮点击，并校验最近己方消息。
- 求简历按钮点击、确认弹层点击。
- 常用语入口、同意接收简历、推荐候选人打招呼、不合适标记。
- `run_boss_once.py` 的选择器健康检查与处理循环。

51job：

- 人才沟通入口、未读筛选、职位筛选、候选人会话打开。
- 发送前关闭遮挡层，填入后点击发送并校验最近己方消息。
- 求简历按钮和确认按钮。
- 推荐入口、推荐职位切换、推荐候选人打招呼、分段滚动。

智联：

- 未读筛选、职位筛选、候选人会话打开。
- 输入框填入、发送按钮点击，并校验最近己方消息。
- 要附件简历按钮和确认按钮。
- 主动联系打招呼。

共享脚本：

- `scripts/platform_once_common.py` 使用可靠点击打开 51job / 智联候选人。
- `scripts/run_boss_once.py` 使用可靠点击打开 BOSS 候选人并输出动作记录。
- `scripts/boss_targeting.py` 指定会话补处理也通过可靠点击打开会话。

## 6. 配置

配置项在 `.env` / `settings.py`：

- `INTERACTION_ENABLED=true`
- `INTERACTION_PROFILE=normal`

三档参数：

- `fast`：短等待、少重试，用于本地快速验证。
- `normal`：默认真实页面处理节奏。
- `slow`：页面较慢或网络波动时使用。

关闭 `INTERACTION_ENABLED` 只会取消节流与退避休眠；等待、验证和结构化结果仍保留。

## 7. 安全边界

可靠动作层不是安全开关：

- 不读取 `DRY_RUN`。
- 不决定是否允许发送消息。
- 不决定是否允许求简历、下载、打招呼或写飞书。

安全边界仍由 adapter / runner 控制。`DRY_RUN=true` 时，真实副作用应在平台动作执行前
被拦截并写入决策日志；可靠动作层只服务于被允许执行的页面动作。

## 8. 验证

离线验证：

- `tests/platforms/test_reliable_actions.py` 覆盖动作记录、重试前验证、防重复点击、
  填入校验和分段滚动。
- 既有 BOSS / 51job / 智联测试继续使用 FakePage，不依赖真实浏览器。

建议命令：

```powershell
python -m pytest tests
python -m ruff check .
python -m compileall app scripts run_control_plane.py run_worker.py
```

真实浏览器验证：

- 先跑 `scripts/check_cdp_connection.py` 验证 CDP 和 BrowserPage。
- 再跑各平台 DOM 采样脚本查看选择器。
- 最后在 `DRY_RUN=true` 下跑 `run_boss_once.py` / `run_job51_once.py` /
  `run_zhilian_once.py`，观察可靠动作记录和决策日志。
