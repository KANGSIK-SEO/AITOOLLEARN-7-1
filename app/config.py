"""AI 모델 설정과 외부 API 키.

주 모델: OpenAI GPT-6 Astra(모델 ID `gpt-6-astra`). GPT 쪽 키가 소진·장애(429/401/403)일 때만
비상용으로 Upstage solar-pro4로 넘어간다 (`UPSTAGE_API_KEY`가 설정된 경우에만 활성).
solar-pro4는 2026-10 기준 무료·무제한이지만, 2027-04-01부터는 Upstage 쪽에서 모든 모델을 과금 전환해
무효화한다고 공지했다 — 그 날짜 이후엔 이 폴백도 더 이상 쓸 수 없다.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """의존성 없이 .env를 읽는다. 이미 설정된 환경 변수(Vercel 등)는 덮어쓰지 않는다."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

OPENAI_MODEL = "gpt-6-astra"
OPENAI_BASE_URL = "https://api.openai.com/v1"
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# 비상 폴백 (GPT 키 소진/장애 시에만 사용)
UPSTAGE_MODEL = "solar-pro4"
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"


class ConfigError(RuntimeError):
    """환경변수가 없거나 형식이 틀려 서버를 띄울 수 없을 때. 메시지에 고칠 방법까지 담는다."""


def _env_number(name: str, default: str, cast, minimum=None):
    raw = os.environ.get(name, "").strip() or default
    try:
        value = cast(raw)
    except ValueError:
        kind = "정수" if cast is int else "숫자"
        raise ConfigError(f"환경변수 {name}는 {kind}여야 합니다 (현재 값: {raw!r}). .env 또는 Vercel 환경변수를 확인하세요.") from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"환경변수 {name}는 {minimum} 이상이어야 합니다 (현재 값: {raw!r}).")
    return value


class AIUnavailableError(RuntimeError):
    """AI 호출이 실패했을 때 발생. code는 API 오류 응답에 그대로 쓴다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def get_api_key() -> str:
    key = os.environ.get("GPT_ASTRA_API_KEY", "")
    if not key:
        raise AIUnavailableError("AI_KEY_MISSING", "GPT_ASTRA_API_KEY가 설정되지 않았습니다.")
    return key


def get_fallback_api_key() -> str:
    """비어 있으면 폴백 비활성 (에러를 던지지 않는다 — 있으면 쓰고, 없으면 그냥 넘어간다)."""
    return os.environ.get("UPSTAGE_API_KEY", "")


def get_secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "")
    if len(key) < 32:
        raise RuntimeError("SECRET_KEY가 없거나 너무 짧습니다 (32자 이상).")
    return key


def get_premium_code() -> str:
    """가입 시 이 값과 일치하는 코드를 입력하면 프리미엄으로 전환. 비어 있으면 프리미엄 가입 비활성."""
    return os.environ.get("PREMIUM_CODE", "")


LLM_TIMEOUT_SECONDS = _env_number("LLM_TIMEOUT_SECONDS", "20", float, minimum=1)  # 요청 1회의 소켓 타임아웃
# chat_completion 1번(재시도·폴백 포함)에 쓸 수 있는 총 시간. /api/chat은 AI를 2번(의도 추출, 답변) 부르고
# Vercel 함수 최대 실행시간이 60초(vercel.json)이므로 2번 × 25초 + DB 여유가 그 안에 들어오게 잡았다.
LLM_CALL_BUDGET_SECONDS = _env_number("LLM_CALL_BUDGET_SECONDS", "25", float, minimum=1)
LLM_MAX_RETRIES = _env_number("LLM_MAX_RETRIES", "1", int, minimum=0)  # 일시 장애(5xx·연결 오류) 시 같은 제공자 재시도 횟수
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "low")  # low|medium|high|xhigh|max
CHAT_MAX_LENGTH = 500          # 질문 최대 글자 수
CONTEXT_TURNS = 5              # 문맥으로 넘기는 최근 대화 수
CHAT_LIMIT_PER_HOUR = 30               # 일반 사용자 시간당 질문 상한 (버스트 방지 + 비용 보호)
CHAT_LIMIT_PER_HOUR_PREMIUM = _env_number("CHAT_LIMIT_PER_HOUR_PREMIUM", "300", int, minimum=1)  # 초대코드 사용자 시간당 상한
CHAT_LIFETIME_LIMIT_FREE = _env_number("CHAT_LIFETIME_LIMIT_FREE", "100", int, minimum=0)  # 초대코드 없는 사용자의 평생 무료 질문 수
FREE_LIMIT_WARNING_THRESHOLD = _env_number("FREE_LIMIT_WARNING_THRESHOLD", "10", int, minimum=0)  # 남은 무료 질문이 이 수 이하면 화면에 안내

ART_RESULTS_LIMIT = 6                  # 일반 사용자에게 보여줄 추천 작품 수
ART_RESULTS_LIMIT_PREMIUM = _env_number("ART_RESULTS_LIMIT_PREMIUM", "100", int, minimum=1)  # 초대코드 사용자 추천 작품 수
ANSWER_NARRATION_LIMIT = 6             # 답변 본문에서 번호로 설명하는 작품 수 상한 (프리미엄이어도 동일 — 토큰 비용 보호)

BROWSE_PAGE_SIZE = 24                  # '더 보기' 한 번에 보여줄 작품 수 (AI 없이 DB만 조회)
BROWSE_LIMIT_PER_HOUR = 600            # IP당 '더 보기' 시간당 상한
FAVORITES_MAX = 500                    # 사용자당 즐겨찾기 상한
RECORD_LIMIT_PER_HOUR = 60             # IP당 권리 근거 기록 발급 시간당 상한 (아카이브 호출 남용 방지)

REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def validate_env() -> list[str]:
    """서버 시작 시 한 번 호출한다. 서버를 띄울 수 없는 문제는 한꺼번에 모아 ConfigError로 던지고,
    기능 일부만 꺼지는 문제는 경고 목록으로 돌려준다 (호출한 쪽이 로그로 남긴다).

    기존에는 SECRET_KEY가 없으면 첫 로그인 요청에서야 RuntimeError로 500이 났고,
    정수 환경변수에 오타가 있으면 import 중 ValueError 스택트레이스만 남았다.
    """
    errors, warnings = [], []
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        errors.append("SECRET_KEY가 없습니다. 생성: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    elif len(secret) < 32:
        errors.append(f"SECRET_KEY가 너무 짧습니다 ({len(secret)}자, 32자 이상 필요).")
    if os.environ.get("TURSO_DATABASE_URL", "").strip() and not os.environ.get("TURSO_AUTH_TOKEN", "").strip():
        errors.append("TURSO_DATABASE_URL이 설정됐지만 TURSO_AUTH_TOKEN이 없습니다. 로컬 SQLite를 쓰려면 TURSO_DATABASE_URL을 비우세요.")
    if LLM_REASONING_EFFORT not in REASONING_EFFORTS:
        errors.append(f"LLM_REASONING_EFFORT는 {'|'.join(sorted(REASONING_EFFORTS))} 중 하나여야 합니다 (현재 값: {LLM_REASONING_EFFORT!r}).")
    if errors:
        raise ConfigError("필수 환경변수 설정 오류:\n- " + "\n- ".join(errors))

    if not os.environ.get("GPT_ASTRA_API_KEY", ""):
        warnings.append("GPT_ASTRA_API_KEY가 없어 챗봇 질문이 503 AI_KEY_MISSING으로 실패합니다"
                        + (" (UPSTAGE_API_KEY 폴백으로 동작)." if get_fallback_api_key() else "."))
    if not CRON_SECRET:
        warnings.append("CRON_SECRET이 없어 가디언 일일 점검(/api/guardian/daily-digest)이 비활성입니다.")
    return warnings
