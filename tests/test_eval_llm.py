import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import eval_llm  # noqa: E402


def test_intent_scoring():
    intent = {"chitchat": False, "keywords": ["Still life", "fruit"], "artist": None,
              "orientation": "portrait", "purpose": "메뉴판"}
    checks = eval_llm.score_intent(intent, {"chitchat": False, "orientation": "portrait",
                                            "purpose": True, "keywords_any": ["still"]})
    assert all(checks.values())
    assert eval_llm.score_intent(intent, {"orientation": None}) == {"orientation": False}


def test_answer_scoring_catches_hallucinated_citation_and_forbidden_words():
    good = "[1] 좋아요. [2] 좋아요. 사용 전 '근거 기록'을 발급하세요.\n\nEnglish: [1] ok"
    assert all(eval_llm.score_answer(good, narrated=2, relaxed=False).values())
    bad = "[3] 이 작품은 저작권이 보증됩니다."   # 2개만 넘겼는데 [3] 인용, 영어 없음, 금지어
    checks = eval_llm.score_answer(bad, narrated=2, relaxed=False)
    assert not checks["grounded"] and not checks["bilingual"] and not checks["no_forbidden_words"]
    assert eval_llm.score_answer("조건을 빼고 찾았어요. [1] … 근거 기록\nEnglish:", 1, True)["relaxed_notice"]


def test_eval_set_has_20_cases_with_chitchat_and_orientation_coverage():
    assert len(eval_llm.CASES) == 20
    assert sum(c["expect"].get("chitchat") is True for c in eval_llm.CASES) >= 3
    assert {"landscape", "portrait", "square"} <= {c["expect"].get("orientation") for c in eval_llm.CASES}
