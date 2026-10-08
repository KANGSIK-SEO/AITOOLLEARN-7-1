"""Claude(Anthropic) 호출 — ANTHROPIC_API_KEY가 있으면 app/llm.py가 이쪽을 먼저 쓴다.

- 모델: CLAUDE_MODEL(기본 claude-fable-5-1). 의도 추출만 다른 모델로 돌리려면 CLAUDE_INTENT_MODEL.
- 속도: effort를 CLAUDE_EFFORT(기본 low)로 둔다. Fable은 생각(thinking)이 항상 켜져 있어 끌 수 없고,
  effort가 생각의 깊이를 정한다. 검색어 뽑기·짧은 설명에는 low로 충분하다.
- 의도 추출은 structured outputs(JSON 스키마)로 받아 형식이 깨질 일이 없다.
- 안전 분류기가 요청을 거절하면 서버 쪽 폴백(fallbacks="default")이 다른 모델로 다시 시도한다.
  Haiku는 서버 폴백이 없어 이 옵션을 보내지 않는다.
- 실패는 app/llm.py와 같은 AIUnavailableError 코드로 바꿔서 올린다 (화면 안내·가디언 집계가 그대로 동작).
"""
import logging
import os
from collections.abc import Iterator

import anthropic

from .config import AIUnavailableError

log = logging.getLogger("app.claude")

DEFAULT_MODEL = "claude-fable-5-1"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
# 생각 토큰도 max_tokens 안에 들어가므로, 화면에 나갈 글 길이보다 넉넉히 잡는다 (글 길이는 프롬프트가 정한다)
MAX_TOKENS = 8000

_client: anthropic.Anthropic | None = None


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def model_for(purpose: str) -> str:
    main = os.environ.get("CLAUDE_MODEL", "").strip() or DEFAULT_MODEL
    if purpose == "intent":
        return os.environ.get("CLAUDE_INTENT_MODEL", "").strip() or main
    return main


def effort() -> str:
    value = os.environ.get("CLAUDE_EFFORT", "low").strip()
    return value if value in EFFORTS else "low"


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        timeout = float(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "40") or 40)
        _client = anthropic.Anthropic(timeout=timeout, max_retries=1)
    return _client


def _params(messages: list[dict], purpose: str, json_schema: dict | None) -> dict:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    model = model_for(purpose)
    output_config: dict = {"effort": effort()}
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    params = {"model": model, "max_tokens": MAX_TOKENS, "system": system, "messages": turns,
              "output_config": output_config}
    if not model.startswith("claude-haiku"):
        params.update(betas=[FALLBACK_BETA], fallbacks="default")
    return params


def _as_unavailable(e: Exception) -> AIUnavailableError:
    if isinstance(e, anthropic.APITimeoutError):
        return AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.")
    if isinstance(e, anthropic.RateLimitError):
        return AIUnavailableError("AI_RATE_LIMITED", "AI 서비스 요청이 많아 잠시 제한되었어요. 잠시 후 다시 시도해 주세요.")
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return AIUnavailableError("AI_KEY_MISSING", "AI 서비스 인증에 실패했어요.")
    return AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.")


def _refused() -> AIUnavailableError:
    return AIUnavailableError("AI_REFUSED", "이 질문에는 답할 수 없어요. 질문을 바꿔 다시 시도해 주세요.")


def complete(messages: list[dict], purpose: str = "answer", json_schema: dict | None = None) -> str:
    params = _params(messages, purpose, json_schema)
    try:
        response = _get_client().beta.messages.create(**params)
    except anthropic.APIError as e:
        log.warning("claude_call_failed model=%s error=%s", params["model"], type(e).__name__)
        raise _as_unavailable(e) from e
    if response.stop_reason == "refusal":
        raise _refused()
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise AIUnavailableError("AI_ERROR", "AI 응답이 비어 있어요. 잠시 후 다시 시도해 주세요.")
    return text


def stream(messages: list[dict], purpose: str = "answer") -> Iterator[str]:
    """글이 만들어지는 대로 조각을 내보낸다. 첫 조각 전에 실패하면 호출부가 다른 모델로 넘어갈 수 있다."""
    params = _params(messages, purpose, None)
    try:
        with _get_client().beta.messages.stream(**params) as s:
            for text in s.text_stream:
                if text:
                    yield text
            final = s.get_final_message()
    except anthropic.APIError as e:
        log.warning("claude_stream_failed model=%s error=%s", params["model"], type(e).__name__)
        raise _as_unavailable(e) from e
    if final.stop_reason == "refusal":
        raise _refused()
