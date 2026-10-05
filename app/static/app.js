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
    GUEST_LIMIT_REACHED: "무료 체험을 모두 사용했어요. 가입하면 계속 이용할 수 있어요. / You've used up the free trial. Sign up to keep going.",
    FAVORITES_FULL: "즐겨찾기가 가득 찼어요. / Your favorites are full.",
    ARTWORK_NOT_FOUND: "작품을 찾을 수 없습니다. / Artwork not found.",
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
const MUSEUMS = { met: "The Metropolitan Museum of Art", aic: "Art Institute of Chicago" };
const PAGE_SIZE = 24;

let loggedIn = false;
const favorites = new Set();   // 로그인 사용자의 즐겨찾기 작품 id

function errorMessage(err, generic) {
    const code = err?.code;
    return (code && ERROR_MESSAGES[code]) || err?.message || generic;
}

function show(isLoggedIn, email, isPremium) {
    loggedIn = isLoggedIn;
    $("auth-panel").hidden = true;
    $("chat-panel").hidden = false;
    $("logout-btn").hidden = !isLoggedIn;
    $("favorites-btn").hidden = !isLoggedIn;
    $("open-auth-btn").hidden = isLoggedIn;
    $("guest-banner").hidden = isLoggedIn;
    $("status-bar").textContent = isLoggedIn
        ? `${email}${isPremium ? " · 초대코드 회원 / invite member" : ""}`
        : "가입 없이 체험해 보세요 / Try it without signing up";
    document.body.classList.toggle("light-theme", isLoggedIn && !!isPremium);
    if (isLoggedIn) loadFavorites(); else { favorites.clear(); refreshGuestBanner(); }
}

function openAuth(message) {
    $("auth-panel").hidden = false;
    $("chat-panel").hidden = true;
    $("auth-error").textContent = message || "";
}

function setGuestBanner(remaining) {
    $("guest-banner").textContent = remaining > 0
        ? `가입 없이 ${remaining}번 더 물어볼 수 있어요 · 가입하면 계속 이용하고 즐겨찾기도 쓸 수 있어요 / ${remaining} free question(s) left without signing up`
        : "무료 체험을 모두 사용했어요. 가입하면 계속 이용할 수 있어요. / Free trial used up — sign up to keep going.";
}

async function refreshGuestBanner() {
    const { ok, data } = await api("/api/guest");
    if (ok) setGuestBanner(data.remaining);
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

function renderStar(btn, id) {
    const on = favorites.has(id);
    btn.textContent = on ? "★" : "☆";
    btn.classList.toggle("on", on);
    btn.title = on ? "즐겨찾기 해제 / Remove from favorites" : "즐겨찾기 / Add to favorites";
}

async function toggleFavorite(w, btn) {
    if (!loggedIn) {
        openAuth("즐겨찾기는 가입 후 쓸 수 있어요. / Sign up to save favorites.");
        return;
    }
    const on = favorites.has(w.id);
    const { ok, data } = on
        ? await api(`/api/me/favorites/${w.id}`, { method: "DELETE" })
        : await api("/api/me/favorites", { method: "POST", body: JSON.stringify({ artwork_id: w.id }) });
    if (!ok) { flash(btn, "!"); addMessage("bot error", errorMessage(data.error, GENERIC_CHAT_ERROR)); return; }
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
        actionButton("확인서", "권리 확인서 보기·저장 / Rights record", () => {
            window.open(`/certificate/${w.id}`, "_blank", "noopener");
        }),
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
                if (!ok) { addMessage("bot error", errorMessage(data.error, GENERIC_CHAT_ERROR)); hasMore = false; break; }
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
    const { ok, data } = await api("/api/me/favorites");
    if (!ok) return [];
    favorites.clear();
    data.artworks.forEach((w) => favorites.add(w.id));
    document.querySelectorAll(".star").forEach((b) => renderStar(b, Number(b.dataset.id)));
    return data.artworks;
}

$("favorites-btn").addEventListener("click", async () => {
    const works = await loadFavorites();
    if (!works.length) {
        addMessage("bot", "아직 즐겨찾기한 작품이 없어요. 카드의 ☆를 눌러 모아보세요. / No favorites yet — tap ☆ on a card to save it.");
        return;
    }
    addResultGroup(works, null, `★ 내 즐겨찾기 ${works.length}개 / My favorites`);
});

// ---- 채팅 ----

async function sendMessage(message) {
    $("examples")?.remove();
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
        if (data.error?.code === "GUEST_LIMIT_REACHED") { setGuestBanner(0); openAuth(msg); }
        return;
    }
    addMessage("bot", data.reply);
    if (data.artworks.length) addResultGroup(data.artworks, data.search);
    if (data.guest_remaining !== undefined) setGuestBanner(data.guest_remaining);
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
$("open-auth-btn").addEventListener("click", () => openAuth());
$("close-auth-btn").addEventListener("click", () => { $("auth-panel").hidden = true; $("chat-panel").hidden = false; });
$("logout-btn").addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }); show(false); });

(async () => {
    const { ok, data } = await api("/api/me");
    show(ok, ok ? data.user.email : "", ok ? data.user.is_premium : false);
})();
