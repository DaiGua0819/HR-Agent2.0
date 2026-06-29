const state = {
  user: null,
  resumes: [],
  selectedId: "",
  context: null,
  tab: "all",
};

const tabs = [
  ["all", "全部"],
  ["unread", "未看"],
  ["viewed", "已看"],
  ["undecided", "待判断"],
  ["suitable", "合适"],
  ["unsuitable", "不合适"],
  ["needs_more_info", "待补充"],
  ["queue", "待我处理"],
];

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${text}`);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function labelDecision(value) {
  return {
    suitable: "合适",
    unsuitable: "不合适",
    needs_more_info: "待补充",
    undecided: "待判断",
  }[value || "undecided"];
}

function decisionClass(value) {
  return {
    suitable: "success",
    unsuitable: "danger",
    needs_more_info: "warning",
  }[value] || "";
}

function platformName(value) {
  return { boss: "BOSS", job51: "51job", zhilian: "智联" }[value] || value || "未知";
}

function buildTabs() {
  $("statusTabs").innerHTML = tabs
    .map(([key, label]) => `<button data-tab="${key}" class="${state.tab === key ? "active" : ""}">${label}</button>`)
    .join("");
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.tab = button.dataset.tab;
      loadResumes();
    });
  });
}

function queryFromFilters() {
  const data = new FormData($("filters"));
  const params = new URLSearchParams({ page_size: "100" });
  for (const [key, value] of data.entries()) {
    if (value) params.set(key, value);
  }
  if (state.tab === "unread") params.set("read_status", "unread");
  if (state.tab === "viewed") params.set("read_status", "viewed");
  if (["undecided", "suitable", "unsuitable", "needs_more_info"].includes(state.tab)) {
    params.set("decision", state.tab);
  }
  return params.toString();
}

async function loadUser() {
  const data = await api("/api/auth/me");
  state.user = data;
  $("userName").textContent = data.user.name;
  $("userScope").textContent = `可见：${data.resumeScope.owners.join("、")} / ${data.resumeScope.platforms.join("、")}`;
}

async function loadResumes() {
  buildTabs();
  if (state.tab === "queue") {
    const data = await api("/api/resume-review/queue");
    state.resumes = data.items.map((item) => ({ ...item.resume, assignment: item.assignment })).filter(Boolean);
  } else {
    const data = await api(`/api/resumes?${queryFromFilters()}`);
    state.resumes = data.items || [];
  }
  renderRows();
  renderMiniList();
}

function renderRows() {
  const rows = state.resumes.map((resume) => {
    const review = resume.reviewState || {};
    const name = resume.name || resume.parsedName || "未命名";
    const owner = resume.linkedOwner || resume.source_owner || resume.sourceOwner || "";
    const platform = resume.linkedPlatform || resume.source_platform || resume.sourcePlatform || "";
    return `
      <tr class="${resume.id === state.selectedId ? "active" : ""}">
        <td><strong>${escapeHtml(name)}</strong><br><span class="muted">${escapeHtml(resume.phone || "")}</span></td>
        <td>${escapeHtml(resume.job_type || resume.jobType || resume.applied_position || resume.appliedPosition || "")}</td>
        <td>${escapeHtml(platformName(platform))}</td>
        <td>${escapeHtml(owner)}</td>
        <td>${resume.match_score ?? resume.matchScore ?? ""}</td>
        <td>
          <span class="badge">${review.readStatus === "viewed" ? "已看" : "未看"}</span>
          <span class="badge ${decisionClass(review.decision)}">${labelDecision(review.decision)}</span>
        </td>
        <td>${escapeHtml((resume.updated_at || resume.updatedAt || "").slice(0, 10))}</td>
        <td>
          <button data-open="${resume.id}">查看</button>
          <button data-decision="${resume.id}:suitable">合适</button>
          <button data-decision="${resume.id}:unsuitable">不合适</button>
        </td>
      </tr>
    `;
  });
  $("resumeRows").innerHTML = rows.join("");
  $("emptyState").style.display = rows.length ? "none" : "block";
  $("emptyState").textContent = rows.length ? "" : "暂无符合条件的简历";
  bindRowActions();
}

function renderMiniList() {
  $("miniList").innerHTML = state.resumes
    .map((resume) => {
      const name = resume.name || resume.parsedName || "未命名";
      const job = resume.job_type || resume.jobType || resume.applied_position || "";
      return `
        <button class="mini-item ${resume.id === state.selectedId ? "active" : ""}" data-open="${resume.id}">
          <strong>${escapeHtml(name)}</strong>
          <small>${escapeHtml(job)}</small>
        </button>
      `;
    })
    .join("");
  bindRowActions();
}

function bindRowActions() {
  document.querySelectorAll("[data-open]").forEach((button) => {
    button.onclick = () => openResume(button.dataset.open);
  });
  document.querySelectorAll("[data-decision]").forEach((button) => {
    button.onclick = () => {
      const [id, decision] = button.dataset.decision.split(":");
      setDecision(id, decision);
    };
  });
}

async function openResume(id) {
  state.selectedId = id;
  state.context = await api(`/api/resumes/${id}/review-context`);
  renderRows();
  renderMiniList();
  renderContext();
}

function resumeText(resume) {
  const payload = resume.payload || {};
  const parts = [
    `候选人：${resume.name || resume.parsedName || "未命名"}`,
    `岗位：${resume.job_type || resume.jobType || resume.applied_position || ""}`,
    `学历：${resume.education || ""}`,
    `专业：${resume.major || ""}`,
    `电话：${resume.phone || ""}`,
    "",
    payload.rawText || payload.text || payload.summary || "当前没有解析文本。后续接入 PDF 预览后，这里会显示固定高度的简历页视图。",
  ];
  return parts.join("\n");
}

function renderContext() {
  const context = state.context;
  if (!context) return;
  const resume = context.resume;
  const review = context.reviewState || {};
  $("previewTitle").textContent = `${resume.name || resume.parsedName || "未命名"} · ${resume.job_type || resume.applied_position || ""}`;
  $("resumePreview").textContent = resumeText(resume);
  $("summaryContent").innerHTML = `
    <div class="summary-card">
      <h3>候选人</h3>
      <p>姓名：${escapeHtml(resume.name || resume.parsedName || "未命名")}</p>
      <p>岗位：${escapeHtml(resume.job_type || resume.applied_position || "")}</p>
      <p>电话：${escapeHtml(resume.phone || "")}</p>
      <p>学历：${escapeHtml(resume.education || "")}</p>
    </div>
    <div class="summary-card">
      <h3>评分</h3>
      <p>分数：${context.score.value ?? "暂无"}</p>
      <p>等级：${context.score.grade || "暂无"}</p>
    </div>
    <div class="summary-card">
      <h3>来源</h3>
      <p>平台：${escapeHtml(platformName(context.conversation.platform))}</p>
      <p>负责人：${escapeHtml(context.conversation.owner || "")}</p>
      <p>会话：${escapeHtml(context.conversation.sessionId || "未桥接")}</p>
    </div>
    <div class="summary-card">
      <h3>审阅</h3>
      <p>查看：${review.readStatus === "viewed" ? "已看" : "未看"}</p>
      <p>判断：${labelDecision(review.decision)}</p>
      <p>备注：${escapeHtml(review.note || "暂无")}</p>
    </div>
  `;
}

async function setDecision(id, decision) {
  const reasonTags = {
    suitable: ["岗位匹配"],
    unsuitable: ["暂不匹配"],
    needs_more_info: ["信息待补充"],
  }[decision] || [];
  await api(`/api/resumes/${id}/review-decision`, {
    method: "POST",
    body: JSON.stringify({ decision, reasonTags, note: "" }),
  });
  await loadResumes();
  const index = state.resumes.findIndex((resume) => resume.id === id);
  const next = state.resumes[index + 1] || state.resumes[index] || state.resumes[0];
  if (next) await openResume(next.id);
}

function move(offset) {
  if (!state.resumes.length) return;
  const index = Math.max(0, state.resumes.findIndex((resume) => resume.id === state.selectedId));
  const next = state.resumes[Math.min(state.resumes.length - 1, Math.max(0, index + offset))];
  if (next) openResume(next.id);
}

function bindPageActions() {
  $("filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadResumes();
  });
  $("viewedBtn").onclick = () => state.selectedId && openResume(state.selectedId);
  $("suitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "suitable");
  $("unsuitableBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "unsuitable");
  $("moreInfoBtn").onclick = () => state.selectedId && setDecision(state.selectedId, "needs_more_info");
  $("prevBtn").onclick = () => move(-1);
  $("nextBtn").onclick = () => move(1);
  document.querySelectorAll(".nav button").forEach((button) => {
    button.onclick = () => {
      document.querySelectorAll(".nav button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      if (button.dataset.view === "queue") state.tab = "queue";
      if (button.dataset.view === "suitable") state.tab = "suitable";
      if (button.dataset.view === "archive") state.tab = "unsuitable";
      loadResumes();
    };
  });
}

async function init() {
  bindPageActions();
  buildTabs();
  await loadUser();
  await loadResumes();
}

init().catch((error) => {
  $("emptyState").style.display = "block";
  $("emptyState").textContent = `加载失败：${error.message}`;
});
