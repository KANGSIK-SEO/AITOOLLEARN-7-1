/* TV 앱은 항상 다른 오리진에서 백엔드를 호출하므로 쿠키 대신 Authorization: Bearer 헤더를 쓴다.
 * ?api_base=http://localhost:8000 으로 로컬 개발 서버를 가리킬 수 있다(시뮬레이터/개발용). */
const BASE_URL = new URLSearchParams(location.search).get("api_base") || "https://art-chatbot-eight.vercel.app";
const TOKEN_KEY = "art_chatbot_tv_token";

const ERROR_MESSAGES = {
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
};

function errorMessage(err, generic) {
    const code = err && err.code;
    return (code && ERROR_MESSAGES[code]) || (err && err.message) || generic;
}

function getToken() {
    try { return localStorage.getItem(TOKEN_KEY); } catch (_) { return null; }
}

function setToken(token) {
    try { localStorage.setItem(TOKEN_KEY, token); } catch (_) { /* 저장 실패는 무시, 로그인 화면이 다시 뜰 뿐 */ }
}

function clearToken() {
    try { localStorage.removeItem(TOKEN_KEY); } catch (_) { /* no-op */ }
}

async function api(path, options = {}) {
    const token = getToken();
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    let res;
    try {
        res = await fetch(BASE_URL + path, { headers, ...options });
    } catch (networkError) {
        return { ok: false, status: 0, data: { error: { code: "NETWORK_ERROR", message: "네트워크에 연결할 수 없습니다." } } };
    }
    let data = {};
    try { data = await res.json(); } catch (_) { /* 본문 없음 */ }
    return { ok: res.ok, status: res.status, data };
}
