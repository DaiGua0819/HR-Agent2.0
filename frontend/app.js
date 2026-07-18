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
  resumeJobFacets: [],
  queueJobFacets: [],
  queueSummaryLoaded: false,
  queueVersion: "",
  queueTotal: 0,
  queueSummaryTimer: null,
  queueSummaryAbortController: null,
  queueSummaryInFlight: false,
  interviewSelection: null,
  interviewSessions: [],
  selectedInterviewId: "",
  interviewLogs: [],
  interviewStatus: null,
  interviewSyncStatus: null,
  interviewStatusFilter: "",
  interviewDateStart: "",
  interviewDateEnd: "",
  interviewBusy: false,
  resumePageCache: new Map(),
  resumeContextCache: new Map(),
  resumePrefetchingPages: new Set(),
  resumePrefetchingContexts: new Set(),
  resumePrefetchAbortControllers: new Map(),
  resumeListAbortController: null,
  resumeListRequestSequence: 0,
  resumeContextAbortController: null,
  resumeContextRequestSequence: 0,
  resumeConversationAbortController: null,
  resumeConversationRequestSequence: 0,
  resumeConversationResumeId: "",
  resumeConversationCloseTimer: null,
  resumeConversationPreviousFocus: null,
  resumePreviewPagesAbortController: null,
  resumePreviewPagesRequestSequence: 0,
  resumePreviewPagesRequestKey: "",
  resumePreviewPagesCache: new Map(),
  lastJobTabPrefetchKey: "",
  resumeFilterDebounceTimer: null,
  resumePrefetchDelayTimer: null,
  resumePreviewImageCache: new Set(),
  resumePreviewImageQueue: [],
  resumePreviewImageInFlight: new Set(),
  resumePreviewImageLoaders: new Map(),
  resumePreviewImageActiveCount: 0,
  resumePreviewImageGeneration: 0,
  resumePreviewPageObserver: null,
  resumePreviewPrefetchTimer: null,
  resumePdfjsModulePromise: null,
  resumePdfActiveKey: "",
  resumePdfDocumentLoadingTask: null,
  resumePdfDocument: null,
  resumePdfRenderGeneration: 0,
  resumePdfRenderTasks: new Map(),
  resumePdfRequestedPages: new Set(),
  resumePdfRenderedPages: new Set(),
  resumePdfRenderQueue: [],
  resumePdfRenderActiveCount: 0,
  resumePdfPendingBackgroundPages: [],
  resumePdfBackgroundRenderTimer: null,
  resumePdfForcePageImageFallback: false,
};
const RESUME_FILTER_DEBOUNCE_MS = 250;
const QUEUE_SUMMARY_POLL_MS = 3000;
const RESUME_PREFETCH_AFTER_FILTER_MS = 500;
const RESUME_PREVIEW_PREFETCH_LIMIT = 10;
const RESUME_PREVIEW_PREFETCH_CONCURRENCY = 2;
const RESUME_PREVIEW_PREFETCH_DELAY_MS = 650;
const RESUME_PREVIEW_INITIAL_PAGE_LOAD_COUNT = 2;
const RESUME_PREVIEW_NEXT_PAGE_ROOT_MARGIN = "900px 0px";
const PDFJS_VENDOR_BASE = "/assets/vendor/pdfjs";
const RESUME_PDFJS_INITIAL_PAGE_RENDER_COUNT = 2;
const RESUME_PDFJS_RENDER_CONCURRENCY = 2;
const RESUME_PDFJS_BACKGROUND_RENDER_DELAY_MS = 80;
const RESUME_PDFJS_INITIAL_PAGE_RENDER_TIMEOUT_MS = 1600;
const RESUME_PDFJS_PAGE_RENDER_TIMEOUT_MS = 3000;
const RESUME_PDFJS_RENDER_SCALE_MAX = 1.6;
const SUMMARY_PANEL_STORAGE_KEY = "resumeSummaryPanelWidth";
const SUMMARY_PANEL_COLLAPSED_STORAGE_KEY = "resumeSummaryPanelCollapsed";
const SUMMARY_PANEL_DEFAULT_WIDTH = 276;
const SUMMARY_PANEL_MIN_WIDTH = 180;
const SUMMARY_PANEL_MAX_WIDTH = 460;
const SUMMARY_PANEL_MIN_PREVIEW_WIDTH = 380;
const tabs = [["all", "全部"], ["unread", "未看"], ["viewed", "已看"], ["suitable", "合适"], ["unsuitable", "不合适"], ["needs_more_info", "待补充"], ["queue", "待我处理"]];
const pages = { dashboard: ["Manager Console", "经理驾驶舱"], resumes: ["Resume Library", "简历库"], queue: ["Review Queue", "待我处理"], interviews: ["Interview Center", "面试中心"], automation: ["Automation", "自动化控制"], rules: ["Rules", "规则与知识库"] };
const INTERVIEW_STATUS_LABELS = {
  synced: "已同步",
  non_interview: "非面试",
  ignored: "已忽略",
  needs_match: "待匹配",
  needs_confirmation: "需确认",
  matched: "已绑定",
  questions_generated: "已生成问题",
  prepared: "已准备",
  prepared_local: "本地准备",
  backfilling: "回灌中",
  backfill_failed: "回灌失败",
  needs_review: "待复核",
  completed: "已完成",
  created: "已创建",
};
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
  "AI产品经理",
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
  "AI产品经理": "AI产品经理",
};
const $ = (id) => document.getElementById(id);
async function api(path, options = {}) {
  const { skipAuthExpiredHandler = false, headers = {}, ...fetchOptions } = options;
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...headers }, ...fetchOptions });
  if (!response.ok) {
    const text = await response.text();
    const error = new Error(`${response.status} ${text}`);
    error.status = response.status;
    if (error.status === 401 && !skipAuthExpiredHandler) handleAuthExpired(error);
    throw error;
  }
  return response.json();
}
function handleAuthExpired(error) {
  const message = "登录已失效，请重新使用飞书授权登录";
  state.user = null;
  state.resumes = [];
  closeResumeConversation({ immediate: true });
  state.selectedId = "";
  state.context = null;
  state.total = 0;
  state.pages = 0;
  state.interviewSessions = [];
  state.selectedInterviewId = "";
  stopQueueSummaryPolling();
  clearResumePrefetchCache();
  state.resumeContextCache.clear();
  state.resumePreviewPagesCache.clear();
  const emptyState = $("emptyState");
  if (emptyState) {
    $("emptyState").textContent = "登录已失效，请重新使用飞书授权登录";
    emptyState.style.display = "block";
  }
  if ($("miniList")) $("miniList").innerHTML = "";
  if ($("resumePagination")) $("resumePagination").innerHTML = "";
  if ($("summaryCards")) $("summaryCards").innerHTML = `<p class="muted">${escapeHtml(message)}</p>`;
  if ($("resumePreview")) $("resumePreview").textContent = message;
  setResumeMemberMode();
  hrAuth.showLogin(message);
  return error;
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
  if (
    compact.includes("ai产品经理") ||
    compact.includes("aiproductmanager") ||
    compact.includes("aipm") ||
    text.toLowerCase().includes("ai product manager") ||
    text.toLowerCase().includes("ai pm")
  ) return "AI产品经理";
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
const RESUME_COLLECTOR_ACCOUNT_LABELS = {
  "宋峰峰": "宋",
  "宋锋峰": "宋",
  "和新红": "和",
};
const resumePlatform = (resume) => resume?.linkedPlatform || resume?.linked_platform || resume?.source_platform || resume?.sourcePlatform || "";
function resumeOwnerCandidates(resume) {
  const payload = resume?.payload || {};
  return [
    resume?.linkedOwner,
    resume?.linked_owner,
    resume?.source_owner,
    resume?.sourceOwner,
    payload.linkedOwner,
    payload.linked_owner,
    payload.source_owner,
    payload.sourceOwner,
    payload.owner,
    payload.accountName,
    payload.account_name,
    payload.account,
    payload.operator,
  ];
}
function resumeCollectorAccountLabel(resume) {
  for (const value of resumeOwnerCandidates(resume)) {
    const owner = String(value || "").trim();
    if (Object.prototype.hasOwnProperty.call(RESUME_COLLECTOR_ACCOUNT_LABELS, owner)) {
      return RESUME_COLLECTOR_ACCOUNT_LABELS[owner];
    }
  }
  return "";
}
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
function resumeTopLevelValue(resume, keys) {
  for (const key of keys) {
    const value = resume?.[key];
    if (value === undefined || value === null || typeof value === "object") continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return "";
}
function resumeMajor(resume) {
  return resumePayloadValue(resume, ["major", "profession", "specialty"]);
}
function resumeListMajor(resume) {
  return resumeTopLevelValue(resume, ["major", "profession", "specialty"]);
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
function resumeListSchool(resume) {
  return resumeTopLevelValue(resume, ["school", "college", "university"]);
}
function resumeSchoolLevel(resume) {
  return resumePayloadValue(resume, ["schoolLevel", "school_level", "schoolTier", "school_tier"]) || extractSchoolLevelFromResumeText(resume);
}
function resumeListSchoolLevel(resume) {
  return resumeTopLevelValue(resume, ["schoolLevel", "school_level", "schoolTier", "school_tier"]);
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
function resumeListSchoolTierBadge(resume) {
  const level = resumeListSchoolLevel(resume);
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
function resumeListEducationLine(resume) {
  const degree = resumeTopLevelValue(resume, ["education", "degree"]);
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
function resumeCompactImportDate(resume) {
  const value = resumeImportTime(resume);
  const normalized = String(value).replace(/\//g, "-");
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) return `${match[1].slice(2)}-${match[2]}-${match[3]}`;
  return value;
}
function resumeListCompactImportDate(resume) {
  const value = resumeTopLevelValue(resume, ["updated_at", "updatedAt", "createdAt", "created_at", "downloadedAt"]) || "待提取";
  const normalized = String(value).replace(/\//g, "-");
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) return `${match[1].slice(2)}-${match[2]}-${match[3]}`;
  return value;
}
function resumePlatformAccountLabel(resume) {
  let platform = platformName(resumePlatform(resume));
  if (platform === "51job") platform = "51";
  const account = resumeCollectorAccountLabel(resume);
  return account ? `${platform} ' ${account}` : platform;
}
function resumeScoreLabel(resume) {
  const rawValue = resume?.match_score ?? resume?.matchScore;
  if (rawValue === "" || rawValue == null) return "--";
  const value = Number(rawValue);
  return Number.isFinite(value) ? String(Math.round(value)) : "--";
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
const isAdminUser = () => Boolean((state.user?.roles || []).some((role) => ["admin", "super_admin"].includes(role)));
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
  renderActionDock();
}
function selectedResume() {
  return state.context?.resume || state.resumes.find((resume) => resume.id === state.selectedId) || null;
}
function conversationDateLabel(value) {
  const match = String(value || "").match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : "";
}
function renderResumeConversationMessages(messages, payload) {
  if (!payload?.matched) return '<div class="resume-conversation-empty">暂未找到明确关联的聊天记录。</div>';
  if (!messages.length) return '<div class="resume-conversation-empty">当前会话还没有已保存消息。</div>';
  let previousDate = "";
  return messages.map((message) => {
    const sender = ["me", "other", "system"].includes(message.sender) ? message.sender : "other";
    const date = conversationDateLabel(message.sentAt);
    const separator = date && date !== previousDate
      ? `<div class="resume-conversation-date">${escapeHtml(date)}</div>`
      : "";
    if (date) previousDate = date;
    if (sender === "system") {
      return `${separator}<div class="resume-conversation-system">${escapeHtml(message.text || "")}</div>`;
    }
    return `${separator}
      <article class="resume-conversation-message resume-conversation-message--${sender}">
        <div class="resume-conversation-bubble">
          <span>${escapeHtml(message.text || "")}</span>
          <time>${escapeHtml(message.sentAt || "")}</time>
        </div>
      </article>`;
  }).join("");
}
function renderResumeConversationPayload(payload) {
  const resume = selectedResume() || {};
  const candidate = payload?.candidate || {};
  const conversation = payload?.conversation || {};
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  const name = candidate.name || resumeName(resume) || "候选人";
  const job = candidate.jobType || resumeJob(resume) || "未标注岗位";
  $("resumeConversationAvatar").textContent = name.slice(0, 2);
  $("resumeConversationTitle").textContent = `${name} · ${job}`;
  $("resumeConversationSubtitle").textContent = payload?.matched
    ? `${platformName(conversation.platform)} · ${conversation.owner || "未知账号"} · 最近更新 ${conversation.updatedAt || "待同步"}`
    : "暂未找到明确关联的聊天记录";
  $("resumeConversationMeta").innerHTML = payload?.matched
    ? `<span class="resume-conversation-chip resume-conversation-chip--success">身份已关联</span><span class="resume-conversation-chip">历史消息 ${Number(conversation.messageCount || 0)} 条</span><span class="resume-conversation-chip">只读</span>`
    : '<span class="resume-conversation-chip">未关联</span>';
  $("resumeConversationMessages").innerHTML = renderResumeConversationMessages(messages, payload);
}
function finishResumeConversationClose() {
  const modal = $("resumeConversationModal");
  if (!modal) return;
  if (state.resumeConversationCloseTimer) clearTimeout(state.resumeConversationCloseTimer);
  state.resumeConversationCloseTimer = null;
  modal.hidden = true;
  modal.dataset.state = "closed";
  $("resumeConversationMessages").innerHTML = "";
  const previousFocus = state.resumeConversationPreviousFocus;
  state.resumeConversationPreviousFocus = null;
  if (previousFocus?.focus) previousFocus.focus({ preventScroll: true });
}
function showResumeConversationModalLoading(resumeId) {
  const modal = $("resumeConversationModal");
  const resume = selectedResume() || {};
  if (state.resumeConversationCloseTimer) clearTimeout(state.resumeConversationCloseTimer);
  state.resumeConversationCloseTimer = null;
  state.resumeConversationResumeId = resumeId;
  if (modal.hidden) state.resumeConversationPreviousFocus = document.activeElement;
  modal.hidden = false;
  modal.dataset.state = "opening";
  $("resumeConversationAvatar").textContent = (resumeName(resume) || "候选人").slice(0, 2);
  $("resumeConversationTitle").textContent = `${resumeName(resume)} · ${resumeJob(resume)}`;
  $("resumeConversationSubtitle").textContent = "正在读取平台聊天记录";
  $("resumeConversationMeta").innerHTML = '<span class="resume-conversation-chip">读取中</span>';
  $("resumeConversationMessages").innerHTML = '<div class="resume-conversation-loading">正在读取聊天记录...</div>';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (!modal.hidden && state.resumeConversationResumeId === resumeId) {
      modal.dataset.state = "open";
      $("resumeConversationCloseBtn").focus({ preventScroll: true });
    }
  }));
}
function closeResumeConversation({ immediate = false } = {}) {
  const modal = $("resumeConversationModal");
  if (!modal || modal.hidden) return;
  state.resumeConversationRequestSequence += 1;
  state.resumeConversationResumeId = "";
  if (state.resumeConversationAbortController) {
    state.resumeConversationAbortController.abort();
    state.resumeConversationAbortController = null;
  }
  if (state.resumeConversationCloseTimer) clearTimeout(state.resumeConversationCloseTimer);
  state.resumeConversationCloseTimer = null;
  if (immediate) {
    finishResumeConversationClose();
    return;
  }
  modal.dataset.state = "closing";
  const dialog = modal.querySelector(".resume-conversation-dialog");
  const finish = () => {
    if (modal.hidden || modal.dataset.state !== "closing") return;
    finishResumeConversationClose();
  };
  dialog.addEventListener("transitionend", finish, { once: true });
  state.resumeConversationCloseTimer = setTimeout(finish, 240);
}
function handleResumePreviewContextMenu(event) {
  if (!isAdminUser() || !state.selectedId) return;
  if (!event.target.closest("#resumePreview")) return;
  event.preventDefault();
  openResumeConversation();
}
async function openResumeConversation() {
  if (!isAdminUser() || !state.selectedId) return;
  const resumeId = state.selectedId;
  const requestSequence = (state.resumeConversationRequestSequence += 1);
  if (state.resumeConversationAbortController) state.resumeConversationAbortController.abort();
  const controller = new AbortController();
  state.resumeConversationAbortController = controller;
  showResumeConversationModalLoading(resumeId);
  try {
    const payload = await api(`/api/resumes/${resumeId}/conversation`, { signal: controller.signal });
    if (requestSequence !== state.resumeConversationRequestSequence) return;
    if (state.selectedId !== resumeId) return;
    renderResumeConversationPayload(payload);
  } catch (error) {
    if (error?.name === "AbortError") return;
    if (requestSequence !== state.resumeConversationRequestSequence) return;
    if (state.selectedId !== resumeId) return;
    $("resumeConversationMessages").innerHTML = '<div class="resume-conversation-empty">聊天记录读取失败，请关闭后重试。</div>';
  } finally {
    if (state.resumeConversationAbortController === controller) state.resumeConversationAbortController = null;
  }
}
function selectedReviewState() {
  return state.context?.reviewState || selectedResume()?.reviewState || {};
}
function selectedResumePushedToAdmin() {
  return Boolean(selectedReviewState().assignedTo || selectedReviewState().assigned_to);
}
function renderActionDock() {
  const suitableBtn = $("suitableBtn");
  const unsuitableBtn = $("unsuitableBtn");
  const interviewBtn = $("interviewBtn");
  if (!suitableBtn || !unsuitableBtn || !interviewBtn) return;
  const memberPushMode = isMemberUser() && state.tab === "suitable";
  const alreadyPushed = selectedResumePushedToAdmin();
  suitableBtn.hidden = false;
  suitableBtn.disabled = !state.selectedId || (memberPushMode && alreadyPushed);
  suitableBtn.className = `${memberPushMode ? tsButtonClass("success", "member-push-btn") : tsButtonClass("success")} action-dock-btn`;
  if (memberPushMode) suitableBtn.textContent = "推送";
  else suitableBtn.textContent = "合适";
  if (memberPushMode && alreadyPushed) suitableBtn.textContent = "已推送";
  suitableBtn.onclick = () => {
    if (!state.selectedId) return;
    if (isMemberUser() && state.tab === "suitable") return pushSelectedResumeToAdmin();
    return setDecision(state.selectedId, "suitable");
  };
  unsuitableBtn.hidden = memberPushMode;
  unsuitableBtn.disabled = !state.selectedId;
  unsuitableBtn.textContent = "不合适";
  unsuitableBtn.onclick = () => state.selectedId && setDecision(state.selectedId, "unsuitable");
  interviewBtn.hidden = isMemberUser();
}
function setView(view) {
  if (state.user && !canView(view)) view = uiAccess().defaultView;
  if (view === "queue") {
    state.jobType = "";
    state.page = 1;
    if ($("filters")?.job_type) $("filters").job_type.value = "";
  }
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
  if (view === "resumes") loadCurrentResumeCollection();
  if (view === "queue") loadQueue();
  if (view === "interviews") loadInterviewSessions();
  if (view === "automation") renderAutomationControls();
}
function loadCurrentResumeCollection(options = {}) {
  if (state.tab === "queue") return loadQueue();
  return loadResumes(options);
}
async function loadUser() {
  const data = await api("/api/auth/me", { skipAuthExpiredHandler: true });
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
    .map(([key, label]) => {
      const count = key === "queue" && isAdminUser()
        ? `<span class="queue-status-count">${state.queueSummaryLoaded ? state.queueTotal : "..."}</span>`
        : "";
      return `<button data-tab="${key}" class="${tsSegmentClass(state.tab === key)}">${label}${count}</button>`;
    })
    .join("");
  renderActionDock();
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.onclick = () => {
      state.tab = button.dataset.tab;
      state.page = 1;
      renderActionDock();
      clearResumePrefetchCache();
      buildJobTabs();
      if (state.tab === "queue") return loadQueue();
      loadResumes({ fromFilter: true });
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
  const isQueue = state.tab === "queue";
  const facets = isQueue ? state.queueJobFacets : state.resumeJobFacets;
  const countsLoaded = !isQueue || state.queueSummaryLoaded;
  const counts = new Map();
  (facets || []).forEach((item) => {
    const job = canonicalResumeJobType(item.jobType);
    if (!job) return;
    counts.set(job, Math.max(counts.get(job) || 0, Number(item.count || 0)));
  });
  const allCount = isQueue
    ? state.queueTotal
    : [...counts.values()].reduce((sum, count) => sum + Number(count || 0), 0);
  const countLabel = (count) => countsLoaded ? String(count || 0) : "...";
  const allLabel = isQueue ? "待处理全部" : "全部简历";
  const buttons = [["", `${allLabel} (${countLabel(allCount)})`]].concat(
    jobs.map((job) => [job, `${displayResumeJobType(job)} (${countLabel(counts.get(canonicalResumeJobType(job)))})`]),
  );
  list.innerHTML = buttons
    .map(([job, label]) => `<button data-job-tab="${escapeHtml(job)}" class="filter-tag ${state.jobType === job ? "active" : ""}">${escapeHtml(label)}</button>`)
    .join("");
  list.querySelectorAll("[data-job-tab]").forEach((button) => {
    button.onclick = () => {
      state.jobType = button.dataset.jobTab || "";
      $("filters").job_type.value = state.jobType;
      state.page = 1;
      if (state.tab === "queue") return loadQueue();
      loadResumes({ fromFilter: true, preferCache: true });
    };
  });
}
function queryFromFilters(page = state.page, overrides = {}) {
  const data = new FormData($("filters"));
  const params = new URLSearchParams({ page: String(page), page_size: "10" });
  const hasJobTypeOverride = Object.prototype.hasOwnProperty.call(overrides, "jobType");
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
  const jobType = hasJobTypeOverride ? overrides.jobType : state.jobType;
  if (jobType) params.set("job_type", jobType);
  else if (hasJobTypeOverride) params.delete("job_type");
  if (state.tab === "unread") params.set("read_status", "unread");
  if (state.tab === "viewed") params.set("read_status", "viewed");
  if (["undecided", "suitable", "unsuitable", "needs_more_info"].includes(state.tab)) { params.delete("decision"); params.append("decision", state.tab); }
  return params.toString();
}
function resumeListCacheKey(page) {
  return queryFromFilters(page);
}
function resumeListCacheKeyForJob(job, page) {
  return queryFromFilters(page, { jobType: job });
}
function clearResumePrefetchCache() {
  if (state.resumeFilterDebounceTimer) clearTimeout(state.resumeFilterDebounceTimer);
  if (state.resumePrefetchDelayTimer) clearTimeout(state.resumePrefetchDelayTimer);
  if (state.resumeListAbortController) state.resumeListAbortController.abort();
  state.resumePrefetchAbortControllers.forEach((controller) => controller.abort());
  state.resumeFilterDebounceTimer = null;
  state.resumePrefetchDelayTimer = null;
  state.resumeListAbortController = null;
  state.resumePageCache.clear();
  state.resumePrefetchingPages.clear();
  state.resumePrefetchingContexts.clear();
  state.resumePrefetchAbortControllers.clear();
  clearResumePreviewImagePrefetchQueue();
}
async function clearResumePrefetchCacheAfterMutation() {
  clearResumePrefetchCache();
  state.resumeContextCache.clear();
  state.resumePreviewPagesCache.clear();
}
function applyResumeListData(data, { stale = false } = {}) {
  state.resumes = data.items || [];
  state.total = data.total || 0;
  state.page = data.page || 1;
  state.pageSize = data.pageSize || 10;
  state.pages = data.pages || 0;
  state.resumeJobFacets = data.jobFacets || [];
  buildJobTabs();
  renderRows();
  renderMiniList();
  renderPagination();
  renderActionDock();
  const emptyState = $("emptyState");
  if (emptyState) {
    if (stale) emptyState.dataset.stale = "true";
    else delete emptyState.dataset.stale;
  }
}
function resumePreviewImageUrl(resume) {
  return resume?.filePreviewImageUrl || resume?.file_preview_image_url || resume?.file?.previewImageUrl || "";
}
function resumePreviewPdfUrl(resume, file = {}) {
  if (!resume) return "";
  return (
    file.previewUrl ||
    file.preview_url ||
    resume.filePreviewUrl ||
    resume.file_preview_url ||
    resume.file?.previewUrl ||
    ""
  );
}
function resumePreviewPagesUrl(resume) {
  if (!resume) return "";
  return (
    resume.filePreviewPagesUrl ||
    resume.file_preview_pages_url ||
    resume.file?.previewPagesUrl ||
    (resumePreviewImageUrl(resume) && resume.id ? `/api/resumes/${resume.id}/preview-pages` : "")
  );
}
function clearResumePreviewImagePrefetchQueue() {
  state.resumePreviewImageGeneration += 1;
  if (state.resumePreviewPrefetchTimer) {
    clearTimeout(state.resumePreviewPrefetchTimer);
    state.resumePreviewPrefetchTimer = null;
  }
  disconnectResumePreviewPageObserver();
  state.resumePreviewImageLoaders.forEach((image) => {
    image.onload = null;
    image.onerror = null;
    image.src = "";
  });
  state.resumePreviewImageQueue = [];
  state.resumePreviewImageCache.clear();
  state.resumePreviewImageInFlight.clear();
  state.resumePreviewImageLoaders.clear();
  state.resumePreviewImageActiveCount = 0;
  if (state.resumePreviewPagesAbortController) {
    state.resumePreviewPagesAbortController.abort();
    state.resumePreviewPagesAbortController = null;
  }
  state.resumePreviewPagesRequestKey = "";
}
function followingResumePreviewCandidates(selectedId) {
  if (!selectedId) return [];
  const result = [];
  const seen = new Set([selectedId]);
  const append = (items) => {
    for (const resume of items || []) {
      if (result.length >= RESUME_PREVIEW_PREFETCH_LIMIT) return;
      const id = resume?.id || "";
      if (resumePreviewPdfUrl(resume)) continue;
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
function scheduleFollowingResumePreviewImages(selectedId) {
  if (state.resumePreviewPrefetchTimer) clearTimeout(state.resumePreviewPrefetchTimer);
  state.resumePreviewPrefetchTimer = setTimeout(() => {
    state.resumePreviewPrefetchTimer = null;
    if (state.selectedId !== selectedId) return;
    prefetchFollowingResumePreviewImages(selectedId);
  }, RESUME_PREVIEW_PREFETCH_DELAY_MS);
}
function prefetchNextResumePages() {
  if (state.view !== "resumes" || state.tab === "queue") return;
  for (const page of [state.page + 1, state.page + 2]) {
    if (page < 1 || page > state.pages) continue;
    const cacheKey = resumeListCacheKey(page);
    if (state.resumePageCache.has(cacheKey) || state.resumePrefetchingPages.has(cacheKey)) continue;
    state.resumePrefetchingPages.add(cacheKey);
    const controller = new AbortController();
    state.resumePrefetchAbortControllers.set(cacheKey, controller);
    api(`/api/resumes?${cacheKey}`, { signal: controller.signal })
      .then((data) => {
        state.resumePageCache.set(cacheKey, data);
        prefetchFollowingResumePreviewImages(state.selectedId);
      })
      .catch(() => {})
      .finally(() => {
        state.resumePrefetchingPages.delete(cacheKey);
        state.resumePrefetchAbortControllers.delete(cacheKey);
      });
  }
}
function prefetchAdjacentJobFirstPages() {
  if (state.view !== "resumes" || state.tab === "queue") return;
  const jobs = [""].concat(visibleJobTypes());
  const currentJob = state.jobType || "";
  const currentIndex = jobs.indexOf(currentJob);
  if (currentIndex < 0) return;
  const prefetchKey = `${currentJob}:${queryFromFilters(1)}`;
  if (state.lastJobTabPrefetchKey === prefetchKey) return;
  state.lastJobTabPrefetchKey = prefetchKey;
  for (const index of [currentIndex - 1, currentIndex + 1]) {
    const job = jobs[index];
    if (job === undefined) continue;
    const cacheKey = resumeListCacheKeyForJob(job, 1);
    if (state.resumePageCache.has(cacheKey) || state.resumePrefetchingPages.has(cacheKey)) continue;
    state.resumePrefetchingPages.add(cacheKey);
    const controller = new AbortController();
    state.resumePrefetchAbortControllers.set(cacheKey, controller);
    api(`/api/resumes?${cacheKey}`, { signal: controller.signal })
      .then((data) => {
        state.resumePageCache.set(cacheKey, data);
      })
      .catch(() => {})
      .finally(() => {
        state.resumePrefetchingPages.delete(cacheKey);
        state.resumePrefetchAbortControllers.delete(cacheKey);
      });
  }
}
function scheduleResumePrefetchAfterFilter() {
  if (state.resumePrefetchDelayTimer) clearTimeout(state.resumePrefetchDelayTimer);
  state.resumePrefetchDelayTimer = setTimeout(() => {
    state.resumePrefetchDelayTimer = null;
    prefetchNextResumePages();
    prefetchAdjacentJobFirstPages();
  }, RESUME_PREFETCH_AFTER_FILTER_MS);
}
async function refreshCachedResumeList(cacheKey, requestSequence, fromFilter) {
  const controller = new AbortController();
  state.resumeListAbortController = controller;
  try {
    const data = await api(`/api/resumes?${cacheKey}`, { signal: controller.signal });
    if (requestSequence !== state.resumeListRequestSequence) return null;
    if (cacheKey !== resumeListCacheKey(state.page)) return null;
    state.resumePageCache.set(cacheKey, data);
    applyResumeListData(data);
    if (fromFilter) {
      scheduleResumePrefetchAfterFilter();
    } else {
      prefetchNextResumePages();
    }
    return data;
  } catch (error) {
    if (error?.name === "AbortError") return null;
    throw error;
  } finally {
    if (state.resumeListAbortController === controller) state.resumeListAbortController = null;
  }
}
async function loadResumes({ preferCache = false, fromFilter = false } = {}) {
  if (state.tab === "queue") return loadQueue();
  buildTabs();
  const cacheKey = resumeListCacheKey(state.page);
  const cached = preferCache || fromFilter ? state.resumePageCache.get(cacheKey) : null;
  const requestSequence = (state.resumeListRequestSequence += 1);
  if (state.resumeListAbortController) {
    state.resumeListAbortController.abort();
    state.resumeListAbortController = null;
  }
  if (fromFilter && cached) {
    applyResumeListData(cached, { stale: true });
    scheduleResumePrefetchAfterFilter();
    refreshCachedResumeList(cacheKey, requestSequence, fromFilter).catch((error) => {
      if (error?.name === "AbortError") return;
      console.debug("resume stale refresh failed", error);
    });
    return cached;
  }
  let data = cached || null;
  if (!data) {
    return await refreshCachedResumeList(cacheKey, requestSequence, fromFilter);
  }
  if (requestSequence !== state.resumeListRequestSequence) return null;
  state.resumePageCache.set(cacheKey, data);
  applyResumeListData(data);
  if (fromFilter) {
    scheduleResumePrefetchAfterFilter();
  } else {
    prefetchNextResumePages();
  }
  return data;
}
function queueViewActive() {
  return state.view === "queue" || (state.view === "resumes" && state.tab === "queue");
}
function renderQueueCountIndicators() {
  const visible = isAdminUser();
  const value = state.queueSummaryLoaded ? String(state.queueTotal) : "...";
  [$("queueNavCount"), $("queueTabCount")].forEach((node) => {
    if (!node) return;
    node.hidden = !visible;
    node.textContent = visible ? value : "";
  });
  const statusCount = document.querySelector('[data-tab="queue"] .queue-status-count');
  if (statusCount) statusCount.textContent = value;
}
function stopQueueSummaryPolling() {
  if (state.queueSummaryTimer) clearTimeout(state.queueSummaryTimer);
  if (state.queueSummaryAbortController) state.queueSummaryAbortController.abort();
  state.queueSummaryTimer = null;
  state.queueSummaryAbortController = null;
  state.queueSummaryInFlight = false;
}
function scheduleQueueSummaryPoll(delay = QUEUE_SUMMARY_POLL_MS) {
  if (state.queueSummaryTimer) clearTimeout(state.queueSummaryTimer);
  state.queueSummaryTimer = null;
  if (!isAdminUser() || document.visibilityState !== "visible") return;
  state.queueSummaryTimer = setTimeout(async () => {
    state.queueSummaryTimer = null;
    await refreshQueueSummary();
    scheduleQueueSummaryPoll();
  }, delay);
}
function startQueueSummaryPolling() {
  stopQueueSummaryPolling();
  renderQueueCountIndicators();
  if (!isAdminUser()) return;
  refreshQueueSummary().finally(() => scheduleQueueSummaryPoll());
}
async function refreshQueueNow() {
  await refreshQueueSummary({ forceList: true });
  scheduleQueueSummaryPoll();
}
async function refreshQueueSummary({ forceList = false } = {}) {
  if (!isAdminUser()) return null;
  if (!forceList && document.visibilityState !== "visible") return null;
  if (state.queueSummaryInFlight && !forceList) return null;
  if (forceList && state.queueSummaryAbortController) {
    state.queueSummaryAbortController.abort();
  }
  const controller = new AbortController();
  state.queueSummaryAbortController = controller;
  state.queueSummaryInFlight = true;
  try {
    const data = await api("/api/resume-review/queue-summary", { signal: controller.signal });
    const changed = data.version !== state.queueVersion;
    state.queueJobFacets = data.jobFacets || [];
    state.queueTotal = Number(data.total || 0);
    state.queueVersion = data.version || state.queueVersion;
    state.queueSummaryLoaded = true;
    renderQueueCountIndicators();
    if (state.tab === "queue") buildJobTabs();
    if (forceList || (changed && queueViewActive())) {
      await loadQueue({ preserveSelection: true });
    }
    return data;
  } catch (error) {
    if (error?.name === "AbortError") return null;
    console.debug("shared review queue summary failed", error);
    return null;
  } finally {
    if (state.queueSummaryAbortController === controller) {
      state.queueSummaryAbortController = null;
      state.queueSummaryInFlight = false;
    }
  }
}
async function loadQueue({ preserveSelection = false } = {}) {
  state.tab = "queue";
  buildTabs();
  const requestSequence = (state.resumeListRequestSequence += 1);
  if (state.resumeListAbortController) {
    state.resumeListAbortController.abort();
    state.resumeListAbortController = null;
  }
  const controller = new AbortController();
  state.resumeListAbortController = controller;
  try {
    const params = new URLSearchParams({
      page: String(state.page || 1),
      page_size: String(state.pageSize || 10),
    });
    if (state.jobType) params.set("job_type", state.jobType);
    const data = await api(`/api/resume-review/queue?${params}`, { signal: controller.signal });
    if (requestSequence !== state.resumeListRequestSequence || state.tab !== "queue") return null;
    applySharedQueueData(data, { preserveSelection });
    return data;
  } catch (error) {
    if (error?.name === "AbortError") return null;
    if (requestSequence !== state.resumeListRequestSequence || state.tab !== "queue") return null;
    if (!preserveSelection) {
      applySharedQueueData({
        items: [],
        total: 0,
        page: 1,
        pageSize: state.pageSize || 10,
        pages: 0,
        jobFacets: state.queueJobFacets,
        queueTotal: state.queueTotal,
      });
      $("queueList").innerHTML = `<div class="empty-inline">待处理队列读取失败，请稍后重试。</div>`;
    }
    state.queueVersion = "";
    console.debug("shared review queue failed", error);
    return null;
  } finally {
    if (state.resumeListAbortController === controller) state.resumeListAbortController = null;
  }
}
function applySharedQueueData(data, { preserveSelection = false } = {}) {
  const items = data.items || [];
  state.resumes = items.map((item) => ({ ...item.resume, assignment: item.assignment })).filter(Boolean);
  state.total = Number(data.total || 0);
  state.page = Number(data.page || 1);
  state.pageSize = Number(data.pageSize || 10);
  state.pages = Number(data.pages || 0);
  state.queueJobFacets = data.jobFacets || [];
  const facetTotal = state.queueJobFacets.reduce(
    (sum, item) => sum + Number(item.count || 0),
    0,
  );
  state.queueTotal = Number(data.queueTotal ?? facetTotal);
  state.queueVersion = data.version || state.queueVersion;
  state.queueSummaryLoaded = Boolean(data.version || state.queueSummaryLoaded);
  if (!preserveSelection && state.selectedId && !state.resumes.some((resume) => resume.id === state.selectedId)) {
    closeResumeConversation({ immediate: true });
    state.selectedId = "";
    state.context = null;
  }
  buildTabs();
  buildJobTabs();
  renderQueueCountIndicators();
  renderRows();
  renderMiniList();
  renderPagination();
  renderQueuePagination();
  renderQueue(items);
}
function renderRows() {
  const rows = $("resumeRows");
  if (!rows) return;
  rows.innerHTML = state.resumes
    .map((resume) => {
      const review = resume.reviewState || {};
      return `
        <tr data-resume-row="${escapeHtml(resume.id)}" class="${resume.id === state.selectedId ? "active" : ""}">
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
  hideReviewerDecisionPopover();
  $("miniList").innerHTML = state.resumes
    .map((resume) => {
      const tier = resumeListSchoolTierBadge(resume);
      const review = resume.reviewState || {};
      const readStatus = review.readStatus === "viewed" ? "viewed" : "unread";
      const readLabel = readStatus === "viewed" ? "已读" : "未读";
      const decision = labelDecision(review.decision);
      const imported = resumeListCompactImportDate(resume);
      const major = resumeListMajor(resume) || "暂未提取到";
      const memberDecisionBadge = memberDecisionBadgeMarkup(resume);
      const scoreLabel = resumeScoreLabel(resume);
      return `
        <button class="candidate-card ${resume.id === state.selectedId ? "active candidate-card--focus-pop" : ""}" data-open="${resume.id}" style="z-index: 1; margin: 0px;">
          <span class="candidate-card__heading">
            <strong>${escapeHtml(resumeName(resume))}</strong>
            <span class="candidate-card__score ${scoreLabel === "--" ? "candidate-card__score--empty" : ""}" title="简历评分">${escapeHtml(scoreLabel)}</span>
            <span class="candidate-card__heading-status">
              <span class="${tsTagClass(review.decision)}">${escapeHtml(decision)}</span>
              ${memberDecisionBadge}
            </span>
          </span>
          <span class="candidate-card__job">
            <span class="candidate-card__job-main">${escapeHtml(resumeJob(resume))}</span>
            <span class="candidate-card__major">${escapeHtml(major)}</span>
          </span>
          <span class="candidate-card__meta">
            <span class="candidate-card__meta-item candidate-card__meta-school">
              <span class="candidate-card__meta-value">${escapeHtml(resumeListSchool(resume) || "待提取")}</span>
            </span>
            <span class="candidate-card__meta-item candidate-card__meta-tier">
              ${tier ? `<span class="school-tier-badge">${escapeHtml(tier)}</span>` : `<span class="candidate-card__meta-value">${escapeHtml(resumeListEducationLine(resume))}</span>`}
            </span>
            <span class="candidate-card__meta-item candidate-card__meta-date">${escapeHtml(imported)}</span>
            <span class="candidate-card__meta-item candidate-card__meta-platform">${escapeHtml(resumePlatformAccountLabel(resume))}</span>
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
  bindReviewerDecisionPopovers();
  bindDockEffect($("miniList"), ".candidate-card", { maxScale: 1.08, radius: 120, marginFactor: 8, vertical: true });
  requestAnimationFrame(scrollSelectedCandidateIntoView);
}
function reviewerDecisions(resume) {
  const decisions = resume?.reviewerDecisions || resume?.reviewer_decisions || resume?.memberReviewStates || resume?.member_review_states || [];
  return Array.isArray(decisions) ? decisions : [];
}
function memberReviewStates(resume) {
  return reviewerDecisions(resume);
}
function reviewerDecisionDisplayName(item) {
  const name = item?.userName || item?.user_name;
  if (name) return String(name);
  const userId = String(item?.userId || item?.user_id || "");
  return `历史账号（${userId.slice(-4) || "未知"}）`;
}
function reviewerDecisionPushed(item) {
  return Boolean(item?.assignedTo || item?.assigned_to);
}
function reviewerDecisionDisplayTime(item) {
  if (reviewerDecisionPushed(item)) {
    return item?.pushedAt || item?.pushed_at || item?.updatedAt || item?.updated_at || "";
  }
  return item?.decisionAt || item?.decision_at || item?.updatedAt || item?.updated_at || "";
}
function reviewerDecisionDate(value, compact = false) {
  const normalized = String(value || "").replace(/\//g, "-");
  const match = normalized.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return "";
  return compact ? `${match[2]}-${match[3]}` : `${match[1]}-${match[2]}-${match[3]}`;
}
function reviewerDecisionGroups(resume) {
  const states = reviewerDecisions(resume).filter((item) => ["suitable", "unsuitable"].includes(item?.decision));
  return [
    ["suitable", "合适"],
    ["unsuitable", "不合适"],
  ]
    .map(([decision, label]) => ({ decision, label, items: states.filter((item) => item.decision === decision) }))
    .filter((group) => group.items.length);
}
function memberDecisionBadgeMarkup(resume) {
  const groups = reviewerDecisionGroups(resume);
  if (!groups.length) return "";
  const labels = groups.map((group) => `${group.label} ${group.items.length}`);
  return `
    <span class="member-decision-badge" tabindex="0" data-reviewer-resume-id="${escapeHtml(resume.id)}" aria-label="${escapeHtml(labels.join("，"))}">
      <span class="member-decision-badge__label">${escapeHtml(labels.join(" / "))}</span>
    </span>
  `;
}
function reviewerDecisionPopoverMarkup(resume) {
  return reviewerDecisionGroups(resume)
    .map((group) => `
      <section class="reviewer-decision-popover__group">
        <strong>${escapeHtml(group.label)}</strong>
        ${group.items.map((item) => {
          const time = reviewerDecisionDate(reviewerDecisionDisplayTime(item), true);
          return `<span>${escapeHtml(reviewerDecisionDisplayName(item))}${time ? ` · ${escapeHtml(time)}` : ""}${reviewerDecisionPushed(item) ? " · 已推送" : ""}</span>`;
        }).join("")}
      </section>
    `)
    .join("");
}
let activeReviewerDecisionBadge = null;
let reviewerDecisionPopoverHideTimer = null;
function reviewerDecisionResume(resumeId) {
  if (state.context?.resume?.id === resumeId) return state.context.resume;
  return state.resumes.find((resume) => resume.id === resumeId) || null;
}
function showReviewerDecisionPopover(badge) {
  const root = $("reviewerDecisionPopoverRoot");
  const resume = reviewerDecisionResume(badge?.dataset?.reviewerResumeId || "");
  if (!root || !badge || !resume) return;
  if (reviewerDecisionPopoverHideTimer) clearTimeout(reviewerDecisionPopoverHideTimer);
  reviewerDecisionPopoverHideTimer = null;
  activeReviewerDecisionBadge = badge;
  root.innerHTML = reviewerDecisionPopoverMarkup(resume);
  root.hidden = false;
  positionReviewerDecisionPopover();
}
function positionReviewerDecisionPopover() {
  const root = $("reviewerDecisionPopoverRoot");
  const badge = activeReviewerDecisionBadge;
  if (!root || root.hidden || !badge?.isConnected) return hideReviewerDecisionPopover();
  const anchor = badge.getBoundingClientRect();
  const popover = root.getBoundingClientRect();
  const margin = 12;
  const below = anchor.bottom + 6;
  const above = anchor.top - popover.height - 6;
  const top = below + popover.height <= window.innerHeight - margin ? below : Math.max(margin, above);
  const left = Math.max(margin, Math.min(anchor.left, window.innerWidth - popover.width - margin));
  root.style.top = `${Math.round(top)}px`;
  root.style.left = `${Math.round(left)}px`;
}
function hideReviewerDecisionPopover() {
  if (reviewerDecisionPopoverHideTimer) clearTimeout(reviewerDecisionPopoverHideTimer);
  reviewerDecisionPopoverHideTimer = null;
  activeReviewerDecisionBadge = null;
  const root = $("reviewerDecisionPopoverRoot");
  if (!root) return;
  root.hidden = true;
  root.innerHTML = "";
}
function scheduleReviewerDecisionPopoverHide() {
  if (reviewerDecisionPopoverHideTimer) clearTimeout(reviewerDecisionPopoverHideTimer);
  reviewerDecisionPopoverHideTimer = setTimeout(hideReviewerDecisionPopover, 100);
}
function bindReviewerDecisionPopovers() {
  document.querySelectorAll("[data-reviewer-resume-id]").forEach((badge) => {
    badge.addEventListener("mouseenter", () => showReviewerDecisionPopover(badge));
    badge.addEventListener("mouseleave", scheduleReviewerDecisionPopoverHide);
    badge.addEventListener("focus", () => showReviewerDecisionPopover(badge));
    badge.addEventListener("blur", scheduleReviewerDecisionPopoverHide);
    badge.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      showReviewerDecisionPopover(badge);
    });
  });
}
function memberDecisionSummaryMarkup(resume) {
  const states = reviewerDecisions(resume).filter((item) => item?.decision && item.decision !== "undecided");
  if (!states.length) return "";
  const rows = states
    .map((item) => {
      const pushed = reviewerDecisionPushed(item) ? " · 已推送" : "";
      return `<p><span class="${tsTagClass(item.decision)}">${escapeHtml(labelDecision(item.decision))}</span> ${escapeHtml(reviewerDecisionDisplayName(item))}${escapeHtml(pushed)}</p>`;
    })
    .join("");
  return `<div class="summary-card ts-summary-card member-decision-list"><h3>成员判断</h3>${rows}</div>`;
}
function reviewerDecisionTimelineMarkup(resume) {
  const timeline = { suitable: "", unsuitable: "", pushed: "" };
  reviewerDecisions(resume).forEach((item) => {
    const decisionDate = reviewerDecisionDate(item?.decisionAt || item?.decision_at || item?.updatedAt || item?.updated_at);
    const pushedDate = reviewerDecisionDate(item?.pushedAt || item?.pushed_at);
    if (["suitable", "unsuitable"].includes(item?.decision) && decisionDate > timeline[item.decision]) {
      timeline[item.decision] = decisionDate;
    }
    if (pushedDate > timeline.pushed) timeline.pushed = pushedDate;
  });
  return [
    timeline.suitable ? `<p>合适时间：${escapeHtml(timeline.suitable)}</p>` : "",
    timeline.unsuitable ? `<p>不合适时间：${escapeHtml(timeline.unsuitable)}</p>` : "",
    timeline.pushed ? `<p>推送时间：${escapeHtml(timeline.pushed)}</p>` : "",
  ].join("");
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
    loadCurrentResumeCollection({ preferCache: true });
  });
  node.querySelectorAll("[data-page-move]").forEach((button) => {
    button.onclick = () => {
      const nextPage = current + Number(button.dataset.pageMove || 0);
      if (nextPage < 1 || nextPage > pages) return;
      state.page = nextPage;
      loadCurrentResumeCollection({ preferCache: true });
    };
  });
}
function renderQueuePagination() {
  const node = $("queuePagination");
  if (!node) return;
  const pages = Math.max(1, state.pages || 1);
  const current = Math.min(Math.max(1, state.page || 1), pages);
  node.innerHTML = `
    <span class="pagination-status">第 ${current} / ${pages} 页，共 ${state.total || 0} 份</span>
    <div class="ts-pagination">
      <button class="${tsButtonClass("default")}" data-queue-page-move="-1" ${current <= 1 ? "disabled" : ""}>上一页</button>
      <button class="${tsButtonClass("primary")}" data-queue-page-move="1" ${current >= pages ? "disabled" : ""}>下一页</button>
    </div>
  `;
  node.querySelectorAll("[data-queue-page-move]").forEach((button) => {
    button.onclick = () => {
      const nextPage = current + Number(button.dataset.queuePageMove || 0);
      if (nextPage < 1 || nextPage > pages) return;
      state.page = nextPage;
      loadQueue();
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
function updateResumeSelectionDom(previousId, nextId) {
  const ids = new Set([previousId, nextId].filter(Boolean));
  document.querySelectorAll("[data-open]").forEach((node) => {
    if (!ids.has(node.dataset.open)) return;
    const active = node.dataset.open === nextId;
    node.classList.toggle("active", active);
    node.classList.toggle("candidate-card--focus-pop", active && node.classList.contains("candidate-card"));
  });
  document.querySelectorAll("[data-resume-row]").forEach((row) => {
    if (!ids.has(row.dataset.resumeRow)) return;
    row.classList.toggle("active", row.dataset.resumeRow === nextId);
  });
  requestAnimationFrame(scrollSelectedCandidateIntoView);
}
function renderOptimisticResumeContext(resume) {
  if (!resume) return;
  const previewImageUrl = resumePreviewImageUrl(resume);
  const previewPdfUrl = resumePreviewPdfUrl(resume);
  const context = {
    resume,
    reviewState: resume.reviewState || {},
    score: { value: resume.match_score ?? resume.matchScore ?? "", grade: resume.scoreGrade || "" },
    file: {
      available: Boolean(previewPdfUrl || previewImageUrl),
      previewUrl: previewPdfUrl,
      previewImageUrl,
      previewPagesUrl: resumePreviewPagesUrl(resume),
      downloadUrl: resume.fileDownloadUrl || resume.file_download_url || "",
    },
  };
  state.context = context;
  $("previewTitle").textContent = `${resumeName(resume)} 路 ${resumeJob(resume)}`;
  renderResumePreview(context);
  $("summaryCards").innerHTML = `
    <div class="summary-card ts-summary-card"><h3>候选人</h3>
      <p>姓名：${escapeHtml(resumeName(resume))}</p><p>岗位：${escapeHtml(resumeJob(resume))}</p>
      <p>电话：${escapeHtml(resume.phone || "")}</p><p>学历：${escapeHtml(resumeEducationLine(resume))}</p>
      <p>正在读取审阅详情...</p></div>
  `;
  renderActionDock();
}
async function openResume(id) {
  if (!id) return;
  closeResumeConversation({ immediate: true });
  const previousId = state.selectedId;
  state.selectedId = id;
  updateResumeSelectionDom(previousId, id);
  scheduleFollowingResumePreviewImages(id);
  cancelResumePdfRendering();
  if (state.resumePreviewPagesAbortController) {
    state.resumePreviewPagesAbortController.abort();
    state.resumePreviewPagesAbortController = null;
  }
  state.resumePreviewPagesRequestSequence += 1;
  state.resumePreviewPagesRequestKey = "";
  const resume = state.resumes.find((item) => item.id === id);
  if (state.resumeContextCache.has(id)) {
    state.context = state.resumeContextCache.get(id);
    renderContext();
    return;
  }
  renderOptimisticResumeContext(resume);
  if (state.resumeContextAbortController) {
    state.resumeContextAbortController.abort();
    state.resumeContextAbortController = null;
  }
  const requestSequence = (state.resumeContextRequestSequence += 1);
  const controller = new AbortController();
  state.resumeContextAbortController = controller;
  let context = null;
  try {
    context = await api(`/api/resumes/${id}/review-context`, { signal: controller.signal });
  } catch (error) {
    if (error?.name === "AbortError") return;
    throw error;
  } finally {
    if (state.resumeContextAbortController === controller) state.resumeContextAbortController = null;
  }
  if (requestSequence !== state.resumeContextRequestSequence) return;
  if (state.selectedId !== id) return;
  state.context = context;
  state.resumeContextCache.set(id, state.context);
  renderContext();
  return;
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
function contextPreviewPagesUrl(context) {
  const resume = context?.resume || {};
  const file = context?.file || {};
  return file.previewPagesUrl || file.preview_pages_url || resumePreviewPagesUrl(resume);
}
function normalizedPreviewPages(context) {
  const resume = context?.resume || {};
  const file = context?.file || {};
  const pages = Array.isArray(file.previewPages) ? file.previewPages : [];
  const normalized = pages
    .map((page, index) => ({
      page: Number(page.page || index + 1),
      imageUrl: String(page.imageUrl || page.image_url || "").trim(),
    }))
    .filter((page) => page.imageUrl);
  if (normalized.length) return normalized;
  const firstPageUrl = file.previewImageUrl || resumePreviewImageUrl(resume);
  return firstPageUrl ? [{ page: 1, imageUrl: firstPageUrl }] : [];
}
async function loadPdfjsModule() {
  if (!state.resumePdfjsModulePromise) {
    state.resumePdfjsModulePromise = import(`${PDFJS_VENDOR_BASE}/build/pdf.mjs`).then((pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = `${PDFJS_VENDOR_BASE}/build/pdf.worker.mjs`;
      return pdfjs;
    });
  }
  return state.resumePdfjsModulePromise;
}
function disconnectResumePdfPageObserver() {
  state.resumePdfRenderQueue = [];
  state.resumePdfPendingBackgroundPages = [];
  if (state.resumePdfBackgroundRenderTimer) {
    clearTimeout(state.resumePdfBackgroundRenderTimer);
    state.resumePdfBackgroundRenderTimer = null;
  }
}
function cancelResumePdfRendering() {
  disconnectResumePdfPageObserver();
  state.resumePdfRenderGeneration += 1;
  state.resumePdfRenderTasks.forEach((task) => {
    try {
      task.cancel();
    } catch (error) {
      console.debug("resume pdf render cancel failed", error);
    }
  });
  state.resumePdfRenderTasks.clear();
  state.resumePdfRequestedPages.clear();
  state.resumePdfRenderedPages.clear();
  state.resumePdfRenderQueue = [];
  state.resumePdfRenderActiveCount = 0;
  state.resumePdfPendingBackgroundPages = [];
  state.resumePdfForcePageImageFallback = false;
  if (state.resumePdfDocumentLoadingTask) {
    const loadingTask = state.resumePdfDocumentLoadingTask;
    state.resumePdfDocumentLoadingTask = null;
    try {
      const destroyed = loadingTask.destroy();
      if (destroyed?.catch) destroyed.catch(() => {});
    } catch (error) {
      console.debug("resume pdf loading cancel failed", error);
    }
  }
  if (state.resumePdfDocument?.destroy) {
    try {
      const destroyed = state.resumePdfDocument.destroy();
      if (destroyed?.catch) destroyed.catch(() => {});
    } catch (error) {
      console.debug("resume pdf document destroy failed", error);
    }
  }
  state.resumePdfDocument = null;
  state.resumePdfActiveKey = "";
}
function pdfRenderKey(resume, file = {}) {
  const pdfUrl = resumePreviewPdfUrl(resume, file);
  return resume?.id && pdfUrl ? `${resume.id}:${pdfUrl}` : "";
}
function isCurrentPdfRender(key, generation, resumeId) {
  return (
    key &&
    state.resumePdfActiveKey === key &&
    state.resumePdfRenderGeneration === generation &&
    state.selectedId === resumeId
  );
}
function renderPdfjsPreview(context) {
  const resume = context?.resume || {};
  const file = context?.file || {};
  const preview = $("resumePreview");
  const pdfUrl = resumePreviewPdfUrl(resume, file);
  if (!preview || !resume.id || !pdfUrl) return false;
  const key = pdfRenderKey(resume, file);
  const downloadUrl = file.downloadUrl || `/api/resumes/${resume.id}/download`;
  const existingStack = preview.querySelector(".resume-pdfjs-stack");
  if (state.resumePdfActiveKey === key && existingStack?.dataset.pdfjsActiveKey === key) {
    const link = preview.querySelector(".resume-download-link");
    if (link) link.href = downloadUrl;
    return true;
  }
  cancelResumePdfRendering();
  const generation = state.resumePdfRenderGeneration;
  state.resumePdfActiveKey = key;
  preview.className = "resume-preview image-preview pdfjs-preview";
  preview.innerHTML = `
    <div class="resume-image-stage">
      <a href="${escapeHtml(downloadUrl)}" download class="resume-download-link" title="点击下载简历PDF">
        <div class="resume-pdfjs-stack" data-pdfjs-active-key="${escapeHtml(key)}">
          <div class="resume-pdfjs-loading">Loading resume preview...</div>
        </div>
      </a>
    </div>
  `;
  loadPdfjsImageFallbackStack(context, key, generation).then((rendered) => {
    if (rendered) return;
    return startPdfjsDocumentRender(context, key, generation);
  }).catch((error) => {
    fallbackPdfjsPreview(context, error, generation);
  });
  return true;
}
async function startPdfjsDocumentRender(context, key, generation) {
  const resume = context?.resume || {};
  const file = context?.file || {};
  const pdfUrl = resumePreviewPdfUrl(resume, file);
  const pdfjs = await loadPdfjsModule();
  if (!isCurrentPdfRender(key, generation, resume.id)) return;
  const loadingTask = pdfjs.getDocument({
    url: pdfUrl,
    withCredentials: true,
    cMapUrl: `${PDFJS_VENDOR_BASE}/cmaps/`,
    cMapPacked: true,
    standardFontDataUrl: `${PDFJS_VENDOR_BASE}/standard_fonts/`,
    wasmUrl: `${PDFJS_VENDOR_BASE}/wasm/`,
  });
  state.resumePdfDocumentLoadingTask = loadingTask;
  const pdfDocument = await loadingTask.promise;
  if (!isCurrentPdfRender(key, generation, resume.id)) {
    if (pdfDocument?.destroy) pdfDocument.destroy();
    return;
  }
  state.resumePdfDocument = pdfDocument;
  const pageCount = pdfDocument.numPages || 1;
  renderPdfjsPageFrames(context, pageCount);
  const firstPageCount = Math.min(pageCount, RESUME_PDFJS_INITIAL_PAGE_RENDER_COUNT);
  const firstPageNumbers = Array.from({ length: firstPageCount }, (_, index) => index + 1);
  state.resumePdfPendingBackgroundPages = Array.from(
    { length: Math.max(0, pageCount - firstPageCount) },
    (_, index) => firstPageCount + index + 1,
  );
  queuePdfjsPages(context, key, generation, firstPageNumbers);
}
function renderPdfjsPageFrames(context, pageCount) {
  const resume = context?.resume || {};
  const preview = $("resumePreview");
  const stack = preview?.querySelector(".resume-pdfjs-stack");
  if (!stack) return;
  stack.dataset.pageCount = String(pageCount);
  stack.innerHTML = Array.from({ length: pageCount }, (_, index) => {
    const pageNumber = index + 1;
    return `
      <div class="resume-pdfjs-page" data-pdfjs-frame-page="${escapeHtml(String(pageNumber))}">
        <div class="resume-pdfjs-page-placeholder">
          ${escapeHtml(resumeName(resume))} page ${escapeHtml(String(pageNumber))}
        </div>
      </div>
    `;
  }).join("");
}
async function loadPdfjsImageFallbackStack(context, key, generation) {
  const resume = context?.resume || {};
  if (!isCurrentPdfRender(key, generation, resume.id)) return false;
  let pages = normalizedPreviewPages(context);
  const pagesUrl = contextPreviewPagesUrl(context);
  if (pagesUrl) {
    try {
      if (state.resumePreviewPagesCache.has(pagesUrl)) {
        pages = state.resumePreviewPagesCache.get(pagesUrl);
      } else {
        const data = await api(pagesUrl);
        if (!isCurrentPdfRender(key, generation, resume.id)) return false;
        const loadedPages = Array.isArray(data.pages)
          ? data.pages
              .map((page, index) => ({
                page: Number(page.page || index + 1),
                imageUrl: String(page.imageUrl || page.image_url || "").trim(),
              }))
              .filter((page) => page.imageUrl)
          : [];
        if (loadedPages.length) {
          pages = loadedPages;
          state.resumePreviewPagesCache.set(pagesUrl, loadedPages);
          if (context.file) {
            context.file.previewPageCount = data.pageCount || loadedPages.length;
          }
        }
      }
    } catch (error) {
      if (error?.name === "AbortError") return false;
      console.debug("resume pdfjs image fallback pages failed", error);
    }
  }
  if (!pages.length || !isCurrentPdfRender(key, generation, resume.id)) return false;
  renderPdfjsImageFallbackStack(context, key, generation, pages);
  return true;
}
function renderPdfjsImageFallbackStack(context, key, generation, pages) {
  const resume = context?.resume || {};
  if (!isCurrentPdfRender(key, generation, resume.id)) return;
  state.resumePdfForcePageImageFallback = true;
  state.resumePdfRenderQueue = [];
  state.resumePdfPendingBackgroundPages = [];
  if (state.resumePdfBackgroundRenderTimer) {
    clearTimeout(state.resumePdfBackgroundRenderTimer);
    state.resumePdfBackgroundRenderTimer = null;
  }
  if (context.file) {
    context.file.previewPages = pages;
    context.file.previewPageCount = pages.length;
  }
  const pageCount = pages.reduce((maxPage, page, index) => {
    const pageNumber = Number(page.page || index + 1);
    return Math.max(maxPage, Number.isFinite(pageNumber) ? pageNumber : index + 1);
  }, pages.length);
  renderPdfjsPageFrames(context, pageCount);
  pages.forEach((page, index) => {
    const pageNumber = Number(page.page || index + 1);
    if (!Number.isFinite(pageNumber) || pageNumber < 1) return;
    renderPdfjsPageFallback(pageNumber, context, key, generation);
  });
}
function queuePdfjsPages(context, key, generation, pageNumbers) {
  if (!isCurrentPdfRender(key, generation, context?.resume?.id || "")) return;
  pageNumbers.forEach((pageNumber) => {
    if (!Number.isFinite(pageNumber) || pageNumber < 1) return;
    if (state.resumePdfRequestedPages.has(pageNumber)) return;
    if (state.resumePdfRenderedPages.has(pageNumber)) return;
    if (state.resumePdfRenderQueue.includes(pageNumber)) return;
    state.resumePdfRenderQueue.push(pageNumber);
  });
  pumpPdfjsRenderQueue(context, key, generation);
}
function pumpPdfjsRenderQueue(context, key, generation) {
  if (!isCurrentPdfRender(key, generation, context?.resume?.id || "")) return;
  while (
    state.resumePdfRenderActiveCount < RESUME_PDFJS_RENDER_CONCURRENCY &&
    state.resumePdfRenderQueue.length
  ) {
    const pageNumber = state.resumePdfRenderQueue.shift();
    if (state.resumePdfRequestedPages.has(pageNumber) || state.resumePdfRenderedPages.has(pageNumber)) {
      continue;
    }
    state.resumePdfRenderActiveCount += 1;
    renderPdfjsPage(pageNumber, context, key, generation).finally(() => {
      if (generation !== state.resumePdfRenderGeneration) return;
      state.resumePdfRenderActiveCount = Math.max(0, state.resumePdfRenderActiveCount - 1);
      if (pageNumber === 1) schedulePdfjsBackgroundPages(context, key, generation);
      pumpPdfjsRenderQueue(context, key, generation);
    });
  }
}
function schedulePdfjsBackgroundPages(context, key, generation) {
  if (!isCurrentPdfRender(key, generation, context?.resume?.id || "")) return;
  if (!state.resumePdfPendingBackgroundPages.length) return;
  if (state.resumePdfBackgroundRenderTimer) clearTimeout(state.resumePdfBackgroundRenderTimer);
  state.resumePdfBackgroundRenderTimer = setTimeout(() => {
    state.resumePdfBackgroundRenderTimer = null;
    const pageNumbers = state.resumePdfPendingBackgroundPages.splice(0);
    queuePdfjsPages(context, key, generation, pageNumbers);
  }, RESUME_PDFJS_BACKGROUND_RENDER_DELAY_MS);
}
function previewImageUrlForPdfjsPage(context, pageNumber) {
  const resume = context?.resume || {};
  const pages = normalizedPreviewPages(context);
  const page = pages.find((item) => Number(item.page || 0) === pageNumber);
  if (page?.imageUrl) return page.imageUrl;
  if (!resume.id) return "";
  return `/api/resumes/${resume.id}/preview-image?page=${pageNumber}`;
}
function renderPdfjsPageFallback(pageNumber, context, key, generation) {
  const resume = context?.resume || {};
  if (!isCurrentPdfRender(key, generation, resume.id)) return;
  const preview = $("resumePreview");
  const frame = preview?.querySelector(`[data-pdfjs-frame-page="${pageNumber}"]`);
  const imageUrl = previewImageUrlForPdfjsPage(context, pageNumber);
  if (!frame || !imageUrl) return;
  const image = document.createElement("img");
  image.className = "resume-page-image resume-pdfjs-page-fallback-image";
  image.dataset.previewPage = String(pageNumber);
  image.loading = "eager";
  image.decoding = "async";
  image.alt = `${resumeName(resume)} resume page ${pageNumber}`;
  image.src = imageUrl;
  image.onerror = () => {
    if (!isCurrentPdfRender(key, generation, resume.id)) return;
    frame.innerHTML = `
      <div class="resume-pdfjs-page-placeholder">
        ${escapeHtml(resumeName(resume))} page ${escapeHtml(String(pageNumber))}
      </div>
    `;
    frame.classList.remove("resume-pdfjs-page--loading", "resume-pdfjs-page--loaded");
    frame.classList.add("resume-pdfjs-page--fallback");
  };
  frame.innerHTML = "";
  frame.appendChild(image);
  frame.classList.remove("resume-pdfjs-page--loading");
  frame.classList.add("resume-pdfjs-page--loaded", "resume-pdfjs-page--fallback");
  state.resumePdfRenderedPages.add(pageNumber);
}
function fallbackRemainingPdfjsPages(context, key, generation) {
  const resume = context?.resume || {};
  if (!isCurrentPdfRender(key, generation, resume.id)) return;
  state.resumePdfForcePageImageFallback = true;
  state.resumePdfRenderQueue = [];
  state.resumePdfPendingBackgroundPages = [];
  if (state.resumePdfBackgroundRenderTimer) {
    clearTimeout(state.resumePdfBackgroundRenderTimer);
    state.resumePdfBackgroundRenderTimer = null;
  }
  state.resumePdfRenderTasks.forEach((task) => {
    try {
      task.cancel();
    } catch (error) {
      console.debug("resume pdf fallback cancel failed", error);
    }
  });
  state.resumePdfRenderTasks.clear();
  const preview = $("resumePreview");
  const frames = Array.from(preview?.querySelectorAll("[data-pdfjs-frame-page]") || []);
  frames.forEach((frame) => {
    const pageNumber = Number(frame.dataset.pdfjsFramePage || 0);
    if (!Number.isFinite(pageNumber) || pageNumber < 1) return;
    if (state.resumePdfRenderedPages.has(pageNumber)) return;
    renderPdfjsPageFallback(pageNumber, context, key, generation);
  });
}
function pdfjsPageRenderTimeoutMs(pageNumber) {
  return pageNumber <= RESUME_PDFJS_INITIAL_PAGE_RENDER_COUNT ? RESUME_PDFJS_INITIAL_PAGE_RENDER_TIMEOUT_MS : RESUME_PDFJS_PAGE_RENDER_TIMEOUT_MS;
}
async function waitForPdfjsRenderTask(renderTask, pageNumber) {
  let timeoutId = null;
  const timeoutMs = pdfjsPageRenderTimeoutMs(pageNumber);
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      const error = new Error("resume_pdfjs_page_render_timeout");
      error.name = "ResumePdfjsPageRenderTimeout";
      error.pageNumber = pageNumber;
      error.timeoutMs = timeoutMs;
      reject(error);
    }, timeoutMs);
  });
  try {
    return await Promise.race([renderTask.promise, timeout]);
  } catch (error) {
    if (isPdfjsRenderTimeout(error)) {
      try {
        renderTask.cancel();
      } catch (cancelError) {
        console.debug("resume pdf timeout cancel failed", cancelError);
      }
    }
    throw error;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}
async function renderPdfjsPage(pageNumber, context, key, generation) {
  const resume = context?.resume || {};
  const pdfDocument = state.resumePdfDocument;
  if (
    !Number.isFinite(pageNumber) ||
    pageNumber < 1 ||
    !pdfDocument ||
    pageNumber > (pdfDocument.numPages || 0) ||
    state.resumePdfRequestedPages.has(pageNumber) ||
    !isCurrentPdfRender(key, generation, resume.id)
  ) {
    return;
  }
  state.resumePdfRequestedPages.add(pageNumber);
  if (state.resumePdfForcePageImageFallback) {
    renderPdfjsPageFallback(pageNumber, context, key, generation);
    return;
  }
  const preview = $("resumePreview");
  const frame = preview?.querySelector(`[data-pdfjs-frame-page="${pageNumber}"]`);
  if (frame) frame.classList.add("resume-pdfjs-page--loading");
  try {
    const pdfPage = await pdfDocument.getPage(pageNumber);
    if (!isCurrentPdfRender(key, generation, resume.id)) return;
    const baseViewport = pdfPage.getViewport({ scale: 1 });
    const frameWidth = frame?.clientWidth || Math.min(preview?.clientWidth || 920, 920);
    const pixelRatio = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
    const scale = Math.min(
      RESUME_PDFJS_RENDER_SCALE_MAX,
      Math.max(1, (frameWidth * pixelRatio) / Math.max(baseViewport.width, 1)),
    );
    const viewport = pdfPage.getViewport({ scale });
    const offscreenCanvas = document.createElement("canvas");
    offscreenCanvas.width = Math.ceil(viewport.width);
    offscreenCanvas.height = Math.ceil(viewport.height);
    offscreenCanvas.className = "resume-pdfjs-page-canvas";
    offscreenCanvas.dataset.previewPage = String(pageNumber);
    offscreenCanvas.setAttribute(
      "aria-label",
      `${resumeName(resume)} resume page ${pageNumber}`,
    );
    const canvasContext = offscreenCanvas.getContext("2d", { alpha: false });
    if (!canvasContext) throw new Error("resume_pdf_canvas_context_unavailable");
    const renderTask = pdfPage.render({ canvasContext, viewport });
    state.resumePdfRenderTasks.set(pageNumber, renderTask);
    await waitForPdfjsRenderTask(renderTask, pageNumber);
    state.resumePdfRenderTasks.delete(pageNumber);
    if (!isCurrentPdfRender(key, generation, resume.id)) return;
    if (frame) {
      frame.innerHTML = "";
      frame.appendChild(offscreenCanvas);
      frame.classList.remove("resume-pdfjs-page--loading");
      frame.classList.add("resume-pdfjs-page--loaded");
    }
    state.resumePdfRenderedPages.add(pageNumber);
  } catch (error) {
    state.resumePdfRenderTasks.delete(pageNumber);
    if (isPdfjsRenderCancel(error)) return;
    if (isPdfjsRenderTimeout(error) && pageNumber <= RESUME_PDFJS_INITIAL_PAGE_RENDER_COUNT) {
      console.debug("resume pdfjs initial page timed out; falling back to page images", pageNumber, error);
      fallbackRemainingPdfjsPages(context, key, generation);
      return;
    }
    console.debug("resume pdfjs page failed; falling back to page image", pageNumber, error);
    renderPdfjsPageFallback(pageNumber, context, key, generation);
  }
}
function isPdfjsRenderCancel(error) {
  return (
    error?.name === "RenderingCancelledException" ||
    String(error?.message || "").toLowerCase().includes("rendering cancelled")
  );
}
function isPdfjsRenderTimeout(error) {
  return error?.name === "ResumePdfjsPageRenderTimeout" || error?.message === "resume_pdfjs_page_render_timeout";
}
function fallbackPdfjsPreview(context, error, generation) {
  if (generation !== state.resumePdfRenderGeneration) return;
  console.debug("resume pdfjs preview failed; falling back to preview images", error);
  cancelResumePdfRendering();
  renderResumePreviewImageFallback(context);
}
function renderPreviewPageStackLegacy(resume, pages) {
  return `
    <div class="resume-page-stack" data-page-count="${pages.length}">
      ${pages
        .map(
          (page) => `
            <img
              class="resume-page-image"
              data-preview-page="${escapeHtml(String(page.page))}"
              alt="${escapeHtml(resumeName(resume))} 简历第 ${escapeHtml(String(page.page))} 页"
              src="${escapeHtml(page.imageUrl)}"
            />
          `,
        )
        .join("")}
    </div>
  `;
}
function renderPreviewPageStack(resume, pages) {
  return `
    <div class="resume-page-stack" data-page-count="${pages.length}">
      ${pages
        .map((page) => {
          const pageNumber = Number(page.page || 1);
          const eager = shouldEagerLoadPreviewPage(page);
          const imageUrl = escapeHtml(page.imageUrl);
          const sourceAttribute = eager
            ? `src="${imageUrl}"`
            : `data-preview-page-src="${imageUrl}"`;
          return `
            <div class="resume-page-frame" data-preview-frame-page="${escapeHtml(String(pageNumber))}">
              <img
                class="resume-page-image${eager ? "" : " resume-page-image--pending"}"
                data-preview-page="${escapeHtml(String(pageNumber))}"
                alt="${escapeHtml(resumeName(resume))} resume page ${escapeHtml(String(pageNumber))}"
                loading="${eager ? "eager" : "lazy"}"
                decoding="async"
                ${sourceAttribute}
              />
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}
function shouldEagerLoadPreviewPage(page) {
  return Number(page?.page || page || 0) <= RESUME_PREVIEW_INITIAL_PAGE_LOAD_COUNT;
}
function disconnectResumePreviewPageObserver() {
  if (!state.resumePreviewPageObserver) return;
  state.resumePreviewPageObserver.disconnect();
  state.resumePreviewPageObserver = null;
}
function loadPreviewPageImage(image) {
  if (!image || !image.dataset.previewPageSrc) return;
  image.src = image.dataset.previewPageSrc;
  image.removeAttribute("data-preview-page-src");
  image.classList.remove("resume-page-image--pending");
}
function observeResumePreviewPages() {
  disconnectResumePreviewPageObserver();
  const preview = $("resumePreview");
  if (!preview) return;
  const frames = Array.from(preview.querySelectorAll("[data-preview-frame-page]"));
  if (!frames.length) return;
  if (!("IntersectionObserver" in window)) {
    preview.querySelectorAll("[data-preview-page-src]").forEach(loadPreviewPageImage);
    return;
  }
  state.resumePreviewPageObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const frame = entry.target;
        const pageNumber = Number(frame.dataset.previewFramePage || 0);
        loadPreviewPageImage(frame.querySelector("[data-preview-page-src]"));
        const nextFrame = preview.querySelector(`[data-preview-frame-page="${pageNumber + 1}"]`);
        const nextImage = nextFrame?.querySelector("[data-preview-page-src]");
        loadPreviewPageImage(nextImage);
      });
    },
    { root: preview, rootMargin: RESUME_PREVIEW_NEXT_PAGE_ROOT_MARGIN, threshold: 0.01 },
  );
  frames.forEach((frame) => state.resumePreviewPageObserver.observe(frame));
}
async function loadResumePreviewPages(context) {
  const resume = context?.resume || {};
  const resumeId = resume.id || "";
  const pagesUrl = contextPreviewPagesUrl(context);
  if (!resumeId || !pagesUrl) return;
  if (state.resumePreviewPagesCache.has(pagesUrl)) {
    const pages = state.resumePreviewPagesCache.get(pagesUrl);
    if (state.selectedId !== resumeId || !state.context?.file) return;
    state.context.file.previewPages = pages;
    renderResumePreviewImageFallback(state.context);
    return;
  }
  const requestKey = `${resumeId}:${pagesUrl}`;
  if (state.resumePreviewPagesRequestKey === requestKey) return;
  if (state.resumePreviewPagesAbortController) {
    state.resumePreviewPagesAbortController.abort();
    state.resumePreviewPagesAbortController = null;
  }
  state.resumePreviewPagesRequestKey = requestKey;
  const requestSequence = (state.resumePreviewPagesRequestSequence += 1);
  const controller = new AbortController();
  state.resumePreviewPagesAbortController = controller;
  try {
    const data = await api(pagesUrl, { signal: controller.signal });
    if (requestSequence !== state.resumePreviewPagesRequestSequence) return;
    if (state.selectedId !== resumeId || !state.context?.file) return;
    const pages = Array.isArray(data.pages)
      ? data.pages
          .map((page, index) => ({
            page: Number(page.page || index + 1),
            imageUrl: String(page.imageUrl || page.image_url || "").trim(),
          }))
          .filter((page) => page.imageUrl)
      : [];
    if (!pages.length) return;
    state.resumePreviewPagesCache.set(pagesUrl, pages);
    state.context.file.previewPages = pages;
    state.context.file.previewPageCount = data.pageCount || pages.length;
    renderResumePreviewImageFallback(state.context);
  } catch (error) {
    if (error?.name === "AbortError") return;
    console.debug("resume preview pages failed", error);
  } finally {
    if (state.resumePreviewPagesAbortController === controller) {
      state.resumePreviewPagesAbortController = null;
      state.resumePreviewPagesRequestKey = "";
    }
  }
}
function renderResumePreview(context) {
  const resume = context?.resume || {};
  const file = context?.file || {};
  if (file.available && resumePreviewPdfUrl(resume, file) && renderPdfjsPreview(context)) {
    return;
  }
  renderResumePreviewImageFallback(context);
}
function renderResumePreviewImageFallback(context) {
  const resume = context.resume;
  const file = context.file || {};
  const preview = $("resumePreview");
  if (!preview) return;
  disconnectResumePreviewPageObserver();
  const pages = normalizedPreviewPages(context);
  if (file.available && pages.length) {
    preview.className = "resume-preview image-preview";
    preview.innerHTML = `
      <div class="resume-image-stage">
        <a href="${escapeHtml(file.downloadUrl || '/api/resumes/' + resume.id + '/download')}" download class="resume-download-link" title="点击下载简历PDF">
          ${renderPreviewPageStack(resume, pages)}
        </a>
      </div>
    `;
    observeResumePreviewPages();
    if (!Array.isArray(file.previewPages) || !file.previewPages.length) {
      loadResumePreviewPages(context).catch((error) => {
        if (error?.name !== "AbortError") console.debug("resume preview pages failed", error);
      });
    }
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
  const memberDecisionMarkup = memberDecisionSummaryMarkup(resume);
  const reviewerDecisionTimeline = reviewerDecisionTimelineMarkup(resume);
  $("summaryCards").innerHTML = `
    <div class="summary-card ts-summary-card"><h3>候选人</h3>
      <p>姓名：${escapeHtml(resumeName(resume))}</p><p>岗位：${escapeHtml(resumeJob(resume))}</p>
      <p>电话：${escapeHtml(resume.phone || "")}</p><p>学历：${escapeHtml(resumeEducationLine(resume))}${schoolTierMarkup}</p>
      <p>入库时间：${escapeHtml(resumeImportTime(resume))}</p>${reviewerDecisionTimeline}</div>
    <div class="summary-card ts-summary-card"><h3>评分</h3>
      <p>分数：${escapeHtml(context.score?.value ?? "暂无")}</p><p>等级：${escapeHtml(context.score?.grade || "暂无")}</p></div>
    ${memberDecisionMarkup}
  `;
  renderActionDock();
}
async function setDecision(id, decision) {
  const reasonTags = { suitable: ["岗位匹配"], unsuitable: ["暂不匹配"], needs_more_info: ["信息待补充"] }[decision] || [];
  const result = await api(`/api/resumes/${id}/review-decision`, { method: "POST", body: JSON.stringify({ decision, reasonTags, note: "" }) });
  await clearResumePrefetchCacheAfterMutation();
  await advanceAfterReviewAction(id);
  if (result?.completedAssignment && isAdminUser()) await refreshQueueSummary();
}
async function pushSelectedResumeToAdmin() {
  if (!state.selectedId || selectedResumePushedToAdmin()) return;
  if (!window.confirm("是否推送给管理员")) return;
  const id = state.selectedId;
  await api(`/api/resumes/${id}/push-to-admin`, { method: "POST", body: JSON.stringify({ note: "" }) });
  await clearResumePrefetchCacheAfterMutation();
  await loadResumes();
  if (state.resumes.some((resume) => resume.id === id)) await openResume(id);
  renderActionDock();
}
async function advanceAfterReviewAction(id) {
  const currentIndex = state.resumes.findIndex((resume) => resume.id === id);
  if (state.tab === "queue") {
    await loadQueue();
    const next = state.resumes[Math.max(0, Math.min(currentIndex, state.resumes.length - 1))];
    if (next) {
      await openResume(next.id);
      return;
    }
    closeResumeConversation({ immediate: true });
    state.selectedId = "";
    state.context = null;
    $("previewTitle").textContent = "当前没有待你处理的简历";
    $("resumePreview").textContent = "共享待处理池已经处理完成。";
    $("summaryCards").innerHTML = `<p class="muted">当前没有待你处理的简历。</p>`;
    renderActionDock();
    return;
  }
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
    closeResumeConversation({ immediate: true });
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
function toInterviewDateValue(date) {
  const value = new Date(date);
  if (Number.isNaN(value.getTime())) return "";
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
function setDefaultInterviewDateRange() {
  if (state.interviewDateStart && state.interviewDateEnd) return;
  const start = new Date();
  start.setDate(start.getDate() - 1);
  const end = new Date();
  end.setDate(end.getDate() + 14);
  state.interviewDateStart = toInterviewDateValue(start);
  state.interviewDateEnd = toInterviewDateValue(end);
  if ($("interviewDateStart")) $("interviewDateStart").value = state.interviewDateStart;
  if ($("interviewDateEnd")) $("interviewDateEnd").value = state.interviewDateEnd;
}
function interviewDateRangeParams() {
  setDefaultInterviewDateRange();
  const query = new URLSearchParams();
  const start = state.interviewDateStart ? new Date(`${state.interviewDateStart}T00:00:00`) : null;
  const end = state.interviewDateEnd ? new Date(`${state.interviewDateEnd}T23:59:59`) : null;
  if (start && !Number.isNaN(start.getTime())) query.set("startTime", String(Math.floor(start.getTime() / 1000)));
  if (end && !Number.isNaN(end.getTime())) query.set("endTime", String(Math.floor(end.getTime() / 1000)));
  if (state.interviewStatusFilter) query.set("status", state.interviewStatusFilter);
  return query.toString();
}
function formatInterviewTime(seconds) {
  const value = Number(seconds || 0);
  if (!value) return "未排期";
  return new Date(value * 1000).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function interviewStatusLabel(value) {
  return INTERVIEW_STATUS_LABELS[value] || value || "未识别";
}
function interviewStatusClass(value) {
  if (["prepared", "completed", "matched", "questions_generated"].includes(value)) return "success";
  if (["backfill_failed", "non_interview", "ignored"].includes(value)) return "danger";
  if (["needs_match", "needs_confirmation", "needs_review", "prepared_local"].includes(value)) return "warning";
  return "";
}
function selectedInterviewSession() {
  return state.interviewSessions.find((item) => item.id === state.selectedInterviewId) || null;
}
function updateInterviewButtons() {
  const session = selectedInterviewSession();
  const busy = state.interviewBusy;
  const docUrl = session?.feishuDoc?.url || "";
  if ($("generateQuestionsBtn")) $("generateQuestionsBtn").disabled = busy || !session;
  if ($("backfillBtn")) $("backfillBtn").disabled = busy || !session;
  if ($("openInterviewDocBtn")) $("openInterviewDocBtn").disabled = busy || !docUrl;
  if ($("interviewRefreshBtn")) $("interviewRefreshBtn").disabled = busy;
  if ($("syncFeishuBtn")) $("syncFeishuBtn").disabled = busy;
}
function setInterviewMessage(text, tone = "") {
  if (!$("interviewSyncPill")) return;
  $("interviewSyncPill").textContent = text;
  $("interviewSyncPill").className = ["safety-pill", tone].filter(Boolean).join(" ");
}
function renderInterviewStatus() {
  const status = state.interviewStatus || {};
  const sync = state.interviewSyncStatus || {};
  const connected = Boolean(status.connected);
  if ($("interviewConnectionPill")) {
    $("interviewConnectionPill").textContent = connected ? "飞书已连接" : "飞书未连接";
    $("interviewConnectionPill").className = `safety-pill ${connected ? "safe" : "live"}`;
  }
  if ($("interviewSyncPill")) {
    const total = sync.lastResult?.interviewLike ?? sync.lastResult?.total ?? 0;
    const label = sync.lastRunAt ? `最近同步 ${total} 场` : "尚未同步";
    $("interviewSyncPill").textContent = sync.running ? "同步中" : label;
    $("interviewSyncPill").className = `safety-pill ${sync.lastError ? "live" : "safe"}`;
  }
}
function renderInterviewSessions() {
  const items = state.interviewSessions || [];
  const target = $("interviewSessions");
  if (!target) return;
  if (!items.length) {
    target.innerHTML = `<div class="empty-inline ts-empty-state">当前日期范围内暂无面试会话。</div>`;
    return;
  }
  target.innerHTML = items.map((item) => {
    const statusClass = interviewStatusClass(item.status);
    const flow = item.interviewFlow || {};
    return `
      <button class="candidate-card ts-interview-session-card ${item.id === state.selectedInterviewId ? "active" : ""}" data-open-interview-session="${escapeHtml(item.id)}">
        <span class="candidate-card__heading">
          <strong>${escapeHtml(item.candidateName || "未命名候选人")}</strong>
          <span class="${tsTagClass(statusClass === "success" ? "suitable" : statusClass === "danger" ? "unsuitable" : statusClass === "warning" ? "needs_more_info" : "")}">${escapeHtml(interviewStatusLabel(item.status))}</span>
        </span>
        <span class="candidate-card__job">${escapeHtml(item.jobType || item.position || "未识别岗位")}</span>
        <span class="candidate-card__meta">
          <span class="candidate-card__meta-item">${escapeHtml(formatInterviewTime(item.startTime))}</span>
          <span class="candidate-card__meta-item">${escapeHtml(flow.roundLabel || "面试")}</span>
          <span class="candidate-card__meta-item">${escapeHtml(item.bitableTableName || "未路由表")}</span>
        </span>
      </button>
    `;
  }).join("");
}
function updateInterviewSession(nextSession) {
  if (!nextSession?.id) return;
  const index = state.interviewSessions.findIndex((item) => item.id === nextSession.id);
  if (index >= 0) state.interviewSessions[index] = nextSession;
  else state.interviewSessions.unshift(nextSession);
  state.selectedInterviewId = nextSession.id;
}
async function loadInterviewSyncStatus() {
  const sync = await api("/api/interview-center/sync/status");
  state.interviewSyncStatus = sync;
  renderInterviewStatus();
}
async function loadInterviewSessions(options = {}) {
  setDefaultInterviewDateRange();
  if ($("interviewStatusFilter")) $("interviewStatusFilter").value = state.interviewStatusFilter;
  const suffix = interviewDateRangeParams();
  try {
    const data = await api(`/api/interview-center/sessions${suffix ? `?${suffix}` : ""}`);
    state.interviewStatus = data.status || null;
    state.interviewLogs = data.logs || [];
    state.interviewSessions = data.items || data.sessions || [];
    if (!options.keepSelection || !state.interviewSessions.some((item) => item.id === state.selectedInterviewId)) {
      state.selectedInterviewId = state.interviewSessions[0]?.id || "";
    }
    renderInterviewStatus();
    renderInterviewSessions();
    await loadInterviewSyncStatus().catch(() => {});
  } catch (error) {
    $("interviewSessions").innerHTML = `<div class="empty-inline">面试会话读取失败：${escapeHtml(error.message)}</div>`;
    setInterviewMessage("读取失败", "live");
  }
  renderInterviewDetail();
}
async function openInterviewSession(sessionId) {
  if (!sessionId) return;
  state.interviewSelection = null;
  state.selectedInterviewId = sessionId;
  renderInterviewSessions();
  renderInterviewDetail();
  try {
    const payload = await api(`/api/interview-center/sessions/${encodeURIComponent(sessionId)}`);
    updateInterviewSession(payload.session);
    renderInterviewSessions();
    renderInterviewDetail();
  } catch (error) {
    setInterviewMessage(error.message || "详情读取失败", "live");
  }
}
async function runInterviewAction(label, task) {
  try {
    state.interviewBusy = true;
    setInterviewMessage(label, "");
    updateInterviewButtons();
    const payload = await task();
    if (payload?.session) updateInterviewSession(payload.session);
    if (payload?.sessions || payload?.items) state.interviewSessions = payload.items || payload.sessions || state.interviewSessions;
    if (payload?.logs) state.interviewLogs = payload.logs;
    await loadInterviewSyncStatus().catch(() => {});
    renderInterviewSessions();
    renderInterviewDetail();
    setInterviewMessage("操作完成", "safe");
  } catch (error) {
    setInterviewMessage(error.message || "操作失败", "live");
  } finally {
    state.interviewBusy = false;
    updateInterviewButtons();
  }
}
async function syncInterviewCalendar() {
  await runInterviewAction("正在同步飞书日历", async () => {
    const payload = await api("/api/interview-center/sync", { method: "POST", body: JSON.stringify({ autoPrepare: false }) });
    await loadInterviewSessions({ keepSelection: true });
    return payload;
  });
}
async function prepareSelectedInterview() {
  const session = selectedInterviewSession();
  if (!session) return;
  await runInterviewAction("正在准备面试", () =>
    api(`/api/interview-center/sessions/${encodeURIComponent(session.id)}/prepare`, {
      method: "POST",
      body: JSON.stringify({ force: true }),
    }),
  );
}
async function backfillSelectedInterview() {
  const session = selectedInterviewSession();
  if (!session) return;
  await runInterviewAction("正在回填面试评价", () =>
    api(`/api/interview-center/sessions/${encodeURIComponent(session.id)}/backfill`, {
      method: "POST",
      body: JSON.stringify({ force: true }),
    }),
  );
}
function openSelectedInterviewDoc() {
  const url = selectedInterviewSession()?.feishuDoc?.url;
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}
function renderInterviewDetail() {
  const target = $("interviewDetail");
  if (!target) return;
  if (state.interviewSelection) {
    const selected = state.interviewSelection;
    const resume = selected.resume || {};
    $("interviewWorkspaceTitle").textContent = resumeName(resume);
    target.innerHTML = `
      <section class="ts-interview-hero">
        <div>
          <p class="eyebrow">Invite Preflight</p>
          <h2>${escapeHtml(resumeName(resume))}</h2>
          <p>${escapeHtml(resumeJob(resume))} · ${escapeHtml(platformName(resumePlatform(resume)))} / ${escapeHtml(resumeOwner(resume))}</p>
        </div>
        <span class="badge warning">待确认</span>
      </section>
      ${renderInterviewPreflight(selected)}
    `;
    bindInterviewDetailActions();
    updateInterviewButtons();
    return;
  }
  const session = selectedInterviewSession();
  updateInterviewButtons();
  if (!session) {
    $("interviewWorkspaceTitle").textContent = "请选择面试会话";
    target.innerHTML = `<div class="ts-empty-state">从左侧选择面试会话，或在简历库点击“约面试”。</div>`;
    return;
  }
  const evaluation = session.interviewEvaluation || {};
  const docUrl = session.feishuDoc?.url || "";
  $("interviewWorkspaceTitle").textContent = session.candidateName || "未命名候选人";
  target.innerHTML = `
    <section class="ts-interview-hero">
      <div>
        <p class="eyebrow">Interview Workspace</p>
        <h2>${escapeHtml(session.candidateName || "未命名候选人")}</h2>
        <p>${escapeHtml(session.jobType || "未识别岗位")} · ${escapeHtml(formatInterviewTime(session.startTime))}</p>
      </div>
      <span class="${tsTagClass(interviewStatusClass(session.status) === "success" ? "suitable" : interviewStatusClass(session.status) === "danger" ? "unsuitable" : "needs_more_info")}">${escapeHtml(interviewStatusLabel(session.status))}</span>
    </section>
    <div class="ts-interview-detail-grid">
      <section class="ts-interview-info-card">
        <h3>会话信息</h3>
        <dl>
          <div><dt>阶段</dt><dd>${escapeHtml(session.interviewFlow?.stageText || session.currentStage || "未识别")}</dd></div>
          <div><dt>候选表</dt><dd>${escapeHtml(session.bitableTableName || "未路由")}</dd></div>
          <div><dt>日程 ID</dt><dd>${escapeHtml(session.feishuEventId || "-")}</dd></div>
          <div><dt>飞书文档</dt><dd>${docUrl ? "已创建" : "未创建"}</dd></div>
        </dl>
      </section>
      <section class="ts-interview-info-card">
        <h3>下一步</h3>
        <p>${escapeHtml(session.nextAction || nextInterviewAction(session))}</p>
      </section>
      <section class="ts-interview-info-card ts-interview-info-card--wide">
        <h3>面试题</h3>
        ${renderInterviewQuestions(session)}
      </section>
      <section class="ts-interview-info-card ts-interview-info-card--wide">
        <h3>评价回填</h3>
        ${renderInterviewEvaluation(evaluation, session)}
      </section>
    </div>
  `;
}
function bindInterviewDetailActions() {
  document.querySelector("[data-confirm-interview]")?.addEventListener("click", confirmInterviewInvite);
  document.querySelectorAll("[data-select-interview-session]").forEach((button) => {
    button.addEventListener("click", () => selectInterviewSession(button.dataset.selectInterviewSession || ""));
  });
}
function nextInterviewAction(session) {
  if (!session.resumeId) return "先确认候选人匹配，再准备面试材料。";
  if (!session.feishuDoc?.url) return "准备面试题并创建飞书文档。";
  if (!session.interviewEvaluation?.summary) return "面试结束后读取飞书纪要并回填评价。";
  if (session.status === "needs_review") return "人工复核评价并确认结果。";
  return "当前会话已具备主要材料，可继续跟进候选人。";
}
function renderInterviewQuestions(session) {
  const questions = session.questions || session.questionSet?.questions || [];
  if (!questions.length) return `<p class="muted">尚未生成面试题。</p>`;
  return `<ol class="ts-interview-question-list">${questions.slice(0, 6).map((item) => `<li>${escapeHtml(item.question || item.title || item.text || item)}</li>`).join("")}</ol>`;
}
function renderInterviewEvaluation(evaluation, session) {
  if (!evaluation || !Object.keys(evaluation).length) {
    return `<p class="muted">${escapeHtml(session.lastBackfillError || "尚未回填面试评价。")}</p>`;
  }
  return `
    <div class="ts-interview-evaluation">
      <p>${escapeHtml(evaluation.summary || "已有评价，等待复核。")}</p>
      ${evaluation.review?.decision ? `<span class="badge success">复核：${escapeHtml(evaluation.review.decision)}</span>` : `<span class="badge warning">待复核</span>`}
    </div>
  `;
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
function applyGlobalResumeSearch(globalSearch, { immediate = false } = {}) {
  if (state.view !== "resumes") return;
  const queryField = $("filters")?.q;
  if (!queryField) return;
  queryField.value = globalSearch.value;
  state.page = 1;
  clearResumePrefetchCache();
  if (!immediate) {
    scheduleResumeFilterRefresh();
    return;
  }
  loadResumes({ fromFilter: true }).catch((error) => {
    if (error?.name === "AbortError") return;
    console.debug("resume search refresh failed", error);
  });
}
function bindGlobalSearchToFilters() {
  const globalSearch = $("globalSearch");
  if (!globalSearch) return;
  let composing = false;
  globalSearch.addEventListener("compositionstart", () => {
    composing = true;
  });
  globalSearch.addEventListener("compositionend", () => {
    composing = false;
    applyGlobalResumeSearch(globalSearch);
  });
  globalSearch.addEventListener("input", () => {
    if (composing) return;
    applyGlobalResumeSearch(globalSearch);
  });
  globalSearch.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || composing || state.view !== "resumes") return;
    event.preventDefault();
    applyGlobalResumeSearch(globalSearch, { immediate: true });
  });
}
function applyResumeFilters() {
  state.jobType = $("filters").job_type.value.trim();
  state.page = 1;
  clearResumePrefetchCache();
  scheduleResumeFilterRefresh();
}
function scheduleResumeFilterRefresh() {
  if (state.resumeFilterDebounceTimer) clearTimeout(state.resumeFilterDebounceTimer);
  state.resumeFilterDebounceTimer = setTimeout(() => {
    state.resumeFilterDebounceTimer = null;
    loadResumes({ fromFilter: true }).catch((error) => {
      if (error?.name === "AbortError") return;
      console.debug("resume filter refresh failed", error);
    });
  }, RESUME_FILTER_DEBOUNCE_MS);
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
  $("resumePreview").addEventListener("contextmenu", handleResumePreviewContextMenu);
  $("resumeConversationCloseBtn").onclick = closeResumeConversation;
  $("resumeConversationBackdrop").onclick = closeResumeConversation;
  const reviewerDecisionPopoverRoot = $("reviewerDecisionPopoverRoot");
  reviewerDecisionPopoverRoot?.addEventListener("mouseenter", () => {
    if (reviewerDecisionPopoverHideTimer) clearTimeout(reviewerDecisionPopoverHideTimer);
  });
  reviewerDecisionPopoverRoot?.addEventListener("mouseleave", scheduleReviewerDecisionPopoverHide);
  window.addEventListener("resize", positionReviewerDecisionPopover);
  window.addEventListener("scroll", positionReviewerDecisionPopover, true);
  document.addEventListener("visibilitychange", () => {
    if (!isAdminUser()) return;
    if (document.visibilityState !== "visible") {
      if (state.queueSummaryTimer) clearTimeout(state.queueSummaryTimer);
      if (state.queueSummaryAbortController) state.queueSummaryAbortController.abort();
      state.queueSummaryTimer = null;
      return;
    }
    refreshQueueSummary().finally(() => scheduleQueueSummaryPoll());
  });
  window.addEventListener("focus", () => {
    if (!isAdminUser() || document.visibilityState !== "visible") return;
    refreshQueueSummary().finally(() => scheduleQueueSummaryPoll());
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideReviewerDecisionPopover();
    if (event.key === "Escape" && !$("resumeConversationModal").hidden) closeResumeConversation();
  });
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
  $("refreshQueueBtn").onclick = refreshQueueNow;
  $("suitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "suitable");
  $("unsuitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "unsuitable");
  $("interviewBtn").onclick = requestInterview;
  $("logoutBtn").onclick = logout;
  $("prevBtn").onclick = () => move(-1);
  $("nextBtn").onclick = () => move(1);
  bindDockEffect($("actionDock"), ".action-dock-btn", { maxScale: 1.3, radius: 110, marginFactor: 15 });
  $("interviewRefreshBtn").onclick = () => loadInterviewSessions({ keepSelection: true });
  $("syncFeishuBtn").onclick = syncInterviewCalendar;
  $("generateQuestionsBtn").onclick = prepareSelectedInterview;
  $("openInterviewDocBtn").onclick = openSelectedInterviewDoc;
  $("backfillBtn").onclick = backfillSelectedInterview;
  $("interviewApplyDateBtn").onclick = () => {
    state.interviewDateStart = $("interviewDateStart").value;
    state.interviewDateEnd = $("interviewDateEnd").value;
    loadInterviewSessions();
  };
  $("interviewStatusFilter").onchange = () => {
    state.interviewStatusFilter = $("interviewStatusFilter").value;
    loadInterviewSessions();
  };
  $("interviewSessions").addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-interview-session]");
    if (button) openInterviewSession(button.dataset.openInterviewSession || "");
  });
  bindResumeKeyboardNavigation();
}
async function afterLogin(user) {
  stopQueueSummaryPolling();
  clearResumePrefetchCache();
  state.resumeContextCache.clear();
  state.resumePreviewPagesCache.clear();
  state.user = user;
  state.jobType = "";
  state.resumeJobFacets = [];
  state.queueJobFacets = [];
  state.queueSummaryLoaded = false;
  state.queueVersion = "";
  state.queueTotal = 0;
  hrAuth.updateUserCard(user);
  hrAuth.showApp();
  setAllowedNavigation();
  setResumeMemberMode();
  const landingView = canView("resumes") ? "resumes" : uiAccess().defaultView;
  setView(landingView);
  if (canView("resumes")) await loadResumes();
  startQueueSummaryPolling();
}
async function logout() {
  stopQueueSummaryPolling();
  await api("/api/auth/logout", { method: "POST" });
  state.user = null;
  closeResumeConversation({ immediate: true });
  state.selectedId = "";
  state.context = null;
  state.jobType = "";
  state.resumeJobFacets = [];
  state.queueJobFacets = [];
  state.queueSummaryLoaded = false;
  state.queueVersion = "";
  state.queueTotal = 0;
  clearResumePrefetchCache();
  state.resumeContextCache.clear();
  state.resumePreviewPagesCache.clear();
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
