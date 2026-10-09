"""AI 호출 (서버 측에서만 수행, 키는 응답에 노출하지 않는다).

ANTHROPIC_API_KEY가 있으면 Claude(app/claude_llm.py, 기본 claude-haiku-5-5)를 먼저 쓴다.
Claude가 크레딧 소진·한도·인증 문제로 실패하면 Upstage solar-pro4가 바로 이어받는다
(UPSTAGE_API_KEY가 없으면 GPT로). Claude 키가 없으면 GPT를 쓰고, GPT가 소진되면 solar-pro4가 이어받는다.
거절(AI_REFUSED)은 다른 회사 모델로 넘기지 않는다.

GPT 경로의 주 모델: OpenAI gpt-6-astra. 429/401/403(=키 소진·장애)일 때만 Upstage solar-pro4로
한 번 더 시도한다 (UPSTAGE_API_KEY가 없으면 폴백 없이 원래 에러를 그대로 던진다).

재시도와 타임아웃:
- 5xx·연결 오류(일시 장애)는 같은 제공자에게 LLM_MAX_RETRIES번까지 짧게 쉬었다 다시 보낸다.
- 타임아웃은 재시도하지 않는다 — 이미 LLM_TIMEOUT_SECONDS를 기다렸으므로 다시 보내면 응답이 두 배로 늦어진다.
- 429·401·403·기타 4xx도 재시도하지 않는다 (같은 요청을 다시 보내도 결과가 같다. 429는 폴백이 처리).
- 재시도·폴백을 모두 합쳐 LLM_CALL_BUDGET_SECONDS(25초)와 요청의 남은 시간 중 짧은 쪽 안에서만 시도하고,
  모자라면 AI_TIMEOUT("죄송합니다. 접속자가 많습니다.")으로 끝낸다.
"""
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

from . import claude_llm, reqctx
from .config import (BUSY_MESSAGE, LLM_CALL_BUDGET_SECONDS, LLM_MAX_RETRIES, LLM_REASONING_EFFORT,
                     LLM_TIMEOUT_SECONDS, OPENAI_BASE_URL, OPENAI_MODEL, UPSTAGE_BASE_URL,
                     UPSTAGE_MODEL, AIUnavailableError, get_api_key, get_fallback_api_key)

log = logging.getLogger("app.llm")

_FALLBACK_CODES = {"AI_RATE_LIMITED", "AI_KEY_MISSING"}  # GPT 쪽 "소진" 신호로 보는 코드
_RETRY_STATUS = {500, 502, 503, 504}
RETRY_BACKOFF_SECONDS = 0.5  # n번째 재시도 전 0.5×n초 대기
MIN_ATTEMPT_SECONDS = 2.0    # 남은 예산이 이보다 적으면 새 시도를 시작하지 않는다


def _gpt_available() -> bool:
    return bool(os.environ.get("GPT_ASTRA_API_KEY", "") or get_fallback_api_key())


def _after_claude(messages: list[dict], max_tokens: int, reason: str) -> str:
    """Claude가 안 될 때: solar-pro4가 먼저 이어받고, solar 키가 없으면 GPT(→ solar) 순서로 간다."""
    if get_fallback_api_key():
        log.warning("llm_fallback_to_upstage from=claude reason=%s", reason)
        return _upstage_chat_completion(messages, max_tokens, time.monotonic() + reqctx.remaining(LLM_CALL_BUDGET_SECONDS))
    log.warning("llm_fallback_to_gpt from=claude reason=%s", reason)
    return _gpt_chain(messages, max_tokens)


def chat_completion(messages: list[dict], max_tokens: int = 700, purpose: str = "answer",
                    json_schema: dict | None = None) -> str:
    """purpose: "intent"(검색 조건 뽑기) | "answer"(답변 쓰기) | "watch"(가디언 접속 기록 감시). json_schema는 Claude에서만 쓰인다
    (다른 모델은 프롬프트의 JSON 형식 안내와 chat._parse_intent의 정리로 같은 결과를 낸다)."""
    if claude_llm.enabled():
        try:
            return claude_llm.complete(messages, purpose=purpose, json_schema=json_schema)
        except AIUnavailableError as e:
            if e.code == "AI_REFUSED" or not _gpt_available():
                raise
            return _after_claude(messages, max_tokens, e.code)
    return _gpt_chain(messages, max_tokens)


def stream_completion(messages: list[dict], max_tokens: int = 700, purpose: str = "answer") -> Iterator[str]:
    """답변을 만들어지는 대로 조각조각 돌려준다. Claude가 첫 조각 전에 실패하면 solar-pro4(없으면 GPT)가
    이어받고, 그 모델들은 스트리밍이 없어 완성된 답을 한 조각으로 돌려준다."""
    if claude_llm.enabled():
        sent = False
        try:
            for piece in claude_llm.stream(messages, purpose=purpose):
                sent = True
                yield piece
            return
        except AIUnavailableError as e:
            if sent or e.code == "AI_REFUSED" or not _gpt_available():
                raise
            yield _after_claude(messages, max_tokens, e.code)
            return
    yield _gpt_chain(messages, max_tokens)


def _gpt_chain(messages: list[dict], max_tokens: int) -> str:
    deadline = time.monotonic() + reqctx.remaining(LLM_CALL_BUDGET_SECONDS)
    try:
        return _openai_chat_completion(messages, max_tokens, deadline)
    except AIUnavailableError as e:
        if e.code not in _FALLBACK_CODES or not get_fallback_api_key():
            raise
        log.warning("llm_fallback_to_upstage reason=%s", e.code)
        return _upstage_chat_completion(messages, max_tokens, deadline)


def _urlopen_json(req: urllib.request.Request, deadline: float, provider: str) -> dict:
    """일시 장애만 재시도한다. 소켓 타임아웃은 남은 예산을 넘지 않게 줄인다.
    예산이 부족하면 TimeoutError를 던져 호출부가 AI_TIMEOUT으로 바꾸게 한다."""
    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining < MIN_ATTEMPT_SECONDS:
            raise TimeoutError(f"LLM 호출 시간 예산({LLM_CALL_BUDGET_SECONDS}s) 소진")
        try:
            with urllib.request.urlopen(req, timeout=min(LLM_TIMEOUT_SECONDS, remaining)) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code not in _RETRY_STATUS or attempt >= LLM_MAX_RETRIES:
                raise
            reason = f"http_{e.code}"
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)) or attempt >= LLM_MAX_RETRIES:
                raise
            reason = "connection_error"
        attempt += 1
        wait = RETRY_BACKOFF_SECONDS * attempt
        if deadline - time.monotonic() - wait < MIN_ATTEMPT_SECONDS:
            raise TimeoutError(f"LLM 호출 시간 예산({LLM_CALL_BUDGET_SECONDS}s) 소진 (재시도 전)")
        log.warning("llm_retry provider=%s attempt=%s reason=%s wait_s=%s", provider, attempt, reason, wait)
        time.sleep(wait)


def _openai_chat_completion(messages: list[dict], max_tokens: int, deadline: float) -> str:
    body = json.dumps({
        "model": OPENAI_MODEL, "messages": messages,
        "max_completion_tokens": max_tokens, "reasoning_effort": LLM_REASONING_EFFORT,
    }).encode()
    req = urllib.request.Request(
        f"{OPENAI_BASE_URL}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"},
    )
    try:
        data = _urlopen_json(req, deadline, "openai")
        return data["choices"][0]["message"]["content"].strip()
    except (socket.timeout, TimeoutError) as e:
        raise AIUnavailableError("AI_TIMEOUT", BUSY_MESSAGE) from e
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise AIUnavailableError("AI_RATE_LIMITED", "AI 서비스 요청이 많아 잠시 제한되었어요. 잠시 후 다시 시도해 주세요.") from e
        if e.code in (401, 403):
            raise AIUnavailableError("AI_KEY_MISSING", "AI 서비스 인증에 실패했어요.") from e
        raise AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.") from e
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
            raise AIUnavailableError("AI_TIMEOUT", BUSY_MESSAGE) from e
        raise AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise AIUnavailableError("AI_ERROR", "AI 응답을 해석하지 못했어요.") from e


def _upstage_chat_completion(messages: list[dict], max_tokens: int, deadline: float) -> str:
    body = json.dumps({
        "model": UPSTAGE_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        f"{UPSTAGE_BASE_URL}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {get_fallback_api_key()}", "Content-Type": "application/json"},
    )
    try:
        data = _urlopen_json(req, deadline, "upstage")
        return data["choices"][0]["message"]["content"].strip()
    except (socket.timeout, TimeoutError) as e:
        raise AIUnavailableError("AI_TIMEOUT", BUSY_MESSAGE) from e
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as e:
        raise AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요(폴백도 실패). 잠시 후 다시 시도해 주세요.") from e
