# 简历库实时搜索设计

## 目标

将现有简历库搜索从“按回车后查询”改为“输入停止 250ms 后自动查询”，同时保留回车立即查询。该行为只在用户当前位于简历库时生效，不从仪表盘、我的任务或其他页面自动跳转。

## 交互

- 用户在简历库搜索栏输入时，同步更新隐藏筛选字段 `filters.q`。
- 中文输入法处于 composition 阶段时不发起查询，composition 结束后再进入 250ms 防抖。
- 用户继续输入时取消上一个防抖计时；列表层继续使用现有 `AbortController` 和 request sequence 取消旧请求并阻止迟到响应覆盖新结果。
- 按回车时取消待执行计时并立即查询。
- 清空搜索栏时自动恢复当前岗位、状态、日期、学历等其他筛选条件下的结果。
- 搜索后页码回到第 1 页，不新增自动补全或结果浮层。

## 实现边界

- 修改 `frontend/app.js` 的 `bindGlobalSearchToFilters()`，复用 `scheduleResumeFilterRefresh()`。
- 普通输入不调用 `setView("resumes")`；只有 `state.view === "resumes"` 时才触发实时查询。
- 搜索语义继续由 `/api/resumes?q=...` 提供，不修改后端接口。
- 搜索条件变化时清理列表预取缓存，详情缓存保持不变。

## 测试

- 前端契约测试断言存在 `input`、`compositionstart`、`compositionend` 和 Enter 立即查询逻辑。
- 断言非简历库页面输入不会调用列表加载或切换视图。
- 断言输入和清空都会同步 `filters.q`、重置页码并调度防抖刷新。
- 运行完整前端测试、`node --check frontend/app.js` 和 `ruff check app tests`。

