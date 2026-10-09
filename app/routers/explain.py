"""설명 에이전트 라우트 (피어 리뷰용).

비밀번호 입력 없이 '/explain/{token}' 링크 자체가 암호 역할을 한다(EXPLAIN_AGENT_SECRET과 일치해야 함).
토큰이 틀리거나 비활성(EXPLAIN_AGENT_SECRET 미설정)이면 404 — 평범한 404와 구별되지 않게 해 존재 자체를 숨긴다.
"""
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import explain, guardian
from ..config import CHAT_MAX_LENGTH, AIUnavailableError
from ..errors import STATUS_BY_CODE, error
from ..schemas import ExplainRequest
from .pages import STATIC_DIR

router = APIRouter(tags=["explain"])
log = logging.getLogger("app")


@router.get("/explain/{token}")
def explain_page(token: str):
    secret = explain.get_secret()
    if not secret or not hmac.compare_digest(token, secret):
        raise HTTPException(404)
    return FileResponse(STATIC_DIR / "explain.html")


@router.post("/api/explain")
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
