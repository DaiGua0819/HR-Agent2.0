(function () {
  const api = window.InterviewCenterApi;
  const state = window.InterviewCenterState;

  const els = {
    connectionPill: document.querySelector("#connectionPill"),
    connectBtn: document.querySelector("#connectBtn"),
    disconnectBtn: document.querySelector("#disconnectBtn"),
    syncBtn: document.querySelector("#syncBtn"),
    backHomeBtn: document.querySelector("#backHomeBtn"),
    refreshSessionsBtn: document.querySelector("#refreshSessionsBtn"),
    statusFilter: document.querySelector("#statusFilter"),
    dateStartFilter: document.querySelector("#dateStartFilter"),
    dateEndFilter: document.querySelector("#dateEndFilter"),
    applyDateFilterBtn: document.querySelector("#applyDateFilterBtn"),
    workspaceGrid: document.querySelector(".workspace-grid"),
    eventList: document.querySelector("#eventList"),
    workspaceTitle: document.querySelector("#workspaceTitle"),
    workspaceStatus: document.querySelector("#workspaceStatus"),
    workspaceBody: document.querySelector("#workspaceBody"),
    prepareBtn: document.querySelector("#prepareBtn"),
    openDocBtn: document.querySelector("#openDocBtn"),
    backfillBtn: document.querySelector("#backfillBtn"),
    confirmBtn: document.querySelector("#confirmBtn"),
    metricTotal: document.querySelector("#metricTotal"),
    metricMatched: document.querySelector("#metricMatched"),
    metricPrepared: document.querySelector("#metricPrepared"),
    metricBackfill: document.querySelector("#metricBackfill"),
  };

  const statusLabels = {
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
  };

  const columnStorageKey = "interviewCenter.columnWidths.v2";
  const columnMins = {
    calendar: 360,
    workspace: 420,
  };
  const backfillGraceSeconds = 10 * 60;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatTime(seconds) {
    if (!seconds) return "-";
    return new Date(Number(seconds) * 1000).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function toDateInputValue(date) {
    const value = new Date(date);
    if (Number.isNaN(value.getTime())) return "";
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function setDefaultDateRange() {
    if (state.dateStart && state.dateEnd) return;
    const start = new Date();
    start.setDate(start.getDate() - 1);
    const end = new Date();
    end.setDate(end.getDate() + 14);
    state.dateStart = toDateInputValue(start);
    state.dateEnd = toDateInputValue(end);
    if (els.dateStartFilter) els.dateStartFilter.value = state.dateStart;
    if (els.dateEndFilter) els.dateEndFilter.value = state.dateEnd;
  }

  function dateRangeParams() {
    const start = state.dateStart ? new Date(`${state.dateStart}T00:00:00`) : null;
    const end = state.dateEnd ? new Date(`${state.dateEnd}T23:59:59`) : null;
    return {
      startTime: start && !Number.isNaN(start.getTime()) ? Math.floor(start.getTime() / 1000) : 0,
      endTime: end && !Number.isNaN(end.getTime()) ? Math.floor(end.getTime() / 1000) : 0,
    };
  }

  function backfillAvailability(session) {
    const availableAt = Number(session?.endTime || session?.startTime || 0) + backfillGraceSeconds;
    if (!availableAt) return { ready: false, label: "面试结束后可回灌" };
    const nowSeconds = Math.floor(Date.now() / 1000);
    return {
      ready: nowSeconds >= availableAt,
      availableAt,
      label: nowSeconds >= availableAt ? "读取纪要并回灌" : `面试结束后可回灌 ${formatTime(availableAt)}`,
    };
  }

  function backfillProtection(session) {
    const availableAt = Number(session?.endTime || session?.startTime || 0) + backfillGraceSeconds;
    if (session.earlyBackfillOverride?.usedAt && Number(session.earlyBackfillOverride.availableAt || 0) === availableAt) {
      return { blocked: false, reason: "" };
    }
    const flow = sessionFlow(session);
    const backfill = backfillAvailability(session);
    if (flow.groupKey === "waiting") {
      return {
        blocked: true,
        reason: flow.stageText ? `当前多维表阶段仍为「${flow.stageText}」` : "当前仍处于等待面试阶段",
      };
    }
    if (!backfill.ready) {
      return {
        blocked: true,
        reason: backfill.label,
      };
    }
    return { blocked: false, reason: "" };
  }

  function visibleInterviewEvaluation(session) {
    return backfillProtection(session).blocked ? null : session.interviewEvaluation || null;
  }

  function getSessionBusyAction(sessionOrId) {
    const sessionId = typeof sessionOrId === "string" ? sessionOrId : sessionOrId?.id || "";
    return sessionId ? state.sessionBusy?.[sessionId] || "" : "";
  }

  function hasSessionBusy(sessionOrId) {
    return Boolean(getSessionBusyAction(sessionOrId));
  }

  function isGlobalBusy() {
    return Boolean(state.busy && !state.busySessionId);
  }

  function setSessionBusy(sessionId, action, flag) {
    if (!sessionId) return;
    const next = { ...(state.sessionBusy || {}) };
    if (flag) next[sessionId] = action || "action";
    else delete next[sessionId];
    state.sessionBusy = next;
    state.busySessionId = flag ? sessionId : state.busySessionId === sessionId ? "" : state.busySessionId;
  }

  function setBusy(flag, text = "", options = {}) {
    if (options.sessionId) setSessionBusy(options.sessionId, options.busyAction, flag);
    else if (flag) state.busySessionId = "";
    else if (!flag) state.busySessionId = "";
    state.busy = flag;
    const globalBusy = isGlobalBusy();
    [els.connectBtn, els.disconnectBtn, els.syncBtn, els.refreshSessionsBtn, els.applyDateFilterBtn].forEach((button) => {
      if (button) button.disabled = globalBusy || button.dataset.disabledByState === "true";
    });
    if (text) els.connectionPill.textContent = text;
  }

  function selectedSession() {
    return state.sessions.find((item) => item.id === state.selectedId) || null;
  }

  function filteredSessions() {
    return state.sessions.filter((item) => !state.statusFilter || item.status === state.statusFilter);
  }

  function sessionFlow(session = {}) {
    const fallbackCompleted = Number(session.endTime || session.startTime || 0) && Number(session.endTime || session.startTime || 0) < Math.floor(Date.now() / 1000);
    return {
      groupKey: session.interviewFlow?.groupKey || (fallbackCompleted ? "completed" : "waiting"),
      groupLabel: session.interviewFlow?.groupLabel || (fallbackCompleted ? "已经面试" : "等待面试"),
      roundKey: session.interviewFlow?.roundKey || "first",
      roundLabel: session.interviewFlow?.roundLabel || "初面",
      stageText: session.interviewFlow?.stageText || "",
    };
  }

  function stageLabel(flow = {}) {
    return [flow.roundLabel || "其他轮次", flow.stageText || "未识别阶段"].filter(Boolean).join(" · ");
  }

  function stageKey(flow = {}) {
    return `${flow.roundKey || "other"}:${flow.stageText || "unknown"}`;
  }

  function stageClass(flow = {}) {
    const text = `${flow.groupLabel || ""} ${flow.roundLabel || ""} ${flow.stageText || ""}`;
    if (/未通过|淘汰|不合适|失败|拒绝/.test(text)) return "is-stage-failed";
    if (/待复核|复核|回灌/.test(text)) return "is-stage-review";
    if (/二面|二试|复试|复面/.test(text)) return "is-stage-second";
    if (/简历通过|等待|待面试|已约|邀约/.test(text)) return "is-stage-waiting";
    if (/通过|完成|已面试|初面/.test(text)) return "is-stage-passed";
    return "is-stage-default";
  }

  function collapseKey(type, key) {
    return `${type}:${key}`;
  }

  function isCollapsed(type, key) {
    return Boolean(state.collapsedSections?.[collapseKey(type, key)]);
  }

  function toggleCollapsed(type, key) {
    const next = { ...(state.collapsedSections || {}) };
    const fullKey = collapseKey(type, key);
    if (next[fullKey]) delete next[fullKey];
    else next[fullKey] = true;
    state.collapsedSections = next;
  }

  function compareByNearTime(left, right) {
    const now = Math.floor(Date.now() / 1000);
    const leftTime = Number(left.startTime || 0);
    const rightTime = Number(right.startTime || 0);
    const leftDistance = leftTime ? Math.abs(leftTime - now) : Number.MAX_SAFE_INTEGER;
    const rightDistance = rightTime ? Math.abs(rightTime - now) : Number.MAX_SAFE_INTEGER;
    return leftDistance - rightDistance || leftTime - rightTime || String(left.id || "").localeCompare(String(right.id || ""));
  }

  function groupedSessions() {
    const sessions = filteredSessions().slice().sort(compareByNearTime);
    const groupDefs = [
      { key: "waiting", label: "等待面试" },
      { key: "completed", label: "已经面试" },
    ];
    const roundDefs = [
      { key: "first", label: "初面" },
      { key: "second", label: "二面" },
      { key: "other", label: "其他轮次" },
    ];
    return groupDefs
      .map((group) => {
        const groupItems = sessions.filter((item) => sessionFlow(item).groupKey === group.key);
        const stages = new Map();
        groupItems.forEach((item) => {
          const flow = sessionFlow(item);
          const key = stageKey(flow);
          if (!stages.has(key)) {
            stages.set(key, {
              key,
              label: stageLabel(flow),
              roundKey: flow.roundKey,
              roundLabel: flow.roundLabel,
              className: stageClass(flow),
              count: 0,
              items: [],
            });
          }
          const stage = stages.get(key);
          stage.items.push(item);
          stage.count += 1;
        });
        return {
          ...group,
          count: groupItems.length,
          stages: [...stages.values()].sort((left, right) => {
            const leftRound = roundDefs.findIndex((round) => round.key === left.roundKey);
            const rightRound = roundDefs.findIndex((round) => round.key === right.roundKey);
            return (
              (leftRound < 0 ? 99 : leftRound) - (rightRound < 0 ? 99 : rightRound) ||
              String(left.label).localeCompare(String(right.label), "zh-CN")
            );
          }),
        };
      })
      .filter((group) => group.count);
  }

  function statusClass(status) {
    if (status === "prepared" || status === "completed") return "is-good";
    if (status === "needs_confirmation" || status === "needs_match" || status === "prepared_local" || status === "backfilling") return "is-warn";
    if (status === "needs_review") return "is-review";
    if (status === "backfill_failed") return "is-error";
    return "";
  }

  function updateConnectionUi() {
    els.connectionPill.className = `connection-pill ${state.connected ? "is-connected" : state.configured ? "is-ready" : "is-error"}`;
    if (!state.configured) {
      els.connectionPill.textContent = "飞书应用未配置";
    } else if (state.connected) {
      const name = state.userInfo?.name || state.userInfo?.en_name || "已授权";
      els.connectionPill.textContent = `飞书已连接：${name}`;
    } else {
      els.connectionPill.textContent = "飞书未授权";
    }
    els.connectBtn.hidden = state.connected;
    els.disconnectBtn.hidden = !state.connected;
    els.syncBtn.disabled = !state.connected || isGlobalBusy();
    els.syncBtn.dataset.disabledByState = !state.connected ? "true" : "false";
  }

  function renderMetrics() {
    const sessions = state.sessions;
    els.metricTotal.textContent = sessions.length;
    els.metricMatched.textContent = sessions.filter((item) => item.resumeId).length;
    els.metricPrepared.textContent = sessions.filter((item) => ["prepared", "prepared_local", "backfilling", "needs_review", "completed"].includes(item.status)).length;
    els.metricBackfill.textContent = sessions.filter((item) => ["backfilling", "backfill_failed", "needs_review"].includes(item.status)).length;
  }

  function renderEvents() {
    const groups = groupedSessions();
    if (!groups.length) {
      els.eventList.innerHTML = '<div class="empty-state">当前筛选下暂无面试日程</div>';
      return;
    }
    els.eventList.innerHTML = groups
      .map(
        (group) => {
          const groupCollapsed = isCollapsed("group", group.key);
          return `
          <section class="session-group ${groupCollapsed ? "is-collapsed" : ""}">
            <button class="session-group-head" type="button" data-toggle-collapse="group" data-collapse-key="${escapeHtml(group.key)}" aria-expanded="${groupCollapsed ? "false" : "true"}">
              <strong><span class="collapse-mark">${groupCollapsed ? "▸" : "▾"}</span>${escapeHtml(group.label)}</strong>
              <span>${group.count} 场</span>
            </button>
            ${
              groupCollapsed
                ? ""
                : group.stages
                    .map((stage) => {
                      const stageCollapseKey = `${group.key}:${stage.key}`;
                      const stageCollapsed = isCollapsed("stage", stageCollapseKey);
                      return `
                  <div class="round-group ${stageCollapsed ? "is-collapsed" : ""}">
                    <button class="round-group-head ${escapeHtml(stage.className)}" type="button" data-toggle-collapse="stage" data-collapse-key="${escapeHtml(stageCollapseKey)}" aria-expanded="${stageCollapsed ? "false" : "true"}">
                      <span><span class="collapse-mark">${stageCollapsed ? "▸" : "▾"}</span>${escapeHtml(stage.label)}</span>
                      <strong>${stage.count}</strong>
                    </button>
                    ${
                      stageCollapsed
                        ? ""
                        : stage.items
                      .map((item) => {
                        const flow = sessionFlow(item);
                        return `
                          <button class="event-row ${item.id === state.selectedId ? "is-active" : ""}" type="button" data-select-session="${escapeHtml(item.id)}">
                            <span class="event-time">${escapeHtml(formatTime(item.startTime))}</span>
                            <strong>${escapeHtml(item.title || "未命名日程")}</strong>
                            <small>${escapeHtml(item.matchedResume?.name || item.resume?.name || item.matchMessage || "未绑定候选人")}</small>
                            <em class="status-badge ${statusClass(item.status)}">${escapeHtml(statusLabels[item.status] || item.status || "-")}</em>
                            <span class="event-tags">
                              <span class="stage-chip is-stage-round">${escapeHtml(flow.roundLabel)}</span>
                              ${flow.stageText ? `<span class="stage-chip ${stageClass(flow)}">${escapeHtml(flow.stageText)}</span>` : ""}
                            </span>
                          </button>
                        `;
                      })
                      .join("")
                    }
                  </div>
                `;
                    })
                    .join("")
            }
          </section>
        `;
        }
      )
      .join("");
  }

  function questionHtml(session) {
    const questions = session.questionSet?.questions || [];
    if (!questions.length) return '<div class="empty-state">尚未生成面试问题</div>';
    return questions
      .map(
        (item, index) => `
          <article class="question-item">
            <div class="question-index">${index + 1}</div>
            <div>
              <strong>${escapeHtml(item.ability || "能力项")}</strong>
              <p>${escapeHtml(item.question || "")}</p>
              <small>追问：${escapeHtml((item.followUps || []).join("；") || "-")}</small>
              <small>强信号：${escapeHtml(item.strongSignal || "-")}</small>
              <small>风险信号：${escapeHtml(item.riskSignal || "-")}</small>
            </div>
          </article>
        `
      )
      .join("");
  }

  function sourceTypeLabel(type) {
    const labels = {
      interview_doc: "面试文档",
      linked_doc: "关联文档",
      minutes_transcript: "妙记转录",
    };
    return labels[type] || type || "-";
  }

  function textListHtml(items = [], emptyText = "暂无") {
    const values = (items || []).filter(Boolean);
    if (!values.length) return `<span class="empty-inline">${escapeHtml(emptyText)}</span>`;
    return `<ul>${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
  }

  function sourceSummaryHtml(source = {}, lastError = "") {
    const sources = source.sources || [];
    const errors = [...(source.errors || []), lastError].filter(Boolean);
    const sourceRows = sources.length
      ? sources
          .map(
            (item) => `
              <span>
                ${escapeHtml(sourceTypeLabel(item.type))}
                ${item.length ? ` · ${escapeHtml(item.length)}字` : ""}
                ${item.url ? ` · <a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">打开</a>` : ""}
              </span>
            `
          )
          .join("")
      : '<span class="empty-inline">尚未读取到有效来源</span>';
    return `
      <div class="backfill-source">
        <div><strong>来源</strong><span>${escapeHtml((source.types || []).map(sourceTypeLabel).join("、") || "-")}</span></div>
        <div><strong>文本量</strong><span>${escapeHtml(source.rawTextLength || 0)} 字</span></div>
        <div><strong>读取项</strong><p>${sourceRows}</p></div>
        ${errors.length ? `<div class="source-errors"><strong>异常</strong>${textListHtml(errors)}</div>` : ""}
      </div>
    `;
  }

  function reviewStatusText(evaluation = {}) {
    const decision = evaluation.review?.decision || evaluation.review?.status || "";
    if (decision === "passed") return "已通过复核";
    if (decision === "rejected") return "已淘汰";
    if (decision === "need_followup") return "需补问";
    return "待人工复核";
  }

  function evaluationActionsHtml(session) {
    if (!visibleInterviewEvaluation(session)) return "";
    const disabled = isGlobalBusy() || hasSessionBusy(session) ? "disabled" : "";
    return `
      <div class="review-actions">
        <button class="primary-btn small" type="button" data-review-decision="passed" ${disabled}>通过复核</button>
        <button class="ghost-btn small danger" type="button" data-review-decision="rejected" ${disabled}>淘汰</button>
        <button class="ghost-btn small" type="button" data-review-decision="need_followup" ${disabled}>需要补问</button>
        <button class="ghost-btn small" type="button" data-rerun-backfill="${escapeHtml(session.id)}" ${disabled}>重新回灌</button>
      </div>
    `;
  }

  function evaluationHtml(session) {
    const protection = backfillProtection(session);
    const evaluation = visibleInterviewEvaluation(session);
    if (protection.blocked && session.interviewEvaluation) {
      return `<div class="empty-state">已隐藏历史回灌内容：${escapeHtml(protection.reason)}</div>`;
    }
    if (!evaluation) {
      if (session.status === "backfilling") return '<div class="empty-state">正在读取飞书记录并生成回灌结果</div>';
      if (session.status === "backfill_failed") {
        return `
          <div class="empty-state">回灌失败：${escapeHtml(session.lastBackfillError || "未读取到有效面试记录")}</div>
          ${sourceSummaryHtml(session.backfillSource || {}, session.lastBackfillError || "")}
        `;
      }
      return '<div class="empty-state">尚未回灌面试结果</div>';
    }
    const source = evaluation.source || session.backfillSource || {};
    const qaEvidence = evaluation.qaEvidence || [];
    const qaRows = qaEvidence.length
      ? qaEvidence
      : (evaluation.abilityProfile || []).map((item) => ({
          ability: item.ability,
          question: item.question,
          answerSummary: item.answerSummary,
          signal: item.signal,
          reason: item.reason,
          followUpSuggestion: item.followUp,
          evidenceQuotes: [],
        }));
    return `
      <div class="evaluation-summary">
        <div class="evaluation-heading">
          <strong>总体建议：${escapeHtml(evaluation.overallRecommendation || "待复核")}</strong>
          <span class="status-badge ${evaluation.review?.status && evaluation.review.status !== "pending" ? "is-good" : "is-review"}">${escapeHtml(reviewStatusText(evaluation))}</span>
        </div>
        <p>${escapeHtml(evaluation.summary || "")}</p>
        <div class="evaluation-columns">
          <div><strong>优势</strong>${textListHtml(evaluation.strengths || [])}</div>
          <div><strong>风险</strong>${textListHtml(evaluation.risks || [])}</div>
        </div>
        ${evaluation.nextAction ? `<p class="next-action">${escapeHtml(evaluation.nextAction)}</p>` : ""}
        ${sourceSummaryHtml(source, session.lastBackfillError || "")}
      </div>
      <div class="qa-evidence-list">
        ${qaRows
        .map(
          (item, index) => `
            <article class="qa-evidence-row">
              <span>${escapeHtml(item.signal || "待复核")}</span>
              <div>
                <strong>${escapeHtml(index + 1)}. ${escapeHtml(item.ability || "能力项")}</strong>
                ${item.question ? `<p class="qa-question">${escapeHtml(item.question)}</p>` : ""}
                <p>${escapeHtml(item.answerSummary || "未提取到明确回答")}</p>
                ${item.evidenceQuotes?.length ? `<div class="evidence-quotes">${item.evidenceQuotes.map((quote) => `<em>${escapeHtml(quote)}</em>`).join("")}</div>` : ""}
                ${item.reason ? `<small>${escapeHtml(item.reason)}</small>` : ""}
                ${item.followUpSuggestion ? `<small>建议追问：${escapeHtml(item.followUpSuggestion)}</small>` : ""}
              </div>
            </article>
          `
        )
        .join("")}
      </div>
      ${evaluationActionsHtml(session)}
    `;
  }

  function renderWorkspace() {
    const session = selectedSession();
    if (!session) {
      els.workspaceTitle.textContent = "面试工作区";
      els.workspaceStatus.textContent = "未选择";
      els.workspaceStatus.className = "status-badge";
      els.workspaceBody.innerHTML = '<div class="empty-state large">从左侧选择一个面试日程</div>';
      [els.prepareBtn, els.openDocBtn, els.backfillBtn, els.confirmBtn].forEach((button) => {
        button.disabled = true;
        button.dataset.disabledByState = "true";
      });
      els.prepareBtn.textContent = "生成问题并同步飞书";
      els.backfillBtn.textContent = "读取纪要并回灌";
      els.confirmBtn.textContent = "通过复核";
      return;
    }

    els.workspaceTitle.textContent = session.resume?.name || session.matchedResume?.name || session.title || "面试日程";
    els.workspaceStatus.textContent = statusLabels[session.status] || session.status || "-";
    els.workspaceStatus.className = `status-badge ${statusClass(session.status)}`;
    const sessionBusyAction = getSessionBusyAction(session);
    const sessionBusy = Boolean(sessionBusyAction);
    const globalBusy = isGlobalBusy();
    els.prepareBtn.textContent = sessionBusyAction === "prepare" ? "生成中..." : "生成问题并同步飞书";
    els.prepareBtn.disabled = !session.resumeId || globalBusy || sessionBusy;
    els.prepareBtn.dataset.disabledByState = !session.resumeId ? "true" : "false";
    els.openDocBtn.disabled = !session.feishuDoc?.url || globalBusy;
    els.openDocBtn.dataset.disabledByState = !session.feishuDoc?.url ? "true" : "false";
    const backfill = backfillAvailability(session);
    const protection = backfillProtection(session);
    let backfillDisabledByState = "";
    if (!session.resumeId) backfillDisabledByState = "先绑定候选人";
    else if (!session.feishuDoc?.documentId) backfillDisabledByState = "先生成面试文档";
    else if (session.status === "backfilling") backfillDisabledByState = "正在回灌";
    else if (protection.blocked) backfillDisabledByState = protection.reason;
    else if (!backfill.ready) backfillDisabledByState = backfill.label;
    const visibleEvaluation = visibleInterviewEvaluation(session);
    els.backfillBtn.textContent =
      sessionBusyAction === "backfill" ? "回灌中..." : backfillDisabledByState || (visibleEvaluation ? "重新回灌" : "读取纪要并回灌");
    els.backfillBtn.disabled = Boolean(backfillDisabledByState) || globalBusy || sessionBusy;
    els.backfillBtn.dataset.disabledByState = backfillDisabledByState ? "true" : "false";
    els.backfillBtn.title = backfillDisabledByState || "";
    els.confirmBtn.textContent = sessionBusyAction === "review" ? "复核中..." : "通过复核";
    els.confirmBtn.disabled = !visibleEvaluation || globalBusy || sessionBusy;
    els.confirmBtn.dataset.disabledByState = !visibleEvaluation ? "true" : "false";
    const docLinkText = session.feishuDoc?.contentSynced === false ? "已创建，正文未同步" : "已创建";
    const docErrorHtml =
      session.feishuDoc?.contentSynced === false && session.feishuDoc?.contentError
        ? `<small class="detail-error">${escapeHtml(session.feishuDoc.contentError)}</small>`
        : "";
    const scheduler = state.backfillStatus;
    const schedulerText = scheduler
      ? `${scheduler.enabled ? (scheduler.running ? "扫描中" : "运行中") : "已关闭"}，待处理 ${scheduler.pendingCount || 0}`
      : "-";
    const calendarSync = state.calendarSyncStatus;
    const calendarSyncText = calendarSync
      ? `${calendarSync.enabled ? (calendarSync.running ? "同步中" : "每5分钟自动同步") : "已关闭"}${calendarSync.lastRunAt ? `，上次 ${new Date(calendarSync.lastRunAt).toLocaleTimeString("zh-CN", { hour12: false })}` : ""}`
      : "-";
    const flow = sessionFlow(session);

    els.workspaceBody.innerHTML = `
      <section class="detail-section">
        <h3>日程信息</h3>
        <dl class="detail-grid">
          <div><dt>时间</dt><dd>${escapeHtml(formatTime(session.startTime))}</dd></div>
          <div><dt>标题</dt><dd>${escapeHtml(session.title || "-")}</dd></div>
          <div><dt>候选人</dt><dd>${escapeHtml(session.resume?.name || session.matchedResume?.name || "未绑定")}</dd></div>
          <div><dt>岗位</dt><dd>${escapeHtml(session.resume?.jobType || session.matchedResume?.jobType || "-")}</dd></div>
          <div><dt>面试分组</dt><dd>${escapeHtml(`${flow.groupLabel} / ${flow.roundLabel}`)}</dd></div>
          <div><dt>面试阶段</dt><dd>${escapeHtml(flow.stageText || (session.interviewFlow?.source === "calendar" ? "按日程时间判断" : "-"))}</dd></div>
          <div><dt>飞书文档</dt><dd>${session.feishuDoc?.url ? `<a href="${escapeHtml(session.feishuDoc.url)}" target="_blank" rel="noreferrer">${escapeHtml(docLinkText)}</a>${docErrorHtml}` : "未创建"}</dd></div>
          <div><dt>台账</dt><dd>${escapeHtml(session.bitable?.skipped ? "未配置" : session.bitable?.recordId ? "已同步" : "未同步")}</dd></div>
          <div><dt>日历同步</dt><dd>${escapeHtml(calendarSyncText)}</dd></div>
          <div><dt>自动回灌</dt><dd>${escapeHtml(schedulerText)}</dd></div>
        </dl>
      </section>
      <section class="detail-section">
        <h3>面试问题</h3>
        ${questionHtml(session)}
      </section>
      <section class="detail-section">
        <h3>面试回灌</h3>
        ${evaluationHtml(session)}
      </section>
    `;
  }

  function renderAll() {
    updateConnectionUi();
    renderMetrics();
    renderEvents();
    renderWorkspace();
  }

  function applyColumnWidths(widths = {}) {
    if (!els.workspaceGrid) return;
    if (widths.calendar) els.workspaceGrid.style.setProperty("--calendar-col", `${Math.round(widths.calendar)}px`);
    if (widths.workspace) els.workspaceGrid.style.setProperty("--workspace-col", `${Math.round(widths.workspace)}px`);
  }

  function loadColumnWidths() {
    try {
      const widths = JSON.parse(localStorage.getItem(columnStorageKey) || "{}");
      applyColumnWidths(widths);
    } catch {}
  }

  function saveColumnWidths(widths) {
    try {
      localStorage.setItem(columnStorageKey, JSON.stringify(widths));
    } catch {}
  }

  function currentColumnWidths() {
    const calendar = els.workspaceGrid?.querySelector(".calendar-panel")?.getBoundingClientRect().width || 0;
    const workspace = els.workspaceGrid?.querySelector(".workspace-panel")?.getBoundingClientRect().width || 0;
    return { calendar, workspace };
  }

  function resetColumnWidths() {
    if (!els.workspaceGrid) return;
    ["--calendar-col", "--workspace-col"].forEach((name) => els.workspaceGrid.style.removeProperty(name));
    try {
      localStorage.removeItem(columnStorageKey);
    } catch {}
  }

  function initColumnResizers() {
    if (!els.workspaceGrid) return;
    loadColumnWidths();
    els.workspaceGrid.querySelectorAll(".column-resizer").forEach((handle) => {
      handle.addEventListener("dblclick", resetColumnWidths);
      handle.addEventListener("pointerdown", (event) => {
        if (window.innerWidth <= 1180) return;
        const type = handle.dataset.resizer;
        const startX = event.clientX;
        const start = currentColumnWidths();
        handle.classList.add("is-dragging");
        handle.setPointerCapture?.(event.pointerId);

        const onMove = (moveEvent) => {
          const delta = moveEvent.clientX - startX;
          const next = { ...start };
          if (type === "calendar-workspace") {
            const total = start.calendar + start.workspace;
            next.calendar = Math.max(columnMins.calendar, Math.min(total - columnMins.workspace, start.calendar + delta));
            next.workspace = total - next.calendar;
          }
          applyColumnWidths(next);
          saveColumnWidths(next);
        };

        const onUp = () => {
          handle.classList.remove("is-dragging");
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          window.removeEventListener("pointercancel", onUp);
        };

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("pointercancel", onUp);
      });
    });
  }

  async function loadStatus() {
    const payload = await api.status();
    state.configured = Boolean(payload.configured);
    state.connected = Boolean(payload.connected);
    state.bitableConfigured = Boolean(payload.bitableConfigured);
    state.userInfo = payload.userInfo || null;
    state.calendarSyncStatus = payload.calendarSync || null;
    state.backfillStatus = await api.backfillStatus().catch(() => state.backfillStatus);
    renderAll();
  }

  async function loadSessions() {
    const payload = await api.sessions(dateRangeParams());
    state.sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    state.logs = Array.isArray(payload.logs) ? payload.logs : [];
    state.backfillStatus = await api.backfillStatus().catch(() => state.backfillStatus);
    if (!state.selectedId && state.sessions.length) state.selectedId = state.sessions[0].id;
    if (state.selectedId && !state.sessions.some((item) => item.id === state.selectedId)) {
      state.selectedId = state.sessions[0]?.id || "";
    }
    renderAll();
  }

  function applyDateInputsToState() {
    const nextStart = els.dateStartFilter?.value || "";
    const nextEnd = els.dateEndFilter?.value || "";
    if (nextStart && nextEnd && nextStart > nextEnd) {
      state.dateStart = nextEnd;
      state.dateEnd = nextStart;
    } else {
      state.dateStart = nextStart;
      state.dateEnd = nextEnd;
    }
    if (els.dateStartFilter) els.dateStartFilter.value = state.dateStart;
    if (els.dateEndFilter) els.dateEndFilter.value = state.dateEnd;
  }

  async function runAction(label, task, options = {}) {
    const initialSelectedId = state.selectedId;
    try {
      state.busyAction = options.busyAction || "";
      setBusy(true, label, options);
      renderWorkspace();
      const payload = await task();
      if (payload.sessions) state.sessions = payload.sessions;
      if (payload.session) {
        const index = state.sessions.findIndex((item) => item.id === payload.session.id);
        if (index >= 0) state.sessions[index] = payload.session;
        else state.sessions.unshift(payload.session);
        if (state.selectedId === initialSelectedId || state.selectedId === payload.session.id || !state.selectedId) {
          state.selectedId = payload.session.id;
        }
      }
      if (payload.logs) state.logs = payload.logs;
      await loadStatus().catch(() => {});
      renderAll();
    } catch (error) {
      els.connectionPill.textContent = error.message || "操作失败";
      els.connectionPill.className = "connection-pill is-error";
    } finally {
      state.busyAction = "";
      setBusy(false, "", options);
      updateConnectionUi();
      renderAll();
    }
  }

  function bindEvents() {
    els.backHomeBtn.addEventListener("click", () => {
      location.href = "./index.html";
    });
    els.connectBtn.addEventListener("click", () =>
      runAction("正在打开飞书授权", async () => {
        const payload = await api.authUrl();
        location.href = payload.authUrl;
        return {};
      })
    );
    els.disconnectBtn.addEventListener("click", () =>
      runAction("正在断开飞书", async () => {
        await api.disconnect();
        state.connected = false;
        state.userInfo = null;
        return {};
      })
    );
    els.syncBtn.addEventListener("click", () =>
      runAction("正在同步飞书日历", async () => {
        await api.sync();
        return api.sessions(dateRangeParams());
      })
    );
    els.refreshSessionsBtn.addEventListener("click", () => runAction("正在刷新面试中心", () => api.sessions(dateRangeParams())));
    els.applyDateFilterBtn?.addEventListener("click", () => {
      applyDateInputsToState();
      runAction("正在按日期筛选面试", () => api.sessions(dateRangeParams()));
    });
    [els.dateStartFilter, els.dateEndFilter].forEach((input) => {
      input?.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        applyDateInputsToState();
        runAction("正在按日期筛选面试", () => api.sessions(dateRangeParams()));
      });
    });
    els.statusFilter.addEventListener("change", () => {
      state.statusFilter = els.statusFilter.value;
      renderAll();
    });
    els.eventList.addEventListener("click", handleDelegatedClick);
    els.workspaceBody.addEventListener("click", handleDelegatedClick);
    els.prepareBtn.addEventListener("click", () => {
      const session = selectedSession();
      if (session) runAction("正在生成面试题并同步飞书", () => api.prepare(session.id, true), { busyAction: "prepare", sessionId: session.id });
    });
    els.openDocBtn.addEventListener("click", () => {
      const url = selectedSession()?.feishuDoc?.url;
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    });
    els.backfillBtn.addEventListener("click", () => {
      const session = selectedSession();
      if (session) runAction("正在读取飞书记录并回灌", () => api.backfill(session.id, true), { busyAction: "backfill", sessionId: session.id });
    });
    els.confirmBtn.addEventListener("click", () => {
      const session = selectedSession();
      if (session) runAction("正在确认评估", () => api.review(session.id, "passed"), { busyAction: "review", sessionId: session.id });
    });
  }

  function handleDelegatedClick(event) {
    const selectButton = event.target.closest("[data-select-session]");
    if (selectButton) {
      state.selectedId = selectButton.dataset.selectSession || "";
      renderAll();
      return;
    }
    const toggleButton = event.target.closest("[data-toggle-collapse]");
    if (toggleButton) {
      toggleCollapsed(toggleButton.dataset.toggleCollapse || "", toggleButton.dataset.collapseKey || "");
      renderAll();
      return;
    }
    const bindButton = event.target.closest("[data-bind-session]");
    if (bindButton) {
      const sessionId = bindButton.dataset.bindSession;
      const resumeId = bindButton.dataset.resumeId;
      runAction("正在绑定候选人", () => api.bind(sessionId, resumeId, false), { busyAction: "bind", sessionId });
      return;
    }
    const reviewButton = event.target.closest("[data-review-decision]");
    if (reviewButton) {
      const session = selectedSession();
      if (!session) return;
      const decision = reviewButton.dataset.reviewDecision || "passed";
      const labels = { passed: "通过复核", rejected: "淘汰候选人", need_followup: "标记补问" };
      runAction(`正在${labels[decision] || "复核"}`, () => api.review(session.id, decision), { busyAction: "review", sessionId: session.id });
      return;
    }
    const rerunButton = event.target.closest("[data-rerun-backfill]");
    if (rerunButton) {
      const session = selectedSession();
      if (session) runAction("正在重新读取飞书记录并回灌", () => api.backfill(session.id, true), { busyAction: "backfill", sessionId: session.id });
    }
  }

  async function init() {
    setDefaultDateRange();
    bindEvents();
    initColumnResizers();
    window.setInterval(() => {
      if (!isGlobalBusy()) renderWorkspace();
    }, 60000);
    if (new URLSearchParams(location.search).get("feishu") === "connected") {
      els.connectionPill.textContent = "飞书授权成功，正在加载";
    }
    await loadStatus().catch((error) => {
      els.connectionPill.textContent = error.message || "飞书状态读取失败";
      els.connectionPill.className = "connection-pill is-error";
    });
    await loadSessions().catch(() => renderAll());
  }

  init();
})();
