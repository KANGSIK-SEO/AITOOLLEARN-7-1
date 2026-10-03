const $ = (id) => document.getElementById(id);
const chatLog = $("chat-log");

const ERROR_MESSAGES = {
    UNAUTHENTICATED: "로그인이 필요합니다. / Login required.",
    INVALID_EMAIL: "이메일 형식이 올바르지 않습니다. / That email address isn't valid.",
    INVALID_PASSWORD: "비밀번호는 8자 이상 128자 이하여야 합니다. / Password must be 8–128 characters.",
    EMAIL_TAKEN: "이미 가입된 이메일입니다. / This email is already registered.",
    INVALID_CREDENTIALS: "이메일 또는 비밀번호가 올바르지 않습니다. / Incorrect email or password.",
    RATE_LIMITED: "요청이 너무 많아요. 잠시 후 다시 시도해 주세요. / Too many requests. Please try again shortly.",
    EMPTY_MESSAGE: "질문을 입력해 주세요. / Please enter a question.",
    MESSAGE_TOO_LONG: "질문이 너무 길어요. / Your question is too long.",
    INVALID_INPUT: "허용되지 않는 입력입니다. / That input isn't allowed.",
    AI_BACKED_OFF: "AI 서비스가 일시적으로 쉬고 있어요. 잠시 후 다시 시도해 주세요. / The AI service is taking a short break. Please try again shortly.",
    FREE_LIMIT_REACHED: "무료 이용 횟수를 모두 사용했어요. 초대코드가 있다면 입력해 보세요. / You've used up your free questions. Try entering an invite code.",
    DB_ERROR: "데이터베이스에 문제가 생겼어요. 잠시 후 다시 시도해 주세요. / There was a database problem. Please try again shortly.",
    INTERNAL_ERROR: "예상치 못한 오류가 발생했어요. 잠시 후 다시 시도해 주세요. / An unexpected error occurred. Please try again shortly.",
    ART_DB_ERROR: "작품 데이터베이스를 읽지 못했어요. / Couldn't read the artwork database.",
    AI_TIMEOUT: "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요. / The response is taking too long. Please try again shortly.",
    AI_RATE_LIMITED: "AI 서비스 요청이 많아 잠시 제한되었어요. 잠시 후 다시 시도해 주세요. / The AI service is rate-limited right now. Please try again shortly.",
    AI_KEY_MISSING: "AI 서비스 인증에 실패했어요. / AI service authentication failed.",
    AI_ERROR: "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요. / Couldn't reach the AI server. Please try again shortly.",
};
const GENERIC_AUTH_ERROR = "요청에 실패했습니다. / Request failed.";
const GENERIC_CHAT_ERROR = "오류가 발생했습니다. / Something went wrong.";

function errorMessage(err, generic) {
    const code = err?.code;
    return (code && ERROR_MESSAGES[code]) || err?.message || generic;
}

function show(loggedIn, email, isPremium) {
    $("auth-panel").hidden = loggedIn;
    $("chat-panel").hidden = !loggedIn;
    $("logout-btn").hidden = !loggedIn;
    $("status-bar").textContent = loggedIn
        ? `${email}${isPremium ? " · 초대코드 회원 / invite member" : ""}`
        : "로그인이 필요합니다 / Login required";
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
        $("auth-error").textContent = errorMessage(data.error, GENERIC_AUTH_ERROR);
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
        [["원본 이미지 / Original image", w.image_url], ["출처 페이지 / Source page", w.source_url]].forEach(([label, href], n) => {
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
    const pending = addMessage("bot typing", "명화를 찾는 중… / Searching…");
    $("send-btn").disabled = true;
    const { ok, status, data } = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    pending.remove();
    $("send-btn").disabled = false;
    if (status === 401) { show(false); return; }
    if (!ok) {
        const msg = errorMessage(data.error, GENERIC_CHAT_ERROR);
        addMessage("bot error", `${msg} (${data.error?.code || status})`);
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
