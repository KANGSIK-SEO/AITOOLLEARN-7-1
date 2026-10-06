import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import art, chat, llm  # noqa: E402


def _work(i):
    return {"title": f"Work {i}", "artist": "Artist", "date_display": "1900",
            "medium": "oil", "license": "CC0", "source": "met"}


def test_compose_answer_notes_extra_works_beyond_narration_limit(monkeypatch):
    """100개 중 6개만 LLM에 넘기고, 나머지는 카드로만 보여준다는 안내를 덧붙인다."""
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: "[1] 설명")
    answer = chat.compose_answer("질문", [_work(i) for i in range(10)], [])
    assert "그 외에도 관련 작품 4개를 더 찾았어요" in answer


def test_compose_answer_has_no_extra_note_within_narration_limit(monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: "[1] 설명")
    answer = chat.compose_answer("질문", [_work(i) for i in range(3)], [])
    assert "그 외에도" not in answer


def test_compose_answer_passes_relax_note_to_prompt(monkeypatch):
    seen = {}

    def fake(messages, max_tokens=700):
        seen["prompt"] = messages[1]["content"]
        return "[1] 설명"

    monkeypatch.setattr(llm, "chat_completion", fake)
    chat.compose_answer("질문", [_work(0)], [], relaxed=True)
    assert "조건을 빼고" in seen["prompt"]


def test_compose_answer_no_relax_note_by_default(monkeypatch):
    seen = {}

    def fake(messages, max_tokens=700):
        seen["prompt"] = messages[1]["content"]
        return "[1] 설명"

    monkeypatch.setattr(llm, "chat_completion", fake)
    chat.compose_answer("질문", [_work(0)], [])
    assert "[완화 안내]\n(없음)" in seen["prompt"]


def test_find_artworks_reports_relaxed_when_constraints_dropped(monkeypatch):
    calls = []

    def fake_search(keywords, artist=None, year_from=None, year_to=None, limit=6):
        calls.append(artist)
        return [] if artist else [_work(0)]

    monkeypatch.setattr(art, "search", fake_search)
    intent = {"chitchat": False, "keywords": ["spring"], "artist": "Monet", "year_from": None, "year_to": None}
    works, relaxed = chat.find_artworks(intent)
    assert relaxed is True and len(works) == 1
    assert calls == ["Monet", None]


def test_find_artworks_not_relaxed_when_first_search_succeeds(monkeypatch):
    monkeypatch.setattr(art, "search", lambda *a, **k: [_work(0)])
    intent = {"chitchat": False, "keywords": ["spring"], "artist": "Monet", "year_from": None, "year_to": None}
    works, relaxed = chat.find_artworks(intent)
    assert relaxed is False and len(works) == 1


def test_find_artworks_chitchat_returns_empty_not_relaxed():
    works, relaxed = chat.find_artworks({"chitchat": True, "keywords": [], "artist": None,
                                         "year_from": None, "year_to": None})
    assert works == [] and relaxed is False


# ---- _parse_intent: 모델 출력이 깨지거나 타입이 틀려도 안전한 기본값으로 ----
EMPTY_INTENT = {"chitchat": False, "keywords": [], "artist": None, "year_from": None, "year_to": None}


@pytest.mark.parametrize("raw", [
    "",
    "죄송하지만 이해하지 못했어요.",
    '{"keywords": ["sea",',          # 잘린 JSON
    '{keywords: [sea]}',             # 따옴표 없는 JSON
    "[1, 2, 3]",                     # 객체가 아닌 JSON
])
def test_parse_intent_broken_json_falls_back_to_empty(raw):
    assert chat._parse_intent(raw) == EMPTY_INTENT


def test_parse_intent_extracts_json_wrapped_in_text_and_code_fence():
    raw = '물론이죠!\n```json\n{"chitchat": false, "keywords": ["sea", "storm"], "artist": "Turner", ' \
          '"year_from": 1800, "year_to": 1850}\n```\n참고: {추가 설명}'
    assert chat._parse_intent(raw) == {"chitchat": False, "keywords": ["sea", "storm"], "artist": "Turner",
                                       "year_from": 1800, "year_to": 1850}


@pytest.mark.parametrize("value, expected", [
    (True, True), ("true", True), (" TRUE ", True),
    (False, False), ("false", False), ("no", False), (1, False), (None, False),
])
def test_parse_intent_chitchat_only_accepts_explicit_true(value, expected):
    """문자열 "false"가 bool()로 참이 되면 작품 검색 자체를 건너뛴다 — 회귀 방지."""
    assert chat._parse_intent(json.dumps({"chitchat": value}))["chitchat"] is expected


def test_parse_intent_type_mismatch_keywords():
    out = chat._parse_intent('{"keywords": [null, "sea", 1, ["x"], "", "  sky  "]}')
    assert out["keywords"] == ["sea", "sky"]
    assert chat._parse_intent('{"keywords": "sunset"}')["keywords"] == ["sunset"]
    assert chat._parse_intent('{"keywords": {"a": 1}}')["keywords"] == []
    assert len(chat._parse_intent('{"keywords": ["a","b","c","d","e","f","g","h"]}')["keywords"]) == 6


@pytest.mark.parametrize("value, expected", [
    (1850, 1850), ("1850", 1850), (-500, -500), (True, None), (False, None),
    (1850.5, None), ("1850s", None), (None, None), ([1850], None),
])
def test_parse_intent_type_mismatch_years(value, expected):
    out = chat._parse_intent(json.dumps({"year_from": value, "year_to": value}))
    assert out["year_from"] == expected and out["year_to"] == expected
    assert type(out["year_from"]) is (int if expected is not None else type(None))


@pytest.mark.parametrize("value, expected", [
    ("Monet", "Monet"), ("  Monet ", "Monet"), ("", None), (123, None), (["Monet"], None), (None, None),
])
def test_parse_intent_type_mismatch_artist(value, expected):
    assert chat._parse_intent(json.dumps({"artist": value}))["artist"] == expected
