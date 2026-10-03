const $ = (id) => document.getElementById(id);
const chatLog = $("chat-log");

const I18N = {
    ko: {
        title: "저작권 걱정 없는 퍼블릭 도메인 명화 찾기 챗봇",
        headerTitle: "🖼️ 저작권 걱정 없는 퍼블릭 도메인 명화 찾기",
        loginRequired: "로그인이 필요합니다",
        logout: "로그아웃",
        hint: '상업적으로 써도 되는 CC0 명화를 한국어로 물어보세요.<br>(MET · Art Institute of Chicago 공개 데이터)',
        emailPlaceholder: "이메일",
        passwordPlaceholder: "비밀번호 (8자 이상)",
        privateCodePlaceholder: "초대코드 (선택, 회원가입 시에만 적용)",
        login: "로그인",
        signup: "회원가입",
        greeting: '안녕하세요! 어떤 명화를 찾으세요?<br>예) "봄 느낌 풍경화 보여줘", "모네 작품 중 물이 나오는 그림"',
        messagePlaceholder: "질문을 입력하세요 (최대 500자)",
        typing: "명화를 찾는 중…",
        genericAuthError: "요청에 실패했습니다.",
        genericChatError: "오류가 발생했습니다.",
        statusSuffix: " 님",
        premiumSuffix: " · 초대코드 회원",
        originalImage: "원본 이미지",
        sourcePage: "출처 페이지",
        errors: {
            UNAUTHENTICATED: "로그인이 필요합니다.",
            INVALID_EMAIL: "이메일 형식이 올바르지 않습니다.",
            INVALID_PASSWORD: "비밀번호는 8자 이상 128자 이하여야 합니다.",
            EMAIL_TAKEN: "이미 가입된 이메일입니다.",
            INVALID_CREDENTIALS: "이메일 또는 비밀번호가 올바르지 않습니다.",
            RATE_LIMITED: "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
            EMPTY_MESSAGE: "질문을 입력해 주세요.",
            MESSAGE_TOO_LONG: "질문이 너무 길어요.",
            INVALID_INPUT: "허용되지 않는 입력입니다.",
            AI_BACKED_OFF: "AI 서비스가 일시적으로 쉬고 있어요. 잠시 후 다시 시도해 주세요.",
            FREE_LIMIT_REACHED: "무료 이용 횟수를 모두 사용했어요. 초대코드가 있다면 입력해 보세요.",
            DB_ERROR: "데이터베이스에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.",
            INTERNAL_ERROR: "예상치 못한 오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
            ART_DB_ERROR: "작품 데이터베이스를 읽지 못했어요.",
            AI_TIMEOUT: "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
            AI_RATE_LIMITED: "AI 서비스 요청이 많아 잠시 제한되었어요. 잠시 후 다시 시도해 주세요.",
            AI_KEY_MISSING: "AI 서비스 인증에 실패했어요.",
            AI_ERROR: "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.",
        },
    },
    en: {
        title: "Copyright-Free Public Domain Masterpiece Finder",
        headerTitle: "🖼️ Public Domain Masterpiece Finder",
        loginRequired: "Login required",
        logout: "Log out",
        hint: 'Ask (in English or Korean) for CC0 masterpieces you can use commercially.<br>(Open data from the MET and the Art Institute of Chicago)',
        emailPlaceholder: "Email",
        passwordPlaceholder: "Password (8+ characters)",
        privateCodePlaceholder: "Invite code (optional, sign-up only)",
        login: "Log in",
        signup: "Sign up",
        greeting: 'Hi! What masterpiece are you looking for?<br>e.g. "Show me a spring landscape", "Monet paintings with water"',
        messagePlaceholder: "Type your question (max 500 characters)",
        typing: "Searching for masterpieces…",
        genericAuthError: "Request failed.",
        genericChatError: "Something went wrong.",
        statusSuffix: "",
        premiumSuffix: " · invite member",
        originalImage: "Original image",
        sourcePage: "Source page",
        errors: {
            UNAUTHENTICATED: "Login required.",
            INVALID_EMAIL: "That email address isn't valid.",
            INVALID_PASSWORD: "Password must be 8–128 characters.",
            EMAIL_TAKEN: "This email is already registered.",
            INVALID_CREDENTIALS: "Incorrect email or password.",
            RATE_LIMITED: "Too many requests. Please try again shortly.",
            EMPTY_MESSAGE: "Please enter a question.",
            MESSAGE_TOO_LONG: "Your question is too long.",
            INVALID_INPUT: "That input isn't allowed.",
            AI_BACKED_OFF: "The AI service is taking a short break. Please try again shortly.",
            FREE_LIMIT_REACHED: "You've used up your free questions. Try entering an invite code.",
            DB_ERROR: "There was a database problem. Please try again shortly.",
            INTERNAL_ERROR: "An unexpected error occurred. Please try again shortly.",
            ART_DB_ERROR: "Couldn't read the artwork database.",
            AI_TIMEOUT: "The response is taking too long. Please try again shortly.",
            AI_RATE_LIMITED: "The AI service is rate-limited right now. Please try again shortly.",
            AI_KEY_MISSING: "AI service authentication failed.",
            AI_ERROR: "Couldn't reach the AI server. Please try again shortly.",
        },
    },
};

function loadLang() {
    try {
        const saved = localStorage.getItem("lang");
        if (saved === "ko" || saved === "en") return saved;
    } catch (_) { /* 프라이빗 모드 등에서 접근 불가 */ }
    return "ko";
}

let lang = loadLang();

function t() { return I18N[lang]; }

function errorMessage(err, generic) {
    const code = err?.code;
    return (code && t().errors[code]) || err?.message || generic;
}

function applyLang() {
    document.documentElement.lang = lang;
    document.title = t().title;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.innerHTML = t()[el.dataset.i18n];
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        el.placeholder = t()[el.dataset.i18nPlaceholder];
    });
}

function toggleLang() {
    lang = lang === "ko" ? "en" : "ko";
    try { localStorage.setItem("lang", lang); } catch (_) { /* 저장 실패해도 세션 내 동작은 유지 */ }
    applyLang();
}

function show(loggedIn, email, isPremium) {
    $("auth-panel").hidden = loggedIn;
    $("chat-panel").hidden = !loggedIn;
    $("logout-btn").hidden = !loggedIn;
    $("status-bar").textContent = loggedIn
        ? `${email}${t().statusSuffix}${isPremium ? t().premiumSuffix : ""}`
        : t().loginRequired;
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
        $("auth-error").textContent = errorMessage(data.error, t().genericAuthError);
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
        [[t().originalImage, w.image_url], [t().sourcePage, w.source_url]].forEach(([label, href], n) => {
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
    const pending = addMessage("bot typing", t().typing);
    $("send-btn").disabled = true;
    const { ok, status, data } = await api("/api/chat", { method: "POST", body: JSON.stringify({ message, lang }) });
    pending.remove();
    $("send-btn").disabled = false;
    if (status === 401) { show(false); return; }
    if (!ok) {
        const msg = errorMessage(data.error, t().genericChatError);
        addMessage("bot error", `${msg} (${data.error?.code || status})`);
        return;
    }
    addMessage("bot", data.reply);
    addCards(data.artworks);
});

$("login-btn").addEventListener("click", () => submitAuth("login"));
$("signup-btn").addEventListener("click", () => submitAuth("signup"));
$("logout-btn").addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }); show(false); });
$("lang-toggle").addEventListener("click", toggleLang);

applyLang();

(async () => {
    const { ok, data } = await api("/api/me");
    show(ok, ok ? data.user.email : "", ok ? data.user.is_premium : false);
})();
