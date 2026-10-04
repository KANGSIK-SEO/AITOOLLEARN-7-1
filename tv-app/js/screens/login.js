const LoginScreen = (() => {
    const el = (id) => document.getElementById(id);
    let group;

    async function submit(kind) {
        el("auth-error").textContent = "";
        const body = { email: el("email").value.trim(), password: el("password").value };
        if (kind === "signup") {
            const code = el("private-code").value.trim();
            if (code) body.private_code = code;
        }
        const { ok, data } = await api(`/api/auth/${kind}`, { method: "POST", body: JSON.stringify(body) });
        if (!ok) {
            el("auth-error").textContent = errorMessage(data.error, "요청에 실패했습니다.");
            return;
        }
        setToken(data.token);
        el("password").value = "";
        el("private-code").value = "";
        window.onLoginSuccess(data.user);
    }

    function handleAction(action) {
        if (action === "back") return; // 로그인 화면에서 Back은 아무 동작 없음(최상위 화면)
        if (action === "ok") {
            const current = group.current();
            if (current.tagName === "BUTTON") current.click();
            return;
        }
        group.move(action);
    }

    function activate() {
        const elements = [el("email"), el("password"), el("private-code"), el("login-btn"), el("signup-btn")];
        group = createFocusGroup(elements, 1);
        window.activeScreenHandler = handleAction;
    }

    el("login-btn").addEventListener("click", () => submit("login"));
    el("signup-btn").addEventListener("click", () => submit("signup"));

    return { activate };
})();
