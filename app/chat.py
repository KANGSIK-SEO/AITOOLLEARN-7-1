"""질문 → (검색 의도 추출) → 미술 DB 검색 → (근거 기반 답변 생성) 파이프라인."""
import json
import logging
import re

from . import art, llm
from .config import ANSWER_NARRATION_LIMIT

log = logging.getLogger("app.chat")

INTENT_SYSTEM = (
    "너는 퍼블릭 도메인 명화 검색 도우미의 '검색 의도 추출기'다. 사용자의 한국어/영어 요청을 "
    "영어 검색 조건 JSON 하나로만 출력하라. 설명·코드블록 금지.\n"
    '형식: {"chitchat": bool, "keywords": [영어 단어 최대 6개], "artist": 영어 작가명 또는 null, '
    '"year_from": 정수 또는 null, "year_to": 정수 또는 null, "orientation": "landscape" 또는 "portrait" 또는 "square" 또는 null, "purpose": 한국어 용도 요약 또는 null}\n'
    "- 작품 검색이 아니라 직전 대화를 묻는 질문(예: 내가 방금 뭘 물어봤지?)이나 인사면 chitchat=true.\n"
    "- keywords는 주제·분위기·색·소재 등 (예: spring, landscape, flowers, portrait, winter, sea).\n"
    "- orientation: PPT·슬라이드·배너·가로형이면 landscape, 세로형·벽 포스터·액자·폰 배경이면 portrait, "
    "인스타그램 게시물·정사각이면 square, 언급 없으면 null.\n"
    "- purpose: 사용자가 말한 쓰임새를 짧게 (예: '카페 벽 세로형 포스터', '교재 삽화', 'PPT 배경'). 없으면 null.\n"
    "- 용도에서 분위기를 읽어 keywords에 넣는다 (예: 카페 → cozy, still life / 교재 삽화 → still life, clear)."
)

ANSWER_SYSTEM = (
    "너는 '퍼블릭 도메인 명화 찾기' 챗봇이다. 먼저 한국어로 간결하게 답하고, 빈 줄을 하나 띄운 뒤 "
    "'English:'로 시작하는 동일한 내용의 영어 번역을 덧붙인다 — 두 언어 모두 아래 규칙을 똑같이 "
    "따른다 (서비스가 한/영 병용이라 항상 두 언어 모두 보여준다).\n"
    "규칙:\n"
    "1. 아래 [검색 결과]에 있는 작품만 언급한다. 없는 작품·작가·연도를 지어내지 않는다.\n"
    "2. 작품은 [1], [2] 번호로 인용하고, 각 작품이 왜 요청에 맞는지 한 줄씩 설명한다.\n"
    "3. 검색 결과는 MET·Art Institute of Chicago가 CC0(퍼블릭 도메인)로 공개한 것이다. "
    "상업적 이용이 가능하지만 사용 전 '출처 페이지'에서 조건을 확인하도록 한 줄 안내한다.\n"
    "4. 검색 결과가 비어 있으면 없다고 말하고 더 구체적인 조건(작가, 시대, 주제)을 제안한다.\n"
    "5. 직전 대화를 묻는 질문이면 [이전 대화]를 근거로 답한다.\n"
    "6. [완화 안내]가 있으면, 작가/연도 조건에는 맞는 작품을 못 찾아 조건을 일부 빼고 찾았다는 걸 "
    "한 줄로 먼저 알려준다 — 사용자가 결과를 보기 전에 '왜 이게 나왔는지' 판단할 수 있어야 한다.\n"
    "7. [용도]가 있으면 작품마다 그 용도에 왜 맞는지(분위기·구도·색감)를 설명한다. 이미지 비율은 카드의 "
    "가로형/세로형 표시와 비율 필터로 확인하라고 안내하고, 해상도 수치는 지어내지 말고 '원본'에서 확인하라고 한다.\n"
    "8. 상업적으로 쓰기 전에 카드의 '근거 기록'을 발급해 보관해 두라고 마지막에 한 줄 안내한다 "
    "('보증'이나 '인증'이라는 말은 쓰지 않는다 — 기관이 공개한 근거를 기록해 주는 것이다)."
)


def _parse_intent(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    kw = data.get("keywords")
    return {
        "chitchat": bool(data.get("chitchat")),
        "keywords": [str(k) for k in kw][:6] if isinstance(kw, list) else [],
        "artist": data.get("artist") if isinstance(data.get("artist"), str) else None,
        "year_from": data.get("year_from") if isinstance(data.get("year_from"), int) else None,
        "year_to": data.get("year_to") if isinstance(data.get("year_to"), int) else None,
        "orientation": data.get("orientation") if data.get("orientation") in ("landscape", "portrait", "square") else None,
        "purpose": data.get("purpose")[:60] if isinstance(data.get("purpose"), str) and data.get("purpose") else None,
    }


def extract_intent(question: str) -> dict:
    raw = llm.chat_completion(
        [{"role": "system", "content": INTENT_SYSTEM}, {"role": "user", "content": question}],
        max_tokens=200,
    )
    return _parse_intent(raw)


def find_artworks(intent: dict, limit: int = 6) -> tuple[list[dict], bool]:
    """두 번째 반환값(relaxed)은 작가/연도 조건을 빼고 키워드만으로 다시 찾았는지 여부.
    사용자가 '왜 이 작품이 나왔는지' 판단하는 비용을 줄이려면 이걸 숨기면 안 된다."""
    if intent["chitchat"]:
        return [], False
    found = art.search(intent["keywords"], intent["artist"], intent["year_from"], intent["year_to"], limit=limit)
    if not found and (intent["artist"] or intent["year_from"] or intent["year_to"]):
        found = art.search(intent["keywords"], limit=limit)  # 조건이 너무 좁으면 키워드만으로 완화
        return found, bool(found)
    return found, False


def _format_results(works: list[dict]) -> str:
    if not works:
        return "(없음)"
    return "\n".join(
        f"[{i}] {w['title']} — {w['artist'] or '작가 미상'}, {w['date_display'] or '연도 미상'}, "
        f"{w['medium'] or ''} | {w['license']} | 출처: {w['source'].upper()}"
        for i, w in enumerate(works, 1)
    )


def compose_answer(question: str, works: list[dict], history: list[dict], relaxed: bool = False,
                   purpose: str | None = None) -> str:
    """works가 ANSWER_NARRATION_LIMIT보다 많아도(예: 프리미엄 100개) 모델에는 그 안에서만 넘긴다.
    본문에서 100개를 전부 한 줄씩 설명시키면 토큰 비용이 폭증하고 잘릴 수 있어서, 나머지는
    카드로만 보여주고 몇 개 더 있는지 한 줄 안내를 덧붙인다.

    relaxed=True면 작가/연도 조건을 빼고 키워드만으로 다시 찾은 결과라는 뜻 — ANSWER_SYSTEM
    규칙 6에 따라 모델이 이를 먼저 알려주게 한다(사용자의 '사전 판단 비용'을 줄이기 위함).

    서비스가 한/영 상시 병기라 ANSWER_SYSTEM이 늘 한국어+영어 답변을 함께 생성한다(토글 없음)."""
    narrated = works[:ANSWER_NARRATION_LIMIT]
    past = "\n".join(f"Q: {h['question']}\nA: {(h['answer'] or '')[:300]}" for h in history) or "(없음)"
    relax_note = "작가/연도 조건에는 맞는 작품이 없어 그 조건을 빼고 키워드만으로 찾은 결과입니다." if relaxed else "(없음)"
    user = (f"[이전 대화]\n{past}\n\n[완화 안내]\n{relax_note}\n\n[용도]\n{purpose or '(없음)'}\n\n"
           f"[검색 결과]\n{_format_results(narrated)}\n\n[질문]\n{question}")
    answer = llm.chat_completion(
        [{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": user}],
        max_tokens=900,
    )
    extra = len(works) - len(narrated)
    if extra > 0:
        answer += (f"\n\n그 외에도 관련 작품 {extra}개를 더 찾았어요. 아래 카드에서 확인해 보세요. / "
                   f"Found {extra} more related works — check the cards below.")
    return answer
