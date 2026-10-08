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
    AI_REFUSED: "이 질문에는 답할 수 없어요. 질문을 바꿔 다시 시도해 주세요. / I can't answer this question. Please rephrase and try again.",
    AI_RATE_LIMITED: "AI 서비스 요청이 많아 잠시 제한되었어요. 잠시 후 다시 시도해 주세요. / The AI service is rate-limited right now. Please try again shortly.",
    AI_KEY_MISSING: "AI 서비스 인증에 실패했어요. / AI service authentication failed.",
    AI_ERROR: "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요. / Couldn't reach the AI server. Please try again shortly.",
    ARTWORK_NOT_FOUND: "작품을 찾을 수 없습니다. / Artwork not found.",
    RECORD_NOT_ALLOWED: "이 작품은 판단 규칙을 통과하지 못해 권리 근거 기록을 발급할 수 없어요. / This artwork didn't pass our rights rules.",
};
const GENERIC_AUTH_ERROR = "요청에 실패했습니다. / Request failed.";
const GENERIC_CHAT_ERROR = "오류가 발생했습니다. / Something went wrong.";
const MUSEUMS = { met: "The Metropolitan Museum of Art", aic: "Art Institute of Chicago", cma: "Cleveland Museum of Art" };
const PAGE_SIZE = 24;

let loggedIn = false;
const favorites = new Set();   // 로그인 사용자의 즐겨찾기 작품 id

function errorMessage(err, generic) {
    const code = err?.code;
    return (code && ERROR_MESSAGES[code]) || err?.message || generic;
}

function show(isLoggedIn, email, isPremium) {
    loggedIn = isLoggedIn;
    $("auth-panel").hidden = isLoggedIn;
    $("chat-panel").hidden = !isLoggedIn;
    $("logout-btn").hidden = !isLoggedIn;
    $("favorites-btn").hidden = !isLoggedIn;
    // '본문으로 건너뛰기'는 지금 보이는 패널로 보낸다 (숨겨진 패널로 보내면 포커스가 움직이지 않는다)
    const skip = $("skip-link");
    if (skip) skip.setAttribute("href", isLoggedIn ? "#chat-panel" : "#auth-panel");
    if (isLoggedIn) loadFavorites(); else favorites.clear();
    $("status-bar").textContent = isLoggedIn
        ? `${email}${isPremium ? " · 초대코드 회원 / invite member" : ""}`
        : "로그인이 필요합니다 / Login required";
    document.body.classList.toggle("light-theme", isLoggedIn && !!isPremium);
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
    div.setAttribute("role", "article");
    const content = document.createElement("span");
    content.textContent = text;   // 사용자·AI 텍스트는 항상 textContent로 넣어 XSS를 막는다
    const timestamp = new Date();
    const time = document.createElement("time");
    time.className = "message-time";
    time.dateTime = timestamp.toISOString();
    time.textContent = timestamp.toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
    });
    time.setAttribute("aria-label", `보낸 시간 ${time.textContent}`);
    div.append(content, time);
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    return div;
}

const STATUS_MESSAGE_TYPES = new Set(["error", "success", "warning"]);

function addStatusMessage(type, text) {
    if (!STATUS_MESSAGE_TYPES.has(type)) {
        throw new TypeError(`지원하지 않는 상태 메시지 유형입니다: ${type}`);
    }
    return addMessage(`message-status ${type}`, text);
}

function addTypingIndicator() {
    const indicator = document.createElement("div");
    indicator.className = "message bot typing";
    indicator.setAttribute("role", "status");
    indicator.setAttribute("aria-label", "명화 검색 중 / Searching for masterpieces");

    const label = document.createElement("span");
    label.textContent = "명화를 찾는 중… / Searching…";
    const dots = document.createElement("span");
    dots.className = "typing-dots";
    dots.setAttribute("aria-hidden", "true");
    for (let i = 0; i < 3; i += 1) {
        dots.appendChild(document.createElement("span"));
    }

    indicator.append(label, dots);
    chatLog.appendChild(indicator);
    chatLog.scrollTop = chatLog.scrollHeight;
    return indicator;
}

// ---- 작품 카드 ----

function creditLine(w) {
    const parts = [`"${w.title}"`, w.artist || "Unknown artist"];
    if (w.date_display) parts.push(w.date_display);
    return `${parts.join(", ")}. ${MUSEUMS[w.source] || w.source.toUpperCase()}, CC0 (Public Domain). ${w.source_url}`;
}

async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (_) {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        const done = document.execCommand("copy");
        ta.remove();
        return done;
    }
}

function flash(btn, text) {
    const original = btn.textContent;
    btn.textContent = text;
    setTimeout(() => { btn.textContent = original; }, 1500);
}

async function download(w, btn) {
    // AIC는 우리 서버 프록시가 첨부파일로 내려준다. MET는 원본 서버에서 받아 저장을 시도하고, 막히면 새 탭으로 연다.
    if (w.source === "aic") {
        const a = document.createElement("a");
        a.href = `${w.image_url}&download=1`;
        a.click();
        return;
    }
    btn.disabled = true;
    try {
        const res = await fetch(w.image_url);
        if (!res.ok) throw new Error(String(res.status));
        const url = URL.createObjectURL(await res.blob());
        const a = document.createElement("a");
        a.href = url;
        a.download = `met-${w.id}.jpg`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (_) {
        window.open(w.image_url, "_blank", "noopener");
    } finally {
        btn.disabled = false;
    }
}

async function issueRecord(w, btn) {
    // 서버 응답을 기다린 뒤 새 탭을 열면 팝업 차단에 걸려서, 탭을 먼저 열어두고 주소만 나중에 넣는다
    const tab = window.open("", "_blank");
    if (tab) tab.document.write("<p style='font-family:sans-serif;padding:24px'>권리 근거 기록을 만들고 인터넷 아카이브에 보관을 요청하는 중… (10초 정도)</p>");
    btn.disabled = true;
    const original = btn.textContent;
    btn.textContent = "발급 중…";
    const { ok, data } = await api("/api/records", { method: "POST", body: JSON.stringify({ artwork_id: w.id }) });
    btn.disabled = false;
    btn.textContent = original;
    if (!ok) {
        if (tab) tab.close();
        addStatusMessage("error", errorMessage(data.error, GENERIC_CHAT_ERROR));
        return;
    }
    if (tab) tab.location.href = data.url; else window.location.href = data.url;
}

function renderStar(btn, id) {
    const on = favorites.has(id);
    btn.textContent = on ? "★" : "☆";
    btn.classList.toggle("on", on);
    btn.title = on ? "즐겨찾기 해제 / Remove from favorites" : "즐겨찾기 / Add to favorites";
}

async function toggleFavorite(w, btn) {
    if (!loggedIn) {
        show(false);
        return;
    }
    const on = favorites.has(w.id);
    const { ok, data } = on
        ? await api(`/api/favorites/${w.id}`, { method: "DELETE" })
        : await api("/api/favorites", { method: "POST", body: JSON.stringify({ artwork_id: w.id }) });
    if (!ok) { flash(btn, "!"); addStatusMessage("error", errorMessage(data.error, GENERIC_CHAT_ERROR)); return; }
    if (on) favorites.delete(w.id); else favorites.add(w.id);
    document.querySelectorAll(`.star[data-id="${w.id}"]`).forEach((b) => renderStar(b, w.id));
}

function actionButton(label, title, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "card-btn";
    b.textContent = label;
    b.title = title;
    b.addEventListener("click", () => onClick(b));
    return b;
}

function makeCard(w, index) {
    const card = document.createElement("div");
    card.className = "card";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = w.title;
    img.src = w.thumbnail_url || w.image_url;
    const orient = document.createElement("span");
    orient.className = "orient";
    // 이미지 비율로 가로형/세로형을 판별한다 (PPT 배경은 가로형이 필요)
    img.addEventListener("load", () => {
        const r = img.naturalWidth / img.naturalHeight;
        const kind = r >= 1.15 ? "landscape" : r <= 0.87 ? "portrait" : "square";
        card.dataset.orient = kind;
        orient.textContent = { landscape: "가로형", portrait: "세로형", square: "정사각" }[kind];
    });
    const meta = document.createElement("div");
    meta.className = "meta";
    const title = document.createElement("div");
    title.className = "title";
    title.textContent = `[${index}] ${w.title}`;
    const sub = document.createElement("div");
    sub.className = "sub";
    sub.textContent = [w.artist, w.date_display].filter(Boolean).join(" · ");
    const badges = document.createElement("div");
    badges.className = "badges";
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = `${w.license} · ${w.source.toUpperCase()}`;
    badges.append(badge, orient);

    const actions = document.createElement("div");
    actions.className = "card-actions";
    const star = actionButton("☆", "", (b) => toggleFavorite(w, b));
    star.classList.add("star");
    star.dataset.id = w.id;
    renderStar(star, w.id);
    actions.append(
        star,
        actionButton("⬇", "고화질 다운로드 / Download", (b) => download(w, b)),
        actionButton("출처 복사", "출처 표기 문구 복사 / Copy credit line", async (b) => {
            flash(b, (await copyText(creditLine(w))) ? "복사됨 ✓" : "실패");
        }),
        actionButton("근거 기록", "권리 근거 기록 발급·저장 / Rights evidence record", (b) => issueRecord(w, b)),
    );

    const links = document.createElement("div");
    [["원본 / Original", w.image_url], ["출처 / Source", w.source_url]].forEach(([label, href], n) => {
        if (n) links.append(" · ");
        const a = document.createElement("a");
        a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = label;
        links.append(a);
    });
    meta.append(title, sub, badges, actions, links);
    card.append(img, meta);
    return card;
}

// 결과 묶음: 비율 필터 + 카드 격자 + (검색 조건이 있으면) '더 보기'
function addResultGroup(works, search, heading) {
    const group = document.createElement("div");
    group.className = "result-group";
    const seen = new Set();
    let count = 0;

    const toolbar = document.createElement("div");
    toolbar.className = "group-toolbar";
    const label = heading || (search?.purpose ? `용도: ${search.purpose}` : "");
    if (label) {
        const h = document.createElement("span");
        h.className = "group-heading";
        h.textContent = label;
        toolbar.append(h);
    }
    const select = document.createElement("select");
    select.title = "이미지 비율 / Image shape";
    [["all", "전체 비율 / All shapes"], ["landscape", "가로형만 (PPT·배너) / Landscape"],
     ["portrait", "세로형만 (포스터·액자) / Portrait"], ["square", "정사각만 (SNS) / Square"]]
        .forEach(([v, label]) => select.append(new Option(label, v)));
    select.value = search?.orientation || "all";
    group.dataset.filter = select.value;
    select.addEventListener("change", () => { group.dataset.filter = select.value; });
    toolbar.append(select);

    const grid = document.createElement("div");
    grid.className = "cards";
    const append = (list) => {
        let added = 0;
        list.forEach((w) => {
            if (seen.has(w.id)) return;
            seen.add(w.id);
            grid.appendChild(makeCard(w, ++count));
            added++;
        });
        return added;
    };
    append(works);
    group.append(toolbar, grid);

    if (search) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "more-btn";
        more.textContent = "작품 더 보기 / More artworks";
        let offset = 0;
        more.addEventListener("click", async () => {
            more.disabled = true;
            more.textContent = "불러오는 중… / Loading…";
            const params = new URLSearchParams({ q: (search.keywords || []).join(","), limit: PAGE_SIZE });
            if (search.artist) params.set("artist", search.artist);
            if (search.year_from != null) params.set("year_from", search.year_from);
            if (search.year_to != null) params.set("year_to", search.year_to);
            let hasMore = true;
            let added = 0;
            // 첫 페이지는 이미 보여준 작품과 겹칠 수 있어, 새 작품이 나올 때까지 몇 페이지 더 넘긴다
            for (let tries = 0; tries < 3 && hasMore && added === 0; tries++) {
                params.set("offset", offset);
                const { ok, data } = await api(`/api/artworks?${params}`);
                if (!ok) { addStatusMessage("error", errorMessage(data.error, GENERIC_CHAT_ERROR)); hasMore = false; break; }
                offset += PAGE_SIZE;
                hasMore = data.has_more;
                added += append(data.artworks);
            }
            more.disabled = false;
            more.textContent = "작품 더 보기 / More artworks";
            if (!hasMore) more.remove();
        });
        group.append(more);
    }
    chatLog.appendChild(group);
    chatLog.scrollTop = chatLog.scrollHeight;
}

// ---- 즐겨찾기 ----

async function loadFavorites() {
    const { ok, data } = await api("/api/me/favorites?limit=100");
    if (!ok) return [];
    favorites.clear();
    data.favorites.forEach((w) => favorites.add(w.id));
    document.querySelectorAll(".star").forEach((b) => renderStar(b, Number(b.dataset.id)));
    return data.favorites;
}

$("favorites-btn").addEventListener("click", async () => {
    const works = await loadFavorites();
    if (!works.length) {
        addMessage("bot", "아직 즐겨찾기한 작품이 없어요. 카드의 ☆를 눌러 모아보세요. / No favorites yet — tap ☆ on a card to save it.");
        return;
    }
    addResultGroup(works, null, `★ 내 즐겨찾기 ${works.length}개 / My favorites`);
});

function addCards(works) {   // 온디바이스 추천처럼 검색 조건 없이 카드만 보여줄 때
    addResultGroup(works, null);
}

function showLimitWarning(data) {
    if (!data.show_limit_warning) return;
    addStatusMessage("warning",
        `무료 질문이 ${data.remaining_free}개 남았어요. 초대코드가 있다면 입력해 보세요. / ` +
        `${data.remaining_free} free questions left. Enter an invite code if you have one.`);
}

function showChatError(status, error) {
    const msg = errorMessage(error, GENERIC_CHAT_ERROR);
    addStatusMessage("error", `${msg} (${error?.code || status})`);
}

// 답을 한 번에 받는 방식 — 스트리밍을 못 쓰는 브라우저·연결에서 쓴다
async function sendMessageOnce(message, pending) {
    const { ok, status, data } = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    pending.remove();
    if (status === 401) { show(false); return; }
    if (!ok) { showChatError(status, data.error); return; }
    addMessage("bot", data.reply);
    if (data.artworks.length) addResultGroup(data.artworks, data.search);
    showLimitWarning(data);
}

// 스트리밍: 검색이 끝나면 작품 카드부터 보여주고, 답변 글은 만들어지는 대로 이어 붙인다
async function sendMessageStream(message, pending) {
    let res;
    try {
        res = await fetch("/api/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ message }),
        });
    } catch (_) {
        return sendMessageOnce(message, pending);   // 연결 자체가 안 되면 한 번에 받기로 다시 시도
    }
    if (res.status === 401) { pending.remove(); show(false); return; }
    if (!res.ok || !res.body) {
        let data = {};
        try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
        pending.remove();
        showChatError(res.status, data.error);
        return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let text = null;   // 답변 글이 들어갈 자리 (meta를 받으면 만든다)
    let meta = null;
    const handle = (event) => {
        if (event.type === "meta") {
            meta = event;
            pending.remove();
            const bubble = addMessage("bot", "");
            text = bubble.querySelector("span");
            text.textContent = "답변을 쓰는 중… / Writing…";
            text.dataset.empty = "1";
            if (event.artworks.length) addResultGroup(event.artworks, event.search);
        } else if (event.type === "delta" && text) {
            if (text.dataset.empty) { text.textContent = ""; delete text.dataset.empty; }
            text.textContent += event.text;   // textContent로만 넣어 XSS를 막는다
        } else if (event.type === "error") {
            if (text && text.dataset.empty) text.closest(".message").remove();
            showChatError(500, { code: event.code, message: event.message });
        }
    };
    try {
        for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let nl;
            while ((nl = buffer.indexOf("\n")) >= 0) {
                const line = buffer.slice(0, nl).trim();
                buffer = buffer.slice(nl + 1);
                if (line) handle(JSON.parse(line));
            }
        }
    } catch (_) {
        pending.remove();
        addStatusMessage("error", "답변을 받는 중 연결이 끊겼어요. 다시 시도해 주세요. / The connection dropped. Please try again.");
        return;
    }
    if (meta) showLimitWarning(meta); else pending.remove();
}

async function sendMessage(message) {
    $("examples")?.remove();
    addMessage("user", message);
    const pending = addTypingIndicator();
    $("send-btn").disabled = true;
    try {
        await sendMessageStream(message, pending);
    } finally {
        $("send-btn").disabled = false;
    }
}

$("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const message = $("message-input").value.trim();
    if (!message) return;               // 빈 입력 차단 (서버에서도 검증)
    $("message-input").value = "";
    sendMessage(message);
});

document.querySelectorAll("#examples .chip").forEach((chip) =>
    chip.addEventListener("click", () => sendMessage(chip.textContent)));

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
    const isOpen = panel.classList.toggle("is-open");
    $("ondevice-toggle").setAttribute("aria-expanded", String(isOpen));
    if (!isOpen) {
        panel.classList.remove("is-visible");
        const finishClose = (event) => {
            if (event.propertyName === "max-height" && !panel.classList.contains("is-open")) {
                panel.hidden = true;
                panel.removeEventListener("transitionend", finishClose);
            }
        };
        panel.addEventListener("transitionend", finishClose);
        return;
    }
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add("is-visible"));
    if (onDeviceReady) return;
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
