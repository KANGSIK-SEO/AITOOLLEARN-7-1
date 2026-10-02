const $ = (id) => document.getElementById(id);
const chatLog = $("chat-log");

function show(loggedIn, email, isPremium) {
    $("auth-panel").hidden = loggedIn;
    $("chat-panel").hidden = !loggedIn;
    $("logout-btn").hidden = !loggedIn;
    $("status-bar").textContent = loggedIn ? `${email} 님${isPremium ? " · 초대코드 회원" : ""}` : "로그인이 필요합니다";
    document.body.classList.toggle("light-theme", loggedIn && !!isPremium);
}

async function api(path, options = {}) {
    const res = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        ...options,
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
    return { ok: res.ok, status: res.status, data };
}

async function submitAuth(kind) {
    $("auth-error").textContent = "";
    const body = { email: $("email").value, password: $("password").value };
    if (kind === "signup") {
        const code = $("private-code").value.trim();
        if (code) body.private_code = code;
    }
    const { ok, data } = await api(`/api/auth/${kind}`, { method: "POST", body: JSON.stringify(body) });
    if (!ok) {
        $("auth-error").textContent = data.error?.message || "요청에 실패했습니다.";
        return;
    }
    $("password").value = "";
    $("private-code").value = "";
    show(true, data.user.email, data.user.is_premium);
}

function addMessage(kind, text) {
    const div = document.createElement("div");
    div.className = `message ${kind}`;
    div.textContent = text;   // 사용자·AI 텍스트는 항상 textContent로 넣어 XSS를 막는다
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    return div;
}

function addCards(works) {
    if (!works.length) return;
    const wrap = document.createElement("div");
    wrap.className = "cards";
    works.forEach((w, i) => {
        const card = document.createElement("div");
        card.className = "card";
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = w.title;
        img.src = w.thumbnail_url || w.image_url;
        const meta = document.createElement("div");
        meta.className = "meta";
        const title = document.createElement("div");
        title.className = "title";
        title.textContent = `[${i + 1}] ${w.title}`;
        const sub = document.createElement("div");
        sub.className = "sub";
        sub.textContent = [w.artist, w.date_display].filter(Boolean).join(" · ");
        const badge = document.createElement("span");
        badge.className = "badge";
        badge.textContent = `${w.license} · ${w.source.toUpperCase()}`;
        const links = document.createElement("div");
        [["원본 이미지", w.image_url], ["출처 페이지", w.source_url]].forEach(([label, href], n) => {
            if (n) links.append(" · ");
            const a = document.createElement("a");
            a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = label;
            links.append(a);
        });
        meta.append(title, sub, badge, links);
        card.append(img, meta);
        wrap.appendChild(card);
    });
    chatLog.appendChild(wrap);
    chatLog.scrollTop = chatLog.scrollHeight;
}

$("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = $("message-input").value.trim();
    if (!message) return;               // 빈 입력 차단 (서버에서도 검증)
    $("message-input").value = "";
    addMessage("user", message);
    const pending = addMessage("bot typing", "명화를 찾는 중…");
    $("send-btn").disabled = true;
    const { ok, status, data } = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    pending.remove();
    $("send-btn").disabled = false;
    if (status === 401) { show(false); return; }
    if (!ok) {
        addMessage("bot error", `${data.error?.message || "오류가 발생했습니다."} (${data.error?.code || status})`);
        return;
    }
    addMessage("bot", data.reply);
    addCards(data.artworks);
});

$("login-btn").addEventListener("click", () => submitAuth("login"));
$("signup-btn").addEventListener("click", () => submitAuth("signup"));
$("logout-btn").addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }); show(false); });

(async () => {
    const { ok, data } = await api("/api/me");
    show(ok, ok ? data.user.email : "", ok ? data.user.is_premium : false);
})();
