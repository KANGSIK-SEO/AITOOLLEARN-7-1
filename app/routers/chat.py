"""챗봇 라우트: 질문 → 입력 검사·사용량 확인 → AI 파이프라인(app/chat.py) → 대화 로그 저장 → 응답.

로그인 필수(current_session): 대화 로그를 사용자별로 남기고, 사용자별 시간당·평생 질문 수를 제한해
AI 비용을 보호하기 위해서다. AI가 실패·지연돼도 서버는 죽지 않고 오류 코드와 안내 문구를 돌려주며,
실패한 질문도 status='error'로 로그에 남아 원인을 추적할 수 있다.
"""
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import chat, guardian, reqctx, repository
from ..config import (ART_RESULTS_LIMIT, ART_RESULTS_LIMIT_PREMIUM, CHAT_LIFETIME_LIMIT_FREE,
                      CHAT_LIMIT_PER_HOUR, CHAT_LIMIT_PER_HOUR_PREMIUM, CHAT_MAX_LENGTH,
                      CONTEXT_TURNS, FREE_LIMIT_WARNING_THRESHOLD, AIUnavailableError)
from ..deps import current_session
from ..errors import STATUS_BY_CODE, error
from ..schemas import ChatRequest, ErrorResponse

router = APIRouter(prefix="/api/chat", tags=["chat"])
log = logging.getLogger("app")

CHAT_ERRORS = {400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
               429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse},
               504: {"model": ErrorResponse}}


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
    hour_limit = CHAT_LIMIT_PER_HOUR_PREMIUM if is_premium else CHAT_LIMIT_PER_HOUR
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    backoff_rows, hour_rows, lifetime_rows, history_rows = repository.chat_precheck(user_id, since, CONTEXT_TURNS)
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
    repository.save_chat(ctx["user_id"], ctx["question"], None, "error", e.code, latency, [])
    guardian.record_incident("reliability", e.code, str(e), {"request_id": ctx["request_id"], "latency_ms": latency},
                             "medium" if e.code == "AI_RATE_LIMITED" else "low")
    guardian.note_ai_failure(e.code)


def _art_db_failure(ctx: dict, e: sqlite3.Error, started: float) -> JSONResponse:
    latency = int((time.monotonic() - started) * 1000)
    log.error("art_db_failure detail=%s", e)
    repository.save_chat(ctx["user_id"], ctx["question"], None, "error", "ART_DB_ERROR", latency, [])
    guardian.record_incident("reliability", "ART_DB_ERROR", "작품 DB를 읽지 못함", {"request_id": ctx["request_id"]}, "high")
    return error(503, "ART_DB_ERROR", "작품 데이터베이스를 읽지 못했어요.")


def _search_conditions(intent: dict, relaxed: bool) -> dict | None:
    """'더 보기'가 AI를 다시 부르지 않고 같은 조건으로 DB만 넘겨 볼 수 있게 검색 조건을 함께 돌려준다."""
    if intent["chitchat"]:
        return None
    search = {k: intent.get(k) for k in ("keywords", "artist", "year_from", "year_to", "orientation", "purpose")}
    if relaxed:  # 작가/연도 조건을 빼고 찾은 결과면 '더 보기'도 같은 완화 조건을 쓴다
        search.update(artist=None, year_from=None, year_to=None)
    return search


@router.post("", responses=CHAT_ERRORS)
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
    chat_id = repository.save_chat(ctx["user_id"], ctx["question"], answer, "ok", None, latency,
                                   [w["id"] for w in works])
    return {"chat_id": chat_id, "saved": chat_id is not None, "request_id": request_id,
            "reply": answer, "artworks": works, "search": _search_conditions(intent, relaxed),
            "remaining_free": ctx["remaining_free"], "show_limit_warning": ctx["show_limit_warning"]}


def _ndjson(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


@router.post("/stream", responses=CHAT_ERRORS)
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
        chat_id = repository.save_chat(ctx["user_id"], ctx["question"], "".join(parts), "ok", None, latency,
                                       [w["id"] for w in works])
        yield _ndjson({"type": "done", "chat_id": chat_id, "saved": chat_id is not None})

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
