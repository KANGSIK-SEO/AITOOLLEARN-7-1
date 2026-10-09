"""인증 의존성(FastAPI Depends): 라우터마다 로그인 검사를 다시 쓰지 않고 이름만 붙여 재사용한다.

- current_session / current_user: 로그인 필수. 없거나 위조된 토큰이면 401 UNAUTHENTICATED
  → 챗봇·내 대화 기록·즐겨찾기는 '누가 물었는지' 알아야 기록·사용량 제한·비용 보호를 할 수 있어서 로그인을 요구한다
- optional_session: 로그인했으면 세션, 아니면 None (권리 근거 기록처럼 비로그인도 쓰는 기능)
- require_cron: 운영 점검 주소(/api/guardian/*)는 CRON_SECRET을 아는 스케줄러만 부를 수 있다
"""
import hmac

from fastapi import Cookie, Depends, Header, HTTPException, Request

from . import auth
from .config import CRON_SECRET

COOKIE = "session"


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


def cron_authorized(request: Request) -> bool:
    """크론 전용 주소 확인. 값을 복사할 때 딸려 온 앞뒤 공백·줄바꿈과 'bearer' 대소문자는 무시하고,
    비교는 걸리는 시간으로 값을 추측할 수 없게 compare_digest로 한다."""
    secret = CRON_SECRET.strip()
    scheme, _, token = request.headers.get("authorization", "").strip().partition(" ")
    # compare_digest는 한글 같은 비ASCII 글자가 든 문자열을 받으면 TypeError로 터진다 → 바이트로 바꿔 비교 (2026-10-09 500의 원인)
    return bool(secret) and scheme.lower() == "bearer" and hmac.compare_digest(token.strip().encode(), secret.encode())


def require_cron(request: Request) -> None:
    if not cron_authorized(request):
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "cron only"})
