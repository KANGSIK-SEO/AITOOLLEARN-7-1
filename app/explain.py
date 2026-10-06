"""피어 리뷰용 프로젝트 설명 에이전트.

동료가 /explain 페이지에서 뭘 물어도, 이 레포의 전체 소스코드를 근거로
gpt-6-astra(app/llm.py와 동일한 호출·폴백)가 대신 답한다. 만든 사람이 AI 도구로
혼자 구현해서 세부를 다 기억하지 못해도, 코드에 있는 그대로 답할 수 있게 하기 위함이다.

EXPLAIN_AGENT_SECRET으로 보호한다 — 비어 있으면(기본값) 항상 401. 평가가 끝나면
Vercel 환경변수에서 지워서 끄면 된다.
"""
import logging
import os
from pathlib import Path

from .config import AIUnavailableError
from .llm import chat_completion

log = logging.getLogger("app.explain")

ROOT = Path(__file__).resolve().parent.parent

CONTEXT_FILES = [
    "README.md",
    "db/schema.sql",
    "app/config.py",
    "app/main.py",
    "app/auth.py",
    "app/chat.py",
    "app/art.py",
    "app/llm.py",
    "app/db.py",
    "app/guardian.py",
    "app/static/index.html",
    "app/static/app.js",
    "app/static/style.css",
]

SYSTEM_PROMPT = """당신은 "저작권 걱정 없는 퍼블릭 도메인 명화 찾기 챗봇"(AITOOLLEARN-7-1) 프로젝트를 만든
개발자를 대신해, 동료 평가(피어 리뷰) 자리에서 팀원들의 질문에 답하는 설명 에이전트입니다.

이 프로젝트는 실제로는 한 사람이 AI 도구를 적극 활용해 혼자 설계·구현했습니다. 동료들은 "혼자 만들었으니
제대로 아는지" 확인하려고 코드 품질, 기능 완성도, 설계/아키텍처, 문서화, 컨벤션(노름) 준수 등 다양한 각도에서
샅샅이 질문할 것입니다.

아래에는 이 프로젝트의 전체 소스코드와 README가 그대로 담겨 있습니다. 답할 때 반드시 지킬 것:
1. 반드시 아래 코드/문서에 근거해서만 답하라. 파일명과 함수·변수명을 구체적으로 인용하라
   (예: "app/chat.py의 compose_answer 함수에서 ...").
2. "왜 이렇게 설계했는가"를 물으면 코드 주석이나 구조(예: app/guardian.py의 즉시 대응 vs 배치 분석 분리)를
   근거로 설명하라.
3. 코드에 없는 내용은 추측하지 말고 "코드에는 명시돼 있지 않습니다"라고 솔직히 답하라.
4. 평가 상황이므로 자신감 있고 명확한 어조로, 하지만 사실만 답하라. 과장하지 말 것.
5. 질문이 모호하면 가장 가능성 높은 해석으로 답하되, 다른 해석의 여지가 있으면 짧게 덧붙여라.

[프로젝트 전체 소스코드]
{context}
"""

_context_cache: str | None = None

# 평가 자리에서 동료가 보는 화면이라, 내부 사정(환경변수 이름, 제공자 이름) 대신 "지금 무엇을 하면 되는지"를 말한다.
# 코드(AI_TIMEOUT 등)는 그대로 두고 메시지만 바꾼다 — 상태 코드·로그·가디언 집계는 기존과 같다.
FRIENDLY_AI_ERRORS = {
    "AI_TIMEOUT": "프로젝트 코드 전체를 읽고 답하느라 시간이 너무 걸렸어요. 질문을 조금 더 짧고 구체적으로"
                  "(예: 파일이나 함수 이름을 넣어서) 다시 물어봐 주세요.",
    "AI_RATE_LIMITED": "지금 질문이 몰려 AI가 잠시 쉬고 있어요. 1분쯤 뒤에 다시 물어봐 주세요.",
    "AI_KEY_MISSING": "설명 에이전트가 지금 AI에 연결되어 있지 않아요. 발표자에게 알려 주세요.",
}
DEFAULT_AI_ERROR = "AI가 답을 만들지 못했어요. 같은 질문을 한 번 더 보내 보시고, 계속되면 질문을 바꿔 주세요."


class ExplainUnavailable(RuntimeError):
    """AI 호출 전 단계(프로젝트 코드 읽기)에서 실패. 사용자에게 보여줄 메시지를 담는다."""


def friendly_ai_message(code: str) -> str:
    return FRIENDLY_AI_ERRORS.get(code, DEFAULT_AI_ERROR)


def get_secret() -> str:
    return os.environ.get("EXPLAIN_AGENT_SECRET", "")


def build_context() -> str:
    """같은 서버리스 인스턴스가 재사용되는 동안은 한 번만 읽는다(Vercel Fluid Compute)."""
    global _context_cache
    if _context_cache is None:
        parts = []
        for rel in CONTEXT_FILES:
            path = ROOT / rel
            if path.is_file():
                parts.append(f"\n\n===== {rel} =====\n{path.read_text(encoding='utf-8')}")
        _context_cache = "".join(parts)
    return _context_cache


def ask(question: str) -> str:
    """AI 실패는 AIUnavailableError(코드 유지), 코드 읽기 실패는 ExplainUnavailable로 올린다."""
    try:
        context = build_context()
    except (OSError, UnicodeDecodeError) as e:
        log.error("explain_context_failure detail=%s", e)
        raise ExplainUnavailable("설명 에이전트가 프로젝트 코드를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.") from e
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
        {"role": "user", "content": question},
    ]
    return chat_completion(messages, max_tokens=1200)
