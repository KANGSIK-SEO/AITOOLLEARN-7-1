"""작품 라우트: '더 보기'(AI 없이 DB만 조회)와 AIC 이미지 프록시. 로그인 없이 쓸 수 있고 IP당 횟수만 제한한다."""
import logging
import re
import socket
import sqlite3
import urllib.error
import urllib.request

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import art, guardian
from ..config import BROWSE_LIMIT_PER_HOUR, BROWSE_PAGE_SIZE, TIMEOUT_SECONDS
from ..errors import error

router = APIRouter(tags=["artworks"])
log = logging.getLogger("app")


@router.get("/api/artworks")
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


# ---- AIC 이미지 프록시 ----
# AIC 이미지 서버는 `AIC-User-Agent` 헤더와 (파이썬 기본이 아닌) User-Agent가 없으면 403을 준다. 브라우저 <img>는 헤더를 붙일 수 없어 서버가 대신 받는다.
AIC_IIIF = "https://www.artic.edu/iiif/2"
AIC_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
AIC_WIDTHS = {200, 400, 843, 1686}
AIC_UA = "AITOOLLEARN-7-1 (student project; https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1)"


@router.get("/api/img/aic/{image_id}")
def aic_image(image_id: str, request: Request, w: int = 400, download: int = 0):
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"img:{ip}", limit=300, window_seconds=3600):
        return error(429, "RATE_LIMITED", "이미지 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
    if not AIC_ID_RE.match(image_id) or w not in AIC_WIDTHS:
        return error(400, "INVALID_IMAGE", "지원하지 않는 이미지 요청입니다.")
    req = urllib.request.Request(f"{AIC_IIIF}/{image_id}/full/{w},/0/default.jpg", headers={"AIC-User-Agent": AIC_UA, "User-Agent": "AITOOLLEARN-7-1/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
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
