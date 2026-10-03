"""FastAPI 앱: 회원가입/로그인, 챗봇 질문/응답, 내 대화 로그 조회, 작품 즐겨찾기."""
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

from . import art, auth, chat, db
from .config import (ART_RESULTS_LIMIT, ART_RESULTS_LIMIT_PREMIUM, CHAT_LIFETIME_LIMIT_FREE,
                     CHAT_LIMIT_PER_HOUR, CHAT_LIMIT_PER_HOUR_PREMIUM, CHAT_MAX_LENGTH,
                     CONTEXT_TURNS, AIUnavailableError)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("app")

STATIC_DIR = Path(__file__).parent / "static"
COOKIE = "session"

app = FastAPI(title="저작권 걱정 없는 퍼블릭 도메인 명화 찾기 챗봇")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

STATUS_BY_CODE = {"AI_TIMEOUT": 504, "AI_ERROR": 502, "AI_EXPIRED": 503,
                  "AI_MODEL_NOT_ALLOWED": 503, "AI_KEY_MISSING": 503}


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
    return error(503, "DB_ERROR", "데이터베이스에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.")


def current_session(session: str | None = Cookie(default=None)) -> dict:
    data = auth.read_token(session)
    if data is None:
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "로그인이 필요합니다."})
    return data


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


@app.post("/api/auth/signup")
def signup(body: Credentials, request: Request):
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
    email = body.email.strip().lower()
    rows = db.execute("SELECT id, password_hash, is_premium FROM users WHERE email = ?", (email,))
    if not rows or not auth.verify_password(body.password, rows[0]["password_hash"]):
        log.info("login_failed")
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
def chat_endpoint(body: ChatRequest, session_data: dict = Depends(current_session)):
    user_id, is_premium = session_data["uid"], session_data["premium"]
    request_id = uuid.uuid4().hex[:8]
    log.info("request_received user_id=%s path=/api/chat request_id=%s", user_id, request_id)

    question = body.message.strip()
    if not question:
        return error(400, "EMPTY_MESSAGE", "질문을 입력해 주세요.")
    if len(question) > CHAT_MAX_LENGTH:
        return error(400, "MESSAGE_TOO_LONG", f"질문은 {CHAT_MAX_LENGTH}자 이하로 입력해 주세요.")

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

    started = time.monotonic()
    log.info("ai_call_start user_id=%s request_id=%s", user_id, request_id)
    art_limit = ART_RESULTS_LIMIT_PREMIUM if is_premium else ART_RESULTS_LIMIT
    try:
        intent = chat.extract_intent(question)
        works = chat.find_artworks(intent, limit=art_limit)
        answer = chat.compose_answer(question, works, history)
    except AIUnavailableError as e:
        latency = int((time.monotonic() - started) * 1000)
        log.error("ai_call_failure request_id=%s code=%s latency_ms=%s", request_id, e.code, latency)
        _save_chat(user_id, question, None, "error", e.code, latency, [])
        return error(STATUS_BY_CODE.get(e.code, 502), e.code, str(e))
    except sqlite3.Error as e:
        latency = int((time.monotonic() - started) * 1000)
        log.error("art_db_failure request_id=%s detail=%s", request_id, e)
        _save_chat(user_id, question, None, "error", "ART_DB_ERROR", latency, [])
        return error(503, "ART_DB_ERROR", "작품 데이터베이스를 읽지 못했어요.")

    latency = int((time.monotonic() - started) * 1000)
    log.info("ai_call_success request_id=%s latency_ms=%s artworks=%s", request_id, latency, len(works))
    chat_id = _save_chat(user_id, question, answer, "ok", None, latency, [w["id"] for w in works])
    return {"chat_id": chat_id, "saved": chat_id is not None, "request_id": request_id,
            "reply": answer, "artworks": works}


@app.get("/api/me/chats")
def my_chats(limit: int = 20, offset: int = 0, user_id: int = Depends(current_user)):
    limit = max(1, min(limit, 100))
    rows = db.execute(
        "SELECT id, question, answer, status, error_code, latency_ms, created_at FROM chats "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limit, max(0, offset)))
    return {"chats": rows}


# ---- 작품 즐겨찾기 ----
def _artwork_or_404(artwork_id: int) -> None:
    try:
        exists = artwork_id in art.get_by_ids([artwork_id])
    except sqlite3.Error as e:
        log.error("art_db_failure path=/api/favorites detail=%s", e)
        raise HTTPException(503, {"code": "ART_DB_ERROR", "message": "작품 데이터베이스를 읽지 못했어요."})
    if not exists:
        raise HTTPException(404, {"code": "ARTWORK_NOT_FOUND", "message": "존재하지 않는 작품입니다."})


@app.post("/api/favorites")
def add_favorite(body: FavoriteRequest, user_id: int = Depends(current_user)):
    """이미 저장한 작품이면 200(created=false), 새로 저장하면 201. 같은 요청을 반복해도 안전하다."""
    _artwork_or_404(body.artwork_id)
    created = db.execute(
        "INSERT INTO favorites (user_id, artwork_id, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT (user_id, artwork_id) DO NOTHING RETURNING id",
        (user_id, body.artwork_id, _now()))
    log.info("favorite_add user_id=%s artwork_id=%s created=%s", user_id, body.artwork_id, bool(created))
    return JSONResponse({"artwork_id": body.artwork_id, "created": bool(created)},
                        status_code=201 if created else 200)


@app.delete("/api/favorites/{artwork_id}")
def remove_favorite(artwork_id: int, user_id: int = Depends(current_user)):
    """저장하지 않은 작품을 지워도 오류가 아니다(removed=false)."""
    removed = db.execute("DELETE FROM favorites WHERE user_id = ? AND artwork_id = ? RETURNING id",
                         (user_id, artwork_id))
    log.info("favorite_remove user_id=%s artwork_id=%s removed=%s", user_id, artwork_id, bool(removed))
    return {"artwork_id": artwork_id, "removed": bool(removed)}


# ---- AIC 이미지 프록시 ----
# AIC 이미지 서버는 `AIC-User-Agent` 헤더와 (파이썬 기본이 아닌) User-Agent가 없으면 403을 준다. 브라우저 <img>는 헤더를 붙일 수 없어 서버가 대신 받는다.
AIC_IIIF = "https://www.artic.edu/iiif/2"
AIC_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
AIC_WIDTHS = {200, 400, 843, 1686}
AIC_UA = "AITOOLLEARN-7-1 (student project; https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1)"


@app.get("/api/img/aic/{image_id}")
def aic_image(image_id: str, w: int = 400):
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
    return Response(body, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400, s-maxage=31536000, immutable"})
