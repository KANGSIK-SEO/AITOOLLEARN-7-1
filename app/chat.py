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
    '"year_from": 정수 또는 null, "year_to": 정수 또는 null}\n'
    "- 작품 검색이 아니라 직전 대화를 묻는 질문(예: 내가 방금 뭘 물어봤지?)이나 인사면 chitchat=true.\n"
    "- keywords는 주제·분위기·색·소재 등 (예: spring, landscape, flowers, portrait, winter, sea)."
)

ANSWER_SYSTEM_KO = (
    "너는 '퍼블릭 도메인 명화 찾기' 챗봇이다. 한국어로 간결하게 답한다.\n"
    "규칙:\n"
    "1. 아래 [검색 결과]에 있는 작품만 언급한다. 없는 작품·작가·연도를 지어내지 않는다.\n"
    "2. 작품은 [1], [2] 번호로 인용하고, 각 작품이 왜 요청에 맞는지 한 줄씩 설명한다.\n"
    "3. 검색 결과는 MET·Art Institute of Chicago가 CC0(퍼블릭 도메인)로 공개한 것이다. "
    "상업적 이용이 가능하지만 사용 전 '출처 페이지'에서 조건을 확인하도록 한 줄 안내한다.\n"
    "4. 검색 결과가 비어 있으면 없다고 말하고 더 구체적인 조건(작가, 시대, 주제)을 제안한다.\n"
    "5. 직전 대화를 묻는 질문이면 [이전 대화]를 근거로 답한다.\n"
    "6. [완화 안내]가 있으면, 작가/연도 조건에는 맞는 작품을 못 찾아 조건을 일부 빼고 찾았다는 걸 "
    "한 줄로 먼저 알려준다 — 사용자가 결과를 보기 전에 '왜 이게 나왔는지' 판단할 수 있어야 한다."
)

ANSWER_SYSTEM_EN = (
    "You are the 'Public Domain Masterpiece Finder' chatbot. Answer concisely in English.\n"
    "Rules:\n"
    "1. Only mention works listed in [Search Results] below. Never invent a work, artist, or year "
    "that isn't there.\n"
    "2. Cite works by number [1], [2], and explain in one line why each fits the request.\n"
    "3. The search results are released as CC0 (public domain) by the MET and the Art Institute "
    "of Chicago. They can be used commercially, but add one line advising the user to check the "
    "terms on the 'source page' before use.\n"
    "4. If the search results are empty, say so and suggest more specific conditions (artist, era, "
    "theme).\n"
    "5. If the question asks about the previous conversation, answer based on [Previous "
    "Conversation].\n"
    "6. If [Relaxation Notice] is present, first tell the user in one line that no works matched "
    "the artist/year condition so that condition was dropped — the user should be able to judge "
    "'why these results' before seeing them."
)

ANSWER_SYSTEM_BY_LANG = {"ko": ANSWER_SYSTEM_KO, "en": ANSWER_SYSTEM_EN}


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


def _format_results(works: list[dict], lang: str) -> str:
    none_label = "(none)" if lang == "en" else "(없음)"
    if not works:
        return none_label
    unknown_artist = "Unknown artist" if lang == "en" else "작가 미상"
    unknown_date = "Unknown date" if lang == "en" else "연도 미상"
    source_label = "Source" if lang == "en" else "출처"
    return "\n".join(
        f"[{i}] {w['title']} — {w['artist'] or unknown_artist}, {w['date_display'] or unknown_date}, "
        f"{w['medium'] or ''} | {w['license']} | {source_label}: {w['source'].upper()}"
        for i, w in enumerate(works, 1)
    )


def compose_answer(question: str, works: list[dict], history: list[dict], relaxed: bool = False,
                    lang: str = "ko") -> str:
    """works가 ANSWER_NARRATION_LIMIT보다 많아도(예: 프리미엄 100개) 모델에는 그 안에서만 넘긴다.
    본문에서 100개를 전부 한 줄씩 설명시키면 토큰 비용이 폭증하고 잘릴 수 있어서, 나머지는
    카드로만 보여주고 몇 개 더 있는지 한 줄 안내를 덧붙인다.

    relaxed=True면 작가/연도 조건을 빼고 키워드만으로 다시 찾은 결과라는 뜻 — ANSWER_SYSTEM
    규칙 6에 따라 모델이 이를 먼저 알려주게 한다(사용자의 '사전 판단 비용'을 줄이기 위함).

    lang은 프론트엔드 언어 토글(ko/en)을 그대로 받는다 — 응답 언어만 바꾸고 검색 로직은 그대로."""
    lang = lang if lang in ANSWER_SYSTEM_BY_LANG else "ko"
    none_label = "(none)" if lang == "en" else "(없음)"
    narrated = works[:ANSWER_NARRATION_LIMIT]
    past = "\n".join(f"Q: {h['question']}\nA: {(h['answer'] or '')[:300]}" for h in history) or none_label
    if relaxed:
        relax_note = ("No works matched the artist/year condition, so the results below were "
                       "found using only the keywords." if lang == "en" else
                       "작가/연도 조건에는 맞는 작품이 없어 그 조건을 빼고 키워드만으로 찾은 결과입니다.")
    else:
        relax_note = none_label
    label = {"ko": ("[이전 대화]", "[완화 안내]", "[검색 결과]", "[질문]"),
             "en": ("[Previous Conversation]", "[Relaxation Notice]", "[Search Results]", "[Question]")}[lang]
    user = (f"{label[0]}\n{past}\n\n{label[1]}\n{relax_note}\n\n"
           f"{label[2]}\n{_format_results(narrated, lang)}\n\n{label[3]}\n{question}")
    answer = llm.chat_completion(
        [{"role": "system", "content": ANSWER_SYSTEM_BY_LANG[lang]}, {"role": "user", "content": user}],
        max_tokens=700,
    )
    extra = len(works) - len(narrated)
    if extra > 0:
        tail = (f"\n\nFound {extra} more related works. Check the cards below." if lang == "en" else
                f"\n\n그 외에도 관련 작품 {extra}개를 더 찾았어요. 아래 카드에서 확인해 보세요.")
        answer += tail
    return answer
