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


LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "20"))
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "low")  # low|medium|high|xhigh|max
CHAT_MAX_LENGTH = 500          # 질문 최대 글자 수
CONTEXT_TURNS = 5              # 문맥으로 넘기는 최근 대화 수
CHAT_LIMIT_PER_HOUR = 30               # 일반 사용자 시간당 질문 상한 (버스트 방지 + 비용 보호)
CHAT_LIMIT_PER_HOUR_PREMIUM = int(os.environ.get("CHAT_LIMIT_PER_HOUR_PREMIUM", "300"))  # 초대코드 사용자 시간당 상한
CHAT_LIFETIME_LIMIT_FREE = int(os.environ.get("CHAT_LIFETIME_LIMIT_FREE", "100"))  # 초대코드 없는 사용자의 평생 무료 질문 수

ART_RESULTS_LIMIT = 6                  # 일반 사용자에게 보여줄 추천 작품 수
ART_RESULTS_LIMIT_PREMIUM = int(os.environ.get("ART_RESULTS_LIMIT_PREMIUM", "100"))  # 초대코드 사용자 추천 작품 수
ANSWER_NARRATION_LIMIT = 6             # 답변 본문에서 번호로 설명하는 작품 수 상한 (프리미엄이어도 동일 — 토큰 비용 보호)

# 가입 전 체험: 처음 온 사람이 가치를 먼저 확인할 수 있게 로그인 없이 질문을 허용한다.
# IP 기준으로 세므로 쿠키를 지워도 늘어나지 않는다 (AI 비용 보호).
GUEST_TRIAL_LIMIT = int(os.environ.get("GUEST_TRIAL_LIMIT", "3"))
GUEST_TRIAL_WINDOW_SECONDS = 24 * 3600

BROWSE_PAGE_SIZE = 24                  # '더 보기' 한 번에 보여줄 작품 수 (AI 없이 DB만 조회)
BROWSE_LIMIT_PER_HOUR = 600            # IP당 '더 보기' 시간당 상한
FAVORITES_MAX = 500                    # 사용자당 즐겨찾기 상한
