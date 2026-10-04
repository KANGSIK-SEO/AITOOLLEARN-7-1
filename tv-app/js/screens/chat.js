const ChatScreen = (() => {
    const el = (id) => document.getElementById(id);
    const chatLog = () => el("chat-log");

    let zone = "composer";
    let groups = {};
    let lastArtworks = [];

    function addMessage(kind, text) {
        const div = document.createElement("div");
        div.className = `message ${kind}`;
        div.textContent = text; // XSS 방지: 항상 textContent
        chatLog().appendChild(div);
        chatLog().scrollTop = chatLog().scrollHeight;
        return div;
    }

    function addCards(works) {
        lastArtworks = works;
        const container = document.createElement("div");
        container.className = "cards";
        works.forEach((w, i) => {
            const card = document.createElement("div");
            card.className = "card focusable";
            card.dataset.index = i;
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
            meta.append(title, sub, badge);
            card.append(img, meta);
            container.appendChild(card);
        });
        chatLog().appendChild(container);
        chatLog().scrollTop = chatLog().scrollHeight;
        groups.cards = createFocusGroup(Array.from(container.querySelectorAll(".card")), 4);
    }

    function showDetail(work) {
        el("detail-img").src = work.thumbnail_url || work.image_url;
        el("detail-title").textContent = work.title;
        el("detail-sub").textContent = [work.artist, work.date_display].filter(Boolean).join(" · ");
        el("detail-badge").textContent = `${work.license} · ${work.source.toUpperCase()} · ${work.source_url}`;
        el("detail-overlay").hidden = false;
    }

    function hideDetail() { el("detail-overlay").hidden = true; }

    async function send() {
        const input = el("message-input");
        const message = input.value.trim();
        if (!message) return;
        input.value = "";
        addMessage("user", message);
        const pending = addMessage("bot", "명화를 찾는 중…");
        el("send-btn").disabled = true;
        const { ok, status, data } = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
        pending.remove();
        el("send-btn").disabled = false;
        if (status === 401) { window.onLoggedOut(); return; }
        if (!ok) {
            addMessage("bot error", `${errorMessage(data.error, "오류가 발생했습니다.")} (${(data.error && data.error.code) || status})`);
            return;
        }
        addMessage("bot", data.reply);
        if (data.artworks && data.artworks.length) {
            addCards(data.artworks);
            zone = "cards"; // 카드가 새로 생기면 포커스 영역을 카드 그리드로 옮긴다
        }
    }

    async function logout() {
        await api("/api/auth/logout", { method: "POST" });
        clearToken();
        window.onLoggedOut();
    }

    function handleAction(action) {
        if (!el("detail-overlay").hidden) {
            if (action === "ok" || action === "back") hideDetail();
            return;
        }
        if (action === "back") {
            if (typeof tizen !== "undefined" && tizen.application) {
                tizen.application.getCurrentApplication().exit();
            }
            return;
        }
        if (action === "ok") {
            const current = groups[zone].current();
            if (!current) return;
            if (current.id === "logout-btn") logout();
            else if (current.id === "send-btn" || current.id === "message-input") send();
            else if (current.classList.contains("card")) showDetail(lastArtworks[Number(current.dataset.index)]);
            return;
        }
        if (action === "up") {
            if (zone === "cards" && groups.cards.current() && Number(groups.cards.current().dataset.index) < 4) zone = "composer";
            else if (zone === "composer") zone = "header";
            else groups[zone].move("up");
            return;
        }
        if (action === "down") {
            if (zone === "header") zone = "composer";
            else if (zone === "composer" && groups.cards) zone = "cards";
            else groups[zone].move("down");
            return;
        }
        groups[zone].move(action); // left/right는 현재 영역 안에서만
    }

    function activate() {
        groups = {
            header: createFocusGroup([el("logout-btn")], 1),
            composer: createFocusGroup([el("message-input"), el("send-btn")], 2),
            cards: createFocusGroup([], 4),
        };
        zone = "composer";
        groups.composer.setIndex(0);
        window.activeScreenHandler = handleAction;
    }

    el("send-btn").addEventListener("click", send);
    el("message-input").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
    el("logout-btn").addEventListener("click", logout);
    el("detail-overlay").addEventListener("click", hideDetail);

    return { activate, addMessage, addCards };
})();
