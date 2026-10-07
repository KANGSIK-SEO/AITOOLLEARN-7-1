function showScreen(name) {
    document.getElementById("screen-login").hidden = name !== "login";
    document.getElementById("screen-chat").hidden = name !== "chat";
    if (name === "login") LoginScreen.activate();
    else ChatScreen.activate();
}

window.onLoginSuccess = function (user) {
    document.getElementById("status-bar").textContent =
        `${user.email}${user.is_premium ? " · 초대코드 회원" : ""}`;
    showScreen("chat");
};

window.onLoggedOut = function () {
    clearToken();
    showScreen("login");
};

(async function boot() {
    if (!getToken()) { showScreen("login"); return; }
    const { ok, data } = await api("/api/me");
    if (!ok) { showScreen("login"); return; }
    window.onLoginSuccess(data.user);
})();
