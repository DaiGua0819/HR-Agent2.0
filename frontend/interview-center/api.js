(function () {
  async function requestJson(url, options = {}) {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      ...options,
      body: options.body && typeof options.body !== "string" ? JSON.stringify(options.body) : options.body,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || payload.message || `请求失败：${response.status}`);
    }
    return payload;
  }

  window.InterviewCenterApi = {
    requestJson,
    status: () => requestJson("/api/interview-center/feishu/status"),
    backfillStatus: () => requestJson("/api/interview-center/backfill/status"),
    authUrl: () => requestJson("/api/interview-center/feishu/auth-url"),
    disconnect: () => requestJson("/api/interview-center/feishu/disconnect", { method: "POST", body: {} }),
    sessions: (params = {}) => {
      const query = new URLSearchParams();
      if (params.startTime) query.set("startTime", String(params.startTime));
      if (params.endTime) query.set("endTime", String(params.endTime));
      const suffix = query.toString() ? `?${query.toString()}` : "";
      return requestJson(`/api/interview-center/sessions${suffix}`);
    },
    sync: () => requestJson("/api/interview-center/sync", { method: "POST", body: { autoPrepare: false } }),
    bind: (sessionId, resumeId, prepare = false) =>
      requestJson(`/api/interview-center/sessions/${encodeURIComponent(sessionId)}/bind`, {
        method: "POST",
        body: { resumeId, prepare },
      }),
    prepare: (sessionId, force = false) =>
      requestJson(`/api/interview-center/sessions/${encodeURIComponent(sessionId)}/prepare`, {
        method: "POST",
        body: { force },
      }),
    backfill: (sessionId, force = false) =>
      requestJson(`/api/interview-center/sessions/${encodeURIComponent(sessionId)}/backfill`, {
        method: "POST",
        body: { force },
      }),
    backfillSource: (sessionId) => requestJson(`/api/interview-center/sessions/${encodeURIComponent(sessionId)}/backfill-source`),
    review: (sessionId, decision = "passed", note = "") =>
      requestJson(`/api/interview-center/sessions/${encodeURIComponent(sessionId)}/review`, {
        method: "POST",
        body: { decision, note },
      }),
    confirm: (sessionId) =>
      requestJson(`/api/interview-center/sessions/${encodeURIComponent(sessionId)}/review`, {
        method: "POST",
        body: { decision: "passed" },
      }),
  };
})();
