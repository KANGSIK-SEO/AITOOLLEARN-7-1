"""FastAPI 앱: 회원가입/로그인, 챗봇 질문/응답, 내 대화 로그 조회."""
import html
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import art, auth, chat, db, guardian, rights
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
        answer = chat.compose_answer(question, works, history, relaxed=relaxed, purpose=intent.get("purpose"))
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
    search = {k: intent.get(k) for k in ("keywords", "artist", "year_from", "year_to", "orientation", "purpose")}
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


CERT_CAUTIONS = [
    "작품에 사람의 얼굴·이름이 나오면 초상권·퍼블리시티권 문제가 따로 있을 수 있습니다.",
    "작품 속 상표·로고는 상표법으로 따로 보호될 수 있습니다.",
    "기관 이름·로고를 써서 기관이 보증·후원하는 것처럼 보이게 하면 안 됩니다.",
    "출처 표시는 의무가 아니지만 기관들은 권장합니다. 아래 출처 표기 예시를 써 주세요.",
    "이 확인서는 법률 자문이 아닙니다. 중요한 상업 프로젝트는 사용 직전 출처 페이지를 다시 확인하세요.",
]
CERT_VERDICT = {
    "ok": ("✅ 사용 가능 — CC0 (조건 없이 상업적 이용·수정 가능)", "#0a7d45"),
    "recheck": ("⚠️ 재확인 필요 — 권리 확인일이 오래되어 출처 페이지에서 다시 확인해야 합니다", "#a86400"),
    "blocked": ("⛔ 확인서 발급 불가 — 판단 규칙을 통과하지 못한 작품입니다", "#b00020"),
}


def credit_example(work: dict, source: rights.Source | None) -> str:
    parts = [f'"{work["title"]}"', work.get("artist") or "Unknown artist"]
    if work.get("date_display"):
        parts.append(work["date_display"])
    return f'{", ".join(parts)}. {source.name if source else work["source"]}, CC0 (Public Domain). {work["source_url"]}'


@app.get("/certificate/{artwork_id}", response_class=HTMLResponse)
def certificate(artwork_id: int):
    """권리 확인서 (docs/rights-policy.md §5). 인쇄하거나 PDF로 저장해 보관할 수 있는 한 장짜리 문서."""
    work = art.get_rights_record(artwork_id)
    if not work:
        return HTMLResponse("<h1>작품을 찾을 수 없습니다.</h1>", status_code=404)
    result = rights.evaluate(work)
    src = rights.SOURCES.get(work["source"])
    e = html.escape
    verdict, color = CERT_VERDICT[result["status"]]
    issuable = result["status"] != "blocked"
    thumb = art.with_proxy_urls(work).get("thumbnail_url") or work["image_url"]
    checks = "".join(f"<li>{'✅' if c['ok'] else '❌'} <b>{c['code']}</b> {e(c['label'])}</li>" for c in result["checks"])
    cautions = "".join(f"<li>{e(c)}</li>" for c in CERT_CAUTIONS)
    rows = [
        ("기관", src.name if src else work["source"]),
        ("기관 작품 ID", work["source_id"]),
        ("작품 단위 근거", f"{src.basis if src else '-'} (기관 API 값)"),
        ("라이선스", work["license"]),
        ("권리 확인일", result["checked_at"] or "-"),
    ]
    links = [("기관 정책 페이지", src.policy_url if src else ""), ("작품 상세 페이지", work["source_url"]),
             ("원본 이미지", work["image_url"])]
    table = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in rows)
    table += "".join(f'<tr><th>{e(k)}</th><td><a href="{e(v)}" target="_blank" rel="noopener">{e(v)}</a></td></tr>'
                     for k, v in links if v)
    number = rights.certificate_number(work) if issuable else "발급 불가"
    issued = datetime.now(timezone.utc).date().isoformat()
    page = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>권리 확인서 — {e(work['title'])}</title>
<style>
body{{font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#1a1a1a;background:#f4f4f7;margin:0;padding:16px}}
.doc{{max-width:760px;margin:0 auto;background:#fff;padding:32px;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.08)}}
h1{{font-size:1.4rem;margin:0 0 4px}} .sub{{color:#666;font-size:.85rem;margin:0 0 20px}}
.verdict{{border:2px solid {color};color:{color};padding:12px 14px;border-radius:8px;font-weight:700;margin:16px 0}}
.work{{display:flex;gap:16px;align-items:flex-start}} .work img{{width:160px;max-width:40%;border-radius:6px;background:#eee}}
table{{width:100%;border-collapse:collapse;font-size:.88rem;margin:12px 0}} th{{text-align:left;width:130px;color:#555;vertical-align:top}}
th,td{{padding:6px 4px;border-bottom:1px solid #eee;word-break:break-all}} h2{{font-size:1rem;margin:22px 0 6px}}
ul{{padding-left:20px;font-size:.88rem;line-height:1.6}} .credit{{background:#f6f6f8;padding:10px;border-radius:6px;font-size:.85rem;word-break:break-all}}
.foot{{display:flex;justify-content:space-between;color:#666;font-size:.8rem;margin-top:24px;border-top:1px solid #eee;padding-top:10px}}
button{{margin:12px auto;display:block;padding:10px 18px;border:0;border-radius:20px;background:#0066ff;color:#fff;font-size:.9rem;cursor:pointer}}
@media print{{body{{background:#fff;padding:0}} .doc{{box-shadow:none}} button{{display:none}}}}
</style></head><body><div class="doc">
<h1>퍼블릭 도메인 권리 확인서</h1>
<p class="sub">Public Domain Rights Record · 저작권 걱정 없는 퍼블릭 도메인 명화 찾기</p>
<div class="work"><img src="{e(thumb)}" alt="{e(work['title'])}"><div>
<h2 style="margin-top:0">{e(work['title'])}</h2>
<div>{e(work.get('artist') or '작가 미상')}{' · ' + e(work['date_display']) if work.get('date_display') else ''}</div>
<div style="color:#666;font-size:.85rem">{e(work.get('medium') or '')}</div>
<div style="color:#666;font-size:.85rem">{e(work.get('credit_line') or '')}</div></div></div>
<div class="verdict">{e(verdict)}</div>
<h2>권리 근거</h2><table>{table}</table>
<h2>판단 결과 (판단 규칙 R1~R6)</h2><ul>{checks}</ul>
{'<h2>출처 표기 예시</h2><div class="credit">' + e(credit_example(work, src)) + '</div>' if issuable else ''}
<h2>주의사항</h2><ul>{cautions}</ul>
<div class="foot"><span>확인서 번호 {e(number)}</span><span>발급일 {issued}</span></div>
</div><button onclick="window.print()">인쇄 / PDF로 저장</button></body></html>"""
    return HTMLResponse(page)


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
