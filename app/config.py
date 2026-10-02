"""AI 모델 사용 정책.

- solar-pro4만 허용한다. 다른 모델은 과금되므로 코드 어디서도 호출할 수 없다.
- 2027-04-01부터는 solar-pro4도 과금되므로 모든 모델을 무효화한다.
"""
import os
from datetime import date
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

ALLOWED_MODEL = "solar-pro4"
AI_CUTOFF_DATE = date(2027, 4, 1)  # 이 날짜 이후(포함) 모든 AI 호출 차단
UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"


class AIUnavailableError(RuntimeError):
    """정책상 AI 호출이 허용되지 않을 때 발생. code는 API 오류 응답에 그대로 쓴다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def ensure_ai_allowed(model: str, today: date | None = None) -> str:
    """호출 직전에 반드시 통과시킬 것. 허용되면 모델명을 그대로 반환한다."""
    if (today or date.today()) >= AI_CUTOFF_DATE:
        raise AIUnavailableError(
            "AI_EXPIRED", "2027-04 이후에는 모든 AI 모델이 과금되어 사용이 종료되었습니다."
        )
    if model != ALLOWED_MODEL:
        raise AIUnavailableError("AI_MODEL_NOT_ALLOWED", f"허용되지 않은 모델입니다: {model}")
    return model


def get_api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY", "")
    if not key:
        raise AIUnavailableError("AI_KEY_MISSING", "UPSTAGE_API_KEY가 설정되지 않았습니다.")
    return key


def get_secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "")
    if len(key) < 32:
        raise RuntimeError("SECRET_KEY가 없거나 너무 짧습니다 (32자 이상).")
    return key


def get_premium_code() -> str:
    """가입 시 이 값과 일치하는 코드를 입력하면 프리미엄으로 전환. 비어 있으면 프리미엄 가입 비활성."""
    return os.environ.get("PREMIUM_CODE", "")


LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "20"))
CHAT_MAX_LENGTH = 500          # 질문 최대 글자 수
CONTEXT_TURNS = 5              # 문맥으로 넘기는 최근 대화 수
CHAT_LIMIT_PER_HOUR = 30               # 일반 사용자 시간당 질문 상한 (무료 API 보호)
CHAT_LIMIT_PER_HOUR_PREMIUM = int(os.environ.get("CHAT_LIMIT_PER_HOUR_PREMIUM", "300"))  # 프리미엄 사용자 상한
