"""FastAPI 앱: 회원가입/로그인, 챗봇 질문/응답, 내 대화 로그 조회."""
import json
import logging
import re
import socket
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import art, auth, chat, db, guardian
from .config import (ART_RESULTS_LIMIT, ART_RESULTS_LIMIT_PREMIUM, BROWSE_LIMIT_PER_HOUR, BROWSE_PAGE_SIZE,
                     CHAT_LIFETIME_LIMIT_FREE, CHAT_LIMIT_PER_HOUR, CHAT_LIMIT_PER_HOUR_PREMIUM,
                     CHAT_MAX_LENGTH, CONTEXT_TURNS, CRON_SECRET, FAVORITES_MAX, GUEST_TRIAL_LIMIT,
                     GUEST_TRIAL_WINDOW_SECONDS, AIUnavailableError)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("app")

STATIC_DIR = Path(__file__).parent / "static"
COOKIE = "session"

app = FastAPI(title="저작권 걱정 없는 퍼블릭 도메인 명화 찾기 챗봇")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

STATUS_BY_CODE = {"AI_TIMEOUT": 504, "AI_ERROR": 502, "AI_RATE_LIMITED": 429,
                  "AI_KEY_MISSING": 503, "AI_BACKED_OFF": 503}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    return JSONResponse({"error": detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exc(_: Request, __: RequestValidationError):
    return error(422, "INVALID_INPUT", "요청 형식이 올바르지 않습니다.")


@app.exception_handler(db.DbError)
async def db_exc(_: Request, exc: db.DbError):
    log.error("db_error detail=%s", exc)
    guardian.record_incident("reliability", "DB_ERROR", str(exc), {}, "high")
    return error(503, "DB_ERROR", "데이터베이스에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.")


@app.exception_handler(Exception)
async def unhandled_exc(_: Request, exc: Exception):
    log.error("unhandled_exception detail=%r", exc, exc_info=True)
    guardian.record_incident("reliability", "UNHANDLED_EXCEPTION", repr(exc), {}, "high")
    return error(500, "INTERNAL_ERROR", "예상치 못한 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")


def current_session(session: str | None = Cookie(default=None)) -> dict:
    data = auth.read_token(session)
    if data is None:
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "로그인이 필요합니다."})
    return data


def optional_session(session: str | None = Cookie(default=None)) -> dict | None:
    """로그인했으면 세션, 아니면 None (가입 전 체험 사용자)."""
    return auth.read_token(session)


def current_user(session_data: dict = Depends(current_session)) -> int:
    return session_data["uid"]


class Credentials(BaseModel):
    email: str
    password: str
    private_code: str | None = None  # 회원가입 시에만 사용. 일치하면 프리미엄으로 가입된다.


class ChatRequest(BaseModel):
    message: str


class FavoriteRequest(BaseModel):
    artwork_id: int


def _set_cookie(resp: JSONResponse, user_id: int, is_premium: bool, request: Request) -> None:
    resp.set_cookie(COOKIE, auth.make_token(user_id, is_premium), max_age=auth.TOKEN_TTL_SECONDS,
                    httponly=True, samesite="lax", secure=request.url.scheme == "https")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/guardian/daily-digest")
def guardian_daily_digest(request: Request):
    """가디언의 일일 점검 (Vercel Cron 전용, CRON_SECRET으로 보호)."""
    if not CRON_SECRET or request.headers.get("authorization") != f"Bearer {CRON_SECRET}":
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "cron only"})
    return guardian.run_daily_digest()


@app.post("/api/auth/signup")
def signup(body: Credentials, request: Request):
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"signup:{ip}", limit=10, window_seconds=3600):
        guardian.record_incident("security", "SIGNUP_RATE_LIMITED", f"{ip} 가입 시도 과다", {"ip": ip}, "medium")
        return error(429, "RATE_LIMITED", "가입 시도가 너무 많아요. 잠시 후 다시 시도해 주세요.")
    email = body.email.strip().lower()
    if not auth.EMAIL_RE.match(email) or len(email) > 254:
        return error(400, "INVALID_EMAIL", "이메일 형식이 올바르지 않습니다.")
    if not 8 <= len(body.password) <= 128:
        return error(400, "INVALID_PASSWORD", "비밀번호는 8자 이상 128자 이하여야 합니다.")
    if db.execute("SELECT 1 AS x FROM users WHERE email = ?", (email,)):
        return error(409, "EMAIL_TAKEN", "이미 가입된 이메일입니다.")
    is_premium = auth.check_premium_code(body.private_code)
    try:
        row = db.execute(
            "INSERT INTO users (email, password_hash, is_premium, created_at) VALUES (?, ?, ?, ?) RETURNING id",
            (email, auth.hash_password(body.password), int(is_premium), _now()))[0]
    except db.DbError:  # 동시 가입으로 UNIQUE 충돌
        return error(409, "EMAIL_TAKEN", "이미 가입된 이메일입니다.")
    log.info("signup_success user_id=%s is_premium=%s", row["id"], is_premium)
    resp = JSONResponse({"user": {"id": row["id"], "email": email, "is_premium": is_premium}}, status_code=201)
    _set_cookie(resp, row["id"], is_premium, request)
    return resp


@app.post("/api/auth/login")
def login(body: Credentials, request: Request):
    ip = guardian.client_ip(request)
    email = body.email.strip().lower()
    if guardian.check_login_lockout(email) or not guardian.check_rate(f"login:{ip}", limit=20, window_seconds=600):
        return error(429, "RATE_LIMITED", "로그인 시도가 너무 많아요. 잠시 후 다시 시도해 주세요.")
    rows = db.execute("SELECT id, password_hash, is_premium FROM users WHERE email = ?", (email,))
    if not rows or not auth.verify_password(body.password, rows[0]["password_hash"]):
        log.info("login_failed")
        guardian.note_login_failure(email)
        return error(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
    is_premium = bool(rows[0]["is_premium"])
    log.info("login_success user_id=%s is_premium=%s", rows[0]["id"], is_premium)
    resp = JSONResponse({"user": {"id": rows[0]["id"], "email": email, "is_premium": is_premium}})
    _set_cookie(resp, rows[0]["id"], is_premium, request)
    return resp


@app.post("/api/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/api/me")
def me(user_id: int = Depends(current_user)):
    rows = db.execute("SELECT id, email, created_at, is_premium FROM users WHERE id = ?", (user_id,))
    if not rows:
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "로그인이 필요합니다."})
    user = rows[0]
    user["is_premium"] = bool(user["is_premium"])
    return {"user": user}


@app.get("/api/guest")
def guest_status(request: Request):
    """가입 전 체험 사용자가 남은 무료 질문 수를 화면에 보여주기 위한 조회 (카운터는 올리지 않음)."""
    used = guardian.rate_used(f"guest:{guardian.client_ip(request)}", GUEST_TRIAL_WINDOW_SECONDS)
    return {"limit": GUEST_TRIAL_LIMIT, "remaining": max(0, GUEST_TRIAL_LIMIT - used)}


def _save_chat(user_id, question, answer, status, error_code, latency_ms, artwork_ids) -> int | None:
    try:
        row = db.execute(
            "INSERT INTO chats (user_id, question, answer, status, error_code, latency_ms, artwork_ids, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (user_id, question, answer, status, error_code, latency_ms, json.dumps(artwork_ids), _now()))[0]
        log.info("db_save_success user_id=%s chat_id=%s status=%s", user_id, row["id"], status)
        return row["id"]
    except db.DbError as e:
        log.error("db_save_failure user_id=%s detail=%s", user_id, e)
        return None


@app.post("/api/chat")
def chat_endpoint(body: ChatRequest, request: Request, session_data: dict | None = Depends(optional_session)):
    is_guest = session_data is None
    user_id = None if is_guest else session_data["uid"]
    is_premium = False if is_guest else session_data["premium"]
    guest_bucket = f"guest:{guardian.client_ip(request)}"
    request_id = uuid.uuid4().hex[:8]
    log.info("request_received user_id=%s path=/api/chat request_id=%s", user_id, request_id)

    question = body.message.strip()
    if not question:
        return error(400, "EMPTY_MESSAGE", "질문을 입력해 주세요.")
    if len(question) > CHAT_MAX_LENGTH:
        return error(400, "MESSAGE_TOO_LONG", f"질문은 {CHAT_MAX_LENGTH}자 이하로 입력해 주세요.")
    if guardian.looks_malicious(question):
        guardian.record_incident("security", "MALICIOUS_INPUT_BLOCKED", "의심스러운 입력 패턴 차단",
                                 {"user_id": user_id, "request_id": request_id}, "medium")
        return error(400, "INVALID_INPUT", "허용되지 않는 입력입니다.")
    if guardian.is_ai_backed_off():
        return error(503, "AI_BACKED_OFF", "AI 서비스가 일시적으로 쉬고 있어요. 잠시 후 다시 시도해 주세요.")

    if is_guest:
        # 체험은 성공한 질문만 센다 — AI 장애로 실패한 질문 때문에 체험 기회를 잃지 않게.
        if guardian.rate_used(guest_bucket, GUEST_TRIAL_WINDOW_SECONDS) >= GUEST_TRIAL_LIMIT:
            log.warning("guest_limit_reached request_id=%s", request_id)
            return error(403, "GUEST_LIMIT_REACHED",
                         f"무료 체험 {GUEST_TRIAL_LIMIT}회를 모두 사용했어요. 가입하면 계속 이용할 수 있어요.")
        # 성공만 세면 동시에 여러 요청을 보내 체험 한도를 넘길 수 있어, 시도 횟수 자체에도 상한을 둔다
        if not guardian.check_rate(f"guest_try:{guardian.client_ip(request)}", limit=GUEST_TRIAL_LIMIT * 3,
                                   window_seconds=GUEST_TRIAL_WINDOW_SECONDS):
            return error(429, "RATE_LIMITED", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
        return _run_chat(None, False, question, [], request_id, guest_bucket)

    hour_limit = CHAT_LIMIT_PER_HOUR_PREMIUM if is_premium else CHAT_LIMIT_PER_HOUR
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    used_hour = db.execute("SELECT COUNT(*) AS n FROM chats WHERE user_id = ? AND created_at > ?", (user_id, since))[0]["n"]
    if used_hour >= hour_limit:
        log.warning("rate_limited user_id=%s request_id=%s is_premium=%s", user_id, request_id, is_premium)
        return error(429, "RATE_LIMITED", "질문이 너무 많아요. 잠시 후 다시 시도해 주세요.")

    if not is_premium:
        used_lifetime = db.execute(
            "SELECT COUNT(*) AS n FROM chats WHERE user_id = ? AND status = 'ok'", (user_id,))[0]["n"]
        if used_lifetime >= CHAT_LIFETIME_LIMIT_FREE:
            log.warning("free_limit_reached user_id=%s request_id=%s", user_id, request_id)
            return error(403, "FREE_LIMIT_REACHED",
                        f"무료 이용 {CHAT_LIFETIME_LIMIT_FREE}회를 모두 사용했어요. 초대코드가 있다면 입력해 보세요.")

    history = list(reversed(db.execute(
        "SELECT question, answer FROM chats WHERE user_id = ? AND status = 'ok' ORDER BY id DESC LIMIT ?",
        (user_id, CONTEXT_TURNS))))
    return _run_chat(user_id, is_premium, question, history, request_id, None)


def _run_chat(user_id: int | None, is_premium: bool, question: str, history: list[dict],
              request_id: str, guest_bucket: str | None):
    """user_id가 None이면 가입 전 체험: 대화 로그를 남기지 않고(users FK 없음) 체험 카운터만 올린다."""
    save = _save_chat if user_id is not None else (lambda *a, **k: None)
    started = time.monotonic()
    log.info("ai_call_start user_id=%s request_id=%s", user_id, request_id)
    art_limit = ART_RESULTS_LIMIT_PREMIUM if is_premium else ART_RESULTS_LIMIT
    try:
        intent = chat.extract_intent(question)
        works, relaxed = chat.find_artworks(intent, limit=art_limit)
        answer = chat.compose_answer(question, works, history, relaxed=relaxed)
    except AIUnavailableError as e:
        latency = int((time.monotonic() - started) * 1000)
        log.error("ai_call_failure request_id=%s code=%s latency_ms=%s", request_id, e.code, latency)
        save(user_id, question, None, "error", e.code, latency, [])
        guardian.record_incident("reliability", e.code, str(e), {"request_id": request_id, "latency_ms": latency},
                                 "medium" if e.code == "AI_RATE_LIMITED" else "low")
        guardian.note_ai_failure(e.code)
        return error(STATUS_BY_CODE.get(e.code, 502), e.code, str(e))
    except sqlite3.Error as e:
        latency = int((time.monotonic() - started) * 1000)
        log.error("art_db_failure request_id=%s detail=%s", request_id, e)
        save(user_id, question, None, "error", "ART_DB_ERROR", latency, [])
        return error(503, "ART_DB_ERROR", "작품 데이터베이스를 읽지 못했어요.")

    latency = int((time.monotonic() - started) * 1000)
    log.info("ai_call_success request_id=%s latency_ms=%s artworks=%s", request_id, latency, len(works))
    chat_id = save(user_id, question, answer, "ok", None, latency, [w["id"] for w in works])
    # '더 보기'가 AI를 다시 부르지 않고 같은 조건으로 DB만 넘겨 볼 수 있게 검색 조건을 함께 돌려준다
    search = {k: intent.get(k) for k in ("keywords", "artist", "year_from", "year_to", "orientation")}
    if relaxed:  # 작가/연도 조건을 빼고 찾은 결과면 '더 보기'도 같은 완화 조건을 쓴다
        search.update(artist=None, year_from=None, year_to=None)
    result = {"chat_id": chat_id, "saved": chat_id is not None, "request_id": request_id,
              "reply": answer, "artworks": works, "search": None if intent["chitchat"] else search}
    if guest_bucket:
        guardian.check_rate(guest_bucket, GUEST_TRIAL_LIMIT, GUEST_TRIAL_WINDOW_SECONDS)
        used = guardian.rate_used(guest_bucket, GUEST_TRIAL_WINDOW_SECONDS)
        result["guest_remaining"] = max(0, GUEST_TRIAL_LIMIT - used)
    return result


@app.get("/api/me/chats")
def my_chats(limit: int = 20, offset: int = 0, user_id: int = Depends(current_user)):
    limit = max(1, min(limit, 100))
    rows = db.execute(
        "SELECT id, question, answer, status, error_code, latency_ms, created_at FROM chats "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limit, max(0, offset)))
    return {"chats": rows}


@app.get("/api/artworks")
def browse_artworks(request: Request, q: str = "", artist: str | None = None, year_from: int | None = None,
                    year_to: int | None = None, offset: int = 0, limit: int = BROWSE_PAGE_SIZE):
    """'더 보기' — 채팅 답변의 검색 조건으로 작품을 더 넘겨 본다. AI를 부르지 않아 비용이 없고 체험 사용자도 쓸 수 있다."""
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"browse:{ip}", limit=BROWSE_LIMIT_PER_HOUR, window_seconds=3600):
        return error(429, "RATE_LIMITED", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
    keywords = [k for k in q.split(",") if k.strip()][:6]
    try:
        works, has_more = art.browse(keywords, artist or None, year_from, year_to,
                                     offset=max(0, min(offset, 5000)), limit=max(1, min(limit, 60)))
    except sqlite3.Error as e:
        log.error("art_db_failure path=/api/artworks detail=%s", e)
        return error(503, "ART_DB_ERROR", "작품 데이터베이스를 읽지 못했어요.")
    return {"artworks": works, "has_more": has_more}


@app.get("/api/me/favorites")
def list_favorites(user_id: int = Depends(current_user)):
    rows = db.execute("SELECT artwork_id FROM favorites WHERE user_id = ? ORDER BY created_at DESC, artwork_id DESC",
                      (user_id,))
    return {"artworks": art.get_by_ids([r["artwork_id"] for r in rows])}


@app.post("/api/me/favorites")
def add_favorite(body: FavoriteRequest, user_id: int = Depends(current_user)):
    if not art.get_by_ids([body.artwork_id]):
        return error(404, "ARTWORK_NOT_FOUND", "작품을 찾을 수 없습니다.")
    if db.execute("SELECT COUNT(*) AS n FROM favorites WHERE user_id = ?", (user_id,))[0]["n"] >= FAVORITES_MAX:
        return error(409, "FAVORITES_FULL", f"즐겨찾기는 최대 {FAVORITES_MAX}개까지 저장할 수 있어요.")
    db.execute("INSERT INTO favorites (user_id, artwork_id, created_at) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, artwork_id) DO NOTHING", (user_id, body.artwork_id, _now()))
    return {"ok": True}


@app.delete("/api/me/favorites/{artwork_id}")
def remove_favorite(artwork_id: int, user_id: int = Depends(current_user)):
    db.execute("DELETE FROM favorites WHERE user_id = ? AND artwork_id = ?", (user_id, artwork_id))
    return {"ok": True}


# ---- AIC 이미지 프록시 ----
# AIC 이미지 서버는 `AIC-User-Agent` 헤더와 (파이썬 기본이 아닌) User-Agent가 없으면 403을 준다. 브라우저 <img>는 헤더를 붙일 수 없어 서버가 대신 받는다.
AIC_IIIF = "https://www.artic.edu/iiif/2"
AIC_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
AIC_WIDTHS = {200, 400, 843, 1686}
AIC_UA = "AITOOLLEARN-7-1 (student project; https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1)"


@app.get("/api/img/aic/{image_id}")
def aic_image(image_id: str, w: int = 400, download: int = 0, request: Request = None):
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"img:{ip}", limit=300, window_seconds=3600):
        return error(429, "RATE_LIMITED", "이미지 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
    if not AIC_ID_RE.match(image_id) or w not in AIC_WIDTHS:
        return error(400, "INVALID_IMAGE", "지원하지 않는 이미지 요청입니다.")
    req = urllib.request.Request(f"{AIC_IIIF}/{image_id}/full/{w},/0/default.jpg", headers={"AIC-User-Agent": AIC_UA, "User-Agent": "AITOOLLEARN-7-1/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        log.warning("image_proxy_failure image_id=%s status=%s", image_id, e.code)
        return error(404 if e.code == 404 else 502, "IMAGE_UNAVAILABLE", "이미지를 불러오지 못했습니다.")
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        log.warning("image_proxy_failure image_id=%s detail=%s", image_id, e)
        return error(502, "IMAGE_UNAVAILABLE", "이미지를 불러오지 못했습니다.")
    # 이미지는 바뀌지 않으므로 CDN·브라우저에 오래 캐시해 프록시 호출을 최소화한다
    headers = {"Cache-Control": "public, max-age=86400, s-maxage=31536000, immutable"}
    if download:  # '다운로드' 버튼: 브라우저가 새 탭 대신 파일로 저장하게 한다
        headers["Content-Disposition"] = f'attachment; filename="aic-{image_id}.jpg"'
    return Response(body, media_type="image/jpeg", headers=headers)
