"""화면(HTML) 라우트: 첫 화면, 서비스워커, 배포 시 캐시 무효화."""
import hashlib
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["pages"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# ---- 배포 시 캐시 무효화 ----
# 화면 파일 내용으로 버전을 만든다. 파일이 바뀌어 배포되면 버전이 바뀌므로
# ① index.html의 정적 파일 주소(?v=버전)가 달라져 브라우저·CDN 캐시를 우회하고
# ② 서비스워커 캐시 이름이 달라져 새 서비스워커가 옛 캐시를 지운다 (sw.js의 activate).
VERSIONED_ASSETS = ("style.css", "app.js", "ondevice.js", "boot.js", "theme-init.js")
ASSET_VERSION = hashlib.sha256(b"".join(
    (STATIC_DIR / name).read_bytes() for name in (*VERSIONED_ASSETS, "index.html", "sw.js")
)).hexdigest()[:10]
NO_CACHE = {"Cache-Control": "no-cache"}  # 매번 서버에 새 버전이 있는지 확인 (내용이 같으면 304로 가볍게)
# 버전(?v=현재 버전)이 붙은 정적 파일은 내용이 바뀌면 주소도 바뀌므로 1년 동안 재확인 없이 캐시해도 안전하다.
# 버전이 없거나 다른 버전의 요청은 StaticFiles 기본값(매번 재확인)을 그대로 둔다.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def static_cache_headers(request: Request, response: Response) -> None:
    """/static/<VERSIONED_ASSETS>?v=<ASSET_VERSION> 의 정상 응답(200/304)에만 장기 캐시 헤더를 붙인다.
    쿼리는 FastAPI가 이미 해석해 둔 request.query_params를 쓴다 (별도 해석 모듈 불필요)."""
    path = request.url.path
    if request.method != "GET" or not path.startswith("/static/") or response.status_code not in (200, 304):
        return
    if path[len("/static/"):] not in VERSIONED_ASSETS:
        return
    if request.query_params.get("v") != ASSET_VERSION:
        return
    response.headers["Cache-Control"] = IMMUTABLE_CACHE


def _versioned(text: str) -> str:
    for name in VERSIONED_ASSETS:
        text = text.replace(f"/static/{name}'", f"/static/{name}?v={ASSET_VERSION}'")
        text = text.replace(f'/static/{name}"', f'/static/{name}?v={ASSET_VERSION}"')
    return text


INDEX_HTML = _versioned((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
SW_JS = _versioned((STATIC_DIR / "sw.js").read_text(encoding="utf-8")).replace("__ASSET_VERSION__", ASSET_VERSION)


@router.get("/")
def index():
    return HTMLResponse(INDEX_HTML, headers=NO_CACHE)


@router.get("/sw.js")
def service_worker():
    # 정적 마운트(/static)가 아니라 루트에서 서빙해야 서비스워커 적용 범위가 사이트 전체(/)가 된다.
    return Response(SW_JS, media_type="application/javascript", headers=NO_CACHE)
