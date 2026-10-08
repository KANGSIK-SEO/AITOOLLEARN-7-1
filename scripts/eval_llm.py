"""LLM 답변 품질 평가 (docs/llm-eval.md).

사용: python3 scripts/eval_llm.py               # 실제 AI 호출 (GPT_ASTRA_API_KEY 필요, 질문 20개 × 2회 호출)
      python3 scripts/eval_llm.py --dry-run     # 가짜 AI로 채점기 자체만 점검 (비용 0)
결과: 콘솔 점수표 + data/eval/llm-eval-<시각>.json (기록을 쌓아 프롬프트를 바꿀 때마다 비교한다)

두 단계를 따로 잰다.
1) 의도 추출(extract_intent): 잡담 여부·비율·용도·검색어를 기대값과 비교 → 정확도(%)
2) 답변(compose_answer): 규칙 위반을 자동으로 찾는다 → 준수율(%)
   - 근거성: 답변의 [n] 인용이 실제로 넘긴 작품 번호 범위 안에 있는가 (없는 작품을 지어내지 않았나)
   - 한/영 병기: 'English:' 섹션이 있는가
   - 금지어: '보증'·'인증'처럼 공신력을 주장하는 말을 쓰지 않았나 (근거 기록은 보증이 아니다)
   - 근거 기록 안내: 작품이 있으면 '근거 기록'을 안내했나
   - 완화 안내: 조건을 빼고 찾은 경우 그 사실을 먼저 알렸나
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "eval-only-secret-key-eval-only-secret")

from app import chat, llm  # noqa: E402
from app.config import ANSWER_NARRATION_LIMIT  # noqa: E402

# expect: 의도 추출 기대값. None인 항목은 채점하지 않는다.
#   chitchat(bool) · orientation("landscape"|"portrait"|"square"|None=언급 없음이어야 함) ·
#   purpose(True=있어야 함) · keywords_any(이 중 하나 이상이 키워드에 있어야 함) · artist_has(작가명 포함)
CASES = [
    {"q": "카페 벽에 걸 세로형 포스터", "expect": {"chitchat": False, "orientation": "portrait", "purpose": True}},
    {"q": "교재 삽화용 정물화", "expect": {"chitchat": False, "purpose": True, "keywords_any": ["still", "life"]}},
    {"q": "PPT 배경용 가로형 풍경화", "expect": {"chitchat": False, "orientation": "landscape", "keywords_any": ["landscape"]}},
    {"q": "인스타그램 정사각 게시물용 꽃 그림", "expect": {"chitchat": False, "orientation": "square", "keywords_any": ["flower", "flowers"]}},
    {"q": "봄 느낌 풍경화 3개", "expect": {"chitchat": False, "orientation": None, "keywords_any": ["spring", "landscape"]}},
    {"q": "고흐 작품 보여줘", "expect": {"chitchat": False, "artist_has": "gogh"}},
    {"q": "모네의 수련", "expect": {"chitchat": False, "artist_has": "monet", "keywords_any": ["water", "lilies", "lily"]}},
    {"q": "19세기 바다 그림", "expect": {"chitchat": False, "keywords_any": ["sea", "ocean", "seascape", "marine"]}},
    {"q": "겨울 눈 풍경, 블로그 대표 이미지용", "expect": {"chitchat": False, "orientation": "landscape", "keywords_any": ["winter", "snow"]}},
    {"q": "폰 배경화면으로 쓸 밤하늘", "expect": {"chitchat": False, "orientation": "portrait", "keywords_any": ["night", "sky", "stars"]}},
    {"q": "아이 방 액자용 동물 그림", "expect": {"chitchat": False, "orientation": "portrait", "keywords_any": ["animal", "animals", "dog", "cat", "bird"]}},
    {"q": "Show me a spring landscape for a presentation slide", "expect": {"chitchat": False, "orientation": "landscape", "keywords_any": ["spring", "landscape"]}},
    {"q": "일본 판화 고양이", "expect": {"chitchat": False, "keywords_any": ["cat", "cats", "japanese", "print"]}},
    {"q": "따뜻한 느낌의 초상화", "expect": {"chitchat": False, "keywords_any": ["portrait"]}},
    {"q": "안녕하세요", "expect": {"chitchat": True}},
    {"q": "내가 방금 뭘 물어봤지?", "expect": {"chitchat": True}},
    {"q": "고마워요!", "expect": {"chitchat": True}},
    {"q": "렘브란트 1650년 이후 작품", "expect": {"chitchat": False, "artist_has": "rembrandt"}},
    {"q": "식당 메뉴판에 넣을 과일 정물화", "expect": {"chitchat": False, "purpose": True, "keywords_any": ["fruit", "still"]}},
    {"q": "배너용 가로로 긴 도시 풍경", "expect": {"chitchat": False, "orientation": "landscape", "keywords_any": ["city", "cityscape", "street", "town"]}},
]

FORBIDDEN = ("보증", "인증")


def score_intent(intent: dict, expect: dict) -> dict:
    checks = {}
    if "chitchat" in expect:
        checks["chitchat"] = intent["chitchat"] is expect["chitchat"]
    if "orientation" in expect:
        checks["orientation"] = intent.get("orientation") == expect["orientation"]
    if expect.get("purpose"):
        checks["purpose"] = bool(intent.get("purpose"))
    if expect.get("keywords_any"):
        kws = [k.lower() for k in intent["keywords"]]
        checks["keywords"] = any(any(e in k for k in kws) for e in expect["keywords_any"])
    if expect.get("artist_has"):
        checks["artist"] = expect["artist_has"] in (intent.get("artist") or "").lower()
    return checks


def score_answer(answer: str, narrated: int, relaxed: bool) -> dict:
    cited = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    checks = {
        "grounded": all(1 <= n <= narrated for n in cited) and (narrated == 0 or bool(cited)),
        "bilingual": "English:" in answer,
        "no_forbidden_words": not any(w in answer for w in FORBIDDEN),
    }
    if narrated:
        checks["record_guide"] = "근거 기록" in answer
    if relaxed:
        checks["relaxed_notice"] = any(w in answer for w in ("조건", "빼고", "완화"))
    return checks


def run(dry_run: bool) -> dict:
    if dry_run:  # 채점기 점검용 가짜 AI: 첫 번째 사례 기대값을 그대로 돌려준다
        def fake(messages, max_tokens=700, **kwargs):
            if "검색 의도 추출기" in messages[0]["content"]:
                return '{"chitchat": false, "keywords": ["landscape"], "orientation": "portrait", "purpose": "테스트"}'
            return "[1] 테스트 작품입니다. 상업 이용 전 카드의 '근거 기록'을 발급해 두세요.\n\nEnglish: [1] Test."
        llm.chat_completion = fake

    rows = []
    for case in CASES:
        started = time.monotonic()
        row = {"q": case["q"]}
        try:
            intent = chat.extract_intent(case["q"])
            row["intent"] = intent
            row["intent_checks"] = score_intent(intent, case["expect"])
            works, relaxed = chat.find_artworks(intent, limit=6)
            narrated = min(len(works), ANSWER_NARRATION_LIMIT)
            answer = chat.compose_answer(case["q"], works, [], relaxed=relaxed, purpose=intent.get("purpose"))
            row.update(answer=answer, works=len(works), relaxed=relaxed,
                       answer_checks=score_answer(answer, narrated, relaxed))
        except Exception as e:  # noqa: BLE001 — 한 사례 실패가 전체 평가를 멈추지 않게
            row["error"] = f"{type(e).__name__}: {e}"
        row["latency_ms"] = int((time.monotonic() - started) * 1000)
        rows.append(row)

    def rate(key):
        vals = [ok for r in rows for ok in r.get(key, {}).values()]
        return round(100 * sum(vals) / len(vals), 1) if vals else None

    per_check = {}
    for r in rows:
        for key in ("intent_checks", "answer_checks"):
            for name, ok in r.get(key, {}).items():
                per_check.setdefault(name, []).append(ok)
    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "cases": len(rows),
        "errors": sum("error" in r for r in rows),
        "intent_accuracy_pct": rate("intent_checks"),
        "answer_compliance_pct": rate("answer_checks"),
        "per_check_pct": {k: round(100 * sum(v) / len(v), 1) for k, v in sorted(per_check.items())},
        "avg_latency_ms": int(sum(r["latency_ms"] for r in rows) / len(rows)),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="가짜 AI로 채점기만 점검")
    args = parser.parse_args()
    result = run(args.dry_run)
    print(f"사례 {result['cases']}개 · 오류 {result['errors']}개 · 평균 {result['avg_latency_ms']}ms")
    print(f"의도 추출 정확도 {result['intent_accuracy_pct']}% · 답변 규칙 준수율 {result['answer_compliance_pct']}%")
    for name, pct in result["per_check_pct"].items():
        print(f"  {name:20s} {pct}%")
    for r in result["rows"]:
        bad = [k for key in ("intent_checks", "answer_checks") for k, ok in r.get(key, {}).items() if not ok]
        if bad or "error" in r:
            print(f"  ✗ {r['q']}: {r.get('error') or ', '.join(bad)}")
    if not args.dry_run:
        out = ROOT / "data" / "eval" / f"llm-eval-{result['run_at'].replace(':', '')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
