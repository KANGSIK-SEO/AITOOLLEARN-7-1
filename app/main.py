"""FastAPI 앱 조립: 보안 헤더·요청 감시 미들웨어·오류 처리기를 걸고, 목적별 라우터(app/routers/*)를 붙인다.

구조 (요청이 지나가는 순서)
  app/main.py        미들웨어(request_id·가디언 감시·보안 헤더) → 라우터 연결
  app/routers/*.py   목적별 API: auth(가입·로그인) · chat(챗봇) · logs(내 대화 로그) · favorites · artworks
                     · records(권리 근거 기록) · explain · health · ops(운영 점검) · pages(화면)
  app/deps.py        인증 의존성(로그인 필수/선택, 크론 전용) — 라우터가 Depends로 재사용
  app/schemas.py     요청/응답 스키마
  app/errors.py      공통 오류 응답 {"error": {"code", "message"}} + 예외 처리기
  app/repository.py  사용자 DB(users·chats·favorites) SQL
  app/chat.py · art.py · llm.py · guardian.py · records.py   서비스(AI 파이프라인·작품 검색·AI 호출·가디언·권리 기록)
"""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTasks
from starlette.concurrency import run_in_threadpool

from . import guardian, reqctx
from .config import TIMEOUT_SECONDS, validate_env
from .errors import error, register_exception_handlers
from .routers import artworks, auth, chat, explain, favorites, health, logs, ops, pages, records
from .routers.pages import ASSET_VERSION, STATIC_DIR, VERSIONED_ASSETS, static_cache_headers  # noqa: F401 (테스트가 main에서 읽는다)

reqctx.install()
logging.basicConfig(level=logging.INFO, format=reqctx.LOG_FORMAT)
log = logging.getLogger("app")

# 필수 환경변수가 틀리면 첫 요청이 아니라 서버 시작 시점에 고칠 방법과 함께 실패한다
for _warning in validate_env():
    log.warning("config_warning %s", _warning)

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

# 보안 헤더 (2026-10-09 보안 점수·인증 준비). 모든 응답에 붙인다.
# CSP: 스크립트는 우리 서버의 파일만 실행(화면 안 스크립트 금지 → 해커가 끼워 넣은 스크립트는 실행되지 않음),
#      그림은 미술관 https 주소 허용, 글꼴은 Google Fonts·jsDelivr(Pretendard)만, 다른 사이트가 우리 화면을 틀 안에 넣지 못하게.
CSP = ("default-src 'self'; script-src 'self'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "   # 글꼴 CSS (Pretendard·Inter)
       "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; img-src 'self' data: https:; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'; upgrade-insecure-requests")
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",   # 2년 동안 https로만 접속
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": CSP,
}
# FastAPI 자동 문서(/docs, /redoc)는 CDN 스크립트를 쓰므로 CSP만 뺀다
CSP_EXEMPT = ("/docs", "/redoc")


def _with_security_headers(request: Request, response):
    for name, value in SECURITY_HEADERS.items():
        if name == "Content-Security-Policy" and request.url.path.startswith(CSP_EXEMPT):
            continue
        response.headers.setdefault(name, value)
    return response


@app.middleware("http")
async def request_context(request: Request, call_next):
    """요청마다 request_id를 정하고(app/reqctx.py), 가디언 실시간 감시를 거친다.
    - 차단된 IP는 바로 403, 공격 도구가 찾는 경로는 404로 끝내고 횟수를 센다 (app/guardian.py)
    - 처리 중 생긴 즉시 분석 요청과 접속 기록(1분마다 AI가 읽음)은 응답을 보낸 뒤에 남겨 사용자를 기다리게 하지 않는다
    - 버전(?v=)이 붙은 정적 파일 응답에는 장기 캐시 헤더를 붙인다 (_static_cache_headers)"""
    started = time.monotonic()
    reqctx.set_request_id(reqctx.new_request_id())
    reqctx.start_deadline(TIMEOUT_SECONDS)   # 이 요청은 25초 안에 끝낸다 — 바깥 호출은 남은 시간만큼만 기다린다
    pending = reqctx.start_pending()
    ip = guardian.client_ip(request)
    if await run_in_threadpool(guardian.is_blocked, ip):
        return _with_security_headers(request, error(
            403, "BLOCKED", "의심스러운 요청이 반복되어 잠시 접속이 제한되었어요. 잠시 후 다시 시도해 주세요."))
    if await run_in_threadpool(guardian.is_probe_path, request.url.path):
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
        if response.status_code == 404:
            await run_in_threadpool(guardian.note_not_found, ip, request.url.path)
    static_cache_headers(request, response)
    tasks = BackgroundTasks()
    if response.background is not None:
        tasks.tasks.append(response.background)
    tasks.add_task(_after_response, guardian.log_access, ip, request.method,
                   request.url.path + (f"?{request.url.query}" if request.url.query else ""),
                   response.status_code, request.headers.get("user-agent", ""),
                   int((time.monotonic() - started) * 1000))
    if pending.get("triage"):
        tasks.add_task(_after_response, guardian.run_triage, pending["triage"])
    if pending.get("watch"):   # 1분 점검의 접속 감시(Fable)는 응답을 보낸 뒤에
        tasks.add_task(_after_response, guardian.run_watch_safely)
    # 맨 마지막: 스트리밍 답변·위 진단이 쓴 토큰까지 모아서 한 번에 저장한다
    tasks.add_task(_after_response, guardian.save_pending_usage, pending)
    response.background = tasks
    return _with_security_headers(request, response)


def _after_response(fn, *args) -> None:
    """응답을 보낸 뒤의 일은 사용자가 기다리지 않으므로 요청의 25초 마감에 묶지 않는다 (각 호출의 25초 상한은 그대로)."""
    reqctx.clear_deadline()
    fn(*args)


register_exception_handlers(app)
for module in (pages, health, ops, auth, chat, logs, favorites, artworks, records, explain):
    app.include_router(module.router)
