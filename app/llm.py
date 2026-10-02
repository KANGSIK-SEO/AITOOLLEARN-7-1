"""Upstage solar-pro4 호출 (서버 측에서만 수행, 키는 응답에 노출하지 않는다)."""
import json
import logging
import socket
import urllib.error
import urllib.request

from .config import (ALLOWED_MODEL, LLM_TIMEOUT_SECONDS, UPSTAGE_BASE_URL,
                     AIUnavailableError, ensure_ai_allowed, get_api_key)

log = logging.getLogger("app.llm")


def chat_completion(messages: list[dict], max_tokens: int = 700, temperature: float = 0.3) -> str:
    """정책 검사 → 타임아웃 있는 호출. 실패는 AIUnavailableError(code=AI_TIMEOUT/AI_ERROR ...)로 통일."""
    model = ensure_ai_allowed(ALLOWED_MODEL)
    body = json.dumps({
        "model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        f"{UPSTAGE_BASE_URL}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {get_api_key()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"].strip()
    except (socket.timeout, TimeoutError) as e:
        raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.") from e
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
            raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.") from e
        raise AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.") from e
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise AIUnavailableError("AI_ERROR", "AI 응답을 해석하지 못했어요.") from e
