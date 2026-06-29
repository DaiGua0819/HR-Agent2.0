const state = { view: "dashboard", user: null, dashboard: null, resumes: [], selectedId: "", context: null, tab: "all", interviewSelection: null };
const tabs = [["all", "全部"], ["unread", "未看"], ["viewed", "已看"], ["undecided", "待判断"], ["suitable", "合适"], ["unsuitable", "不合适"], ["needs_more_info", "待补充"], ["queue", "待我处理"]];
const pages = { dashboard: ["Manager Console", "经理驾驶舱"], resumes: ["Resume Library", "简历库"], queue: ["Review Queue", "待我处理"], interviews: ["Interview Center", "面试中心"], automation: ["Automation", "自动化控制"], rules: ["Rules", "规则与知识库"] };
const $ = (id) => document.getElementById(id);
async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const text = await response.text();
    const error = new Error(`${response.status} ${text}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
const platformName = (value) => ({ boss: "BOSS", job51: "51job", zhilian: "智联", all: "全部" }[value] || value || "未知");
const labelDecision = (value) => ({ suitable: "合适", unsuitable: "不合适", needs_more_info: "待补充", undecided: "待判断" }[value || "undecided"]);
const decisionClass = (value) => ({ suitable: "success", unsuitable: "danger", needs_more_info: "warning" }[value] || "");
const multiFilterKeys = new Set(["school_level", "graduation_year", "decision"]);
const resumeName = (resume) => resume?.name || resume?.parsedName || resume?.parsed_name || "未命名";
const resumeJob = (resume) => resume?.job_type || resume?.jobType || resume?.applied_position || resume?.appliedPosition || "";
const resumeOwner = (resume) => resume?.linkedOwner || resume?.linked_owner || resume?.source_owner || resume?.sourceOwner || "";
const resumePlatform = (resume) => resume?.linkedPlatform || resume?.linked_platform || resume?.source_platform || resume?.sourcePlatform || "";
const uiAccess = () => state.user?.uiAccess || { defaultView: "resumes", views: ["resumes"], actions: [] };
const canView = (view) => hrAuth.canView(state.user, view);
const canAction = (action) => hrAuth.canAction(state.user, action);
const setAllowedNavigation = () => hrAuth.setAllowedNavigation(state.user);
function setView(view) {
  if (state.user && !canView(view)) view = uiAccess().defaultView;
  state.view = view;
  document.querySelectorAll("[data-page]").forEach((node) => {
    node.classList.toggle("active", node.dataset.page === view);
  });
  document.querySelectorAll("[data-view]").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === view);
  });
  const [eyebrow, title] = pages[view] || pages.dashboard;
  $("pageEyebrow").textContent = eyebrow;
  $("pageTitle").textContent = title;
  if (view === "dashboard") loadDashboard();
  if (view === "resumes") loadResumes();
  if (view === "queue") loadQueue();
  if (view === "interviews") loadInterviewSessions();
  if (view === "automation") renderAutomationControls();
}
async function loadUser() {
  const data = await api("/api/auth/me");
  state.user = data;
  hrAuth.updateUserCard(data);
  return data;
}
async function loadDashboard() {
  const payload = await api("/api/dashboard/overview");
  state.dashboard = payload;
  renderSafety(payload);
  renderKpis(payload.kpis || []);
  renderServices(payload.services || []);
  renderQuickFilters(payload.quickFilters || []);
  renderDailyRows(payload.recentRecords || []);
  renderAutomationControls();
}
function renderSafety(payload) {
  const text = payload.dryRun ? "DRY_RUN 已开启：真实副作用受保护" : "LIVE 模式：操作前请二次确认";
  ["dashboardSafety", "sidebarSafety", "automationSafety"].forEach((id) => {
    const node = $(id);
    if (!node) return;
    node.textContent = text;
    node.className = payload.dryRun ? "safety-pill safe" : "safety-pill live";
  });
}
function renderKpis(items) {
  $("kpiGrid").innerHTML = items.map((item) => `<article class="kpi ${escapeHtml(item.tone || "")}"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></article>`).join("");
}
function renderServices(items) {
  $("serviceGrid").innerHTML = items.length
    ? items
        .map(
          (item) => `
            <article class="service-card">
              <div>
                <strong>${escapeHtml(item.label || item.owner)}</strong>
                <span class="badge ${item.status === "busy" ? "warning" : item.agentReady ? "success" : ""}">
                  ${escapeHtml(item.status)}
                </span>
              </div>
              <p>浏览器：${item.browserReady ? "在线" : "未就绪"} / CDP：${item.cdpReady ? "通" : "未通"}</p>
              <p>页面：${escapeHtml(item.pageCount || 0)} / 后端：${escapeHtml(item.browserBackend || "-")}</p>
            </article>
          `,
        )
        .join("")
    : `<div class="empty-inline">还没有 worker 状态，启动 worker 后这里会显示服务卡片。</div>`;
}
function renderQuickFilters(items) {
  $("quickFilters").innerHTML = items
    .filter((item) => canView(item.view))
    .map((item) => `<button class="quick-card" data-quick-view="${escapeHtml(item.view)}" data-quick-tab="${escapeHtml(item.tab || "")}">${escapeHtml(item.label)}</button>`)
    .join("");
  document.querySelectorAll("[data-quick-view]").forEach((button) => {
    button.onclick = () => {
      if (button.dataset.quickTab) state.tab = button.dataset.quickTab;
      setView(button.dataset.quickView);
    };
  });
}
function renderDailyRows(items) {
  $("dailyRows").innerHTML = items
    .map(
      (item) => `
        <tr>
          <td>${escapeHtml((item.time || "").slice(0, 19))}</td>
          <td>${escapeHtml(platformName(item.platform))}</td>
          <td>${escapeHtml(item.owner || "")}</td>
          <td>${escapeHtml(item.candidateName || "")}</td>
          <td>${escapeHtml(item.position || "")}</td>
          <td>${escapeHtml(item.action || "")}</td>
          <td>${escapeHtml(item.result || (item.dryRun ? "dry-run" : ""))}</td>
        </tr>
      `,
    )
    .join("");
  $("dailyEmpty").style.display = items.length ? "none" : "block";
}
function buildTabs() {
  $("statusTabs").innerHTML = tabs
    .map(([key, label]) => `<button data-tab="${key}" class="${state.tab === key ? "active" : ""}">${label}</button>`)
    .join("");
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.onclick = () => {
      state.tab = button.dataset.tab;
      if (state.tab === "queue") return loadQueue();
      loadResumes();
    };
  });
}
function queryFromFilters() {
  const data = new FormData($("filters"));
  const params = new URLSearchParams({ page_size: "100" });
  for (const [key, value] of data.entries()) {
    const cleaned = String(value || "").trim();
    if (!cleaned) continue;
    params[multiFilterKeys.has(key) ? "append" : "set"](key, cleaned);
  }
  if (state.tab === "unread") params.set("read_status", "unread");
  if (state.tab === "viewed") params.set("read_status", "viewed");
  if (["undecided", "suitable", "unsuitable", "needs_more_info"].includes(state.tab)) { params.delete("decision"); params.append("decision", state.tab); }
  return params.toString();
}
async function loadResumes() {
  buildTabs();
  const data = await api(`/api/resumes?${queryFromFilters()}`);
  state.resumes = data.items || [];
  renderRows();
  renderMiniList();
}
async function loadQueue() {
  state.tab = "queue";
  buildTabs();
  const data = await api("/api/resume-review/queue");
  const items = data.items || [];
  state.resumes = items.map((item) => ({ ...item.resume, assignment: item.assignment })).filter(Boolean);
  renderRows();
  renderMiniList();
  renderQueue(items);
}
function renderRows() {
  $("resumeRows").innerHTML = state.resumes
    .map((resume) => {
      const review = resume.reviewState || {};
      return `
        <tr class="${resume.id === state.selectedId ? "active" : ""}">
          <td><strong>${escapeHtml(resumeName(resume))}</strong><br><span class="muted">${escapeHtml(resume.phone || "")}</span></td>
          <td>${escapeHtml(resumeJob(resume))}</td>
          <td>${escapeHtml(platformName(resumePlatform(resume)))}</td>
          <td>${escapeHtml(resumeOwner(resume))}</td>
          <td>${escapeHtml(resume.match_score ?? resume.matchScore ?? "")}</td>
          <td><span class="badge">${review.readStatus === "viewed" ? "已看" : "未看"}</span>
              <span class="badge ${decisionClass(review.decision)}">${labelDecision(review.decision)}</span></td>
          <td>${escapeHtml((resume.updated_at || resume.updatedAt || "").slice(0, 10))}</td>
          <td><button data-open="${resume.id}">查看</button> <button data-decision="${resume.id}:suitable">合适</button></td>
        </tr>
      `;
    })
    .join("");
  $("emptyState").style.display = state.resumes.length ? "none" : "block";
  bindRowActions();
}
function renderMiniList() {
  $("miniList").innerHTML = state.resumes
    .map((resume) => `<button class="mini-item ${resume.id === state.selectedId ? "active" : ""}" data-open="${resume.id}"><strong>${escapeHtml(resumeName(resume))}</strong><small>${escapeHtml(resumeJob(resume))}</small></button>`)
    .join("");
  bindRowActions();
}
function renderQueue(items) {
  $("queueList").innerHTML = items.length
    ? items
        .map((item) => {
          const resume = item.resume || {};
          return `
            <article class="task-card">
              <strong>${escapeHtml(resumeName(resume))}</strong>
              <span>${escapeHtml(resumeJob(resume))}</span>
              <p>${escapeHtml(item.assignment?.note || "合适待复核")}</p>
              <button data-open="${resume.id}" data-jump-resumes="true">查看简历</button>
            </article>
          `;
        })
        .join("")
    : `<div class="empty-inline">当前没有待你处理的简历。</div>`;
  bindRowActions();
}
function bindRowActions() {
  document.querySelectorAll("[data-open]").forEach((button) => {
    button.onclick = () => {
      if (button.dataset.jumpResumes) setView("resumes");
      openResume(button.dataset.open);
    };
  });
  document.querySelectorAll("[data-decision]").forEach((button) => {
    button.onclick = () => {
      const [id, decision] = button.dataset.decision.split(":");
      setDecision(id, decision);
    };
  });
}
async function openResume(id) {
  if (!id) return;
  state.selectedId = id;
  state.context = await api(`/api/resumes/${id}/review-context`);
  renderRows();
  renderMiniList();
  renderContext();
}
function resumeText(resume) {
  const payload = resume.payload || {};
  return [
    `候选人：${resumeName(resume)}`,
    `岗位：${resumeJob(resume)}`,
    `学历：${resume.education || ""}`,
    `专业：${resume.major || ""}`,
    `电话：${resume.phone || ""}`,
    "",
    payload.rawText || payload.text || payload.summary || "当前没有解析文本。后续接入 PDF 预览后，这里会显示固定高度的简历页视图。",
  ].join("\n");
}
function renderContext() {
  const context = state.context;
  if (!context) return;
  const resume = context.resume;
  const review = context.reviewState || {};
  $("previewTitle").textContent = `${resumeName(resume)} · ${resumeJob(resume)}`;
  $("resumePreview").textContent = resumeText(resume);
  $("summaryContent").innerHTML = `
    <div class="summary-card"><h3>候选人</h3>
      <p>姓名：${escapeHtml(resumeName(resume))}</p><p>岗位：${escapeHtml(resumeJob(resume))}</p>
      <p>电话：${escapeHtml(resume.phone || "")}</p><p>学历：${escapeHtml(resume.education || "")}</p></div>
    <div class="summary-card"><h3>评分</h3>
      <p>分数：${escapeHtml(context.score?.value ?? "暂无")}</p><p>等级：${escapeHtml(context.score?.grade || "暂无")}</p></div>
    <div class="summary-card"><h3>来源</h3>
      <p>平台：${escapeHtml(platformName(context.conversation?.platform))}</p>
      <p>负责人：${escapeHtml(context.conversation?.owner || "")}</p>
      <p>会话：${escapeHtml(context.conversation?.sessionId || "未桥接")}</p></div>
    <div class="summary-card"><h3>审阅</h3>
      <p>查看：${review.readStatus === "viewed" ? "已看" : "未看"}</p>
      <p>判断：${labelDecision(review.decision)}</p><p>备注：${escapeHtml(review.note || "暂无")}</p></div>
  `;
}
async function setDecision(id, decision) {
  const reasonTags = { suitable: ["岗位匹配"], unsuitable: ["暂不匹配"], needs_more_info: ["信息待补充"] }[decision] || [];
  await api(`/api/resumes/${id}/review-decision`, { method: "POST", body: JSON.stringify({ decision, reasonTags, note: "" }) });
  await loadResumes();
  const next = state.resumes.find((resume) => resume.id === id) || state.resumes[0];
  if (next) await openResume(next.id);
}
async function requestInterview() {
  if (!state.selectedId || !state.context || !canAction("interview:invite")) return;
  const payload = await api("/api/interview/invite", {
    method: "POST",
    body: JSON.stringify({ resumeId: state.selectedId, dryRun: true }),
  });
  state.interviewSelection = { resume: state.context.resume, payload };
  setView("interviews");
  renderInterviewDetail();
}
async function loadInterviewSessions() {
  try {
    const data = await api("/api/interview-center/sessions");
    $("interviewSessions").innerHTML = (data.items || []).length
      ? data.items.map((item) => `<button class="mini-item">${escapeHtml(item.candidateName || item.id)}</button>`).join("")
      : `<div class="empty-inline">暂无面试会话。</div>`;
  } catch (error) {
    $("interviewSessions").innerHTML = `<div class="empty-inline">面试会话读取失败：${escapeHtml(error.message)}</div>`;
  }
  renderInterviewDetail();
}
function renderInterviewDetail() {
  const selected = state.interviewSelection;
  if (!selected) return;
  const resume = selected.resume || {};
  $("interviewDetail").innerHTML = `
    <h3>${escapeHtml(resumeName(resume))}</h3>
    <p>岗位：${escapeHtml(resumeJob(resume))}</p>
    <p>来源：${escapeHtml(platformName(resumePlatform(resume)))} / ${escapeHtml(resumeOwner(resume))}</p>
    <p>入口状态：${selected.payload?.accepted ? "已定位，等待真实约面流程" : "待确认"}</p>
  `;
}
function renderAutomationControls() {
  if (!canAction("automation:run")) {
    $("automationControls").innerHTML = `<div class="empty-inline">当前账号没有自动化控制权限。</div>`;
    return;
  }
  const owners = state.user?.resumeScope?.owners || ["宋峰峰", "和新红"];
  const platforms = state.user?.resumeScope?.platforms || ["boss", "job51", "zhilian"];
  $("automationControls").innerHTML = `
    <button class="control-card primary" data-process-all>按配置处理全部</button>
    ${owners
      .flatMap((owner) =>
        platforms.map(
          (platform) => `
            <button class="control-card" data-run-platform="${platform}" data-run-owner="${escapeHtml(owner)}">
              ${escapeHtml(owner)} · ${platformName(platform)} 处理未读
            </button>
          `,
        ),
      )
      .join("")}
  `;
  document.querySelector("[data-process-all]")?.addEventListener("click", processAll);
  document.querySelectorAll("[data-run-platform]").forEach((button) => {
    button.onclick = () => runProcess(button.dataset.runPlatform, button.dataset.runOwner);
  });
}
async function processAll() {
  await api("/automation/process-all", { method: "POST" });
  await loadDashboard();
}
async function runProcess(platform, owner) {
  await api(`/automation/${platform}/process-messages?owner=${encodeURIComponent(owner)}`, { method: "POST" });
  await loadDashboard();
}
function move(offset) {
  if (!state.resumes.length) return;
  const index = Math.max(0, state.resumes.findIndex((resume) => resume.id === state.selectedId));
  const next = state.resumes[Math.min(state.resumes.length - 1, Math.max(0, index + offset))];
  if (next) openResume(next.id);
}
function bindPageActions() {
  hrAuth.bindLogin(api, afterLogin);
  document.querySelectorAll("[data-view]").forEach((button) => (button.onclick = () => setView(button.dataset.view)));
  $("filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadResumes();
  });
  $("filters").addEventListener("reset", () => setTimeout(loadResumes, 0));
  $("refreshDashboardBtn").onclick = loadDashboard;
  $("globalSearch").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    $("filters").q.value = event.target.value;
    setView("resumes");
  });
  $("viewedBtn").onclick = () => state.selectedId && openResume(state.selectedId);
  $("suitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "suitable");
  $("unsuitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "unsuitable");
  $("moreInfoBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "needs_more_info");
  $("interviewBtn").onclick = requestInterview;
  $("logoutBtn").onclick = logout;
  $("prevBtn").onclick = () => move(-1);
  $("nextBtn").onclick = () => move(1);
  ["generateQuestionsBtn", "syncFeishuBtn", "renderImageBtn", "backfillBtn"].forEach((id) => {
    $(id).onclick = () => ($("interviewStatus").textContent = "当前首版界面已保留入口，真实调用继续复用后端面试中心接口。");
  });
}
async function afterLogin(user) {
  state.user = user; hrAuth.updateUserCard(user); hrAuth.showApp(); setAllowedNavigation(); setView(uiAccess().defaultView);
  if (canView("resumes")) await loadResumes();
}
async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  state.user = null; state.selectedId = ""; state.context = null;
  hrAuth.showLogin();
}
async function init() {
  bindPageActions();
  buildTabs();
  try {
    await afterLogin(await loadUser());
  } catch (error) {
    if (error.status === 401) return hrAuth.showLogin();
    throw error;
  }
}
init().catch((error) => {
  $("pageTitle").textContent = "加载失败";
  $("dailyEmpty").style.display = "block";
  $("dailyEmpty").textContent = error.message;
});
