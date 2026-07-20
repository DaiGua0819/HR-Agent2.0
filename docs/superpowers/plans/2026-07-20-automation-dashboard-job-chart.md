# Automation Dashboard Job Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精简 18080 管理员每日数据仪表盘，增加与旧 8080 一致的岗位处理人数环形图，并让桌面仪表盘可以完整纵向滚动。

**Architecture:** 继续使用现有 `/api/automation-monitoring/daily-summary` 响应。前端把 `byJobPlatform` 统一聚合为岗位统计，岗位列表和环形图共享聚合结果；环形图使用原生 SVG 扇区承载悬停交互，并用 CSS `conic-gradient` 与动画复现旧 8080 视觉，不引入第三方依赖。

**Tech Stack:** 原生 HTML、CSS、JavaScript，Python `pytest` 前端契约测试，Node.js 语法检查。

## Global Constraints

- 不修改每日统计后端接口或数据库结构。
- 不新增公开 API 或第三方图表依赖。
- 不修改、重启或部署 8080 服务。
- 环形图按当前日期、平台、负责人、岗位筛选后的 `processedContacts` 统计。
- 默认最多展示前 8 个岗位，其余合并为“其他岗位”。
- 仪表盘滚动规则不得改变简历库、面试中心等固定工作台页面。
- 保留现有未跟踪目录和压缩包，不提交 `.local-logs/`、`.superpowers/`、`data/`、`deploy_resume_filter_card_ee15093.zip`。

---

### Task 1: 固化精简后的仪表盘契约

**Files:**
- Modify: `tests/domain/test_frontend_automation_monitoring.py`

**Interfaces:**
- Consumes: `frontend/index.html` 中的监控 DOM ID、`frontend/app.js` 中的监控渲染函数、`frontend/styles.css` 中的监控样式选择器。
- Produces: 对 KPI 精简、岗位异常列删除、环形图结构和 dashboard 滚动边界的可执行契约。

- [ ] **Step 1: 写入会失败的前端契约断言**

在 `test_admin_dashboard_contains_daily_monitoring_surfaces` 中增加：

```python
for element_id in (
    "monitoringJobChart",
    "monitoringJobChartTotal",
    "monitoringJobChartLegend",
):
    assert f'id="{element_id}"' in html

assert '["sentCompanyInfo",' not in script
assert '["anomalies",' not in script
assert "monitoring-job-stat--danger" not in script
assert "function groupMonitoringJobs(items = [])" in script
assert "function buildMonitoringJobChartSlices(items = [])" in script
assert "function renderMonitoringJobChart(items = [])" in script
assert 'label: "其他岗位"' in script
assert "MONITORING_JOB_CHART_COLORS" in script
assert "monitoring-job-chart" in styles
assert "monitoring-job-chart-tooltip" in styles
assert "prefers-reduced-motion: reduce" in styles
assert '[data-page="dashboard"].active' in styles
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/domain/test_frontend_automation_monitoring.py::test_admin_dashboard_contains_daily_monitoring_surfaces -q`

Expected: FAIL，首先缺少 `monitoringJobChart`。

- [ ] **Step 3: 提交测试红灯基线**

```bash
git add tests/domain/test_frontend_automation_monitoring.py
git commit -m "测试仪表盘岗位图表契约"
```

### Task 2: 精简 KPI 与岗位统计并接入共享聚合

**Files:**
- Modify: `frontend/app.js`
- Test: `tests/domain/test_frontend_automation_monitoring.py`

**Interfaces:**
- Consumes: `payload.totals` 与 `payload.byJobPlatform`。
- Produces: `groupMonitoringJobs(items = []) -> Array<{jobType, processedContacts, businessResumeAcquisitions}>`，供岗位列表和环形图共同使用。

- [ ] **Step 1: 将 KPI 定义缩减为四项**

把 `MONITORING_METRICS` 调整为：

```javascript
const MONITORING_METRICS = [
  ["processedContacts", "处理联系人", "primary"],
  ["requestedResume", "发起求简历", "warning"],
  ["businessResumeAcquisitions", "业务简历获取", "success"],
  ["candidateQuestions", "候选人提问", "default"],
];
```

- [ ] **Step 2: 提取岗位聚合函数并删除异常字段**

新增并在 `renderMonitoringJobs` 中使用：

```javascript
function groupMonitoringJobs(items = []) {
  const grouped = new Map();
  items.forEach((item) => {
    const jobType = item.jobType || "未识别岗位";
    const current = grouped.get(jobType) || {
      jobType,
      processedContacts: 0,
      businessResumeAcquisitions: 0,
    };
    current.processedContacts += Number(item.processedContacts || 0);
    current.businessResumeAcquisitions += Number(item.businessResumeAcquisitions || 0);
    grouped.set(jobType, current);
  });
  return [...grouped.values()].sort(
    (left, right) => right.processedContacts - left.processedContacts
      || left.jobType.localeCompare(right.jobType, "zh-CN"),
  );
}
```

岗位行模板只渲染 `processedContacts` 和 `businessResumeAcquisitions` 两列。

- [ ] **Step 3: 运行目标测试确认剩余失败只来自图表结构与样式**

Run: `pytest tests/domain/test_frontend_automation_monitoring.py::test_admin_dashboard_contains_daily_monitoring_surfaces -q`

Expected: FAIL，但 KPI 与异常列相关断言通过。

- [ ] **Step 4: 检查 JavaScript 语法**

Run: `node --check frontend/app.js`

Expected: exit code 0。

- [ ] **Step 5: 提交 KPI 与列表修改**

```bash
git add frontend/app.js tests/domain/test_frontend_automation_monitoring.py
git commit -m "精简每日数据岗位统计"
```

### Task 3: 增加原生岗位环形图

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Test: `tests/domain/test_frontend_automation_monitoring.py`

**Interfaces:**
- Consumes: Task 2 的 `groupMonitoringJobs(items)`。
- Produces: `buildMonitoringJobChartSlices(items) -> {slices, total}` 与 `renderMonitoringJobChart(items)`；DOM ID 为 `monitoringJobChart`、`monitoringJobChartTotal`、`monitoringJobChartLegend`。

- [ ] **Step 1: 在岗位列表旁增加图表语义结构**

在 `monitoring-dashboard-grid` 内追加：

```html
<section class="panel monitoring-chart-panel">
  <div class="panel-head">
    <div>
      <h3>岗位处理占比</h3>
      <span class="muted">按处理联系人数统计</span>
    </div>
  </div>
  <div class="monitoring-job-chart-body">
    <div id="monitoringJobChart" class="monitoring-job-chart" role="img" aria-label="岗位处理占比，总计 0 人">
      <span id="monitoringJobChartTotal">0</span>
    </div>
    <div id="monitoringJobChartLegend" class="monitoring-job-chart-legend"></div>
  </div>
</section>
```

- [ ] **Step 2: 实现切片聚合规则**

在 `frontend/app.js` 中定义 9 色调色板和：

```javascript
function buildMonitoringJobChartSlices(items = []) {
  const rows = groupMonitoringJobs(items).filter((item) => item.processedContacts > 0);
  let slices = rows.map((item) => ({
    label: displayResumeJobType(item.jobType) || item.jobType,
    value: item.processedContacts,
  }));
  if (slices.length > 8) {
    const otherValue = slices.slice(8).reduce((total, item) => total + item.value, 0);
    slices = [...slices.slice(0, 8), { label: "其他岗位", value: otherValue }];
  }
  return { slices, total: slices.reduce((sum, item) => sum + item.value, 0) };
}
```

- [ ] **Step 3: 实现 SVG 扇区、悬停提示和图例渲染**

新增 `monitoringJobChartPoint`、`monitoringJobChartSlicePath`、`moveMonitoringJobChartTooltip` 和 `renderMonitoringJobChart`。核心渲染使用以下完整结构：

```javascript
function monitoringJobChartPoint(angleDeg, radius = 48) {
  const angle = (angleDeg * Math.PI) / 180;
  return { x: 50 + radius * Math.cos(angle), y: 50 + radius * Math.sin(angle) };
}

function monitoringJobChartSlicePath(startPercent, endPercent) {
  const startAngle = -90 + startPercent * 3.6;
  const endAngle = -90 + Math.min(endPercent, 99.999) * 3.6;
  const start = monitoringJobChartPoint(startAngle);
  const end = monitoringJobChartPoint(endAngle);
  const largeArc = endPercent - startPercent > 50 ? 1 : 0;
  return `M 50 50 L ${start.x.toFixed(3)} ${start.y.toFixed(3)} A 48 48 0 ${largeArc} 1 ${end.x.toFixed(3)} ${end.y.toFixed(3)} Z`;
}

function moveMonitoringJobChartTooltip(event, tooltip, chart) {
  const rect = chart.getBoundingClientRect();
  tooltip.style.left = `${event.clientX - rect.left}px`;
  tooltip.style.top = `${event.clientY - rect.top}px`;
}

function renderMonitoringJobChart(items = []) {
  const chart = $("monitoringJobChart");
  const totalNode = $("monitoringJobChartTotal");
  const legend = $("monitoringJobChartLegend");
  if (!chart || !totalNode || !legend) return;
  const { slices, total } = buildMonitoringJobChartSlices(items);
  chart.querySelectorAll(".monitoring-job-chart-slices, .monitoring-job-chart-tooltip")
    .forEach((node) => node.remove());
  chart.setAttribute("aria-label", `岗位处理占比，总计 ${total} 人`);
  totalNode.textContent = String(total);
  if (!total) {
    chart.classList.remove("is-animating");
    chart.style.setProperty("--monitoring-chart-gradient", "#eef2f7");
    legend.innerHTML = '<div class="empty-inline">暂无可统计数据</div>';
    return;
  }

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("monitoring-job-chart-slices");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("aria-hidden", "true");
  const tooltip = document.createElement("div");
  tooltip.className = "monitoring-job-chart-tooltip";
  tooltip.setAttribute("role", "tooltip");
  let cursor = 0;
  const gradientParts = [];
  slices.forEach((slice, index) => {
    const start = cursor;
    const next = cursor + (slice.value / total) * 100;
    cursor = next;
    const color = MONITORING_JOB_CHART_COLORS[index % MONITORING_JOB_CHART_COLORS.length];
    const percent = ((slice.value / total) * 100).toFixed(1);
    gradientParts.push(`${color} ${start.toFixed(3)}% ${next.toFixed(3)}%`);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const info = `${slice.label}：${slice.value} 人，占比 ${percent}%`;
    path.classList.add("monitoring-job-chart-slice");
    path.setAttribute("d", monitoringJobChartSlicePath(start, next));
    path.setAttribute("fill", color);
    path.addEventListener("mouseenter", (event) => {
      path.classList.add("is-active");
      tooltip.textContent = info;
      tooltip.classList.add("is-visible");
      moveMonitoringJobChartTooltip(event, tooltip, chart);
    });
    path.addEventListener("mousemove", (event) => moveMonitoringJobChartTooltip(event, tooltip, chart));
    path.addEventListener("mouseleave", () => {
      path.classList.remove("is-active");
      tooltip.classList.remove("is-visible");
    });
    svg.append(path);
  });
  chart.style.setProperty("--monitoring-chart-gradient", `conic-gradient(${gradientParts.join(", ")})`);
  chart.append(svg, tooltip);
  chart.classList.remove("is-animating");
  void chart.offsetWidth;
  chart.classList.add("is-animating");
  legend.innerHTML = slices.map((slice, index) => {
    const color = MONITORING_JOB_CHART_COLORS[index % MONITORING_JOB_CHART_COLORS.length];
    const percent = ((slice.value / total) * 100).toFixed(1);
    return `<div class="monitoring-job-chart-legend-row">
      <span class="monitoring-job-chart-swatch" style="background:${color}"></span>
      <span class="monitoring-job-chart-label" title="${escapeHtml(slice.label)}">${escapeHtml(slice.label)}</span>
      <strong>${slice.value} 人 · ${percent}%</strong>
    </div>`;
  }).join("");
}
```

- [ ] **Step 4: 将图表接入现有摘要刷新**

在 `loadAutomationMonitoringSummary` 的版本变化分支中加入：

```javascript
renderMonitoringJobChart(payload.byJobPlatform || []);
```

- [ ] **Step 5: 添加旧 8080 风格的图表 CSS**

增加稳定正方形图表、46% 中心空洞、SVG hover、提示框和图例样式。动画声明使用：

```css
@property --monitoring-chart-reveal {
  syntax: "<percentage>";
  inherits: false;
  initial-value: 0%;
}
@keyframes monitoringJobChartDraw {
  from { --monitoring-chart-reveal: 0%; }
  to { --monitoring-chart-reveal: 100%; }
}
.monitoring-job-chart.is-animating::before,
.monitoring-job-chart.is-animating .monitoring-job-chart-slices {
  animation: monitoringJobChartDraw 920ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
@media (prefers-reduced-motion: reduce) {
  .monitoring-job-chart.is-animating::before,
  .monitoring-job-chart.is-animating .monitoring-job-chart-slices {
    animation-duration: 1ms;
  }
}
```

- [ ] **Step 6: 运行目标测试**

Run: `pytest tests/domain/test_frontend_automation_monitoring.py::test_admin_dashboard_contains_daily_monitoring_surfaces -q`

Expected: PASS。

- [ ] **Step 7: 检查 JavaScript 与差异格式**

Run: `node --check frontend/app.js && git diff --check`

Expected: 两个命令均 exit code 0。

- [ ] **Step 8: 提交环形图**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/domain/test_frontend_automation_monitoring.py
git commit -m "增加岗位处理占比环形图"
```

### Task 4: 调整数字层级与 dashboard 滚动边界

**Files:**
- Modify: `frontend/styles.css`
- Test: `tests/domain/test_frontend_automation_monitoring.py`

**Interfaces:**
- Consumes: Task 2 的两列岗位统计 DOM、Task 3 的双栏监控结构。
- Produces: 桌面 dashboard 独立纵向滚动、两列稳定对齐和响应式单栏布局。

- [ ] **Step 1: 增加精确样式契约**

测试中读取对应 CSS 块并断言：

```python
assert "grid-template-columns: minmax(240px, 1fr) 76px 76px" in styles
assert ".monitoring-job-stat small" in styles
assert "font-size: 12px" in styles
assert ".monitoring-job-stat strong" in styles
assert "font-size: 17px" in styles
assert "height: 100vh" in styles
assert "overflow-y: auto" in styles
```

- [ ] **Step 2: 运行测试并确认字号与滚动断言失败**

Run: `pytest tests/domain/test_frontend_automation_monitoring.py::test_admin_dashboard_contains_daily_monitoring_surfaces -q`

Expected: FAIL，缺少新网格、字号或桌面滚动声明。

- [ ] **Step 3: 实现桌面双栏、统计字号与滚动**

在桌面断点内将 `.ts-app-shell` 固定为 `height: 100vh`，让 `[data-page="dashboard"].active` 使用 `height: 100%` 和 `overflow-y: auto`。将监控区域设置为岗位列表加图表两栏；岗位行调整为 `minmax(240px, 1fr) 76px 76px`，标签 12px、数字 17px。

- [ ] **Step 4: 实现窄屏回退**

桌面高度约束只写在 `@media (min-width: 1181px)` 内，因此窄屏沿用原有自然高度。在现有 `max-width: 1180px` 中加入 `.monitoring-dashboard-grid { grid-template-columns: 1fr; }`，并在 `max-width: 700px` 中使用 `.monitoring-job-row { grid-template-columns: minmax(120px, 1fr) 58px 58px; }`、`.monitoring-job-chart-body { grid-template-columns: 1fr; }` 和 `.monitoring-job-chart { width: min(220px, 100%); }`。

- [ ] **Step 5: 运行前端契约测试**

Run: `pytest tests/domain/test_frontend_automation_monitoring.py -q`

Expected: PASS。

- [ ] **Step 6: 提交布局修改**

```bash
git add frontend/styles.css tests/domain/test_frontend_automation_monitoring.py
git commit -m "优化每日数据布局与滚动"
```

### Task 5: 全量回归与浏览器视觉验证

**Files:**
- Verify: `frontend/index.html`
- Verify: `frontend/app.js`
- Verify: `frontend/styles.css`
- Verify: `tests/domain/test_frontend_automation_monitoring.py`

**Interfaces:**
- Consumes: 完成后的本地管理员仪表盘。
- Produces: 可部署的验证证据，不修改 8080。

- [ ] **Step 1: 运行监控后端和前端相关测试**

Run: `pytest tests/domain/test_frontend_automation_monitoring.py tests/domain/test_automation_monitoring.py -q`

Expected: PASS。

- [ ] **Step 2: 运行前端相关回归测试**

Run: `pytest tests/domain/test_frontend_resume_member_view.py -q`

Expected: PASS，证明其他工作台滚动与布局契约未回归。

- [ ] **Step 3: 运行静态检查**

Run: `node --check frontend/app.js`

Run: `ruff check app tests/domain/test_frontend_automation_monitoring.py`

Run: `git diff --check`

Expected: 全部 exit code 0。

- [ ] **Step 4: 启动未占用端口的本地预览**

先运行 `Get-NetTCPConnection -State Listen | Select-Object -ExpandProperty LocalPort` 检查端口；若 18082 空闲，运行 `python -m uvicorn app.control_plane.main:create_app --factory --host 127.0.0.1 --port 18082`。不得停止任何已有服务。

- [ ] **Step 5: 验证桌面视口**

在约 1280x720 视口确认：四张 KPI、列表与图表双栏、“处理 / 简历”对齐、异常内容已删除、页面可滚动到最近处理明细底部、环形图悬停提示可见。

- [ ] **Step 6: 验证窄屏视口**

在约 700x900 视口确认：监控区域改为单栏、图例不溢出、页面没有横向滚动、图表中心和文字不重叠。

- [ ] **Step 7: 检查最终工作树**

Run: `git status --short --branch`

Expected: 只保留用户原有未跟踪项目；所有本次修改均已提交。
