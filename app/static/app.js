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

// ---- 앱 설치 (PWA) ----
const SHARE_ICON = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M12 4l-4 4M12 4l4 4"/><path d="M5 10v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9"/></svg>`;
const ADD_ICON = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="M12 8v8M8 12h8"/></svg>`;
const MENU_ICON = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="19" r="1.5" fill="currentColor"/></svg>`;
const CHECK_ICON = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>`;

const IOS_STEPS = [
    [SHARE_ICON, "Safari 하단(또는 상단)의 공유 버튼을 탭하세요. / Tap the Share button in Safari."],
    [ADD_ICON, "아래로 스크롤해서 \"홈 화면에 추가\"를 선택하세요. / Scroll down and tap \"Add to Home Screen\"."],
    [CHECK_ICON, "오른쪽 위 \"추가\"를 탭하면 완료! / Tap \"Add\" in the top right to finish."],
];
const GENERIC_STEPS = [
    [MENU_ICON, "브라우저 메뉴(⋮)를 여세요. / Open the browser menu (⋮)."],
    [ADD_ICON, "\"앱 설치\" 또는 \"홈 화면에 추가\"를 선택하세요. / Tap \"Install app\" or \"Add to Home screen\"."],
];

function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
}
function isIOS() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent)
        || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}
function isMobile() {
    return isIOS() || /Android/i.test(navigator.userAgent);
}

function showInstallSteps(steps) {
    const list = $("install-steps");
    list.innerHTML = "";
    steps.forEach(([icon, text]) => {
        const li = document.createElement("li");
        const iconSpan = document.createElement("span");
        iconSpan.className = "step-icon";
        iconSpan.innerHTML = icon;
        const textSpan = document.createElement("span");
        textSpan.textContent = text;
        li.append(iconSpan, textSpan);
        list.appendChild(li);
    });
    $("install-modal").hidden = false;
}

const IOS_AUTO_PROMPT_KEY = "iosInstallPromptShown";

if (!isStandalone() && isMobile()) {
    $("install-banner").hidden = false;

    if (isIOS()) {
        let alreadyShown = false;
        try { alreadyShown = localStorage.getItem(IOS_AUTO_PROMPT_KEY) === "1"; } catch (_) { /* 프라이빗 모드 등 */ }
        if (!alreadyShown) {
            showInstallSteps(IOS_STEPS);
            try { localStorage.setItem(IOS_AUTO_PROMPT_KEY, "1"); } catch (_) { /* 저장 실패해도 무시 */ }
        }
    }

    let deferredPrompt = null;
    window.addEventListener("beforeinstallprompt", (e) => {
        e.preventDefault();
        deferredPrompt = e;
    });
    window.addEventListener("appinstalled", () => { $("install-banner").hidden = true; });

    $("install-btn").addEventListener("click", async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const choice = await deferredPrompt.userChoice;
            deferredPrompt = null;
            if (choice.outcome === "accepted") $("install-banner").hidden = true;
            return;
        }
        showInstallSteps(isIOS() ? IOS_STEPS : GENERIC_STEPS);
    });
    $("install-modal-close").addEventListener("click", () => { $("install-modal").hidden = true; });
    $("install-modal").addEventListener("click", (e) => {
        if (e.target.id === "install-modal") $("install-modal").hidden = true;
    });
}

// ---- 온디바이스 추천 (Datalog 규칙, 서버/AI 호출 없음) ----
function currentOnDeviceFilters() {
    const yearFrom = $("od-year-from").value.trim();
    const yearTo = $("od-year-to").value.trim();
    const subjects = $("od-subject").value.trim().toLowerCase()
        .split(",").map((s) => s.trim()).filter(Boolean);
    return {
        style: $("od-style").value,
        subjects,
        yearFrom: yearFrom ? Number(yearFrom) : null,
        yearTo: yearTo ? Number(yearTo) : null,
    };
}

function refreshRulePreview() {
    $("od-rule-preview").textContent = OnDevice.buildRuleText(currentOnDeviceFilters());
}

let onDeviceReady = false;
$("ondevice-toggle").addEventListener("click", async () => {
    const panel = $("ondevice-panel");
    panel.hidden = !panel.hidden;
    if (panel.hidden || onDeviceReady) return;
    const facts = await OnDevice.loadFacts();
    const styleSelect = $("od-style");
    OnDevice.styleOptions(facts).forEach((style) => {
        const opt = document.createElement("option");
        opt.value = style;
        opt.textContent = style;
        styleSelect.appendChild(opt);
    });
    onDeviceReady = true;
    refreshRulePreview();
});

["od-style", "od-subject", "od-year-from", "od-year-to"].forEach((id) => {
    $(id).addEventListener("input", refreshRulePreview);
});

$("od-parse-btn").addEventListener("click", () => {
    const text = $("od-freetext").value.trim();
    if (!text) return;
    const parsed = OnDevice.parseFreeText(text);
    $("od-style").value = parsed.style || "";
    $("od-subject").value = parsed.subjects.join(", ");
    $("od-year-from").value = parsed.yearFrom ?? "";
    $("od-year-to").value = parsed.yearTo ?? "";
    refreshRulePreview();
    const explain = parsed.matchedTerms.length
        ? parsed.matchedTerms.map(([ko, en]) => `"${ko}"→${en}`).join(", ")
        : "인식된 키워드가 없어요. 아래 조건을 직접 선택해보세요. / No recognized keywords — try the filters below.";
    addMessage("system", `🔤 키워드 사전으로 해석 (AI 없음) / Parsed via keyword dictionary, no AI: ${explain}`);
});

$("od-run-btn").addEventListener("click", async () => {
    const filters = currentOnDeviceFilters();
    const facts = await OnDevice.loadFacts();
    const works = OnDevice.evalRule(facts, filters);
    addMessage("system", `🧠 온디바이스 추천 (서버·AI 호출 없음, 브라우저에서 규칙 평가) / On-device recommendation (no server/AI call — evaluated in your browser)\n${OnDevice.buildRuleText(filters)}`);
    if (!works.length) {
        addMessage("bot", "조건에 맞는 작품이 없어요. 필터를 줄여보세요. / No matching works. Try loosening the filters.");
        return;
    }
    addCards(works);
});
