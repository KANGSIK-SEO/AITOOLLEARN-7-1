"""오류 응답: 모든 실패를 {"error": {"code": "...", "message": "..."}} 한 가지 모양으로 돌려준다.

라우터는 error()로 응답을 만들고, 라우터가 못 잡은 예외는 register_exception_handlers()로 등록한
처리기가 같은 모양으로 바꾼다 — 어떤 실패든 서버가 죽지 않고 사용자에게 안내 문구가 간다.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from . import db, guardian
from .config import BUSY_MESSAGE

log = logging.getLogger("app")

# AI 실패 종류 → HTTP 상태 코드 (app/llm.py가 던지는 AIUnavailableError.code)
STATUS_BY_CODE = {"AI_TIMEOUT": 504, "AI_ERROR": 502, "AI_RATE_LIMITED": 429,
                  "AI_KEY_MISSING": 503, "AI_BACKED_OFF": 503, "AI_REFUSED": 422}

HTTP_CODES = {400: "INVALID_INPUT", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


async def http_exc(_: Request, exc: HTTPException):
    # FastAPI의 HTTPException만이 아니라 상위 Starlette 것을 잡아야 없는 주소(404)·깨진 본문(400)도 같은 모양이 된다
    detail = exc.detail if isinstance(exc.detail, dict) else {
        "code": HTTP_CODES.get(exc.status_code, "HTTP_ERROR"), "message": str(exc.detail)}
    return JSONResponse({"error": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


async def validation_exc(_: Request, __: RequestValidationError):
    return error(422, "INVALID_INPUT", "요청 형식이 올바르지 않습니다.")


async def db_exc(_: Request, exc: db.DbError):
    log.error("db_error detail=%s", exc)
    if isinstance(exc, db.DbTimeout):   # 25초 안에 답이 없으면 '접속자가 많습니다'
        guardian.record_incident("reliability", "DB_ERROR", str(exc), {"timeout": True}, "high")
        return error(503, "BUSY", BUSY_MESSAGE)
    guardian.record_incident("reliability", "DB_ERROR", str(exc), {}, "high")
    return error(503, "DB_ERROR", "데이터베이스에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.")


async def unhandled_exc(_: Request, exc: Exception):
    log.error("unhandled_exception detail=%r", exc, exc_info=True)
    guardian.record_incident("reliability", "UNHANDLED_EXCEPTION", repr(exc), {}, "high")
    return error(500, "INTERNAL_ERROR", "예상치 못한 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exc)
    app.add_exception_handler(RequestValidationError, validation_exc)
    app.add_exception_handler(db.DbError, db_exc)
    app.add_exception_handler(Exception, unhandled_exc)
