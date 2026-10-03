"""AI 호출 (서버 측에서만 수행, 키는 응답에 노출하지 않는다).

주 모델: OpenAI gpt-6-astra. 429/401/403(=키 소진·장애)일 때만 Upstage solar-pro3로
한 번 더 시도한다 (UPSTAGE_API_KEY가 없으면 폴백 없이 원래 에러를 그대로 던진다).
"""
import json
import logging
import socket
import urllib.error
import urllib.request

from .config import (LLM_REASONING_EFFORT, LLM_TIMEOUT_SECONDS, OPENAI_BASE_URL,
                     OPENAI_MODEL, UPSTAGE_BASE_URL, UPSTAGE_MODEL, AIUnavailableError,
                     get_api_key, get_fallback_api_key)

log = logging.getLogger("app.llm")

_FALLBACK_CODES = {"AI_RATE_LIMITED", "AI_KEY_MISSING"}  # GPT 쪽 "소진" 신호로 보는 코드


def chat_completion(messages: list[dict], max_tokens: int = 700) -> str:
    try:
        return _openai_chat_completion(messages, max_tokens)
    except AIUnavailableError as e:
        if e.code not in _FALLBACK_CODES or not get_fallback_api_key():
            raise
        log.warning("llm_fallback_to_upstage reason=%s", e.code)
        return _upstage_chat_completion(messages, max_tokens)


def _openai_chat_completion(messages: list[dict], max_tokens: int) -> str:
    body = json.dumps({
        "model": OPENAI_MODEL, "messages": messages,
        "max_completion_tokens": max_tokens, "reasoning_effort": LLM_REASONING_EFFORT,
    }).encode()
    req = urllib.request.Request(
        f"{OPENAI_BASE_URL}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"].strip()
    except (socket.timeout, TimeoutError) as e:
        raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.") from e
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise AIUnavailableError("AI_RATE_LIMITED", "AI 서비스 요청이 많아 잠시 제한되었어요. 잠시 후 다시 시도해 주세요.") from e
        if e.code in (401, 403):
            raise AIUnavailableError("AI_KEY_MISSING", "AI 서비스 인증에 실패했어요.") from e
        raise AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.") from e
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
            raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.") from e
        raise AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise AIUnavailableError("AI_ERROR", "AI 응답을 해석하지 못했어요.") from e


def _upstage_chat_completion(messages: list[dict], max_tokens: int) -> str:
    body = json.dumps({
        "model": UPSTAGE_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        f"{UPSTAGE_BASE_URL}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {get_fallback_api_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"].strip()
    except (socket.timeout, TimeoutError) as e:
        raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.") from e
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as e:
        raise AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요(폴백도 실패). 잠시 후 다시 시도해 주세요.") from e
