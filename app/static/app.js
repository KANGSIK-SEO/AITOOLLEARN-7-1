// 명화 찾기 — 화면 로직 (프레임워크·빌드 도구 없이 바닐라 JS 한 파일)
//
// 목차
//   1. 설정값 · 공통 도구        — 상수, DOM 도우미($, el, icon, button), 토스트, 저장소
//   2. 다국어(i18n)              — 한/영 문구, 서버 오류 문구, 언어 전환 시 다시 그리기
//   3. 서버 API                  — 모든 fetch는 api() 한 곳을 지난다. 답변 스트리밍(NDJSON) 읽기
//   4. 화면 상태 · 로그인        — state, 로그인/가입, 로그인 전후 화면 전환
//   5. 랜딩: 컬렉션 미리보기     — 로그인 없이 쓰는 공개 API로 작품 둘러보기
//   6. 작품 카드                 — 카드, 즐겨찾기, 다운로드, 출처 복사, 권리 근거 기록
//   7. 작품 상세 창
//   8. 대화                      — 턴(질문 단위), 스크롤, 메시지, AI 답변, 결과 묶음, 전송(스트리밍)
//   9. 대화 기록 · 즐겨찾기 목록 — 넓은 화면은 왼쪽 사이드바, 좁은 화면은 서랍
//  10. 온디바이스 추천           — 서버·AI 없이 브라우저에서 Datalog 규칙 평가 (ondevice.js)
//  11. 상단 바 접기 · 테마 · 언어 · 앱 설치
//  12. 시작                      — 이벤트 연결과 첫 화면
"use strict";

// =====================================================================
// 1. 설정값 · 공통 도구
// =====================================================================
const CHAT_MAX_LENGTH = 500;          // 서버 CHAT_MAX_LENGTH와 같다 (textarea maxlength도 500)
const PREVIEW_LIMIT = 16;             // 랜딩 미리보기 작품 수
const BROWSE_PAGE_SIZE = 24;          // '작품 더 보기' 한 번에 불러오는 수
const HISTORY_PAGE_SIZE = 20;         // 대화 기록 한 번에 불러오는 수
const PENDING_STEP_MS = 2600;         // 응답 대기 문구가 다음 단계로 바뀌는 간격
const SCROLL_DURATION_MS = 900;       // 새 질문을 화면 위로 올리는 스크롤 시간
const TOPBAR_HIDE_AFTER = 120;        // 이만큼 내려간 뒤부터 상단 바를 접는다
const SCROLL_NOISE = 6;               // 이보다 작은 스크롤 움직임은 무시한다
const TOAST_MS = 2200;
const STORAGE_KEYS = {                // static/theme-init.js(첫 화면 스크립트)도 theme·lang 키를 쓴다
    theme: "pd-theme", lang: "pd-lang", sidebar: "pd-sidebar", iosPrompt: "iosInstallPromptShown",
};
const MUSEUMS = { met: "The Metropolitan Museum of Art", aic: "Art Institute of Chicago", cma: "Cleveland Museum of Art" };

const $ = (id) => document.getElementById(id);
const chatLog = $("chat-log");
const wideScreen = window.matchMedia("(min-width: 1180px)");   // 이 폭 이상이면 대화 기록 사이드바를 띄운다
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

// 프라이빗 모드 등에서 localStorage가 막혀도 앱은 동작해야 한다
const store = {
    get(key) { try { return localStorage.getItem(key); } catch (_) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* 저장 못 해도 무시 */ } },
};

// 요소 만들기. 사용자·AI 텍스트는 항상 textContent로 넣어 XSS를 막는다 (innerHTML 금지)
function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
}

// index.html 맨 위 <symbol id="i-이름">을 재사용하는 SVG 아이콘
function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "i");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#i-${name}`);
    svg.appendChild(use);
    return svg;
}

// 버튼 만들기. labelKey·titleKey는 문구 키라서 언어를 바꾸면 글자도 같이 바뀐다
function button(className, { iconName, labelKey, titleKey, onClick } = {}) {
    const b = el("button", className);
    b.type = "button";
    if (iconName) b.appendChild(icon(iconName));
    if (labelKey) b.appendChild(bindText(el("span"), labelKey));
    if (titleKey) {
        b.dataset.i18nTitle = titleKey;
        b.dataset.i18nAria = titleKey;
        b.title = t(titleKey);
        b.setAttribute("aria-label", t(titleKey));
    }
    if (onClick) b.addEventListener("click", () => onClick(b));
    return b;
}

function setButtonLabel(btn, key) {
    bindText(btn.querySelector("span"), key);
}

let toastTimer;
function toast(message) {
    const box = $("toast");
    box.textContent = message;
    box.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("show"), TOAST_MS);
}

function timeEl(className, date, format) {
    const node = el("time", className, format(date));
    node.dateTime = date.toISOString();
    return node;
}
const locale = () => (state.lang === "en" ? "en-US" : "ko-KR");
const formatTime = (date) => date.toLocaleString(locale(), { hour: "2-digit", minute: "2-digit" });
const formatDateTime = (date) => date.toLocaleString(locale(), { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

// =====================================================================
// 2. 다국어(i18n)
// =====================================================================
// 화면 문구는 한 언어로만 보여주고 상단 KO/EN 버튼으로 바꾼다.
// HTML은 data-i18n(글자) · data-i18n-html · data-i18n-placeholder · data-i18n-aria · data-i18n-title 속성으로 연결한다.
const I18N = {
    ko: {
        skip: "본문으로 건너뛰기", brandName: "명화 찾기", history: "대화 기록", favorites: "즐겨찾기", lab: "온디바이스",
        install: "앱으로 설치하기", theme: "밝게/어둡게 전환", premium: "초대 회원", logout: "로그아웃",
        // 랜딩
        eyebrow: "CC0 · 퍼블릭 도메인 · 상업적 이용 가능",
        heroTitle: "저작권 걱정 없는<br>퍼블릭 도메인 명화 찾기",
        heroLead: "PPT 배경, 카페 포스터, 교재 삽화처럼 쓰임새를 적으면 세계 미술관이 공개한 CC0 작품 중에서 맞는 그림을 골라 드려요. 작품마다 출처 표기 문구와 권리 근거 기록을 함께 제공합니다.",
        statWorks: "CC0 작품", statMuseums: "세계 미술관", statRules: "권리 판단 규칙",
        login: "로그인", signup: "회원가입", email: "이메일", password: "비밀번호", passwordHint: "8자 이상",
        inviteCode: "초대코드", optional: "선택", inviteHint: "받은 코드가 있다면 입력",
        authNote: "질문은 로그인한 사용자만 할 수 있어요. 가입하면 무료 질문 100회가 주어집니다.",
        authFill: "이메일과 비밀번호를 입력해 주세요.",
        previewEyebrow: "로그인 없이 둘러보기", previewTitle: "컬렉션 미리보기", previewTopics: "주제 선택",
        previewSub: "검색에 쓰는 실제 작품 DB에서 바로 불러왔어요. 그림을 누르면 큰 이미지와 출처 정보를 볼 수 있어요.",
        previewFail: "미리보기 작품을 불러오지 못했어요.",
        topics: ["추천", "풍경", "꽃", "인물", "정물", "바다"],
        ctaTitle: "원하는 그림을 문장으로 찾아보세요", ctaSub: "가입하면 무료 질문 100회 · 용도에 맞는 비율 필터 · 권리 근거 기록 발급",
        ctaButton: "무료로 시작하기",
        footerDesc: "세계 미술관이 CC0로 공개한 작품을 한국어로 찾고, 출처 표기와 권리 근거를 함께 챙기는 서비스입니다.",
        footerData: "데이터 출처", footerProject: "프로젝트", footerPolicy: "권리 판단 기준", footerCc0: "CC0 라이선스란?",
        footerNote: "작품 이미지는 각 미술관이 CC0로 공개한 퍼블릭 도메인입니다. 이 서비스의 안내와 근거 기록은 법률 자문이 아닙니다.",
        // 대화
        conversation: "대화 내용", welcomeTitle: "어디에 쓸 그림을 찾으세요?",
        welcomeLead: "용도를 말하면 비율과 분위기에 맞는 CC0 명화를 찾고, 왜 어울리는지 설명해 드려요.",
        examples: "예시 질문", sendForm: "메시지 보내기", questionLabel: "질문 입력",
        questionPlaceholder: "예: 카페 벽에 걸 세로형 포스터", send: "보내기",
        composerHint: "Enter 보내기 · Shift+Enter 줄바꿈",
        exampleList: [
            ["카페 벽에 걸 세로형 포스터", "세로형 · 따뜻한 분위기"],
            ["교재 삽화용 정물화", "정물 · 깔끔한 구도"],
            ["PPT 배경용 가로형 풍경화", "가로형 · 여백 있는 풍경"],
            ["인스타그램 정사각 게시물용 꽃 그림", "정사각 · 꽃"],
        ],
        pending: ["질문을 이해하고 있어요", "어울리는 작품을 찾고 있어요", "추천 이유를 쓰고 있어요"],
        retry: "다시 시도", citeLabel: "{n}번 작품으로 이동", writing: "답변을 쓰는 중…", sessionExpired: "로그인이 만료됐어요. 다시 로그인해 주세요.",
        limitWarn: "무료 질문이 {n}개 남았어요. 초대코드가 있다면 회원가입 때 입력할 수 있어요.",
        genericError: "오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
        // 결과 묶음 · 카드
        count: "{n}점", purpose: "용도 · {p}", all: "전체", landscape: "가로형", portrait: "세로형", square: "정사각",
        more: "작품 더 보기", loading: "불러오는 중…", detailOf: "자세히 보기: {t}", unknownArtist: "작가 미상",
        favAdd: "즐겨찾기", favOn: "즐겨찾기 해제", favAdded: "즐겨찾기에 담았어요", favRemoved: "즐겨찾기에서 뺐어요",
        favNeedLogin: "로그인하면 즐겨찾기에 담을 수 있어요", download: "고화질 다운로드", copyCredit: "출처 표기 복사",
        copied: "출처 표기를 복사했어요", copyFail: "복사하지 못했어요", record: "권리 근거 기록",
        recordIssuing: "발급 중…", recordWait: "권리 근거 기록을 만들고 인터넷 아카이브에 보관을 요청하는 중… (10초 정도)",
        recordNeedLogin: "로그인하면 근거 기록을 발급할 수 있어요",
        // 작품 상세
        close: "닫기", creditLabel: "출처 표기 예시", original: "원본 이미지", sourcePage: "미술관 작품 페이지",
        metaDate: "제작", metaMedium: "재료", metaCredit: "소장 경위", metaLicense: "라이선스", licenseText: "{l} · 퍼블릭 도메인",
        // 대화 기록 · 즐겨찾기
        historyEmpty: "아직 대화 기록이 없어요.", favEmpty: "아직 담은 작품이 없어요. 카드의 ♡를 눌러 모아 보세요.",
        loadMore: "더 불러오기", refresh: "새로고침", hideSidebar: "대화 기록 숨기기", showSidebar: "대화 기록 보기", askAgain: "다시 묻기",
        // 온디바이스
        labEyebrow: "실험실 · 서버/AI 호출 없음", labTitle: "온디바이스 추천",
        labLead: "브라우저에 받아 둔 작품 데이터를 Datalog 규칙으로 바로 걸러요. 자유 문장은 AI 대신 키워드 사전으로 해석합니다.",
        labFree: "자유 문장", labFreePh: "예: 봄 느낌 풍경화, 19세기 인상주의 바다", labParse: "키워드로 해석",
        labStyle: "화풍", labAnyStyle: "전체", labSubject: "주제 키워드", labSubjectPh: "콤마로 여러 개",
        labFrom: "시작 연도", labTo: "종료 연도", labRule: "검색 규칙 미리보기", labRun: "내 기기에서 추천받기",
        labLoading: "작품 데이터를 불러오는 중…",
        odParsed: "키워드 사전으로 해석했어요: {m}", odNone: "인식된 키워드가 없어요. 조건을 직접 골라 보세요.",
        odHeading: "온디바이스 추천", odMsg: "브라우저에서 규칙을 평가했어요 (서버·AI 호출 없음)",
        odEmpty: "조건에 맞는 작품이 없어요. 조건을 줄여 보세요.",
        // 앱 설치
        iosSteps: ["Safari의 공유 버튼을 누르세요.", "아래로 내려 \"홈 화면에 추가\"를 고르세요.", "오른쪽 위 \"추가\"를 누르면 끝!"],
        genericSteps: ["브라우저 메뉴(⋮)를 여세요.", "\"앱 설치\" 또는 \"홈 화면에 추가\"를 고르세요."],
    },
    en: {
        skip: "Skip to content", brandName: "Masterpiece Finder", history: "History", favorites: "Favorites", lab: "On-device",
        install: "Install app", theme: "Toggle light/dark", premium: "Invited", logout: "Log out",
        eyebrow: "CC0 · Public domain · Free for commercial use",
        heroTitle: "Copyright-free<br>public domain masterpieces",
        heroLead: "Describe the use — a slide background, a café poster, a textbook illustration — and we'll pick matching CC0 works released by world museums. Every work comes with a credit line and a rights evidence record.",
        statWorks: "CC0 artworks", statMuseums: "Museums", statRules: "Rights rules",
        login: "Log in", signup: "Sign up", email: "Email", password: "Password", passwordHint: "8+ characters",
        inviteCode: "Invite code", optional: "optional", inviteHint: "Enter it if you have one",
        authNote: "Only signed-in users can ask questions. New accounts get 100 free questions.",
        authFill: "Please enter your email and password.",
        previewEyebrow: "Browse without signing in", previewTitle: "Collection preview", previewTopics: "Choose a topic",
        previewSub: "Loaded straight from the artwork database our search uses. Click a work to see it large with its source details.",
        previewFail: "Couldn't load preview artworks.",
        topics: ["Featured", "Landscape", "Flowers", "Portrait", "Still life", "Sea"],
        ctaTitle: "Find the art you need in a sentence", ctaSub: "100 free questions · shape filters for your use · rights evidence records",
        ctaButton: "Get started free",
        footerDesc: "Find CC0 artworks released by world museums — with credit lines and rights evidence included.",
        footerData: "Data sources", footerProject: "Project", footerPolicy: "Rights policy", footerCc0: "What is CC0?",
        footerNote: "Artwork images are public domain works released under CC0 by each museum. Guidance and records here are not legal advice.",
        conversation: "Conversation", welcomeTitle: "What will you use the art for?",
        welcomeLead: "Describe the use and we'll find CC0 masterpieces that fit the shape and mood — and explain why.",
        examples: "Example questions", sendForm: "Send a message", questionLabel: "Your question",
        questionPlaceholder: "e.g. A portrait-shaped poster for a café wall", send: "Send",
        composerHint: "Enter to send · Shift+Enter for a new line",
        exampleList: [
            ["A portrait-shaped poster for a café wall", "Portrait · warm mood"],
            ["A still life for a textbook illustration", "Still life · clean composition"],
            ["A landscape painting for a slide background", "Landscape · open space"],
            ["Flowers for a square Instagram post", "Square · flowers"],
        ],
        pending: ["Understanding your request", "Finding matching artworks", "Writing why they fit"],
        retry: "Try again", citeLabel: "Go to artwork {n}", writing: "Writing the answer…", sessionExpired: "Your session expired. Please sign in again.",
        limitWarn: "{n} free questions left. Invite codes can be entered at sign-up.",
        genericError: "Something went wrong. Please try again shortly.",
        count: "{n} works", purpose: "For · {p}", all: "All", landscape: "Landscape", portrait: "Portrait", square: "Square",
        more: "More artworks", loading: "Loading…", detailOf: "View details: {t}", unknownArtist: "Unknown artist",
        favAdd: "Add to favorites", favOn: "Remove from favorites", favAdded: "Added to favorites", favRemoved: "Removed from favorites",
        favNeedLogin: "Sign in to save favorites", download: "Download", copyCredit: "Copy credit line",
        copied: "Credit line copied", copyFail: "Couldn't copy", record: "Rights record",
        recordIssuing: "Issuing…", recordWait: "Creating the rights record and requesting an Internet Archive snapshot… (about 10s)",
        recordNeedLogin: "Sign in to issue rights records",
        close: "Close", creditLabel: "Credit line example", original: "Original image", sourcePage: "Museum page",
        metaDate: "Date", metaMedium: "Medium", metaCredit: "Credit", metaLicense: "License", licenseText: "{l} · Public domain",
        historyEmpty: "No conversations yet.", favEmpty: "No favorites yet — tap ♡ on a card to save it.",
        loadMore: "Load more", refresh: "Refresh", hideSidebar: "Hide history", showSidebar: "Show history", askAgain: "Ask again",
        labEyebrow: "Lab · no server or AI calls", labTitle: "On-device recommendations",
        labLead: "Filters artwork data cached in your browser with Datalog-style rules. Free text is parsed with a keyword dictionary instead of AI.",
        labFree: "Free text", labFreePh: "e.g. spring landscape, 19th-century impressionist sea", labParse: "Parse keywords",
        labStyle: "Style", labAnyStyle: "Any", labSubject: "Subjects", labSubjectPh: "comma-separated",
        labFrom: "Year from", labTo: "Year to", labRule: "Rule preview", labRun: "Recommend on this device",
        labLoading: "Loading artwork data…",
        odParsed: "Parsed with the keyword dictionary: {m}", odNone: "No known keywords — pick the filters yourself.",
        odHeading: "On-device picks", odMsg: "Rules evaluated in your browser (no server or AI calls)",
        odEmpty: "No matching works. Try loosening the filters.",
        iosSteps: ["Tap the Share button in Safari.", "Scroll down and choose \"Add to Home Screen\".", "Tap \"Add\" in the top right — done!"],
        genericSteps: ["Open the browser menu (⋮).", "Choose \"Install app\" or \"Add to Home screen\"."],
    },
};

// 서버 25초 + 네트워크 여유. 이만큼 아무 응답(스트리밍은 조각)이 없으면 기다리지 않고 '접속자가 많습니다'를 보여준다
const CLIENT_TIMEOUT_MS = 30000;

// 서버 오류 코드(README '오류 코드' 참고) → 안내 문구. retry: 같은 질문을 다시 보내 볼 만한 일시적 오류인지
const ERRORS = {
    UNAUTHENTICATED: { ko: "로그인이 필요합니다.", en: "Please sign in." },
    INVALID_EMAIL: { ko: "이메일 형식이 올바르지 않습니다.", en: "That email address isn't valid." },
    INVALID_PASSWORD: { ko: "비밀번호는 8자 이상 128자 이하여야 합니다.", en: "Password must be 8–128 characters." },
    EMAIL_TAKEN: { ko: "이미 가입된 이메일입니다.", en: "This email is already registered." },
    INVALID_CREDENTIALS: { ko: "이메일 또는 비밀번호가 올바르지 않습니다.", en: "Incorrect email or password." },
    RATE_LIMITED: { ko: "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.", en: "Too many requests. Please wait a moment." },
    EMPTY_MESSAGE: { ko: "질문을 입력해 주세요.", en: "Please enter a question." },
    MESSAGE_TOO_LONG: { ko: "질문은 500자 이하로 입력해 주세요.", en: "Questions can be up to 500 characters." },
    INVALID_INPUT: { ko: "허용되지 않는 입력입니다.", en: "That input isn't allowed." },
    FREE_LIMIT_REACHED: { ko: "무료 질문 100회를 모두 사용했어요.", en: "You've used all your free questions." },
    AI_KEY_MISSING: { ko: "AI 서비스에 연결되어 있지 않아요. 관리자에게 알려 주세요.", en: "The AI service isn't connected. Please tell the admin." },
    AI_REFUSED: { ko: "이 질문에는 답할 수 없어요. 질문을 바꿔 다시 시도해 주세요.", en: "I can't answer this question. Please rephrase and try again." },
    ARTWORK_NOT_FOUND: { ko: "작품을 찾을 수 없습니다.", en: "Artwork not found." },
    RECORD_NOT_ALLOWED: { ko: "이 작품은 판단 규칙을 통과하지 못해 근거 기록을 발급할 수 없어요.", en: "This artwork didn't pass our rights rules." },
    AI_BACKED_OFF: { ko: "AI 서비스가 잠시 쉬고 있어요. 잠시 후 다시 시도해 주세요.", en: "The AI service is taking a short break.", retry: true },
    // 25초 안에 답을 못 주면 서버도 화면도 같은 안내를 쓴다 (app/config.py BUSY_MESSAGE, 서버 DB 시간 초과는 BUSY)
    AI_TIMEOUT: { ko: "죄송합니다. 접속자가 많습니다. 잠시 후 다시 시도해 주세요.", en: "Sorry, we have a lot of visitors right now. Please try again shortly.", retry: true },
    BUSY: { ko: "죄송합니다. 접속자가 많습니다. 잠시 후 다시 시도해 주세요.", en: "Sorry, we have a lot of visitors right now. Please try again shortly.", retry: true },
    AI_RATE_LIMITED: { ko: "AI 요청이 많아 잠시 제한됐어요.", en: "The AI service is rate-limited right now.", retry: true },
    AI_ERROR: { ko: "AI 서버와 통신하지 못했어요.", en: "Couldn't reach the AI server.", retry: true },
    DB_ERROR: { ko: "데이터베이스에 문제가 생겼어요.", en: "There was a database problem.", retry: true },
    ART_DB_ERROR: { ko: "작품 데이터베이스를 읽지 못했어요.", en: "Couldn't read the artwork database.", retry: true },
    INTERNAL_ERROR: { ko: "예상치 못한 오류가 발생했어요.", en: "An unexpected error occurred.", retry: true },
    NETWORK_ERROR: { ko: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.", en: "Couldn't reach the server. Check your connection.", retry: true },
    STREAM_DROPPED: { ko: "답변을 받는 중 연결이 끊겼어요. 다시 시도해 주세요.", en: "The connection dropped while answering. Please try again.", retry: true },   // 화면 전용 코드
};

function t(key, vars) {
    let text = I18N[state.lang][key] ?? I18N.ko[key] ?? key;
    if (vars && typeof text === "string") {
        Object.entries(vars).forEach(([name, value]) => { text = text.replace(`{${name}}`, value); });
    }
    return text;
}

function errorMessage(err) {
    const entry = ERRORS[err?.code];
    return entry ? entry[state.lang] : (err?.message || t("genericError"));
}

// 동적으로 그린 글자도 언어 전환 때 바뀌도록, 문구 키(와 변수)를 요소에 적어 둔다
function bindText(node, key, vars) {
    node.dataset.i18n = key;
    if (vars) node.dataset.i18nVars = JSON.stringify(vars);
    node.textContent = t(key, vars);
    return node;
}

// 서버 오류는 코드로 문구를 고르므로, 코드를 기억해 두면 언어 전환 때 다시 고를 수 있다
function bindError(node, err) {
    if (ERRORS[err?.code]) node.dataset.err = err.code;
    node.textContent = errorMessage(err);
    return node;
}

const varsOf = (node) => (node.dataset.i18nVars ? JSON.parse(node.dataset.i18nVars) : undefined);

// 화면 전체의 문구를 현재 언어로 다시 채운다
function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n, varsOf(n)); });
    // data-i18n-html은 이 파일에 적힌 고정 문구(<br> 포함)만 넣는다 — 사용자 입력은 절대 여기로 오지 않는다
    document.querySelectorAll("[data-i18n-html]").forEach((n) => { n.innerHTML = t(n.dataset.i18nHtml); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => { n.placeholder = t(n.dataset.i18nPlaceholder); });
    document.querySelectorAll("[data-i18n-aria]").forEach((n) => { n.setAttribute("aria-label", t(n.dataset.i18nAria, varsOf(n))); });
    document.querySelectorAll("[data-i18n-title]").forEach((n) => { n.title = t(n.dataset.i18nTitle); });
    document.querySelectorAll("[data-err]").forEach((n) => { n.textContent = errorMessage({ code: n.dataset.err }); });
    document.querySelectorAll("time.msg-time").forEach((n) => { n.textContent = formatTime(new Date(n.dateTime)); });
    document.querySelectorAll("time.history-meta").forEach((n) => { n.textContent = formatDateTime(new Date(n.dateTime)); });
    $("lang-btn").textContent = state.lang === "en" ? "KO" : "EN";
    $("lang-btn").title = state.lang === "en" ? "한국어로 보기" : "View in English";
}

// =====================================================================
// 3. 서버 API
// =====================================================================
// 모든 요청이 이 함수를 지난다. 네트워크 오류도 서버 오류와 같은 모양({ error: { code } })으로 돌려준다
async function api(path, options = {}) {
    let res;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);
    try {
        res = await fetch(path, { headers: { "Content-Type": "application/json" }, credentials: "same-origin",
                                  signal: controller.signal, ...options });
    } catch (e) {
        const code = e?.name === "AbortError" ? "BUSY" : "NETWORK_ERROR";   // 30초 넘게 답이 없으면 '접속자가 많습니다'
        return { ok: false, status: 0, data: { error: { code } } };
    } finally {
        clearTimeout(timer);
    }
    let data = {};
    try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
    return { ok: res.ok, status: res.status, data };
}

const postJson = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });

// 답변 스트리밍(POST /api/chat/stream)은 NDJSON — 한 줄에 이벤트 하나({"type": "meta" | "delta" | "done" | "error", ...})
// 받는 대로 줄 단위로 잘라 onEvent에 넘긴다. 중간에 연결이 끊기면 예외를 던진다
async function readNdjson(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
            const line = buffer.slice(0, newline).trim();
            buffer = buffer.slice(newline + 1);
            if (line) onEvent(JSON.parse(line));
        }
    }
}

// =====================================================================
// 4. 화면 상태 · 로그인
// =====================================================================
const state = {
    lang: document.documentElement.lang === "en" ? "en" : "ko",   // index.html 첫 화면 스크립트가 저장된 언어를 넣어 둔다
    loggedIn: false,
    authMode: "login",        // "login" | "signup"
    favorites: new Set(),     // 즐겨찾기한 작품 id
    sending: false,           // 질문 전송 중이면 중복 전송을 막는다
    currentTurn: null,        // 지금 결과가 채워지는 턴(질문 단위)
    previewTopic: 0,
    previewLoaded: false,
    onDeviceReady: false,
};
const langRerenders = new Set();   // 언어 전환 때 다시 그릴 영역 (AI 답변 본문처럼 bindText로 못 묶는 것)

function setAuthMode(mode) {
    state.authMode = mode;
    $("tab-login").setAttribute("aria-selected", String(mode === "login"));
    $("tab-signup").setAttribute("aria-selected", String(mode === "signup"));
    $("code-field").hidden = mode !== "signup";
    $("password").autocomplete = mode === "signup" ? "new-password" : "current-password";
    bindText($("auth-submit"), mode);
    $("auth-error").textContent = "";
}

async function submitAuth(event) {
    event.preventDefault();
    const email = $("email").value.trim();
    const password = $("password").value;
    if (!email || !password) { $("auth-error").textContent = t("authFill"); return; }
    const body = { email, password };
    const code = $("private-code").value.trim();
    if (state.authMode === "signup" && code) body.private_code = code;

    $("auth-submit").disabled = true;
    const { ok, data } = await postJson(`/api/auth/${state.authMode}`, body);
    $("auth-submit").disabled = false;
    if (!ok) { $("auth-error").textContent = errorMessage(data.error); return; }
    $("password").value = "";
    $("private-code").value = "";
    show(true, data.user.email, data.user.is_premium);
}

async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    resetChat();
    show(false);
}

// 로그인 전(랜딩) ↔ 로그인 후(대화) 화면 전환
function show(isLoggedIn, email = "", isPremium = false) {
    state.loggedIn = isLoggedIn;
    document.body.classList.toggle("signed-in", isLoggedIn);
    $("auth-panel").hidden = isLoggedIn;
    $("site-footer").hidden = isLoggedIn;        // 대화 화면은 입력창이 하단에 고정이라 푸터를 두지 않는다
    $("chat-panel").hidden = !isLoggedIn;
    $("sidebar").hidden = !isLoggedIn;
    ["history-btn", "favorites-btn", "lab-btn", "user-chip"].forEach((id) => { $(id).hidden = !isLoggedIn; });
    $("user-email").textContent = email;
    $("premium-badge").hidden = !(isLoggedIn && isPremium);
    syncHistoryButton();
    if (isLoggedIn) {
        refreshSidebar();
        loadFavorites();
        $("message-input").focus();
    } else {
        state.favorites.clear();
        loadPreview();
    }
    showTopbar();
    window.scrollTo(0, 0);
}

// =====================================================================
// 5. 랜딩: 컬렉션 미리보기
// =====================================================================
// 주제 칩 → '더 보기'용 공개 API(로그인 불필요, AI 호출 없음)의 검색어. 순서는 I18N topics와 같다
const PREVIEW_TOPICS = ["landscape,flowers,portrait,garden", "landscape", "flowers", "portrait", "still,life", "sea,ocean"];

function renderTopics() {
    $("preview-topics").replaceChildren(...t("topics").map((label, i) => {
        const b = el("button", "topic", label);
        b.type = "button";
        b.setAttribute("role", "tab");
        b.setAttribute("aria-selected", String(i === state.previewTopic));
        b.addEventListener("click", () => {
            if (i === state.previewTopic) return;
            state.previewTopic = i;
            renderTopics();
            loadPreview(true);
        });
        return b;
    }));
}

async function loadPreview(force = false) {
    if (state.previewLoaded && !force) return;
    state.previewLoaded = true;
    const grid = $("preview-grid");
    grid.classList.add("loading");
    const { ok, data } = await api(`/api/artworks?q=${PREVIEW_TOPICS[state.previewTopic]}&limit=${PREVIEW_LIMIT}`);
    grid.classList.remove("loading");
    if (!ok) { grid.replaceChildren(bindText(el("p", "empty"), "previewFail")); return; }
    grid.replaceChildren(...data.artworks.map((w) => makeCard(w)));
}

// =====================================================================
// 6. 작품 카드
// =====================================================================
const museumName = (w) => MUSEUMS[w.source] || (w.source || "").toUpperCase();

// 이미지의 실제 가로세로 비율로 판별한다 (PPT 배경은 가로형, 포스터는 세로형이 필요)
function orientationOf(img) {
    const ratio = img.naturalWidth / img.naturalHeight;
    return ratio >= 1.15 ? "landscape" : ratio <= 0.87 ? "portrait" : "square";
}

// index가 있으면 답변의 [n] 인용과 이어지도록 카드에 번호를 단다
function makeCard(w, index) {
    const card = el("article", "card");
    card.dataset.id = w.id;
    if (index) card.dataset.index = index;

    const media = el("button", "card-media");
    media.type = "button";
    media.dataset.i18nAria = "detailOf";
    media.dataset.i18nVars = JSON.stringify({ t: w.title });
    media.setAttribute("aria-label", t("detailOf", { t: w.title }));
    media.addEventListener("click", () => openArtwork(w));

    const orientTag = el("span", "tag");
    const img = el("img");
    img.alt = w.title;
    img.loading = "lazy";
    img.decoding = "async";
    img.addEventListener("load", () => {
        img.classList.add("loaded");
        const kind = orientationOf(img);
        card.dataset.orient = kind;           // 결과 묶음의 비율 필터가 이 값으로 카드를 숨긴다 (style.css)
        bindText(orientTag, kind);
    });
    img.addEventListener("error", () => img.classList.add("broken"));
    img.src = w.thumbnail_url || w.image_url;
    media.appendChild(img);
    card.appendChild(media);

    if (index) card.appendChild(el("span", "card-num", String(index)));

    const quick = el("div", "card-quick");
    quick.append(
        favButton(w, "quick-btn"),
        button("quick-btn", { iconName: "download", titleKey: "download", onClick: (b) => download(w, b) }),
    );
    card.appendChild(quick);

    const sub = el("p", "card-sub");
    sub.appendChild(w.artist ? el("span", null, w.artist) : bindText(el("span"), "unknownArtist"));
    if (w.date_display) sub.appendChild(el("span", null, ` · ${w.date_display}`));
    const tags = el("div", "card-tags");
    tags.append(el("span", "tag cc0", w.license || "CC0"), el("span", "tag", (w.source || "").toUpperCase()), orientTag);
    const caption = el("div", "card-caption");
    caption.append(el("h3", "card-title", w.title), sub, tags);
    card.appendChild(caption);
    return card;
}

// ---- 즐겨찾기 ----
// 같은 작품의 하트는 화면 여러 곳(카드·상세 창·즐겨찾기 목록)에 있을 수 있어 data-id로 한꺼번에 맞춘다
function favButton(w, className, labelKey) {
    const b = button(`${className} fav-btn`, { iconName: "heart", labelKey, onClick: () => toggleFavorite(w) });
    b.dataset.id = w.id;
    renderFav(b);
    return b;
}

function renderFav(btn) {
    const on = state.favorites.has(Number(btn.dataset.id));
    const label = t(on ? "favOn" : "favAdd");
    btn.classList.toggle("on", on);
    btn.title = label;
    btn.setAttribute("aria-label", label);
    btn.setAttribute("aria-pressed", String(on));
}

function renderFavButtons(id) {
    const selector = id == null ? ".fav-btn" : `.fav-btn[data-id="${id}"]`;
    document.querySelectorAll(selector).forEach(renderFav);
}

async function loadFavorites() {
    const { ok, data } = await api("/api/me/favorites?limit=100");
    if (!ok) return [];
    state.favorites = new Set(data.favorites.map((w) => w.id));
    renderFavButtons();
    return data.favorites;
}

async function toggleFavorite(w) {
    if (!state.loggedIn) { toast(t("favNeedLogin")); $("email").focus(); return; }
    const on = state.favorites.has(w.id);
    const { ok, data } = on
        ? await api(`/api/favorites/${w.id}`, { method: "DELETE" })
        : await postJson("/api/favorites", { artwork_id: w.id });
    if (!ok) { toast(errorMessage(data.error)); return; }
    if (on) state.favorites.delete(w.id); else state.favorites.add(w.id);
    renderFavButtons(w.id);
    toast(t(on ? "favRemoved" : "favAdded"));
}

// ---- 다운로드 · 출처 복사 · 권리 근거 기록 ----
async function download(w, btn) {
    // AIC는 우리 서버 프록시가 첨부파일로 내려준다. 다른 기관은 원본을 받아 저장을 시도하고, 막히면 새 탭으로 연다
    if (w.source === "aic") {
        const a = el("a");
        a.href = `${w.image_url}&download=1`;
        a.click();
        return;
    }
    btn.disabled = true;
    try {
        const res = await fetch(w.image_url);
        if (!res.ok) throw new Error(String(res.status));
        const url = URL.createObjectURL(await res.blob());
        const a = el("a");
        a.href = url;
        a.download = `${w.source}-${w.id}.jpg`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (_) {
        window.open(w.image_url, "_blank", "noopener");
    } finally {
        btn.disabled = false;
    }
}

function creditLine(w) {
    const parts = [`"${w.title}"`, w.artist || "Unknown artist"];
    if (w.date_display) parts.push(w.date_display);
    return `${parts.join(", ")}. ${museumName(w)}, CC0 (Public Domain). ${w.source_url}`;
}

async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (_) {   // 클립보드 API가 막힌 환경(http 등)용 예전 방식
        const ta = el("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        const done = document.execCommand("copy");
        ta.remove();
        return done;
    }
}

async function issueRecord(w, btn) {
    if (!state.loggedIn) { toast(t("recordNeedLogin")); return; }
    // 서버 응답을 기다린 뒤 새 탭을 열면 팝업 차단에 걸려서, 탭을 먼저 열어두고 주소만 나중에 넣는다
    const tab = window.open("", "_blank");
    if (tab) tab.document.write(`<p style="font-family:sans-serif;padding:24px">${t("recordWait")}</p>`);
    btn.disabled = true;
    setButtonLabel(btn, "recordIssuing");
    const { ok, data } = await postJson("/api/records", { artwork_id: w.id });
    btn.disabled = false;
    setButtonLabel(btn, "record");
    if (!ok) {
        tab?.close();
        toast(errorMessage(data.error));
        return;
    }
    if (tab) tab.location.href = data.url; else window.location.href = data.url;
}

// =====================================================================
// 7. 작품 상세 창
// =====================================================================
function openArtwork(w) {
    const img = $("art-img");
    img.removeAttribute("src");   // 이전 작품 이미지가 잠깐 보이지 않게
    img.alt = w.title;
    // MET·CMA의 image_url은 수 MB짜리 원본이라 화면에는 웹용(thumbnail_url)을, AIC는 1686px 프록시를 쓴다
    img.src = w.source === "aic" ? w.image_url : (w.thumbnail_url || w.image_url);
    $("art-museum").textContent = museumName(w);
    $("art-title").textContent = w.title;
    $("art-artist").textContent = [w.artist || t("unknownArtist"), w.date_display].filter(Boolean).join(" · ");

    $("art-meta").replaceChildren(...[
        ["metaDate", w.date_display], ["metaMedium", w.medium], ["metaCredit", w.credit_line],
        ["metaLicense", t("licenseText", { l: w.license || "CC0" })],
    ].filter(([, value]) => value).flatMap(([key, value]) => [bindText(el("dt"), key), el("dd", null, value)]));

    $("art-actions").replaceChildren(
        button("btn btn-primary btn-sm", { iconName: "download", labelKey: "download", onClick: (b) => download(w, b) }),
        favButton(w, "btn btn-soft btn-sm", "favorites"),
        button("btn btn-ghost btn-sm", { iconName: "copy", labelKey: "copyCredit",
            onClick: async () => toast(t((await copyText(creditLine(w))) ? "copied" : "copyFail")) }),
        button("btn btn-ghost btn-sm", { iconName: "record", labelKey: "record", onClick: (b) => issueRecord(w, b) }),
    );
    $("art-credit").textContent = creditLine(w);

    $("art-links").replaceChildren(...[["original", w.image_url], ["sourcePage", w.source_url]]
        .filter(([, href]) => href)
        .map(([key, href]) => {
            const a = el("a");
            a.href = href;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.append(bindText(el("span"), key), icon("external"));
            return a;
        }));
    $("artwork-modal").showModal();
}

// =====================================================================
// 8. 대화
// =====================================================================
const welcomeTemplate = $("welcome").cloneNode(true);   // 로그아웃 때 첫 화면으로 되돌리기 위한 원본

function renderExamples() {
    $("examples")?.replaceChildren(...t("exampleList").map(([question, hint]) => {
        const b = el("button", "example");
        b.type = "button";
        b.append(el("span", "example-title", question), el("span", "example-sub", hint));
        b.addEventListener("click", () => sendMessage(question));
        return b;
    }));
}

function resetChat() {
    chatLog.replaceChildren(welcomeTemplate.cloneNode(true));
    langRerenders.clear();
    state.currentTurn = null;
    applyI18n();
    renderExamples();
}

// ---- 턴: 질문(또는 온디바이스 검색) 하나와 그 결과를 한 덩어리로 묶는다 ----
// 새 턴은 화면 맨 위로 올리고 아래 빈 공간에 결과가 채워진다. 이전 턴은 지우지 않고 위로 밀려난다
function startTurn() {
    $("welcome")?.remove();
    // 지난 턴은 최소 높이를 풀어 원래 내용 높이로 돌려놓는다 — 안 풀면 위로 올려 봤을 때 턴마다 빈 화면이 생긴다
    const previous = chatLog.querySelector(".turn.latest");
    if (previous) {
        previous.classList.remove("latest");
        previous.style.minHeight = "";
    }
    state.currentTurn = el("div", "turn latest");
    chatLog.appendChild(state.currentTurn);
    fitLatestTurn();
    // 레이아웃이 반영된 다음 프레임에 스크롤해야 새 턴이 정확히 맨 위에 붙는다
    requestAnimationFrame(() => slowScrollTo(state.currentTurn));
}

// 마지막 턴의 최소 높이 = 상단 바와 입력창을 뺀 화면 높이. 답이 짧아도 질문이 맨 위에 머물게 한다
function fitLatestTurn() {
    const turn = chatLog.querySelector(".turn.latest");
    if (!turn) return;
    const topbar = document.querySelector(".topbar").offsetHeight;
    const composer = document.querySelector(".composer-wrap").offsetHeight;
    turn.style.minHeight = `${Math.max(0, window.innerHeight - topbar - composer - 32)}px`;
}

const turnTarget = () => (state.currentTurn?.isConnected ? state.currentTurn : chatLog);

// 브라우저 기본 smooth 스크롤은 속도를 바꿀 수 없어 너무 빠르다 → 직접 천천히(ease-in-out) 움직인다
let scrollAnimation = 0;
function slowScrollTo(target) {
    const gap = parseFloat(getComputedStyle(target).scrollMarginTop) || 0;
    const startY = window.scrollY;
    const endY = Math.max(0, startY + target.getBoundingClientRect().top - gap);
    showTopbar();   // 질문이 상단 바 바로 아래에 붙어야 하므로, 자동 스크롤 동안은 상단 바를 펼쳐 둔다
    if (reducedMotion.matches) { window.scrollTo(0, endY); return; }

    const started = performance.now();
    const animation = ++scrollAnimation;   // 새 스크롤이 시작되면 이전 애니메이션은 멈춘다
    topbarScroll.auto = true;
    const step = (now) => {
        if (animation !== scrollAnimation) return;
        const p = Math.min(1, (now - started) / SCROLL_DURATION_MS);
        const eased = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
        window.scrollTo(0, startY + (endY - startY) * eased);
        if (p < 1) requestAnimationFrame(step);
        else setTimeout(() => { topbarScroll.auto = false; topbarScroll.lastY = window.scrollY; }, 100);
    };
    requestAnimationFrame(step);
}

// ---- 메시지 ----
function addUserMessage(text) {
    const row = el("div", "msg msg-user", text);
    row.appendChild(timeEl("msg-time", new Date(), formatTime));
    turnTarget().appendChild(row);
}

function addBotRow({ avatar = true } = {}) {
    const row = el("div", avatar ? "msg msg-bot" : "msg msg-bot no-avatar");
    row.setAttribute("role", "article");
    if (avatar) {
        const mark = el("span", "bot-avatar");
        mark.appendChild(icon("spark"));
        row.appendChild(mark);
    }
    const body = el("div", "bot-body");
    row.appendChild(body);
    turnTarget().appendChild(row);
    return { row, body };
}

// 응답 대기 표시. 서버는 의도 추출 → 검색 → 답변 작성 순서로 일하므로 그 단계를 대략 보여준다
function addPending() {
    const { row, body } = addBotRow();
    row.setAttribute("role", "status");
    const text = el("span", null, t("pending")[0]);
    const label = el("span", "pending-label");
    label.append(el("span", "pending-dot"), text);
    const lines = el("div", "skeleton-lines");
    lines.append(el("span"), el("span"), el("span"));
    const tiles = el("div", "skeleton-grid");
    tiles.append(...[150, 190, 130].map((h) => { const tile = el("div", "skeleton-tile"); tile.style.height = `${h}px`; return tile; }));
    body.append(label, lines, tiles);

    let step = 0;
    const timer = setInterval(() => {
        step = Math.min(step + 1, t("pending").length - 1);
        text.textContent = t("pending")[step];
    }, PENDING_STEP_MS);
    return { remove() { clearInterval(timer); row.remove(); } };
}

// 안내·오류 상자. message는 { key, vars }(화면 문구) 또는 { error }(서버 오류)
function addNotice(type, message, { code, onRetry } = {}) {
    const box = el("div", `msg notice ${type}`);
    box.setAttribute("role", type === "error" ? "alert" : "status");
    box.appendChild(icon("alert"));
    const body = el("div", "notice-body");
    body.appendChild(message.error ? bindError(el("span"), message.error) : bindText(el("span"), message.key, message.vars));
    if (code) body.appendChild(el("span", "notice-code", code));
    if (onRetry) {
        body.appendChild(button("btn", { iconName: "retry", labelKey: "retry", onClick: () => { box.remove(); onRetry(); } }));
    }
    box.appendChild(body);
    turnTarget().appendChild(box);
}

// ---- AI 답변 ----
// 답변은 "한국어 …\n\nEnglish: …" 형태다. 고른 언어를 본문으로, 다른 언어는 접어 둔다
function splitReply(reply) {
    const text = reply.replace(/\n*그 외에도 관련 작품 \d+개를 더 찾았어요[^\n]*\s*$/, "").trim();
    const m = text.match(/\n\s*English\s*:\s*/i);
    if (!m) return { ko: text, en: "" };
    return { ko: text.slice(0, m.index).trim(), en: text.slice(m.index + m[0].length).trim() };
}

// 답변 속 [1] 같은 인용 번호를, 누르면 해당 카드로 이동하는 버튼으로 바꾼다
function richText(text, onCite) {
    const frag = document.createDocumentFragment();
    text.split(/\[(\d+)\]/).forEach((part, i) => {
        if (i % 2 === 0) { if (part) frag.appendChild(document.createTextNode(part)); return; }
        const cite = el("button", "cite", part);
        cite.type = "button";
        cite.setAttribute("aria-label", t("citeLabel", { n: part }));
        cite.addEventListener("click", () => onCite(Number(part)));
        frag.appendChild(cite);
    });
    return frag;
}

// AI 답변 한 덩어리(글 + 작품 카드)를 만들고 조작 함수를 돌려준다.
// 스트리밍이면 카드부터 보이고 글은 append()로 이어 붙인 뒤, finish()에서 [n] 인용·언어 접기를 입힌다
function addBotAnswer(works, search) {
    const { row, body } = addBotRow();
    const group = works.length
        ? buildResultGroup(works, search, search?.purpose ? { key: "purpose", vars: { p: search.purpose } } : null)
        : null;
    const onCite = (n) => {
        const card = group?.querySelector(`.card[data-index="${n}"]`);
        if (!card) return;
        if (card.offsetParent === null) group.setFilter("all");   // 비율 필터에 가려진 카드면 필터를 푼다
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.classList.remove("flash");
        void card.offsetWidth;   // 애니메이션을 처음부터 다시 재생하기 위한 리플로우
        card.classList.add("flash");
    };

    const answeredAt = new Date();
    const textBox = el("div", "answer-box");
    let reply = "";
    let live = null;   // 스트리밍 중인 글 (끝나면 render()가 다시 그린다)

    // 언어를 바꾸면 본문과 접힌 쪽을 서로 바꿔 다시 그린다
    const render = () => {
        const { ko, en } = splitReply(reply);
        const primary = state.lang === "en" && en ? en : ko;
        const secondary = primary === ko ? en : ko;
        const answer = el("div", "answer");
        answer.append(richText(primary, onCite), timeEl("msg-time", answeredAt, formatTime));
        textBox.replaceChildren(answer);
        if (secondary) {
            const alt = el("details", "answer-alt");
            const altText = el("div", "answer");
            altText.appendChild(richText(secondary, onCite));
            alt.append(el("summary", null, primary === ko ? "English" : "한국어"), altText);
            textBox.appendChild(alt);
        }
    };
    const writing = el("span", "pending-label");
    writing.append(el("span", "pending-dot"), bindText(el("span"), "writing"));
    textBox.appendChild(writing);
    body.appendChild(textBox);
    if (group) body.appendChild(group);

    return {
        append(piece) {
            if (!live) { live = el("div", "answer"); textBox.replaceChildren(live); }
            reply += piece;
            live.append(piece);   // 문자열 append = 텍스트 노드 — HTML로 해석되지 않는다
        },
        finish(fullReply) {
            if (fullReply != null) reply = fullReply;
            if (!reply) { textBox.remove(); return; }   // 글 없이 실패했으면 카드만 남긴다
            render();
            langRerenders.add(render);
        },
        remove() { row.remove(); },
    };
}

// ---- 결과 묶음: 제목 + 비율 필터 + 메이슨리 카드 + (검색 조건이 있으면) '작품 더 보기' ----
const ORIENTATION_FILTERS = ["all", "landscape", "portrait", "square"];

// heading: { key, vars } 또는 null
function buildResultGroup(works, search, heading) {
    const group = el("section", "result-group");

    const head = el("span", "group-heading");
    if (heading) head.appendChild(bindText(el("span", "group-title"), heading.key, heading.vars));
    const countLabel = el("span", "group-count");
    head.appendChild(countLabel);

    const segmented = el("div", "segmented");
    segmented.setAttribute("role", "group");
    const filterButtons = ORIENTATION_FILTERS.map((filter) => {
        const b = bindText(el("button"), filter);
        b.type = "button";
        b.addEventListener("click", () => group.setFilter(filter));
        return b;
    });
    segmented.append(...filterButtons);
    // 실제로 숨기는 일은 CSS가 한다: .result-group[data-filter] .card[data-orient]
    group.setFilter = (filter) => {
        group.dataset.filter = filter;
        filterButtons.forEach((b, i) => b.setAttribute("aria-pressed", String(ORIENTATION_FILTERS[i] === filter)));
    };
    group.setFilter(search?.orientation || "all");

    const toolbar = el("div", "group-toolbar");
    toolbar.append(head, segmented);
    const grid = el("div", "masonry");
    group.append(toolbar, grid);

    const seen = new Set();
    const appendWorks = (list) => {
        const fresh = list.filter((w) => !seen.has(w.id));
        fresh.forEach((w) => {
            seen.add(w.id);
            grid.appendChild(makeCard(w, seen.size));
        });
        bindText(countLabel, "count", { n: seen.size });
        return fresh.length;
    };
    appendWorks(works);
    if (search) group.appendChild(moreButton(search, appendWorks));
    return group;
}

// '작품 더 보기' — AI를 다시 부르지 않고 같은 검색 조건으로 DB만 넘겨 본다 (GET /api/artworks)
function moreButton(search, appendWorks) {
    const more = button("btn btn-ghost btn-sm more-btn", { labelKey: "more" });
    const params = new URLSearchParams({ q: (search.keywords || []).join(","), limit: BROWSE_PAGE_SIZE });
    if (search.artist) params.set("artist", search.artist);
    if (search.year_from != null) params.set("year_from", search.year_from);
    if (search.year_to != null) params.set("year_to", search.year_to);
    let offset = 0;

    more.addEventListener("click", async () => {
        more.disabled = true;
        setButtonLabel(more, "loading");
        let hasMore = true;
        let added = 0;
        // 첫 페이지는 이미 보여준 작품과 겹칠 수 있어, 새 작품이 나올 때까지 몇 페이지 더 넘긴다
        for (let tries = 0; tries < 3 && hasMore && added === 0; tries++) {
            params.set("offset", offset);
            const { ok, data } = await api(`/api/artworks?${params}`);
            if (!ok) { toast(errorMessage(data.error)); hasMore = false; break; }
            offset += BROWSE_PAGE_SIZE;
            hasMore = data.has_more;
            added += appendWorks(data.artworks);
        }
        more.disabled = false;
        setButtonLabel(more, "more");
        if (!hasMore) more.remove();
    });
    return more;
}

// ---- 전송 ----
// 스트리밍(/api/chat/stream)으로 받아 카드를 먼저 보여주고 글은 오는 대로 이어 붙인다.
// 브라우저나 연결이 스트리밍을 못 쓰면 한 번에 받기(/api/chat)로 대신한다
async function sendMessage(message) {
    if (state.sending) return;
    startTurn();
    addUserMessage(message);
    const pending = addPending();
    setSending(true);
    try {
        await receiveStream(message, pending);
    } finally {
        pending.remove();
        setSending(false);
        if (state.loggedIn) refreshSidebar();   // 성공·실패 모두 서버 대화 기록에 남는다
    }
}

async function receiveStream(message, pending) {
    // 30초 동안 아무것도(첫 응답·답변 조각) 오지 않으면 끊고 '접속자가 많습니다'를 보여준다 — 조각이 올 때마다 다시 잰다
    const controller = new AbortController();
    let timedOut = false;
    let timer = null;
    const arm = () => {
        clearTimeout(timer);
        timer = setTimeout(() => { timedOut = true; controller.abort(); }, CLIENT_TIMEOUT_MS);
    };
    arm();
    let res;
    try {
        res = await fetch("/api/chat/stream", {
            method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
            body: JSON.stringify({ message }), signal: controller.signal,
        });
    } catch (_) {
        clearTimeout(timer);
        if (timedOut) return showChatError(message, 504, { code: "BUSY" });
        return receiveOnce(message);   // 연결 자체가 안 되면 한 번에 받기로 다시 시도
    }
    if (!res.ok || !res.body) {   // 답변 전 단계(의도 추출·검색)에서 실패하면 스트림 없이 일반 오류 응답이 온다
        clearTimeout(timer);
        let data = {};
        try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
        return showChatError(message, res.status, data.error);
    }

    let answer = null;
    let meta = null;
    try {
        await readNdjson(res, (event) => {
            arm();
            if (event.type === "meta") {           // 검색이 끝났다 → 카드부터
                meta = event;
                pending.remove();
                answer = addBotAnswer(event.artworks || [], event.search);
            } else if (event.type === "delta") {   // 답변 글 조각
                answer?.append(event.text);
            } else if (event.type === "error") {   // 답변을 쓰다가 실패
                answer?.finish();
                showChatError(message, 500, { code: event.code, message: event.message });
            }
        });
    } catch (_) {
        clearTimeout(timer);
        answer?.finish();
        return showChatError(message, 0, { code: timedOut ? "BUSY" : "STREAM_DROPPED" });
    }
    clearTimeout(timer);
    answer?.finish();
    showLimitWarning(meta);
}

async function receiveOnce(message) {
    const { ok, status, data } = await postJson("/api/chat", { message });
    if (!ok) return showChatError(message, status, data.error);
    addBotAnswer(data.artworks || [], data.search).finish(data.reply);
    showLimitWarning(data);
}

function showChatError(message, status, error) {
    if (status === 401) { show(false); toast(t("sessionExpired")); return; }
    // Vercel이 시간 초과로 끊으면 JSON 없이 504가 온다 — 이것도 '접속자가 많습니다'로 안내한다
    if (!error?.code && [502, 503, 504].includes(status)) error = { code: "BUSY" };
    const code = error?.code;
    const retryable = ERRORS[code]?.retry || status === 0;
    addNotice("error", { error }, { code: code || String(status), onRetry: retryable ? () => sendMessage(message) : null });
}

function showLimitWarning(data) {
    if (data?.show_limit_warning) addNotice("warning", { key: "limitWarn", vars: { n: data.remaining_free } });
}

function setSending(value) {
    state.sending = value;
    updateComposer();
}

// 글자 수 표시, 보내기 버튼 활성화, 입력창 높이 자동 조절
function updateComposer() {
    const input = $("message-input");
    const length = input.value.length;
    $("char-count").textContent = `${length} / ${CHAT_MAX_LENGTH}`;
    $("char-count").classList.toggle("near", length > CHAT_MAX_LENGTH * 0.9);
    $("send-btn").disabled = state.sending || !input.value.trim();
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
}

function submitChat(event) {
    event.preventDefault();
    const input = $("message-input");
    const message = input.value.trim();
    if (!message || state.sending) return;   // 빈 입력 차단 (서버에서도 검증한다)
    input.value = "";
    updateComposer();
    sendMessage(message);
}

// =====================================================================
// 9. 대화 기록 · 즐겨찾기 목록
// =====================================================================
// 대화 기록 버튼: 넓은 화면에서는 왼쪽 사이드바 숨기기/보기, 좁은 화면에서는 서랍 열기
function onHistoryButton() {
    if (wideScreen.matches) {
        const collapsed = document.body.classList.toggle("sidebar-collapsed");
        store.set(STORAGE_KEYS.sidebar, collapsed ? "hidden" : "shown");
        syncHistoryButton();
        if (!collapsed) fitLatestTurn();
        return;
    }
    openDrawer("history");
    loadHistoryInto($("drawer-body"));
}

function syncHistoryButton() {
    const pressed = wideScreen.matches && !document.body.classList.contains("sidebar-collapsed");
    $("history-btn").setAttribute("aria-pressed", String(pressed));
    $("history-btn").title = t(wideScreen.matches ? (pressed ? "hideSidebar" : "showSidebar") : "history");
}

function refreshSidebar() {
    if (state.loggedIn) loadHistoryInto($("sidebar-body"));
}

// GET /api/me/chats를 페이지 단위로 불러와 목록을 그린다 (사이드바와 서랍이 같이 쓴다)
let historyRequest = 0;
async function loadHistoryInto(list) {
    const request = ++historyRequest;   // 새로 불러오기 시작하면 이전에 늦게 도착한 응답은 버린다
    list.replaceChildren(bindText(el("p", "empty"), "loading"));
    let offset = 0;
    const loadPage = async () => {
        const { ok, data } = await api(`/api/me/chats?limit=${HISTORY_PAGE_SIZE}&offset=${offset}`);
        if (request !== historyRequest) return;
        list.querySelector(".empty, .load-more")?.remove();
        if (!ok) { list.appendChild(bindError(el("p", "empty"), data.error)); return; }
        if (!offset && !data.chats.length) { list.appendChild(bindText(el("p", "empty"), "historyEmpty")); return; }
        list.append(...data.chats.map(historyItem));
        offset += data.chats.length;
        if (data.chats.length === HISTORY_PAGE_SIZE) {
            list.appendChild(button("btn btn-ghost btn-sm load-more", { labelKey: "loadMore", onClick: loadPage }));
        }
    };
    await loadPage();
}

// 질문 + 날짜·시간 한 줄. 펼치면 저장된 답변과 '다시 묻기'
function historyItem(chat) {
    const item = el("details", "history-item");
    const summary = el("summary");
    summary.append(el("span", "history-q", chat.question), timeEl("history-meta", new Date(chat.created_at), formatDateTime));
    item.appendChild(summary);
    if (chat.answer) item.appendChild(el("div", "history-answer", chat.answer));
    const actions = el("div", "history-actions");
    actions.appendChild(button("btn btn-soft btn-sm", { iconName: "retry", labelKey: "askAgain", onClick: () => {
        if ($("drawer").open) $("drawer").close();
        sendMessage(chat.question);
    } }));
    item.appendChild(actions);
    return item;
}

async function openFavorites() {
    openDrawer("favorites");
    const list = $("drawer-body");
    list.replaceChildren(bindText(el("p", "empty"), "loading"));
    const works = await loadFavorites();
    if (!works.length) { list.replaceChildren(bindText(el("p", "empty"), "favEmpty")); return; }
    const grid = el("div", "masonry");
    grid.append(...works.map((w) => makeCard(w)));
    list.replaceChildren(grid);
}

function openDrawer(titleKey) {
    bindText($("drawer-title"), titleKey);
    $("drawer").showModal();
}

// =====================================================================
// 10. 온디바이스 추천 (ondevice.js의 OnDevice 사용)
// =====================================================================
function currentOnDeviceFilters() {
    const yearFrom = $("od-year-from").value.trim();
    const yearTo = $("od-year-to").value.trim();
    return {
        style: $("od-style").value,
        subjects: $("od-subject").value.toLowerCase().split(",").map((s) => s.trim()).filter(Boolean),
        yearFrom: yearFrom ? Number(yearFrom) : null,
        yearTo: yearTo ? Number(yearTo) : null,
    };
}

function refreshRulePreview() {
    $("od-rule-preview").textContent = OnDevice.buildRuleText(currentOnDeviceFilters());
}

async function openLab() {
    $("lab-modal").showModal();
    if (state.onDeviceReady) return;
    $("od-rule-preview").textContent = t("labLoading");
    const facts = await OnDevice.loadFacts();   // artworks.json — 처음 열 때 한 번만 받는다
    $("od-style").append(...OnDevice.styleOptions(facts).map((style) => new Option(style, style)));
    state.onDeviceReady = true;
    refreshRulePreview();
}

// 자유 문장을 AI 없이 키워드 사전으로 해석해 조건 칸을 채운다
function parseOnDevice() {
    const text = $("od-freetext").value.trim();
    if (!text) return;
    const parsed = OnDevice.parseFreeText(text);
    $("od-style").value = parsed.style || "";
    $("od-subject").value = parsed.subjects.join(", ");
    $("od-year-from").value = parsed.yearFrom ?? "";
    $("od-year-to").value = parsed.yearTo ?? "";
    refreshRulePreview();
    toast(parsed.matchedTerms.length
        ? t("odParsed", { m: parsed.matchedTerms.map(([ko, en]) => `${ko}→${en}`).join(", ") })
        : t("odNone"));
}

async function runOnDevice() {
    const filters = currentOnDeviceFilters();
    const works = OnDevice.evalRule(await OnDevice.loadFacts(), filters);
    $("lab-modal").close();
    startTurn();
    const note = el("div", "msg msg-system");
    note.append(bindText(el("span"), "odMsg"), el("code", null, OnDevice.buildRuleText(filters)));
    turnTarget().appendChild(note);
    if (!works.length) { addNotice("warning", { key: "odEmpty" }); return; }
    addBotRow({ avatar: false }).body.appendChild(buildResultGroup(works, null, { key: "odHeading" }));
}

// =====================================================================
// 11. 상단 바 접기 · 테마 · 언어 · 앱 설치
// =====================================================================
// 아래로 내리면 상단 바를 위로 접어 작품 볼 공간을 넓히고, 위로 조금이라도 올리면 다시 펼친다.
// 페이지 맨 위 근처와 자동 스크롤(slowScrollTo) 중에는 항상 펼쳐 둔다.
const topbarScroll = { lastY: window.scrollY, auto: false };

function showTopbar() {
    document.body.classList.remove("topbar-hidden");
}

function onPageScroll() {
    const y = window.scrollY;
    const dy = y - topbarScroll.lastY;
    if (y < TOPBAR_HIDE_AFTER || topbarScroll.auto) {
        showTopbar();
        topbarScroll.lastY = y;
        return;
    }
    if (Math.abs(dy) < SCROLL_NOISE) return;
    document.body.classList.toggle("topbar-hidden", dy > 0);
    topbarScroll.lastY = y;
}

function toggleTheme() {
    const root = document.documentElement;
    const isDark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = isDark ? "light" : "dark";
    store.set(STORAGE_KEYS.theme, root.dataset.theme);
}

function toggleLang() {
    state.lang = state.lang === "en" ? "ko" : "en";
    document.documentElement.lang = state.lang;
    store.set(STORAGE_KEYS.lang, state.lang);
    applyI18n();
    renderExamples();
    renderTopics();
    langRerenders.forEach((render) => render());
    renderFavButtons();
    syncHistoryButton();
}

// ---- 앱 설치 (PWA) ----
const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
const isIOS = () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isMobile = () => isIOS() || /Android/i.test(navigator.userAgent);
const INSTALL_STEP_ICONS = { ios: ["external", "plus", "check"], generic: ["lab", "plus"] };

function showInstallSteps(kind) {
    $("install-steps").replaceChildren(...t(kind === "ios" ? "iosSteps" : "genericSteps").map((text, i) => {
        const badge = el("span", "step-icon");
        badge.appendChild(icon(INSTALL_STEP_ICONS[kind][i] || "check"));
        const li = el("li");
        li.append(badge, el("span", null, text));
        return li;
    }));
    $("install-modal").showModal();
}

// 모바일 브라우저에서만 설치 버튼을 보여준다. iOS는 설치 이벤트가 없어 안내 단계를 첫 방문에 한 번 띄운다
function setupInstall() {
    if (isStandalone() || !isMobile()) return;
    $("install-btn").hidden = false;
    if (isIOS() && store.get(STORAGE_KEYS.iosPrompt) !== "1") {
        showInstallSteps("ios");
        store.set(STORAGE_KEYS.iosPrompt, "1");
    }
    let deferredPrompt = null;
    window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredPrompt = e; });
    window.addEventListener("appinstalled", () => { $("install-btn").hidden = true; });
    $("install-btn").addEventListener("click", async () => {
        if (!deferredPrompt) { showInstallSteps(isIOS() ? "ios" : "generic"); return; }
        deferredPrompt.prompt();
        const choice = await deferredPrompt.userChoice;
        deferredPrompt = null;
        if (choice.outcome === "accepted") $("install-btn").hidden = true;
    });
    $("install-modal-close").addEventListener("click", () => $("install-modal").close());
}

// =====================================================================
// 12. 시작
// =====================================================================
function bindEvents() {
    // 모든 창(dialog)은 닫기 버튼과 바깥(어두운 배경) 클릭으로 닫힌다. Esc는 브라우저가 처리한다
    document.querySelectorAll("dialog").forEach((dialog) => {
        dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
        dialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dialog.close()));
    });

    // 상단 바
    $("history-btn").addEventListener("click", onHistoryButton);
    $("favorites-btn").addEventListener("click", openFavorites);
    $("lab-btn").addEventListener("click", openLab);
    $("logout-btn").addEventListener("click", logout);
    $("lang-btn").addEventListener("click", toggleLang);
    $("theme-btn").addEventListener("click", toggleTheme);
    window.addEventListener("scroll", onPageScroll, { passive: true });

    // 랜딩 · 로그인
    $("tab-login").addEventListener("click", () => setAuthMode("login"));
    $("tab-signup").addEventListener("click", () => setAuthMode("signup"));
    $("auth-form").addEventListener("submit", submitAuth);
    $("cta-signup").addEventListener("click", () => {
        setAuthMode("signup");
        window.scrollTo({ top: 0, behavior: "smooth" });
        setTimeout(() => $("email").focus({ preventScroll: true }), 400);
    });

    // 대화
    $("chat-form").addEventListener("submit", submitChat);
    $("message-input").addEventListener("input", updateComposer);
    $("message-input").addEventListener("keydown", (e) => {
        // 한글 입력 중(조합 중) Enter는 글자 확정용이라 보내지 않는다
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            $("chat-form").requestSubmit();
        }
    });
    window.addEventListener("resize", fitLatestTurn);

    // 대화 기록 사이드바
    $("sidebar-refresh").addEventListener("click", refreshSidebar);
    wideScreen.addEventListener("change", () => {
        syncHistoryButton();
        if (wideScreen.matches && $("drawer").open) $("drawer").close();   // 넓어지면 사이드바가 대신 보인다
    });

    // 온디바이스
    $("od-parse-btn").addEventListener("click", parseOnDevice);
    $("od-run-btn").addEventListener("click", runOnDevice);
    ["od-style", "od-subject", "od-year-from", "od-year-to"].forEach((id) => {
        $(id).addEventListener("input", () => { if (state.onDeviceReady) refreshRulePreview(); });
    });
}

async function init() {
    if (store.get(STORAGE_KEYS.sidebar) === "hidden") document.body.classList.add("sidebar-collapsed");
    bindEvents();
    applyI18n();
    setAuthMode("login");
    renderExamples();
    renderTopics();
    updateComposer();
    setupInstall();
    // 쿠키가 살아 있으면 바로 대화 화면, 아니면 랜딩
    const { ok, data } = await api("/api/me");
    show(ok, ok ? data.user.email : "", ok ? data.user.is_premium : false);
}

init();
