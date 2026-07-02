const state = {
  view: "dashboard",
  user: null,
  dashboard: null,
  resumes: [],
  selectedId: "",
  context: null,
  tab: "all",
  page: 1,
  pageSize: 10,
  total: 0,
  pages: 0,
  jobType: "",
  jobFacets: [],
  interviewSelection: null,
  resumePageCache: new Map(),
  resumeContextCache: new Map(),
  resumePrefetchingPages: new Set(),
  resumePrefetchingContexts: new Set(),
  resumePreviewImageCache: new Set(),
  resumePreviewImageQueue: [],
  resumePreviewImageInFlight: new Set(),
  resumePreviewImageLoaders: new Map(),
  resumePreviewImageActiveCount: 0,
  resumePreviewImageGeneration: 0,
};
const RESUME_PREVIEW_PREFETCH_LIMIT = 10;
const RESUME_PREVIEW_PREFETCH_CONCURRENCY = 2;
const SUMMARY_PANEL_STORAGE_KEY = "resumeSummaryPanelWidth";
const SUMMARY_PANEL_COLLAPSED_STORAGE_KEY = "resumeSummaryPanelCollapsed";
const SUMMARY_PANEL_DEFAULT_WIDTH = 276;
const SUMMARY_PANEL_MIN_WIDTH = 180;
const SUMMARY_PANEL_MAX_WIDTH = 460;
const SUMMARY_PANEL_MIN_PREVIEW_WIDTH = 380;
const tabs = [["all", "全部"], ["unread", "未看"], ["viewed", "已看"], ["suitable", "合适"], ["unsuitable", "不合适"], ["needs_more_info", "待补充"], ["queue", "待我处理"]];
const pages = { dashboard: ["Manager Console", "经理驾驶舱"], resumes: ["Resume Library", "简历库"], queue: ["Review Queue", "待我处理"], interviews: ["Interview Center", "面试中心"], automation: ["Automation", "自动化控制"], rules: ["Rules", "规则与知识库"] };
const RESUME_LIBRARY_JOB_TYPES = [
  "AI应用开发实习生",
  "应用技术经理（工业涂料领域）",
  "膨润土销售人员",
  "销售管培生",
  "HRBP",
  "人力资源管培生",
  "国际业务管培生",
  "销售工程师（石油钻井泥浆膨润土）_湖州",
  "电气工程师",
  "运营A",
  "运营B",
  "外部财务产品顾问",
  "投资交易策略研究员（量化与市场情绪方向）",
  "AI智能体解决方案负责人",
];
const RESUME_JOB_DISPLAY_LABELS = {
  "AI应用开发实习生": "AI实习生",
  "应用技术经理（工业涂料领域）": "应用技术",
  "人力资源管培生": "人资管培",
  "销售工程师（石油钻井泥浆膨润土）_湖州": "石油销售",
  "运营A": "运营A",
  "运营B": "运营B",
  "外部财务产品顾问": "财务顾问",
  "投资交易策略研究员（量化与市场情绪方向）": "投资策略研究",
  "AI智能体解决方案负责人": "AI方案负责人",
};
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
function tsButtonClass(tone = "default", extra = "") {
  const tones = {
    default: "ts-btn",
    primary: "ts-btn ts-btn--primary",
    success: "ts-btn ts-btn--success",
    danger: "ts-btn ts-btn--danger",
    warning: "ts-btn ts-btn--warning",
    text: "ts-btn ts-btn--text",
  };
  return [tones[tone] || tones.default, extra].filter(Boolean).join(" ");
}
function tsTagClass(value = "default") {
  const tone = decisionClass(value) || (value === "viewed" ? "success" : value === "unread" ? "warning" : "default");
  return ["ts-tag", tone !== "default" ? `ts-tag--${tone}` : ""].filter(Boolean).join(" ");
}
function tsSegmentClass(active) {
  return `ts-segment-button${active ? " active" : ""}`;
}
const multiFilterKeys = new Set([]);
const resumeName = (resume) => resume?.name || resume?.parsedName || resume?.parsed_name || "未命名";
function canonicalResumeJobType(value) {
  const text = String(value || "").trim();
  const compact = text.replace(/\s+/g, "").toLowerCase();
  if (!text) return "";
  if (/运营a/i.test(compact) || text.includes("企业内容运营负责人") || (/b2b/i.test(compact) && text.includes("短视频")) || (text.includes("内容运营负责人") && text.includes("短视频"))) return "运营A";
  if (/运营b/i.test(compact) || compact.includes("b端社交媒体运营") || text.includes("社交媒体运营") || (compact.includes("b端") && text.includes("运营"))) return "运营B";
  if (
    text.includes("投资策略研究") ||
    text.includes("投资交易策略研究员") ||
    text.includes("交易策略研究员") ||
    text.includes("量化交易策略研究员") ||
    text.includes("量化策略研究员") ||
    text.includes("市场情绪研究员") ||
    text.includes("量化与市场情绪方向")
  ) return "投资交易策略研究员（量化与市场情绪方向）";
  return text.replace("(", "（").replace(")", "）");
}
function uniqueJobTypes(values) {
  const seen = new Set();
  const result = [];
  (values || []).forEach((value) => {
    const canonical = canonicalResumeJobType(value);
    if (!canonical || seen.has(canonical)) return;
    seen.add(canonical);
    result.push(canonical);
  });
  return result;
}
function displayResumeJobType(value) {
  const canonical = canonicalResumeJobType(value);
  if (!canonical) return "";
  return RESUME_JOB_DISPLAY_LABELS[canonical] || canonical;
}
const resumeJob = (resume) => resume?.displayJobType || displayResumeJobType(resume?.job_type || resume?.jobType || resume?.applied_position || resume?.appliedPosition || "");
const resumeOwner = (resume) => resume?.linkedOwner || resume?.linked_owner || resume?.source_owner || resume?.sourceOwner || "";
const resumePlatform = (resume) => resume?.linkedPlatform || resume?.linked_platform || resume?.source_platform || resume?.sourcePlatform || "";
function resumePayloadValue(resume, keys) {
  const payload = resume?.payload || {};
  for (const key of keys) {
    const value = resume?.[key] ?? payload[key];
    if (value === undefined || value === null || typeof value === "object") continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}
function resumeRawText(resume) {
  return resumePayloadValue(resume, ["rawText", "text", "summary", "content"]);
}
function cleanSchoolCandidate(value) {
  let text = String(value || "").replace(/[：:，,。；;\s]+$/g, "").trim();
  text = text.replace(/^.*?(?:毕业院校|毕业学校|院校|学校|毕业于|就读于|教育经历)[：:\s]*/g, "");
  text = text.replace(/^(?:全日制|统招|最高学历|本科|硕士|博士|大专|专科)+[：:\s]*/g, "");
  return text.length <= 24 ? text : "";
}
function extractSchoolFromResumeText(resume) {
  const text = resumeRawText(resume);
  const matches = text.matchAll(/[\u4e00-\u9fa5A-Za-z0-9·]{2,40}(?:大学|职业技术学院|技术学院|高等专科学校|专科学校|学院)/g);
  for (const match of matches) {
    const candidate = cleanSchoolCandidate(match[0]);
    if (candidate) return candidate;
  }
  return "";
}
function extractSchoolLevelFromResumeText(resume) {
  const text = resumeRawText(resume);
  if (/985|九八五/.test(text)) return "985";
  if (/211|二一一/.test(text)) return "211";
  if (/双一流/.test(text)) return "双一流";
  if (/一本|第一批本科/.test(text)) return "一本";
  if (/二本|第二批本科/.test(text)) return "二本";
  if (/大专|专科/.test(text)) return "大专";
  if (/海外院校|海外高校|国外高校|海外学历/.test(text)) return "海外院校";
  return "";
}
function resumeSchool(resume) {
  return resumePayloadValue(resume, ["school", "college", "university"]) || extractSchoolFromResumeText(resume);
}
function resumeSchoolLevel(resume) {
  return resumePayloadValue(resume, ["schoolLevel", "school_level", "schoolTier", "school_tier"]) || extractSchoolLevelFromResumeText(resume);
}
function resumeSchoolTierBadge(resume) {
  const level = resumeSchoolLevel(resume);
  if (level.includes("985")) return "985";
  if (level.includes("211")) return "211";
  if (level.includes("双一流")) return "双一流";
  if (level.includes("一本")) return "一本";
  if (level.includes("二本")) return "二本";
  return "";
}
function resumeEducationLine(resume) {
  const degree = resumePayloadValue(resume, ["education", "degree"]);
  return degree || "待提取";
}
function resumeImportTime(resume) {
  const payload = resume.payload || {};
  const value = resume.updated_at || resume.updatedAt || payload.createdAt || payload.created_at || payload.downloadedAt || "";
  if (!value) return "待提取";
  const normalized = String(value).replace(/\//g, "-");
  const match = normalized.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : String(value).slice(0, 10);
}
function dateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
function shiftedDate(days) {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() + days);
  return date;
}
function importDateRange(value) {
  if (value === "today") return { dateFrom: dateKey(shiftedDate(0)), dateTo: dateKey(shiftedDate(0)) };
  if (value === "yesterday") return { dateFrom: dateKey(shiftedDate(-1)), dateTo: dateKey(shiftedDate(-1)) };
  if (value === "last_7_days") return { dateFrom: dateKey(shiftedDate(-6)), dateTo: dateKey(shiftedDate(0)) };
  if (value === "last_30_days") return { dateFrom: dateKey(shiftedDate(-29)), dateTo: dateKey(shiftedDate(0)) };
  if (value === "last_90_days") return { dateFrom: dateKey(shiftedDate(-89)), dateTo: dateKey(shiftedDate(0)) };
  return null;
}
function customImportDateRange() {
  const select = document.querySelector('select[name="import_date_range"]');
  const dateFrom = select?.dataset.dateFrom || "";
  const dateTo = select?.dataset.dateTo || "";
  if (!dateFrom && !dateTo) return null;
  const singleDate = dateFrom || dateTo;
  if (!dateFrom || !dateTo) return { dateFrom: singleDate, dateTo: singleDate };
  return dateFrom <= dateTo ? { dateFrom, dateTo } : { dateFrom: dateTo, dateTo: dateFrom };
}
function applyImportDateRangeParams(params, values) {
  const customRange = customImportDateRange();
  if (customRange) {
    if (customRange.dateFrom) params.set("date_from", customRange.dateFrom);
    if (customRange.dateTo) params.set("date_to", customRange.dateTo);
    return;
  }
  const ranges = (values || []).map(importDateRange).filter(Boolean);
  if (!ranges.length) return;
  const range = {
    dateFrom: ranges.map((item) => item.dateFrom).sort()[0],
    dateTo: ranges.map((item) => item.dateTo).sort().at(-1),
  };
  if (range.dateFrom) params.set("date_from", range.dateFrom);
  if (range.dateTo) params.set("date_to", range.dateTo);
}
const uiAccess = () => state.user?.uiAccess || { defaultView: "resumes", views: ["resumes"], actions: [] };
const canView = (view) => hrAuth.canView(state.user, view);
const canAction = (action) => hrAuth.canAction(state.user, action);
const setAllowedNavigation = () => hrAuth.setAllowedNavigation(state.user);
const isMemberUser = () => (state.user?.roles || []).includes("member") && !(state.user?.roles || []).includes("super_admin");
function visibleStatusTabs() {
  if (!isMemberUser()) return tabs;
  return tabs.filter(([key]) => !["undecided", "needs_more_info", "queue"].includes(key));
}
function visibleJobTypes() {
  const values = state.user?.resumeScope?.jobTypes || [];
  if (!Array.isArray(values)) return [];
  if (values.includes("*")) return uniqueJobTypes(RESUME_LIBRARY_JOB_TYPES);
  return uniqueJobTypes(values);
}
function bindDockEffect(container, selector, options = {}) {
  if (!container || container.dataset.dockBound === "true") return;
  container.dataset.dockBound = "true";
  const maxScale = options.maxScale || 1.3;
  const radius = options.radius || 100;
  const marginFactor = options.marginFactor || 15;
  const vertical = Boolean(options.vertical);
  const reset = () => {
    container.querySelectorAll(selector).forEach((item) => {
      requestAnimationFrame(() => {
        item.style.transform = "scale(1)";
        item.style.margin = "0px";
        item.style.zIndex = "1";
      });
    });
  };
  container.addEventListener("mousemove", (event) => {
    container.querySelectorAll(selector).forEach((item) => {
      const rect = item.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const distanceX = event.clientX - centerX;
      const distanceY = event.clientY - centerY;
      const distance = Math.sqrt(distanceX * distanceX + distanceY * distanceY);
      let scale = 1;
      let margin = "0px";
      let zIndex = "1";
      if (distance < radius) {
        const normalizedDistance = distance / radius;
        scale = 1 + (maxScale - 1) * Math.max(0, 1 - Math.pow(normalizedDistance, 1.6));
        if (scale > 1.03) {
          const marginValue = (scale - 1) * marginFactor;
          margin = vertical ? `${marginValue}px 0px` : `0px ${marginValue}px`;
          zIndex = String(Math.round(scale * 10));
        }
      }
      requestAnimationFrame(() => {
        item.style.transform = `scale(${scale})`;
        item.style.margin = margin;
        item.style.zIndex = zIndex;
      });
    });
  });
  container.addEventListener("mouseleave", reset);
}
function toggleLibraryPanel() {
  const panel = $("resumeLibraryPanel");
  const button = $("libraryToggleBtn");
  const icon = $("libraryIcon");
  if (!panel || !button) return;
  const workspace = panel.closest(".ts-resume-workspace");
  const collapsed = !panel.classList.contains("is-library-collapsed");
  panel.classList.toggle("is-library-collapsed", collapsed);
  workspace?.classList.toggle("is-library-collapsed", collapsed);
  button.setAttribute("aria-expanded", String(!collapsed));
  button.setAttribute("title", collapsed ? "展开名单" : "收起名单");
  if (icon) icon.textContent = collapsed ? "v" : "^";
}
function toggleFilterPanel() {
  const panel = $("filterPanel");
  const button = $("filterToggleBtn");
  const icon = $("filterIcon");
  if (!panel || !button) return;
  const nextOpen = !panel.classList.contains("is-open");
  panel.classList.toggle("is-open", nextOpen);
  button.setAttribute("aria-expanded", String(nextOpen));
  if (icon) icon.textContent = nextOpen ? "⌃" : "⌄";
}
function toggleSegmentPanel() {
  const panel = $("segmentPanel");
  const button = $("segmentToggleBtn");
  const icon = $("segmentIcon");
  if (!panel || !button) return;
  const nextOpen = !panel.classList.contains("is-open");
  panel.classList.toggle("is-open", nextOpen);
  button.setAttribute("aria-expanded", String(nextOpen));
  if (icon) icon.textContent = nextOpen ? "^" : "v";
}
function setResumeMemberMode() {
  document.body.classList.toggle("member-resume-mode", isMemberUser());
}
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
  if (!visibleStatusTabs().some(([key]) => key === state.tab)) state.tab = "all";
  $("statusTabs").innerHTML = visibleStatusTabs()
    .map(([key, label]) => `<button data-tab="${key}" class="${tsSegmentClass(state.tab === key)}">${label}</button>`)
    .join("");
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.onclick = () => {
      state.tab = button.dataset.tab;
      state.page = 1;
      clearResumePrefetchCache();
      if (state.tab === "queue") return loadQueue();
      loadResumes();
    };
  });
}
function buildJobTabs() {
  const block = $("jobTabsBlock");
  const list = $("jobTabs");
  if (!block || !list) return;
  const jobs = visibleJobTypes();
  block.hidden = !jobs.length;
  if (!jobs.length) {
    list.innerHTML = "";
    return;
  }
  const counts = new Map();
  (state.jobFacets || []).forEach((item) => {
    const job = canonicalResumeJobType(item.jobType);
    if (!job) return;
    counts.set(job, Math.max(counts.get(job) || 0, Number(item.count || 0)));
  });
  const allCount = [...counts.values()].reduce((sum, count) => sum + Number(count || 0), 0);
  const buttons = [["", `全部简历 (${allCount})`]].concat(
    jobs.map((job) => [job, `${displayResumeJobType(job)} (${counts.get(canonicalResumeJobType(job)) || 0})`]),
  );
  list.innerHTML = buttons
    .map(([job, label]) => `<button data-job-tab="${escapeHtml(job)}" class="filter-tag ${state.jobType === job ? "active" : ""}">${escapeHtml(label)}</button>`)
    .join("");
  list.querySelectorAll("[data-job-tab]").forEach((button) => {
    button.onclick = () => {
      state.jobType = button.dataset.jobTab || "";
      $("filters").job_type.value = state.jobType;
      state.page = 1;
      clearResumePrefetchCache();
      loadResumes();
    };
  });
}
function queryFromFilters(page = state.page) {
  const data = new FormData($("filters"));
  const params = new URLSearchParams({ page: String(page), page_size: "10" });
  const importDateValues = [];
  for (const [key, value] of data.entries()) {
    const cleaned = String(value || "").trim();
    if (!cleaned) continue;
    if (key === "import_date_range") {
      importDateValues.push(cleaned);
      continue;
    }
    params[multiFilterKeys.has(key) ? "append" : "set"](key, cleaned);
  }
  applyImportDateRangeParams(params, importDateValues);
  if (state.jobType) params.set("job_type", state.jobType);
  if (state.tab === "unread") params.set("read_status", "unread");
  if (state.tab === "viewed") params.set("read_status", "viewed");
  if (["undecided", "suitable", "unsuitable", "needs_more_info"].includes(state.tab)) { params.delete("decision"); params.append("decision", state.tab); }
  return params.toString();
}
function resumeListCacheKey(page) {
  return queryFromFilters(page);
}
function clearResumePrefetchCache() {
  state.resumePageCache.clear();
  state.resumeContextCache.clear();
  state.resumePrefetchingPages.clear();
  state.resumePrefetchingContexts.clear();
  clearResumePreviewImagePrefetchQueue();
}
async function clearResumePrefetchCacheAfterMutation() {
  clearResumePrefetchCache();
}
function applyResumeListData(data) {
  state.resumes = data.items || [];
  state.total = data.total || 0;
  state.page = data.page || 1;
  state.pageSize = data.pageSize || 10;
  state.pages = data.pages || 0;
  state.jobFacets = data.jobFacets || [];
  buildJobTabs();
  renderRows();
  renderMiniList();
  renderPagination();
}
function resumePreviewImageUrl(resume) {
  return resume?.filePreviewImageUrl || resume?.file_preview_image_url || resume?.file?.previewImageUrl || "";
}
function clearResumePreviewImagePrefetchQueue() {
  state.resumePreviewImageGeneration += 1;
  state.resumePreviewImageQueue = [];
  state.resumePreviewImageCache.clear();
  state.resumePreviewImageInFlight.clear();
  state.resumePreviewImageLoaders.clear();
  state.resumePreviewImageActiveCount = 0;
}
function followingResumePreviewCandidates(selectedId) {
  if (!selectedId) return [];
  const result = [];
  const seen = new Set([selectedId]);
  const append = (items) => {
    for (const resume of items || []) {
      if (result.length >= RESUME_PREVIEW_PREFETCH_LIMIT) return;
      const id = resume?.id || "";
      const url = resumePreviewImageUrl(resume);
      if (!id || seen.has(id) || !url) continue;
      seen.add(id);
      result.push({ id, url });
    }
  };
  const currentIndex = state.resumes.findIndex((resume) => resume.id === selectedId);
  if (currentIndex >= 0) append(state.resumes.slice(currentIndex + 1));
  for (const page of [state.page + 1, state.page + 2]) {
    if (result.length >= RESUME_PREVIEW_PREFETCH_LIMIT) break;
    const cached = state.resumePageCache.get(resumeListCacheKey(page));
    append(cached?.items || []);
  }
  return result.slice(0, RESUME_PREVIEW_PREFETCH_LIMIT);
}
function enqueueResumePreviewImagePrefetch(url) {
  if (!url || state.resumePreviewImageCache.has(url) || state.resumePreviewImageInFlight.has(url)) return;
  if (state.resumePreviewImageQueue.some((item) => item.url === url)) return;
  state.resumePreviewImageQueue.push({ url, generation: state.resumePreviewImageGeneration });
  runResumePreviewImagePrefetchQueue();
}
function runResumePreviewImagePrefetchQueue() {
  while (
    state.resumePreviewImageActiveCount < RESUME_PREVIEW_PREFETCH_CONCURRENCY &&
    state.resumePreviewImageQueue.length
  ) {
    const item = state.resumePreviewImageQueue.shift();
    if (!item || item.generation !== state.resumePreviewImageGeneration) continue;
    const { url, generation } = item;
    if (state.resumePreviewImageCache.has(url) || state.resumePreviewImageInFlight.has(url)) continue;
    state.resumePreviewImageActiveCount += 1;
    state.resumePreviewImageInFlight.add(url);
    const image = new Image();
    state.resumePreviewImageLoaders.set(url, image);
    const finish = (loaded) => {
      if (generation !== state.resumePreviewImageGeneration) return;
      if (loaded) state.resumePreviewImageCache.add(url);
      state.resumePreviewImageInFlight.delete(url);
      state.resumePreviewImageLoaders.delete(url);
      state.resumePreviewImageActiveCount = Math.max(0, state.resumePreviewImageActiveCount - 1);
      runResumePreviewImagePrefetchQueue();
    };
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.decoding = "async";
    image.src = url;
  }
}
function prefetchFollowingResumePreviewImages(selectedId) {
  if (state.view !== "resumes" || state.tab === "queue") return;
  followingResumePreviewCandidates(selectedId).forEach(({ url }) => {
    enqueueResumePreviewImagePrefetch(url);
  });
}
function prefetchNextResumePages() {
  if (state.view !== "resumes" || state.tab === "queue") return;
  for (const page of [state.page + 1, state.page + 2]) {
    if (page < 1 || page > state.pages) continue;
    const cacheKey = resumeListCacheKey(page);
    if (state.resumePageCache.has(cacheKey) || state.resumePrefetchingPages.has(cacheKey)) continue;
    state.resumePrefetchingPages.add(cacheKey);
    api(`/api/resumes?${cacheKey}`)
      .then((data) => {
        state.resumePageCache.set(cacheKey, data);
        prefetchFollowingResumePreviewImages(state.selectedId);
      })
      .catch(() => {})
      .finally(() => state.resumePrefetchingPages.delete(cacheKey));
  }
}
async function loadResumes({ preferCache = false } = {}) {
  buildTabs();
  const cacheKey = resumeListCacheKey(state.page);
  const cached = preferCache ? state.resumePageCache.get(cacheKey) : null;
  const data = cached || (await api(`/api/resumes?${cacheKey}`));
  state.resumePageCache.set(cacheKey, data);
  applyResumeListData(data);
  prefetchNextResumePages();
}
async function loadQueue() {
  state.tab = "queue";
  buildTabs();
  const data = await api("/api/resume-review/queue");
  const items = data.items || [];
  state.resumes = items.map((item) => ({ ...item.resume, assignment: item.assignment })).filter(Boolean);
  state.total = state.resumes.length;
  state.page = 1;
  state.pageSize = 10;
  state.pages = state.resumes.length ? 1 : 0;
  renderRows();
  renderMiniList();
  renderPagination();
  renderQueue(items);
}
function renderRows() {
  const rows = $("resumeRows");
  if (!rows) return;
  rows.innerHTML = state.resumes
    .map((resume) => {
      const review = resume.reviewState || {};
      return `
        <tr class="${resume.id === state.selectedId ? "active" : ""}">
          <td><strong>${escapeHtml(resumeName(resume))}</strong><br><span class="muted">${escapeHtml(resume.phone || "")}</span></td>
          <td>${escapeHtml(resumeJob(resume))}</td>
          <td>${escapeHtml(platformName(resumePlatform(resume)))}</td>
          <td>${escapeHtml(resumeOwner(resume))}</td>
          <td>${escapeHtml(resume.match_score ?? resume.matchScore ?? "")}</td>
          <td><span class="${tsTagClass(review.readStatus === "viewed" ? "viewed" : "unread")}">${review.readStatus === "viewed" ? "已看" : "未看"}</span>
              <span class="${tsTagClass(review.decision)}">${labelDecision(review.decision)}</span></td>
          <td>${escapeHtml((resume.updated_at || resume.updatedAt || "").slice(0, 10))}</td>
          <td><button class="${tsButtonClass("text")}" data-open="${resume.id}">查看</button> <button class="${tsButtonClass("success")}" data-decision="${resume.id}:suitable">合适</button></td>
        </tr>
      `;
    })
    .join("");
  $("emptyState").style.display = state.resumes.length ? "none" : "block";
  bindRowActions();
}
function renderMiniList() {
  $("miniList").innerHTML = state.resumes
    .map((resume) => {
      const tier = resumeSchoolTierBadge(resume);
      const review = resume.reviewState || {};
      const readStatus = review.readStatus === "viewed" ? "viewed" : "unread";
      const readLabel = readStatus === "viewed" ? "已读" : "未读";
      const decision = labelDecision(review.decision);
      const imported = resumeImportTime(resume);
      return `
        <button class="candidate-card ${resume.id === state.selectedId ? "active candidate-card--focus-pop" : ""}" data-open="${resume.id}" style="z-index: 1; margin: 0px;">
          <span class="candidate-card__heading">
            <strong>${escapeHtml(resumeName(resume))}</strong>
            <span class="${tsTagClass(review.decision)}">${escapeHtml(decision)}</span>
          </span>
          <span class="candidate-card__job">${escapeHtml(resumeJob(resume))}</span>
          <span class="candidate-card__meta">
            <span class="candidate-card__meta-item candidate-card__meta-school">
              <span class="candidate-card__meta-value">${escapeHtml(resumeSchool(resume) || "待提取")}</span>
            </span>
            <span class="candidate-card__meta-item candidate-card__meta-tier">
              ${tier ? `<span class="school-tier-badge">${escapeHtml(tier)}</span>` : `<span class="candidate-card__meta-value">${escapeHtml(resumeEducationLine(resume))}</span>`}
            </span>
            <span class="candidate-card__meta-item candidate-card__meta-date">${escapeHtml(imported)}</span>
            <span class="candidate-card__meta-item candidate-card__meta-platform">${escapeHtml(platformName(resumePlatform(resume)))}</span>
            <span class="candidate-card__meta-item candidate-card__meta-read">
              <span class="candidate-card__read-badge candidate-card__read-badge--${readStatus}">${escapeHtml(readLabel)}</span>
            </span>
          </span>
        </button>
      `;
    })
    .join("");
  $("emptyState").textContent = state.resumes.length ? "" : "当前筛选条件下暂无简历";
  $("emptyState").style.display = state.resumes.length ? "none" : "block";
  bindRowActions();
  bindDockEffect($("miniList"), ".candidate-card", { maxScale: 1.08, radius: 120, marginFactor: 8, vertical: true });
  requestAnimationFrame(scrollSelectedCandidateIntoView);
}
function scrollSelectedCandidateIntoView() {
  const list = $("miniList");
  const selected = list?.querySelector(".candidate-card.active");
  if (!selected) return;
  selected.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
}
function renderPagination() {
  const node = $("resumePagination");
  if (!node) return;
  const pages = Math.max(1, state.pages || 1);
  const current = Math.min(Math.max(1, state.page || 1), pages);
  node.innerHTML = `
    <label class="pagination-status" for="resumePageInput">
      <span>第</span>
      <input id="resumePageInput" class="pagination-input" data-page-input type="number" min="1" max="${pages}" value="${current}" aria-label="跳转页码" />
      <span>/ ${pages} 页，共 ${state.total || 0} 份</span>
    </label>
    <div class="ts-pagination">
      <button class="${tsButtonClass("default")}" data-page-move="-1" ${current <= 1 ? "disabled" : ""}>上一页</button>
      <button class="${tsButtonClass("primary")}" data-page-move="1" ${current >= pages ? "disabled" : ""}>下一页</button>
    </div>
  `;
  const pageInput = node.querySelector("[data-page-input]");
  pageInput?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const targetPage = Math.min(Math.max(1, Number(pageInput.value) || current), pages);
    pageInput.value = String(targetPage);
    if (targetPage === current) return;
    state.page = targetPage;
    loadResumes({ preferCache: true });
  });
  node.querySelectorAll("[data-page-move]").forEach((button) => {
    button.onclick = () => {
      const nextPage = current + Number(button.dataset.pageMove || 0);
      if (nextPage < 1 || nextPage > pages) return;
      state.page = nextPage;
      loadResumes({ preferCache: true });
    };
  });
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
              <button class="${tsButtonClass("primary")}" data-open="${resume.id}" data-jump-resumes="true">查看简历</button>
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
  renderRows();
  renderMiniList();
  prefetchFollowingResumePreviewImages(id);
  if (state.resumeContextCache.has(id)) {
    state.context = state.resumeContextCache.get(id);
    renderContext();
    return;
  }
  $("previewTitle").textContent = "正在读取简历...";
  $("resumePreview").className = "resume-preview";
  $("resumePreview").textContent = "正在加载候选人详情和审阅摘要，请稍候。";
  $("summaryCards").innerHTML = `<p class="muted">正在读取审阅摘要...</p>`;
  state.context = await api(`/api/resumes/${id}/review-context`);
  state.resumeContextCache.set(id, state.context);
  renderRows();
  renderMiniList();
  renderContext();
}
function resumeText(resume) {
  const payload = resume.payload || {};
  return [
    `候选人：${resumeName(resume)}`,
    `岗位：${resumeJob(resume)}`,
    `学历：${resumeEducationLine(resume)}`,
    `专业：${resume.major || ""}`,
    `电话：${resume.phone || ""}`,
    "",
    payload.rawText || payload.text || payload.summary || "当前没有解析文本。后续接入 PDF 预览后，这里会显示固定高度的简历页视图。",
  ].join("\n");
}
function renderResumePreview(context) {
  const resume = context.resume;
  const file = context.file || {};
  const preview = $("resumePreview");
  if (!preview) return;
  if (file.available && file.previewImageUrl) {
    preview.className = "resume-preview image-preview";
    preview.innerHTML = `
      <div class="resume-image-stage">
        <a href="${escapeHtml(file.downloadUrl || '/api/resumes/' + resume.id + '/download')}" download class="resume-download-link" title="点击下载简历PDF">
          <img alt="${escapeHtml(resumeName(resume))} 简历内容" src="${escapeHtml(file.previewImageUrl)}" />
        </a>
      </div>
    `;
    return;
  }
  preview.className = "resume-preview text-preview";
  preview.textContent = resumeText(resume);
}
function renderContext() {
  const context = state.context;
  if (!context) return;
  const resume = context.resume;
  const review = context.reviewState || {};
  const schoolTier = resumeSchoolTierBadge(resume) || resumeSchoolLevel(resume);
  const schoolTierMarkup = schoolTier ? `<span class="summary-school-level">${escapeHtml(schoolTier)}</span>` : "";
  $("previewTitle").textContent = `${resumeName(resume)} · ${resumeJob(resume)}`;
  renderResumePreview(context);
  $("summaryCards").innerHTML = `
    <div class="summary-card ts-summary-card"><h3>候选人</h3>
      <p>姓名：${escapeHtml(resumeName(resume))}</p><p>岗位：${escapeHtml(resumeJob(resume))}</p>
      <p>电话：${escapeHtml(resume.phone || "")}</p><p>学历：${escapeHtml(resumeEducationLine(resume))}${schoolTierMarkup}</p>
      <p>入库时间：${escapeHtml(resumeImportTime(resume))}</p></div>
    <div class="summary-card ts-summary-card"><h3>评分</h3>
      <p>分数：${escapeHtml(context.score?.value ?? "暂无")}</p><p>等级：${escapeHtml(context.score?.grade || "暂无")}</p></div>
  `;
}
async function setDecision(id, decision) {
  const reasonTags = { suitable: ["岗位匹配"], unsuitable: ["暂不匹配"], needs_more_info: ["信息待补充"] }[decision] || [];
  await api(`/api/resumes/${id}/review-decision`, { method: "POST", body: JSON.stringify({ decision, reasonTags, note: "" }) });
  await clearResumePrefetchCacheAfterMutation();
  await advanceAfterReviewAction(id);
}
async function advanceAfterReviewAction(id) {
  const currentIndex = state.resumes.findIndex((resume) => resume.id === id);
  const nextId = currentIndex >= 0 ? state.resumes[currentIndex + 1]?.id : "";
  const currentPage = state.page;
  const shouldLoadNextPage = !nextId && currentIndex >= 0 && currentPage < state.pages;
  await loadResumes();
  if (nextId && state.resumes.some((resume) => resume.id === nextId)) {
    await openResume(nextId);
    return;
  }
  if (shouldLoadNextPage) {
    state.page = currentPage + 1;
    await loadResumes();
    const first = state.resumes[0];
    if (first) await openResume(first.id);
    return;
  }
  const fallbackIndex = currentIndex >= 0 ? Math.min(currentIndex, state.resumes.length - 1) : 0;
  const fallback = state.resumes[fallbackIndex];
  if (fallback && fallback.id !== id) {
    await openResume(fallback.id);
    return;
  }
  if (!state.resumes.length) {
    state.selectedId = "";
    state.context = null;
    renderRows();
    renderMiniList();
    $("previewTitle").textContent = "没有更多简历";
    $("resumePreview").textContent = "当前筛选条件下已经没有待查看的简历。";
    $("summaryCards").innerHTML = `<p class="muted">当前筛选条件下没有更多简历。</p>`;
  }
}
async function requestInterview() {
  if (!state.selectedId || !state.context || !canAction("interview:invite")) return;
  const payload = await api("/api/interview/invite", {
    method: "POST",
    body: JSON.stringify({ "resumeId": state.selectedId, "dryRun": true }),
  });
  state.interviewSelection = { resume: state.context.resume, preflight: payload, live: null };
  setView("interviews");
  renderInterviewDetail();
}
async function confirmInterviewInvite() {
  const selected = state.interviewSelection;
  const resume = selected?.resume || {};
  const preflight = selected?.preflight || {};
  const resumeId = resume.id || state.selectedId;
  if (!resumeId || !canAction("interview:invite")) return;
  const payload = await api("/api/interview/invite", {
    method: "POST",
    body: JSON.stringify({
      "resumeId": resumeId,
      "dryRun": false,
      "confirmLive": true,
      "selectedSessionId": preflight.sourceSessionId || "",
    }),
  });
  state.interviewSelection = { resume, preflight, live: payload };
  renderInterviewDetail();
}
async function selectInterviewSession(sessionId) {
  const selected = state.interviewSelection;
  const resume = selected?.resume || {};
  const resumeId = resume.id || state.selectedId;
  if (!resumeId || !sessionId || !canAction("interview:invite")) return;
  const payload = await api("/api/interview/invite", {
    method: "POST",
    body: JSON.stringify({
      "resumeId": resumeId,
      "dryRun": true,
      "selectedSessionId": sessionId,
    }),
  });
  state.interviewSelection = { resume, preflight: payload, live: null };
  renderInterviewDetail();
}
async function loadInterviewSessions() {
  try {
    const data = await api("/api/interview-center/sessions");
    $("interviewSessions").innerHTML = (data.items || []).length
      ? data.items.map((item) => `<button class="candidate-card">${escapeHtml(item.candidateName || item.id)}</button>`).join("")
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
    ${renderInterviewPreflight(selected)}
  `;
  document.querySelector("[data-confirm-interview]")?.addEventListener("click", confirmInterviewInvite);
  document.querySelectorAll("[data-select-interview-session]").forEach((button) => {
    button.addEventListener("click", () => selectInterviewSession(button.dataset.selectInterviewSession || ""));
  });
}
function renderInterviewPreflight(selected) {
  const preflight = selected.preflight || {};
  const live = selected.live || null;
  const contact = preflight.platformContact || {};
  const ready = Boolean(preflight.readyToExchange || preflight.workerResult?.readyToExchange);
  if (live) {
    return `
      <div class="ts-preflight-card">
        <p>入口状态：${live.accepted ? "约面试已发起" : "约面试失败"}</p>
        <p>结果：${escapeHtml(live.reason || live.workerResult?.reason || "已发送加我微信沟通")}</p>
      </div>
    `;
  }
  if (preflight.requiresConfirmation) {
    const candidates = preflight.candidates || [];
    const buttons = candidates.map((item) => `
      <button class="candidate-card" data-select-interview-session="${escapeHtml(item.id || "")}">
        <strong>${escapeHtml(item.candidateName || "候选会话")}</strong>
        <span>${escapeHtml(item.position || "")}</span>
      </button>
    `).join("");
    return `
      <div class="ts-preflight-card">
        <p>入口状态：需要人工确认候选会话</p>
        <div class="mini-list">${buttons || `<div class="empty-inline ts-empty-state">无候选会话</div>`}</div>
      </div>
    `;
  }
  return `
    <div class="ts-preflight-card">
      <p>入口状态：${ready ? "预检通过，可以确认发起约面试" : "预检未通过"}</p>
      <p>平台：${escapeHtml(platformName(preflight.platform))} / ${escapeHtml(preflight.owner || "")}</p>
      <p>候选人：${escapeHtml(contact.displayName || "")}</p>
      <p>核对岗位：${escapeHtml(contact.appliedPosition || "")}</p>
      <p>换微信按钮：${ready ? "已定位" : escapeHtml(preflight.reason || preflight.workerResult?.reason || "未定位")}</p>
      ${ready ? `<button class="${tsButtonClass("primary", "wide")}" data-confirm-interview>确认发起约面试</button>` : ""}
    </div>
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
    <button class="control-card primary ts-btn ts-btn--primary" data-process-all>按配置处理全部</button>
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
async function moveToAdjacentResume(direction) {
  if (!state.resumes.length) return;
  const selectedIndex = state.resumes.findIndex((resume) => resume.id === state.selectedId);
  const index = selectedIndex >= 0 ? selectedIndex : direction > 0 ? -1 : state.resumes.length;
  const nextIndex = index + direction;
  if (nextIndex >= 0 && nextIndex < state.resumes.length) {
    await openResume(state.resumes[nextIndex].id);
    return;
  }
  const targetPage = state.page + direction;
  if (targetPage < 1 || targetPage > state.pages) return;
  state.page = targetPage;
  await loadResumes({ preferCache: true });
  const target = direction > 0 ? state.resumes[0] : state.resumes[state.resumes.length - 1];
  if (target) await openResume(target.id);
}
function move(offset) {
  void moveToAdjacentResume(offset);
}
function shouldIgnoreResumeShortcut(event) {
  const target = event.target;
  if (!target) return false;
  const tag = (target.tagName || "").toUpperCase();
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(tag);
}
function bindResumeKeyboardNavigation() {
  document.addEventListener("keydown", (event) => {
    if (state.view !== "resumes" || shouldIgnoreResumeShortcut(event)) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      moveToAdjacentResume(-1);
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      moveToAdjacentResume(1);
    }
  });
}
function closeSmoothFilterSelects(except = null) {
  document.querySelectorAll(".smooth-select.is-open").forEach((wrapper) => {
    if (wrapper === except) return;
    wrapper.classList.remove("is-open");
    wrapper.querySelector(".smooth-select__button")?.setAttribute("aria-expanded", "false");
    smoothMenuForWrapper(wrapper)?.classList.remove("is-open");
  });
}
function smoothMenuForWrapper(wrapper) {
  const id = wrapper?.dataset.smoothSelectId || "";
  return id ? document.querySelector(`[data-smooth-select-for="${id}"]`) : null;
}
function isImportDateSelect(select) {
  return select?.name === "import_date_range";
}
function smoothWrapperForSelect(select) {
  return select?.parentElement?.querySelector(".smooth-select") || null;
}
function normalizedImportDateRange(dateFrom, dateTo) {
  const from = dateFrom || "";
  const to = dateTo || "";
  if (!from && !to) return { dateFrom: "", dateTo: "" };
  const singleDate = from || to;
  if (!from || !to) return { dateFrom: singleDate, dateTo: singleDate };
  return from <= to ? { dateFrom: from, dateTo: to } : { dateFrom: to, dateTo: from };
}
function importDateCalendarText(select) {
  const range = normalizedImportDateRange(select?.dataset.dateFrom || "", select?.dataset.dateTo || "");
  if (!range.dateFrom && !range.dateTo) return "";
  return range.dateFrom === range.dateTo ? range.dateFrom : `${range.dateFrom} - ${range.dateTo}`;
}
function clearImportDatePresetOptions(select) {
  [...(select?.options || [])].forEach((option) => {
    option.selected = false;
  });
}
function syncImportDateCalendar(select) {
  if (!isImportDateSelect(select)) return;
  const menu = smoothMenuForWrapper(smoothWrapperForSelect(select));
  if (!menu) return;
  const range = normalizedImportDateRange(select.dataset.dateFrom || "", select.dataset.dateTo || "");
  const fromInput = menu.querySelector('[data-import-date-boundary="from"]');
  const toInput = menu.querySelector('[data-import-date-boundary="to"]');
  if (fromInput) fromInput.value = range.dateFrom || "";
  if (toInput) toInput.value = range.dateTo || "";
}
function setImportDateCalendarRange(select, dateFrom, dateTo) {
  const range = normalizedImportDateRange(dateFrom, dateTo);
  if (range.dateFrom || range.dateTo) {
    select.dataset.dateFrom = range.dateFrom;
    select.dataset.dateTo = range.dateTo;
    clearImportDatePresetOptions(select);
  } else {
    delete select.dataset.dateFrom;
    delete select.dataset.dateTo;
  }
  syncImportDateCalendar(select);
  select.dispatchEvent(new Event("change", { bubbles: true }));
  syncSmoothSelectLabel(select);
}
function addImportDateCalendar(menu, select) {
  if (!isImportDateSelect(select)) return;
  const calendar = document.createElement("div");
  calendar.className = "smooth-select__calendar";
  calendar.innerHTML = `
    <div class="smooth-select__calendar-title">精确日期</div>
    <div class="smooth-select__calendar-grid">
      <label class="smooth-select__calendar-field">
        <span>开始</span>
        <input class="smooth-select__calendar-input" data-import-date-boundary="from" type="date" />
      </label>
      <label class="smooth-select__calendar-field">
        <span>结束</span>
        <input class="smooth-select__calendar-input" data-import-date-boundary="to" type="date" />
      </label>
    </div>
    <button class="smooth-select__calendar-clear" type="button">清除日期</button>
  `;
  const fromInput = calendar.querySelector('[data-import-date-boundary="from"]');
  const toInput = calendar.querySelector('[data-import-date-boundary="to"]');
  const updateRange = () => setImportDateCalendarRange(select, fromInput?.value || "", toInput?.value || "");
  fromInput?.addEventListener("change", updateRange);
  toInput?.addEventListener("change", updateRange);
  calendar.querySelector(".smooth-select__calendar-clear")?.addEventListener("click", (event) => {
    event.preventDefault();
    setImportDateCalendarRange(select, "", "");
  });
  menu.appendChild(calendar);
  syncImportDateCalendar(select);
}
function positionSmoothSelectMenu(wrapper) {
  const button = wrapper?.querySelector(".smooth-select__button");
  const menu = smoothMenuForWrapper(wrapper);
  if (!button || !menu) return;
  const rect = button.getBoundingClientRect();
  const viewportPadding = 12;
  const hasCalendar = wrapper.dataset.smoothSelectCalendar === "true";
  const menuWidth = hasCalendar ? Math.max(rect.width, 304) : rect.width;
  const menuHeight = Math.min(hasCalendar ? 330 : 260, menu.scrollHeight || (hasCalendar ? 300 : 220));
  const left = Math.max(viewportPadding, Math.min(rect.left, window.innerWidth - menuWidth - viewportPadding));
  const preferAbove = wrapper.dataset.smoothSelectMultiple === "true";
  const top = preferAbove
    ? Math.max(viewportPadding, rect.top - menuHeight - 6)
    : Math.max(viewportPadding, Math.min(rect.bottom + 6, window.innerHeight - menuHeight - viewportPadding));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  menu.style.width = `${menuWidth}px`;
  menu.style.transformOrigin = preferAbove ? "bottom center" : "top center";
}
function updateOpenSmoothSelectMenuPosition() {
  document.querySelectorAll(".smooth-select.is-open").forEach(positionSmoothSelectMenu);
}
function syncSmoothSelectLabel(select) {
  const wrapper = select.parentElement?.querySelector(".smooth-select");
  const menu = smoothMenuForWrapper(wrapper);
  const button = wrapper?.querySelector(".smooth-select__button");
  const label = wrapper?.querySelector(".smooth-select__label");
  if (select.multiple) {
    const selectedOptions = [...select.selectedOptions].filter((option) => option.value);
    const placeholder = select.options[0]?.textContent || "";
    const calendarText = importDateCalendarText(select);
    const text = calendarText || (selectedOptions.length
      ? selectedOptions.map((option) => option.textContent).join(" / ")
      : placeholder);
    if (label) label.textContent = text;
    if (button) button.title = text;
    menu?.querySelectorAll("[data-smooth-select-value]").forEach((optionButton) => {
      const value = optionButton.dataset.smoothSelectValue || "";
      const selected = [...select.selectedOptions].some((option) => option.value === value);
      optionButton.classList.toggle("is-selected", selected);
    });
    syncImportDateCalendar(select);
    return;
  }
  const selected = select.selectedOptions?.[0] || select.options[select.selectedIndex];
  if (label) label.textContent = selected?.textContent || "";
  if (button) button.title = selected?.textContent || "";
  menu?.querySelectorAll("[data-smooth-select-value]").forEach((optionButton) => {
    optionButton.classList.toggle("is-selected", optionButton.dataset.smoothSelectValue === select.value);
  });
}
function syncSmoothFilterSelects() {
  document.querySelectorAll(".filter-field--compact select").forEach(syncSmoothSelectLabel);
}
function initializeSmoothFilterSelects() {
  document.querySelectorAll(".filter-field--compact select").forEach((select, index) => {
    if (select.dataset.smoothSelectReady === "true") return;
    select.dataset.smoothSelectReady = "true";
    select.classList.add("smooth-select__native");
    const wrapper = document.createElement("div");
    wrapper.className = "smooth-select";
    wrapper.dataset.smoothSelectId = `smooth-select-${select.name || "filter"}-${index}`;
    wrapper.dataset.smoothSelectMultiple = String(select.multiple);
    wrapper.dataset.smoothSelectCalendar = String(isImportDateSelect(select));
    const button = document.createElement("button");
    button.type = "button";
    button.className = "smooth-select__button";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", `${wrapper.dataset.smoothSelectId}-menu`);
    button.innerHTML = `<span class="smooth-select__label"></span><span class="smooth-select__chevron" aria-hidden="true">⌄</span>`;
    const menu = document.createElement("div");
    menu.className = "smooth-select__menu";
    if (isImportDateSelect(select)) menu.classList.add("smooth-select__menu--calendar");
    menu.id = `${wrapper.dataset.smoothSelectId}-menu`;
    menu.dataset.smoothSelectFor = wrapper.dataset.smoothSelectId;
    menu.setAttribute("role", "listbox");
    menu.addEventListener("click", (event) => event.stopPropagation());
    [...select.options].forEach((option) => {
      const optionButton = document.createElement("button");
      optionButton.type = "button";
      optionButton.className = "smooth-select__option";
      optionButton.dataset.smoothSelectValue = option.value;
      optionButton.textContent = option.textContent;
      optionButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (select.multiple) {
          if (isImportDateSelect(select)) {
            delete select.dataset.dateFrom;
            delete select.dataset.dateTo;
          }
          if (!option.value) {
            [...select.options].forEach((item) => {
              item.selected = false;
            });
          } else {
            option.selected = !option.selected;
            if (select.options[0]) select.options[0].selected = false;
          }
          select.dispatchEvent(new Event("change", { bubbles: true }));
          syncSmoothSelectLabel(select);
          return;
        }
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        syncSmoothSelectLabel(select);
        wrapper.classList.remove("is-open");
        menu.classList.remove("is-open");
        button.setAttribute("aria-expanded", "false");
      });
      menu.appendChild(optionButton);
    });
    addImportDateCalendar(menu, select);
    select.insertAdjacentElement("afterend", wrapper);
    wrapper.append(button);
    document.body.appendChild(menu);
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const shouldOpen = !wrapper.classList.contains("is-open");
      closeSmoothFilterSelects(wrapper);
      if (shouldOpen) {
        wrapper.classList.toggle("is-open");
        menu.classList.add("is-open");
        positionSmoothSelectMenu(wrapper);
      } else {
        wrapper.classList.remove("is-open");
        menu.classList.remove("is-open");
      }
      button.setAttribute("aria-expanded", String(shouldOpen));
    });
    select.addEventListener("change", () => syncSmoothSelectLabel(select));
    syncSmoothSelectLabel(select);
  });
  if (document.body.dataset.smoothSelectCloseBound === "true") return;
  document.body.dataset.smoothSelectCloseBound = "true";
  document.addEventListener("click", () => closeSmoothFilterSelects());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSmoothFilterSelects();
  });
  window.addEventListener("resize", updateOpenSmoothSelectMenuPosition);
  window.addEventListener("scroll", updateOpenSmoothSelectMenuPosition, true);
}
function bindGlobalSearchToFilters() {
  const globalSearch = $("globalSearch");
  if (!globalSearch) return;
  globalSearch.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    $("filters").q.value = globalSearch.value;
    state.page = 1;
    clearResumePrefetchCache();
    setView("resumes");
  });
}
function applyResumeFilters() {
  state.jobType = $("filters").job_type.value.trim();
  state.page = 1;
  clearResumePrefetchCache();
  loadResumes();
}
function bindAutoApplyResumeFilters() {
  const filters = $("filters");
  if (!filters) return;
  $("filters").addEventListener("change", (event) => {
    if (!event.target?.matches?.("select, input")) return;
    applyResumeFilters();
  });
}
function clampSummaryPanelWidth(width, grid = $("previewGrid")) {
  const numeric = Number.parseInt(width, 10);
  const base = Number.isFinite(numeric) ? numeric : SUMMARY_PANEL_DEFAULT_WIDTH;
  const gridWidth = grid?.getBoundingClientRect?.().width || 0;
  const responsiveMax = gridWidth
    ? Math.max(SUMMARY_PANEL_MIN_WIDTH, Math.min(SUMMARY_PANEL_MAX_WIDTH, Math.floor(gridWidth - SUMMARY_PANEL_MIN_PREVIEW_WIDTH)))
    : SUMMARY_PANEL_MAX_WIDTH;
  return Math.min(responsiveMax, Math.max(SUMMARY_PANEL_MIN_WIDTH, base));
}
function currentSummaryPanelWidth() {
  const grid = $("previewGrid");
  if (!grid) return SUMMARY_PANEL_DEFAULT_WIDTH;
  const inlineWidth = grid.style.getPropertyValue("--summary-panel-width");
  const computedWidth = getComputedStyle(grid).getPropertyValue("--summary-panel-width");
  return Number.parseInt(inlineWidth || computedWidth, 10) || SUMMARY_PANEL_DEFAULT_WIDTH;
}
function setSummaryPanelWidth(width, { persist = false } = {}) {
  const grid = $("previewGrid");
  if (!grid) return SUMMARY_PANEL_DEFAULT_WIDTH;
  const next = clampSummaryPanelWidth(width, grid);
  grid.style.setProperty("--summary-panel-width", `${next}px`);
  const handle = $("summaryResizeHandle");
  if (handle) handle.setAttribute("aria-valuenow", String(next));
  if (persist) {
    try {
      localStorage.setItem(SUMMARY_PANEL_STORAGE_KEY, String(next));
    } catch (error) {
      console.debug("summary panel width was not persisted", error);
    }
  }
  return next;
}
function setSummaryPanelCollapsed(collapsed, { persist = false } = {}) {
  const grid = $("previewGrid");
  const button = $("summaryCollapseBtn");
  const icon = $("summaryCollapseIcon");
  if (!grid) return;
  const next = Boolean(collapsed);
  grid.classList.toggle("is-summary-collapsed", next);
  if (button) {
    button.setAttribute("aria-expanded", String(!next));
    button.title = next ? "展开摘要栏" : "收纳摘要栏";
  }
  if (icon) icon.textContent = next ? "‹" : "›";
  if (persist) {
    try {
      localStorage.setItem(SUMMARY_PANEL_COLLAPSED_STORAGE_KEY, String(next));
    } catch (error) {
      console.debug("summary panel collapsed state was not persisted", error);
    }
  }
}
function bindSummaryPanelCollapse() {
  const grid = $("previewGrid");
  const button = $("summaryCollapseBtn");
  if (!grid || !button) return;
  try {
    setSummaryPanelCollapsed(localStorage.getItem(SUMMARY_PANEL_COLLAPSED_STORAGE_KEY) === "true");
  } catch (error) {
    setSummaryPanelCollapsed(false);
  }
  button.addEventListener("click", () => {
    setSummaryPanelCollapsed(!grid.classList.contains("is-summary-collapsed"), { persist: true });
  });
}
function bindSummaryPanelResize() {
  const grid = $("previewGrid");
  const handle = $("summaryResizeHandle");
  if (!grid || !handle) return;
  try {
    setSummaryPanelWidth(localStorage.getItem(SUMMARY_PANEL_STORAGE_KEY) || SUMMARY_PANEL_DEFAULT_WIDTH);
  } catch (error) {
    setSummaryPanelWidth(SUMMARY_PANEL_DEFAULT_WIDTH);
  }
  let startX = 0;
  let startWidth = SUMMARY_PANEL_DEFAULT_WIDTH;
  function stopResize(event) {
    grid.classList.remove("is-summary-resizing");
    window.removeEventListener("pointermove", moveResize);
    window.removeEventListener("pointerup", stopResize);
    window.removeEventListener("pointercancel", stopResize);
    try {
      handle.releasePointerCapture(event.pointerId);
    } catch (error) {
      // Pointer capture may already be released by the browser.
    }
    setSummaryPanelWidth(currentSummaryPanelWidth(), { persist: true });
  }
  function moveResize(event) {
    const delta = event.clientX - startX;
    setSummaryPanelWidth(startWidth - delta);
  }
  handle.addEventListener("pointerdown", (event) => {
    if (grid.classList.contains("is-summary-collapsed")) return;
    if (event.button !== 0) return;
    event.preventDefault();
    startX = event.clientX;
    startWidth = currentSummaryPanelWidth();
    grid.classList.add("is-summary-resizing");
    try {
      handle.setPointerCapture(event.pointerId);
    } catch (error) {
      // Pointer capture is best effort for older embedded browsers.
    }
    window.addEventListener("pointermove", moveResize);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
  });
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const step = event.shiftKey ? 32 : 16;
    const direction = event.key === "ArrowLeft" ? 1 : -1;
    setSummaryPanelWidth(currentSummaryPanelWidth() + direction * step, { persist: true });
  });
  window.addEventListener("resize", () => setSummaryPanelWidth(currentSummaryPanelWidth()));
}
function bindPageActions() {
  hrAuth.bindLogin(api, afterLogin);
  document.querySelectorAll("[data-view]").forEach((button) => (button.onclick = () => setView(button.dataset.view)));
  initializeSmoothFilterSelects();
  bindGlobalSearchToFilters();
  bindAutoApplyResumeFilters();
  bindSummaryPanelResize();
  bindSummaryPanelCollapse();
  $("libraryToggleBtn").onclick = toggleLibraryPanel;
  $("segmentToggleBtn").onclick = toggleSegmentPanel;
  $("filterToggleBtn").onclick = toggleFilterPanel;
  $("filters").addEventListener("submit", (event) => {
    event.preventDefault();
    applyResumeFilters();
  });
  $("filters").addEventListener("reset", () =>
    setTimeout(() => {
      state.jobType = "";
      syncSmoothFilterSelects();
      applyResumeFilters();
    }, 0),
  );
  $("refreshDashboardBtn").onclick = loadDashboard;
  $("suitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "suitable");
  $("unsuitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "unsuitable");
  $("interviewBtn").onclick = requestInterview;
  $("logoutBtn").onclick = logout;
  $("prevBtn").onclick = () => move(-1);
  $("nextBtn").onclick = () => move(1);
  bindDockEffect($("actionDock"), ".action-dock-btn", { maxScale: 1.3, radius: 110, marginFactor: 15 });
  ["generateQuestionsBtn", "syncFeishuBtn", "renderImageBtn", "backfillBtn"].forEach((id) => {
    $(id).onclick = () => ($("interviewStatus").textContent = "当前首版界面已保留入口，真实调用继续复用后端面试中心接口。");
  });
  bindResumeKeyboardNavigation();
}
async function afterLogin(user) {
  clearResumePrefetchCache();
  state.user = user; state.jobType = ""; state.jobFacets = []; hrAuth.updateUserCard(user); hrAuth.showApp(); setAllowedNavigation(); setResumeMemberMode();
  const landingView = canView("resumes") ? "resumes" : uiAccess().defaultView;
  setView(landingView);
  if (canView("resumes")) await loadResumes();
}
async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  state.user = null; state.selectedId = ""; state.context = null; state.jobType = ""; state.jobFacets = [];
  clearResumePrefetchCache();
  setResumeMemberMode();
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
