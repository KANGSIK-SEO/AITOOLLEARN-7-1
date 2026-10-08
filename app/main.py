"""FastAPI 앱: 회원가입/로그인, 챗봇 질문/응답, 내 대화 로그 조회, 작품 즐겨찾기."""
import hashlib
import hmac
import json
import logging
import re
import socket
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from . import art, auth, chat, db, explain, guardian, records, reqctx
from .config import (ART_RESULTS_LIMIT, ART_RESULTS_LIMIT_PREMIUM, CHAT_LIFETIME_LIMIT_FREE,
                     CHAT_LIMIT_PER_HOUR, CHAT_LIMIT_PER_HOUR_PREMIUM, CHAT_MAX_LENGTH,
                     CONTEXT_TURNS, CRON_SECRET, FREE_LIMIT_WARNING_THRESHOLD, BROWSE_LIMIT_PER_HOUR,
                     BROWSE_PAGE_SIZE, RECORD_LIMIT_PER_HOUR, AIUnavailableError, validate_env)

reqctx.install()
logging.basicConfig(level=logging.INFO, format=reqctx.LOG_FORMAT)
log = logging.getLogger("app")

# 필수 환경변수가 틀리면 첫 요청이 아니라 서버 시작 시점에 고칠 방법과 함께 실패한다
for _warning in validate_env():
    log.warning("config_warning %s", _warning)

STATIC_DIR = Path(__file__).parent / "static"
COOKIE = "session"

app = FastAPI(title="저작권 걱정 없는 퍼블릭 도메인 명화 찾기 챗봇")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# TV 앱 등 다른 오리진 클라이언트는 쿠키 대신 Authorization: Bearer 헤더로 인증하므로
# 자격 증명(쿠키) 공유는 필요 없다 — allow_credentials=False라 allow_origins="*"와 함께 써도 안전하다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

@app.middleware("http")
async def request_context(request: Request, call_next):
    """요청마다 request_id를 정하고(app/reqctx.py), 가디언 실시간 감시를 거친다.
    - 차단된 IP는 바로 403, 공격 도구가 찾는 경로는 404로 끝내고 횟수를 센다 (app/guardian.py)
    - 처리 중 생긴 즉시 분석 요청은 응답을 보낸 뒤에 실행해 사용자를 기다리게 하지 않는다"""
    reqctx.set_request_id(reqctx.new_request_id())
    pending = reqctx.start_pending()
    ip = guardian.client_ip(request)
    if await run_in_threadpool(guardian.is_blocked, ip):
        return error(403, "BLOCKED", "의심스러운 요청이 반복되어 잠시 접속이 제한되었어요. 잠시 후 다시 시도해 주세요.")
    if guardian.PROBE_PATH_RE.search(request.url.path):
        await run_in_threadpool(guardian.note_probe, ip, request.url.path)
        response = error(404, "NOT_FOUND", "찾을 수 없습니다.")
    else:
        try:
            response = await call_next(request)
        except Exception:  # 처리 못 한 오류도 사건으로 남겨 실시간 감시가 알게 한다
            log.exception("unhandled_error path=%s", request.url.path)
            await run_in_threadpool(guardian.record_incident, "reliability", "SERVER_ERROR",
                                    f"{request.method} {request.url.path} 처리 중 오류", {"path": request.url.path}, "high")
            response = error(500, "SERVER_ERROR", "서버에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.")
    if pending.get("triage") and response.background is None:
        response.background = BackgroundTask(guardian.run_triage, pending["triage"])
    return response


STATUS_BY_CODE = {"AI_TIMEOUT": 504, "AI_ERROR": 502, "AI_RATE_LIMITED": 429,
                  "AI_KEY_MISSING": 503, "AI_BACKED_OFF": 503, "AI_REFUSED": 422}


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


def current_session(session: str | None = Cookie(default=None),
                    authorization: str | None = Header(default=None)) -> dict:
    # 웹 클라이언트는 쿠키로, TV 등 다른 오리진 클라이언트는 Authorization: Bearer 헤더로 인증한다.
    # 쿠키가 있으면 쿠키를 우선한다(기존 동작 그대로 유지).
    token = session
    if token is None and authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]
    data = auth.read_token(token)
    if data is None:
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "로그인이 필요합니다."})
    return data


def optional_session(session: str | None = Cookie(default=None),
                     authorization: str | None = Header(default=None)) -> dict | None:
    """로그인했으면 세션, 아니면 None. 챗봇 질문에는 쓰지 않는다(질문은 로그인 필수)."""
    try:
        return current_session(session, authorization)
    except HTTPException:
        return None


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


def _set_cookie(resp: JSONResponse, token: str, request: Request) -> None:
    resp.set_cookie(COOKIE, token, max_age=auth.TOKEN_TTL_SECONDS,
                    httponly=True, samesite="lax", secure=request.url.scheme == "https")


# ---- 배포 시 캐시 무효화 ----
# 화면 파일 내용으로 버전을 만든다. 파일이 바뀌어 배포되면 버전이 바뀌므로
# ① index.html의 정적 파일 주소(?v=버전)가 달라져 브라우저·CDN 캐시를 우회하고
# ② 서비스워커 캐시 이름이 달라져 새 서비스워커가 옛 캐시를 지운다 (sw.js의 activate).
VERSIONED_ASSETS = ("style.css", "app.js", "ondevice.js")
ASSET_VERSION = hashlib.sha256(b"".join(
    (STATIC_DIR / name).read_bytes() for name in (*VERSIONED_ASSETS, "index.html", "sw.js")
)).hexdigest()[:10]
NO_CACHE = {"Cache-Control": "no-cache"}  # 매번 서버에 새 버전이 있는지 확인 (내용이 같으면 304로 가볍게)


def _versioned(text: str) -> str:
    for name in VERSIONED_ASSETS:
        text = text.replace(f"/static/{name}'", f"/static/{name}?v={ASSET_VERSION}'")
        text = text.replace(f'/static/{name}"', f'/static/{name}?v={ASSET_VERSION}"')
    return text


INDEX_HTML = _versioned((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
SW_JS = _versioned((STATIC_DIR / "sw.js").read_text(encoding="utf-8")).replace("__ASSET_VERSION__", ASSET_VERSION)


@app.get("/")
def index():
    return HTMLResponse(INDEX_HTML, headers=NO_CACHE)


@app.get("/sw.js")
def service_worker():
    # 정적 마운트(/static)가 아니라 루트에서 서빙해야 서비스워커 적용 범위가 사이트 전체(/)가 된다.
    return Response(SW_JS, media_type="application/javascript", headers=NO_CACHE)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/healthz")
def healthz():
    """의존성까지 확인하는 상태 점검 (업타임 모니터·배포 후 확인용).

    /api/health는 프로세스가 떠 있는지만 본다(항상 200). /healthz는 사용자 DB(Turso/로컬)와
    미술 DB(data/art.db)에 실제로 쿼리를 보내, 하나라도 실패하면 503을 돌려준다.
    AI는 호출마다 비용이 들고 외부 장애가 곧 우리 장애는 아니므로 확인하지 않는다.
    오류 상세(접속 주소·경로)는 응답에 넣지 않고 로그에만 남긴다.
    """
    checks = {}
    for name, probe, errors in (("db", lambda: db.execute("SELECT 1 AS ok"), db.DbError),
                                ("art_db", art.ping, sqlite3.Error)):
        started = time.monotonic()
        try:
            probe()
            checks[name] = {"status": "ok", "latency_ms": int((time.monotonic() - started) * 1000)}
        except errors as e:
            log.error("healthz_check_failed check=%s detail=%s", name, e)
            checks[name] = {"status": "error"}
    healthy = all(c["status"] == "ok" for c in checks.values())
    return JSONResponse({"status": "ok" if healthy else "degraded", "checks": checks},
                        status_code=200 if healthy else 503, headers={"Cache-Control": "no-store"})


@app.get("/api/guardian/daily-digest")
def guardian_daily_digest(request: Request):
    """가디언의 일일 점검 (Vercel Cron 전용, CRON_SECRET으로 보호)."""
    if not CRON_SECRET or request.headers.get("authorization") != f"Bearer {CRON_SECRET}":
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "cron only"})
    return guardian.run_daily_digest()


@app.post("/api/guardian/scan")
def guardian_scan(request: Request):
    """실시간 감시 보조: 요청이 없을 때도 5분마다 최근 사건을 훑는다 (.github/workflows/monitor.yml, CRON_SECRET 필요)."""
    if not CRON_SECRET or request.headers.get("authorization") != f"Bearer {CRON_SECRET}":
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "cron only"})
    return guardian.scan()


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
    token = auth.make_token(row["id"], is_premium)
    resp = JSONResponse({"user": {"id": row["id"], "email": email, "is_premium": is_premium}, "token": token},
                        status_code=201)
    _set_cookie(resp, token, request)
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
        guardian.note_login_failure(email, ip)
        return error(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
    is_premium = bool(rows[0]["is_premium"])
    log.info("login_success user_id=%s is_premium=%s", rows[0]["id"], is_premium)
    token = auth.make_token(rows[0]["id"], is_premium)
    resp = JSONResponse({"user": {"id": rows[0]["id"], "email": email, "is_premium": is_premium}, "token": token})
    _set_cookie(resp, token, request)
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


def _chat_context(body: ChatRequest, session_data: dict, request: Request) -> dict | JSONResponse:
    """질문 전 검사(입력·사용량·AI 쉼)를 하고, 통과하면 답변에 필요한 값을 돌려준다. 막히면 오류 응답."""
    user_id, is_premium = session_data["uid"], session_data["premium"]
    request_id = reqctx.get_request_id()
    log.info("request_received user_id=%s path=%s", user_id, request.url.path)

    question = body.message.strip()
    if not question:
        return error(400, "EMPTY_MESSAGE", "질문을 입력해 주세요.")
    if len(question) > CHAT_MAX_LENGTH:
        return error(400, "MESSAGE_TOO_LONG", f"질문은 {CHAT_MAX_LENGTH}자 이하로 입력해 주세요.")
    if guardian.looks_malicious(question):
        ip = guardian.client_ip(request)
        guardian.record_incident("security", "MALICIOUS_INPUT_BLOCKED", "의심스러운 입력 패턴 차단",
                                 {"user_id": user_id, "ip": ip, "request_id": request_id}, "medium")
        guardian.strike("malicious", ip)
        return error(400, "INVALID_INPUT", "허용되지 않는 입력입니다.")
    # 질문 전 확인 4가지(AI 쉬는 중인지·이번 시간 사용량·누적 사용량·최근 대화)를 DB 왕복 한 번으로 읽는다
    hour_limit = CHAT_LIMIT_PER_HOUR_PREMIUM if is_premium else CHAT_LIMIT_PER_HOUR
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    backoff_rows, hour_rows, lifetime_rows, history_rows = db.execute_many([
        ("SELECT value FROM runtime_flags WHERE key = 'ai_backoff_until'", ()),
        ("SELECT COUNT(*) AS n FROM chats WHERE user_id = ? AND created_at > ?", (user_id, since)),
        ("SELECT COUNT(*) AS n FROM chats WHERE user_id = ? AND status = 'ok'", (user_id,)),
        ("SELECT question, answer FROM chats WHERE user_id = ? AND status = 'ok' ORDER BY id DESC LIMIT ?",
         (user_id, CONTEXT_TURNS)),
    ])
    if backoff_rows and datetime.now(timezone.utc) < datetime.fromisoformat(backoff_rows[0]["value"]):
        return error(503, "AI_BACKED_OFF", "AI 서비스가 일시적으로 쉬고 있어요. 잠시 후 다시 시도해 주세요.")
    if hour_rows[0]["n"] >= hour_limit:
        log.warning("rate_limited user_id=%s is_premium=%s", user_id, is_premium)
        return error(429, "RATE_LIMITED", "질문이 너무 많아요. 잠시 후 다시 시도해 주세요.")

    remaining_free = None
    if not is_premium:
        used_lifetime = lifetime_rows[0]["n"]
        if used_lifetime >= CHAT_LIFETIME_LIMIT_FREE:
            log.warning("free_limit_reached user_id=%s", user_id)
            return error(403, "FREE_LIMIT_REACHED",
                        f"무료 이용 {CHAT_LIFETIME_LIMIT_FREE}회를 모두 사용했어요. 초대코드가 있다면 입력해 보세요.")
        remaining_free = CHAT_LIFETIME_LIMIT_FREE - used_lifetime - 1

    return {"user_id": user_id, "request_id": request_id, "question": question,
            "history": list(reversed(history_rows)), "remaining_free": remaining_free,
            "art_limit": ART_RESULTS_LIMIT_PREMIUM if is_premium else ART_RESULTS_LIMIT,
            "show_limit_warning": remaining_free is not None and remaining_free <= FREE_LIMIT_WARNING_THRESHOLD}


def _ai_failure(ctx: dict, e: AIUnavailableError, started: float) -> None:
    latency = int((time.monotonic() - started) * 1000)
    log.error("ai_call_failure code=%s latency_ms=%s", e.code, latency)
    _save_chat(ctx["user_id"], ctx["question"], None, "error", e.code, latency, [])
    guardian.record_incident("reliability", e.code, str(e), {"request_id": ctx["request_id"], "latency_ms": latency},
                             "medium" if e.code == "AI_RATE_LIMITED" else "low")
    guardian.note_ai_failure(e.code)


def _art_db_failure(ctx: dict, e: sqlite3.Error, started: float) -> JSONResponse:
    latency = int((time.monotonic() - started) * 1000)
    log.error("art_db_failure detail=%s", e)
    _save_chat(ctx["user_id"], ctx["question"], None, "error", "ART_DB_ERROR", latency, [])
    return error(503, "ART_DB_ERROR", "작품 데이터베이스를 읽지 못했어요.")


def _search_conditions(intent: dict, relaxed: bool) -> dict | None:
    """'더 보기'가 AI를 다시 부르지 않고 같은 조건으로 DB만 넘겨 볼 수 있게 검색 조건을 함께 돌려준다."""
    if intent["chitchat"]:
        return None
    search = {k: intent.get(k) for k in ("keywords", "artist", "year_from", "year_to", "orientation", "purpose")}
    if relaxed:  # 작가/연도 조건을 빼고 찾은 결과면 '더 보기'도 같은 완화 조건을 쓴다
        search.update(artist=None, year_from=None, year_to=None)
    return search


@app.post("/api/chat")
def chat_endpoint(body: ChatRequest, request: Request, session_data: dict = Depends(current_session)):
    ctx = _chat_context(body, session_data, request)
    if isinstance(ctx, JSONResponse):
        return ctx
    request_id = ctx["request_id"]
    started = time.monotonic()
    log.info("ai_call_start user_id=%s", ctx["user_id"])
    try:
        intent = chat.extract_intent(ctx["question"], request_id=request_id)
        works, relaxed = chat.find_artworks(intent, limit=ctx["art_limit"], request_id=request_id)
        answer = chat.compose_answer(ctx["question"], works, ctx["history"], relaxed=relaxed,
                                     purpose=intent.get("purpose"), request_id=request_id)
    except AIUnavailableError as e:
        _ai_failure(ctx, e, started)
        return error(STATUS_BY_CODE.get(e.code, 502), e.code, str(e))
    except sqlite3.Error as e:
        return _art_db_failure(ctx, e, started)

    latency = int((time.monotonic() - started) * 1000)
    log.info("ai_call_success latency_ms=%s artworks=%s", latency, len(works))
    chat_id = _save_chat(ctx["user_id"], ctx["question"], answer, "ok", None, latency, [w["id"] for w in works])
    return {"chat_id": chat_id, "saved": chat_id is not None, "request_id": request_id,
            "reply": answer, "artworks": works, "search": _search_conditions(intent, relaxed),
            "remaining_free": ctx["remaining_free"], "show_limit_warning": ctx["show_limit_warning"]}


def _ndjson(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest, request: Request, session_data: dict = Depends(current_session)):
    """/api/chat과 같은 일을 하되, 결과를 도착하는 대로 한 줄씩(NDJSON) 보낸다.
    1) meta: 검색이 끝나자마자 작품 카드와 검색 조건 → 화면이 카드부터 그린다
    2) delta: 답변 글 조각 (Claude는 만들어지는 대로, GPT 경로는 한 번에)
    3) done: 대화 저장 결과 / error: 답변 도중 실패
    답변 전에 실패하면(검색 조건 추출·DB) 스트림을 열지 않고 /api/chat과 같은 오류 응답을 준다."""
    ctx = _chat_context(body, session_data, request)
    if isinstance(ctx, JSONResponse):
        return ctx
    request_id = ctx["request_id"]
    started = time.monotonic()
    log.info("ai_call_start user_id=%s", ctx["user_id"])
    try:
        intent = chat.extract_intent(ctx["question"], request_id=request_id)
        works, relaxed = chat.find_artworks(intent, limit=ctx["art_limit"], request_id=request_id)
    except AIUnavailableError as e:
        _ai_failure(ctx, e, started)
        return error(STATUS_BY_CODE.get(e.code, 502), e.code, str(e))
    except sqlite3.Error as e:
        return _art_db_failure(ctx, e, started)

    def events():
        yield _ndjson({"type": "meta", "request_id": request_id, "artworks": works,
                       "search": _search_conditions(intent, relaxed), "remaining_free": ctx["remaining_free"],
                       "show_limit_warning": ctx["show_limit_warning"]})
        parts = []
        try:
            for piece in chat.compose_answer_stream(ctx["question"], works, ctx["history"], relaxed=relaxed,
                                                    purpose=intent.get("purpose"), request_id=request_id):
                parts.append(piece)
                yield _ndjson({"type": "delta", "text": piece})
        except AIUnavailableError as e:
            _ai_failure(ctx, e, started)
            yield _ndjson({"type": "error", "code": e.code, "message": str(e)})
            return
        latency = int((time.monotonic() - started) * 1000)
        log.info("ai_call_success latency_ms=%s artworks=%s stream=true", latency, len(works))
        chat_id = _save_chat(ctx["user_id"], ctx["question"], "".join(parts), "ok", None, latency,
                             [w["id"] for w in works])
        yield _ndjson({"type": "done", "chat_id": chat_id, "saved": chat_id is not None})

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/me/chats")
def my_chats(limit: int = 20, offset: int = 0, user_id: int = Depends(current_user)):
    limit = max(1, min(limit, 100))
    rows = db.execute(
        "SELECT id, question, answer, status, error_code, latency_ms, created_at FROM chats "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limit, max(0, offset)))
    return {"chats": rows}


# ---- 작품 즐겨찾기 ----
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


class RecordRequest(BaseModel):
    artwork_id: int


@app.post("/api/records")
def issue_record(body: RecordRequest, request: Request, session_data: dict | None = Depends(optional_session)):
    """권리 근거 기록 발급 (docs/rights-policy.md §5): 스냅숏 저장 → 인터넷 아카이브 보관 시도 → 기록 번호."""
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"record:{ip}", limit=RECORD_LIMIT_PER_HOUR, window_seconds=3600):
        return error(429, "RATE_LIMITED", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
    try:
        number = records.issue(body.artwork_id, session_data["uid"] if session_data else None)
    except LookupError:
        return error(404, "ARTWORK_NOT_FOUND", "작품을 찾을 수 없습니다.")
    except records.RecordNotAllowed as e:
        return error(409, "RECORD_NOT_ALLOWED", f"판단 규칙({', '.join(e.failed)})을 통과하지 못해 기록을 발급할 수 없어요.")
    archives = records.archive_missing(number)  # 실패해도 기록은 이미 저장됨 — 기록 페이지에서 다시 시도 가능
    return {"number": number, "url": f"/records/{number}", "archived": all(a["archived_url"] for a in archives)}


@app.post("/api/records/{number}/archive")
def retry_archive(number: str, request: Request):
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"archive:{ip}", limit=120, window_seconds=3600):
        return error(429, "RATE_LIMITED", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
    try:
        archives = records.archive_missing(number)
    except LookupError:
        return error(404, "RECORD_NOT_FOUND", "기록을 찾을 수 없습니다.")
    return {"archives": archives}


@app.get("/records/{number}", response_class=HTMLResponse)
def show_record(number: str):
    row = records.get(number)
    if not row:
        return HTMLResponse("<h1>기록을 찾을 수 없습니다.</h1>", status_code=404)
    return HTMLResponse(records.render(row))


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


@app.get("/api/me/favorites")
def my_favorites(limit: int = 20, offset: int = 0, user_id: int = Depends(current_user)):
    """최근 저장 순. 미술 DB에서 사라진 작품은 목록에서 빠진다."""
    limit = max(1, min(limit, 100))
    rows = db.execute(
        "SELECT artwork_id, created_at FROM favorites WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (user_id, limit, max(0, offset)))
    try:
        cards = art.get_by_ids([r["artwork_id"] for r in rows])
    except sqlite3.Error as e:
        log.error("art_db_failure path=/api/me/favorites detail=%s", e)
        return error(503, "ART_DB_ERROR", "작품 데이터베이스를 읽지 못했어요.")
    return {"favorites": [{**cards[r["artwork_id"]], "favorited_at": r["created_at"]}
                          for r in rows if r["artwork_id"] in cards]}


# ---- 설명 에이전트 (피어 리뷰용) ----
# 비밀번호 입력 없이 '/explain/{token}' 링크 자체가 암호 역할을 한다(EXPLAIN_AGENT_SECRET과 일치해야 함).
# 토큰이 틀리거나 비활성(EXPLAIN_AGENT_SECRET 미설정)이면 404 — 평범한 404와 구별되지 않게 해 존재 자체를 숨긴다.
class ExplainRequest(BaseModel):
    question: str
    secret: str


@app.get("/explain/{token}")
def explain_page(token: str):
    secret = explain.get_secret()
    if not secret or not hmac.compare_digest(token, secret):
        raise HTTPException(404)
    return FileResponse(STATIC_DIR / "explain.html")


@app.post("/api/explain")
def explain_endpoint(body: ExplainRequest, request: Request):
    secret = explain.get_secret()
    if not secret or not hmac.compare_digest(body.secret, secret):
        return error(401, "UNAUTHENTICATED", "링크가 올바르지 않거나 만료됐어요. 받은 링크를 다시 확인해 주세요.")
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"explain:{ip}", limit=30, window_seconds=3600):
        return error(429, "RATE_LIMITED", "질문은 1시간에 30개까지 할 수 있어요. 잠시 후 다시 물어봐 주세요.")
    question = body.question.strip()
    if not question:
        return error(400, "EMPTY_MESSAGE", "질문을 입력해 주세요.")
    if len(question) > CHAT_MAX_LENGTH:
        return error(400, "MESSAGE_TOO_LONG",
                     f"질문이 너무 길어요 ({len(question)}자). {CHAT_MAX_LENGTH}자 이하로 줄여서 물어봐 주세요.")
    try:
        return {"answer": explain.ask(question)}
    except AIUnavailableError as e:
        log.warning("explain_ai_failure code=%s detail=%s", e.code, e)  # 원래 메시지는 로그에만
        return error(STATUS_BY_CODE.get(e.code, 502), e.code, explain.friendly_ai_message(e.code))
    except explain.ExplainUnavailable as e:
        return error(503, "EXPLAIN_UNAVAILABLE", str(e))


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
