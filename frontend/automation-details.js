const detailsState = {
  page: 1,
  pages: 1,
  loading: false,
};

const metricLabels = {
  processedContacts: "处理联系人",
  sentCompanyInfo: "发送公司信息",
  requestedResume: "发起求简历",
  candidateQuestions: "候选人提问",
  knowledgeAnswered: "知识库已回复",
  businessResumeAcquisitions: "业务简历获取",
  anomalies: "异常",
};
const actionLabels = {
  process: "处理消息",
  ask: "发送问题",
  ask_question: "发送问题",
  ask_screening: "发送筛选问题",
  ask_basic_conditions: "发送基础条件",
  send_screening_question: "发送筛选问题",
  send_company_info: "发送公司信息",
  answer_question: "回复问题",
  request_resume: "求简历",
  request_resume_failed: "求简历失败",
  interview_invite: "邀请面试",
  proactive_greet: "主动沟通",
  reject: "判定不合适",
  escalate: "转人工处理",
  send_failed: "发送失败",
  skip: "跳过",
  wait: "等待候选人",
};
const stageLabels = {
  candidate_closing: "候选人结束沟通",
  candidate_policy_reject: "候选人不符合岗位要求",
  silent_question: "问题无需自动回复",
  unknown_question: "问题未命中知识库",
  knowledge_hit: "知识库已回复",
  resume_consent_requested: "已请求简历授权",
  direct_resume: "已直接求取简历",
  basic_accept: "基础条件通过",
  basic_reject: "基础条件不通过",
  basic_unclear: "基础条件待确认",
  basic_phrase_missing: "基础条件话术缺失",
  basic_phrase_send_failed: "基础条件发送失败",
  basic_phrase_sent: "已发送基础条件",
  no_screening_questions: "未配置筛选问题",
  no_screening_question_text: "筛选问题内容缺失",
  screening_question_send_failed: "筛选问题发送失败",
  screening_question_sent: "已发送筛选问题",
  screening_accept: "岗位筛选通过",
  screening_reject: "岗位筛选不通过",
  screening_unclear: "岗位筛选结果待确认",
  screening_waiting: "等待筛选回复",
  resume_already_downloaded: "简历已下载",
  resume_attachment_downloaded: "附件简历已下载",
  resume_attachment_download_blocked: "附件简历下载受阻",
  resume_attachment_received: "已收到附件简历",
  resume_already_requested: "已求取简历",
  candidate_unavailable: "候选人当前不可操作",
  request_resume_action_failed: "求简历失败",
  request_confirmed: "求简历已确认",
  open_thread_failed: "打开候选人会话失败",
  candidate_timeout: "候选人处理超时",
  stale_resume_overlay_not_closed: "简历窗口未正常关闭",
  candidate_rejected: "候选人判定不合适",
  direct_resume_prompt_send_failed: "求简历话术发送失败",
  ignored_position: "岗位已跳过",
  last_message_not_candidate: "最后消息非候选人发送",
  unconfigured_position: "岗位未配置",
  handled: "处理完成",
  completed: "处理完成",
};
const anomalyReasonLabels = {
  basic_phrase_send_failed: "基础条件发送失败",
  knowledge_answer_send_failed: "知识库回复发送失败",
  direct_resume_prompt_send_failed: "求简历话术发送失败",
  screening_question_send_failed: "筛选问题发送失败",
  resume_request_unhandled: "求简历操作未完成",
  online_resume_not_exportable_attachment_request_unavailable: "在线简历无法导出",
  online_resume_button_not_found: "未找到在线简历按钮",
  online_resume_save_icon_not_found: "未找到在线简历保存按钮",
  online_resume_preview_not_verified: "在线简历预览校验失败",
  attachment_button_not_found: "未找到附件简历按钮",
  view_attachment_button_not_found: "未找到查看附件按钮",
  invalid_download_url: "简历下载地址无效",
  fetch_failed: "简历文件获取失败",
  invalid_resume_signature: "下载文件不是有效简历",
  confirm_button_not_visible: "确认按钮不可见",
  confirm_button_not_found: "未找到确认按钮",
  request_resume_button_not_found: "未找到求简历按钮",
  request_resume_confirm_not_found: "未找到求简历确认按钮",
  request_resume_confirm_prompt_not_visible: "求简历确认窗口不可见",
  resume_consent_button_not_found: "未找到简历授权按钮",
  boss_candidate_frozen: "候选人会话已冻结",
  candidate_identity_mismatch: "候选人身份校验不一致",
  thread_identity_fields_missing: "候选人身份信息缺失",
  thread_identity_not_found: "未找到候选人身份信息",
  thread_identity_low_confidence: "候选人身份匹配置信度过低",
  thread_identity_ambiguous: "候选人身份存在歧义",
  unread_filter_not_found: "未找到未读筛选入口",
  unread_list_not_found: "未找到未读联系人列表",
  platform_page_missing: "平台页面未打开",
  login_required: "账号需要重新登录",
  security_verification: "平台要求安全验证",
  account_abnormal: "平台账号状态异常",
  download_error: "简历下载失败",
  timeout: "操作超时",
  send_failed: "消息发送失败",
  request_resume_failed: "求简历失败",
  request_resume_action_failed: "求简历操作失败",
  resume_consent_accept_failed: "简历授权确认失败",
  resume_request_button_failed: "求简历按钮操作失败",
  resume_attachment_download_blocked: "附件简历下载受阻",
  unconfigured_position: "岗位未配置",
  escalate: "已转人工处理",
  unknown_question: "问题未命中知识库",
};
const resumeHandlingLabels = {
  boss_request_verified_server_imap: "已求简历，等待服务器邮箱入库",
  local_resume_downloaded: "简历已下载并入库",
  resume_requested_waiting: "已求简历，等待候选人发送",
};

function stageLabel(value) {
  if (!value) return "未记录阶段";
  return stageLabels[value] || "其他阶段";
}

function actionLabel(value) {
  if (!value) return "未记录动作";
  return actionLabels[value] || "其他动作";
}

function anomalyReasonLabel(value) {
  if (!value) return "异常原因未记录";
  return String(value).split(";")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => anomalyReasonLabels[item] || "其他异常")
    .join("；");
}

function resumeHandlingLabel(value) {
  if (!value) return "未发生简历处理";
  return resumeHandlingLabels[value] || "其他简历状态";
}

const byId = (id) => document.getElementById(id);
const escapeDetailsHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;");
const detailsPlatformName = (value) => ({ boss: "BOSS", job51: "51job", zhilian: "智联" }[value] || value || "未知");

async function detailsApi(path) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" } });
  if (!response.ok) {
    const error = new Error(`${response.status} ${await response.text()}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function detailsQuery(page = detailsState.page) {
  const query = new URLSearchParams(window.location.search);
  if (!query.get("date")) query.set("date", new Date().toISOString().slice(0, 10));
  if (!query.get("metric")) query.set("metric", "processedContacts");
  query.set("page", String(page));
  query.set("page_size", "10");
  return query;
}

function formatAutomationDate(value) {
  const [fullYear = "", month = "", day = ""] = String(value || "").split("-");
  if (!fullYear || !month || !day) return "";
  return `${fullYear.slice(-2)}/${month}/${day}`;
}

function formatAutomationDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}/${values.month}/${values.day} ${values.hour}:${values.minute}:${values.second}`;
}

function renderDetailsContext(query) {
  const parts = [formatAutomationDate(query.get("date") || "")];
  if (query.get("platform")) parts.push(detailsPlatformName(query.get("platform")));
  if (query.get("owner")) parts.push(query.get("owner"));
  if (query.get("job_type")) parts.push(query.get("job_type"));
  byId("detailsContext").textContent = parts.filter(Boolean).join(" · ");
  byId("detailsMetricLabel").textContent = metricLabels[query.get("metric")] || "处理联系人";
}

function renderDetailRows(items) {
  byId("automationDetailsRows").innerHTML = items.map((item) => `
    <tr>
      <td>${escapeDetailsHtml(formatAutomationDateTime(item.time))}</td>
      <td>${escapeDetailsHtml(detailsPlatformName(item.platform))}</td>
      <td>${escapeDetailsHtml(item.owner)}</td>
      <td>${escapeDetailsHtml(item.candidateName || "未识别")}</td>
      <td>${escapeDetailsHtml(item.jobType || "未识别岗位")}</td>
      <td title="${escapeDetailsHtml(item.action || "")}">${escapeDetailsHtml(actionLabel(item.action))}</td>
      <td title="${escapeDetailsHtml(item.stage || "")}">${escapeDetailsHtml(stageLabel(item.stage))}</td>
      <td title="${escapeDetailsHtml(item.resumeHandling || "")}">${escapeDetailsHtml(resumeHandlingLabel(item.resumeHandling))}</td>
      <td>${item.resumeDownloadUrl
        ? `<a class="ts-btn automation-resume-download" href="${escapeDetailsHtml(item.resumeDownloadUrl)}" download>下载简历</a>`
        : '<span class="automation-resume-missing">尚未关联</span>'}</td>
      <td class="${item.anomaly ? "details-anomaly" : ""}" title="${escapeDetailsHtml(item.anomalyReason || "")}">${escapeDetailsHtml(item.anomaly ? anomalyReasonLabel(item.anomalyReason) : "无异常")}</td>
    </tr>
  `).join("");
  byId("automationDetailsEmpty").style.display = items.length ? "none" : "block";
}

function renderDetailsPagination(payload) {
  detailsState.page = payload.page;
  detailsState.pages = payload.pages;
  byId("detailsPagination").innerHTML = `
    <button class="ts-btn" type="button" data-details-page="${Math.max(1, payload.page - 1)}" ${payload.page <= 1 ? "disabled" : ""}>上一页</button>
    <span>第 ${payload.page} / ${payload.pages} 页</span>
    <button class="ts-btn" type="button" data-details-page="${Math.min(payload.pages, payload.page + 1)}" ${payload.page >= payload.pages ? "disabled" : ""}>下一页</button>
  `;
  document.querySelectorAll("[data-details-page]").forEach((button) => {
    button.onclick = () => loadAutomationDetails(Number(button.dataset.detailsPage || 1));
  });
}

async function loadAutomationDetails(page = 1) {
  if (detailsState.loading) return;
  detailsState.loading = true;
  try {
    const query = detailsQuery(page);
    const payload = await detailsApi(`/api/automation-monitoring/daily-details?${query}`);
    renderDetailsContext(query);
    renderDetailRows(payload.items || []);
    renderDetailsPagination(payload);
    byId("detailsTotal").textContent = String(payload.total || 0);
  } finally {
    detailsState.loading = false;
  }
}

async function initAutomationDetails() {
  try {
    const session = await detailsApi("/api/auth/me");
    const roles = session.roles || [];
    if (!roles.some((role) => ["admin", "super_admin"].includes(role))) {
      window.location.replace("/index.html");
      return;
    }
    byId("automationDetailsLoading").hidden = true;
    byId("automationDetailsApp").hidden = false;
    byId("detailsBackBtn").onclick = () => window.location.assign("/index.html");
    byId("detailsRefreshBtn").onclick = () => loadAutomationDetails(detailsState.page);
    await loadAutomationDetails(1);
  } catch (error) {
    if (error.status === 401 || error.status === 403) {
      window.location.replace("/index.html");
      return;
    }
    byId("automationDetailsLoading").textContent = `读取失败：${error.message}`;
  }
}

initAutomationDetails();
