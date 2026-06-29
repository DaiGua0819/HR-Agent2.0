const hrAuth = (() => {
  const pageKeys = ["dashboard", "resumes", "queue", "interviews", "automation", "rules"];
  const login = () => document.getElementById("loginScreen");
  const app = () => document.getElementById("app");
  const error = () => document.getElementById("loginError");
  const access = (user) => user?.uiAccess || { defaultView: "resumes", views: ["resumes"], actions: [] };
  const canView = (user, view) => access(user).views.includes(view);
  const canAction = (user, action) => access(user).actions.includes(action);
  function showLogin(message = "") {
    login().hidden = false;
    app().hidden = true;
    error().textContent = message;
    document.getElementById("loginPassword").value = "";
  }
  function showApp() {
    login().hidden = true;
    app().hidden = false;
    error().textContent = "";
  }
  function setAllowedNavigation(user) {
    const allowed = new Set(access(user).views);
    document.querySelectorAll("[data-view]").forEach((button) => {
      button.hidden = !allowed.has(button.dataset.view);
    });
    pageKeys.forEach((view) => {
      const page = document.querySelector(`[data-page="${view}"]`);
      if (page) page.hidden = !allowed.has(view);
    });
    const interview = document.getElementById("interviewBtn");
    if (interview) interview.hidden = !canAction(user, "interview:invite");
  }
  function updateUserCard(user) {
    document.getElementById("userName").textContent = user.user.name;
    const scope = user.resumeScope;
    document.getElementById("userScope").textContent = `可见：${scope.owners.join("、")} / ${scope.platforms.join("、")}`;
  }
  function bindLogin(api, afterLogin) {
    document.getElementById("loginForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      error().textContent = "";
      const body = JSON.stringify({
        username: document.getElementById("loginUsername").value,
        password: document.getElementById("loginPassword").value,
      });
      try {
        const user = await api("/api/auth/login", { method: "POST", body });
        await afterLogin(user);
      } catch {
        showLogin("账号或密码不正确，请重新输入。");
      }
    });
  }
  return { access, canView, canAction, showLogin, showApp, setAllowedNavigation, updateUserCard, bindLogin };
})();
