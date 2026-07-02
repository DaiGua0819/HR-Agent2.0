(function () {
  window.InterviewCenterState = {
    connected: false,
    configured: false,
    bitableConfigured: false,
    userInfo: null,
    sessions: [],
    logs: [],
    selectedId: "",
    statusFilter: "",
    dateStart: "",
    dateEnd: "",
    collapsedSections: {},
    busy: false,
    busyAction: "",
    busySessionId: "",
    sessionBusy: {},
    backfillStatus: null,
    calendarSyncStatus: null,
  };
})();
