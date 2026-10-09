"""Claude(Anthropic) 호출 — ANTHROPIC_API_KEY가 있으면 app/llm.py가 이쪽을 먼저 쓴다.

- 모델: CLAUDE_MODEL(기본 claude-haiku-5-5 — 가장 저렴하고 빠른 Claude). 챗봇 답변·검색 조건 뽑기·가디언 진단·
  접속 기록 감시가 모두 이 모델을 쓴다. Fable(claude-fable-5-1)은 자동 코드 수정(scripts/autofix_propose.py)에만 쓴다.
  의도 추출만 다른 모델로 돌리려면 CLAUDE_INTENT_MODEL.
- 비용·속도 (2026-10-08 사용량 절감):
  - effort는 모든 모델에 CLAUDE_EFFORT(기본 low)로 보낸다. Haiku 5.5는 보내지 않으면 medium으로 생각해 토큰을 더 쓴다.
  - 정해진 형식만 뽑는 일(검색 조건 intent, 상태 확인 probe)은 Haiku의 생각(thinking)을 끈다 — 생각 토큰은 출력 요금이다.
  - 1분 접속 감시(watch)는 저장소 주인 요청으로 Fable(WATCH_MODEL)이 판단한다.
  - 길고 매번 같은 지시문(system)은 프롬프트 캐시에 올린다. 같은 지시문이 5분 안에 다시 쓰이면 그 부분은 1/10 값이다
    (설명 에이전트처럼 프로젝트 코드 전체를 지시문에 넣는 경우 효과가 크다).
  - 쓴 토큰은 목적별로 ai_usage 표에 남긴다 → /api/guardian/summary, 매일 품질 점검이 보고 더 줄일 곳을 찾는다.
- 의도 추출은 structured outputs(JSON 스키마)로 받아 형식이 깨질 일이 없다.
- 안전 분류기가 요청을 거절하면 서버 쪽 폴백(fallbacks="default")이 다른 모델로 다시 시도한다.
  Haiku는 서버 폴백이 없어 이 옵션을 보내지 않는다.
- 실패는 app/llm.py와 같은 AIUnavailableError 코드로 바꿔서 올린다 (화면 안내·가디언 집계가 그대로 동작).
- 타임아웃: 25초(TIMEOUT_SECONDS)와 요청의 남은 시간 중 짧은 쪽. SDK 자체 재시도는 끄고(시간이 두 배가 되므로)
  실패하면 app/llm.py가 다른 AI로 넘긴다. 시간이 다 되면 "죄송합니다. 접속자가 많습니다."로 끝낸다.
"""
import logging
import os
from collections.abc import Iterator

import anthropic

from . import reqctx
from .config import BUSY_MESSAGE, TIMEOUT_SECONDS, AIUnavailableError

log = logging.getLogger("app.claude")

DEFAULT_MODEL = "claude-haiku-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
# 생각 토큰도 max_tokens 안에 들어가므로, 화면에 나갈 글 길이보다 넉넉히 잡는다 (글 길이는 프롬프트가 정한다)
MAX_TOKENS = 8000
NO_THINKING_PURPOSES = {"intent", "watch", "probe"}   # 형식만 맞추면 되는 일 — 생각 없이도 결과가 같다
CACHE_MIN_CHARS = 2000   # 이보다 짧은 지시문은 캐시 최소 길이(512토큰)에 못 미칠 수 있어 그냥 보낸다

_client: anthropic.Anthropic | None = None


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


WATCH_DEFAULT_MODEL = "claude-fable-5-1"   # 1분 접속 감시는 저장소 주인 요청으로 Fable이 판단 (2026-10-09)


def model_for(purpose: str) -> str:
    if purpose == "watch":   # 비용이 크면 Vercel 환경변수 WATCH_MODEL=claude-haiku-5-5 로 바로 되돌린다
        return os.environ.get("WATCH_MODEL", "").strip() or WATCH_DEFAULT_MODEL
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
        _client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=0)
    return _client


def _params(messages: list[dict], purpose: str, json_schema: dict | None) -> dict:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    model = model_for(purpose)
    output_config: dict = {"effort": effort()}
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    # 지시문은 요청마다 같으므로 캐시 표시를 단다 (바뀌는 질문은 messages 쪽이라 캐시를 깨지 않는다)
    system_param = ([{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
                    if len(system) >= CACHE_MIN_CHARS else system)
    params = {"model": model, "max_tokens": MAX_TOKENS, "system": system_param, "messages": turns,
              "output_config": output_config}
    if model.startswith("claude-haiku") and purpose in NO_THINKING_PURPOSES:
        params["thinking"] = {"type": "disabled"}   # Haiku 5.5는 effort high 이하에서 끌 수 있다
    if not model.startswith("claude-haiku"):
        params.update(betas=[FALLBACK_BETA], fallbacks="default")
    return params


def _credit_exhausted(e: Exception) -> bool:
    """크레딧을 다 쓰면 Anthropic은 429가 아니라 400(잔액 부족 안내)을 준다 — 이것도 '소진'으로 본다."""
    return isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e).lower()


def _as_unavailable(e: Exception) -> AIUnavailableError:
    if _credit_exhausted(e):
        return AIUnavailableError("AI_KEY_MISSING", "AI 서비스 크레딧이 소진되었어요.")
    if isinstance(e, anthropic.APITimeoutError):
        return AIUnavailableError("AI_TIMEOUT", BUSY_MESSAGE)
    if isinstance(e, anthropic.RateLimitError):
        return AIUnavailableError("AI_RATE_LIMITED", "AI 서비스 요청이 많아 잠시 제한되었어요. 잠시 후 다시 시도해 주세요.")
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return AIUnavailableError("AI_KEY_MISSING", "AI 서비스 인증에 실패했어요.")
    return AIUnavailableError("AI_ERROR", "AI 서버와 통신하지 못했어요. 잠시 후 다시 시도해 주세요.")


MIN_ATTEMPT_SECONDS = 2.0   # 남은 시간이 이보다 적으면 부르지 않는다


def _time_left() -> float:
    left = reqctx.remaining(TIMEOUT_SECONDS)
    if left < MIN_ATTEMPT_SECONDS:
        raise AIUnavailableError("AI_TIMEOUT", BUSY_MESSAGE)
    return left


def _record_usage(purpose: str, model: str, usage) -> None:
    """토큰 사용량을 남긴다 (목적별로 얼마나 쓰는지 보고 줄이기 위해 — /api/guardian/summary, 품질 점검이 읽는다).
    요청 중이면 응답을 보낸 뒤 한꺼번에 저장하고(app/main.py), 요청 밖(크론)이면 바로 저장한다."""
    if usage is None:
        return
    row = (purpose, model, int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0),
           int(getattr(usage, "cache_read_input_tokens", 0) or 0),
           int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
    pending = reqctx.pending()
    if pending is not None:
        pending.setdefault("ai_usage", []).append(row)
        return
    from . import guardian   # 순환 import를 피하려고 여기서 부른다
    guardian.save_ai_usage([row])


def _refused() -> AIUnavailableError:
    return AIUnavailableError("AI_REFUSED", "이 질문에는 답할 수 없어요. 질문을 바꿔 다시 시도해 주세요.")


def complete(messages: list[dict], purpose: str = "answer", json_schema: dict | None = None) -> str:
    params = _params(messages, purpose, json_schema)
    try:
        response = _get_client().beta.messages.create(**params, timeout=_time_left())
    except anthropic.APIError as e:
        log.warning("claude_call_failed model=%s error=%s", params["model"], type(e).__name__)
        raise _as_unavailable(e) from e
    _record_usage(purpose, params["model"], getattr(response, "usage", None))
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
        with _get_client().beta.messages.stream(**params, timeout=_time_left()) as s:
            for text in s.text_stream:
                if text:
                    yield text
            final = s.get_final_message()
    except anthropic.APIError as e:
        log.warning("claude_stream_failed model=%s error=%s", params["model"], type(e).__name__)
        raise _as_unavailable(e) from e
    _record_usage(purpose, params["model"], getattr(final, "usage", None))
    if final.stop_reason == "refusal":
        raise _refused()
