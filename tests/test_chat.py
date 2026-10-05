import os
import sys
from pathlib import Path

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


def test_parse_intent_orientation():
    from app.chat import _parse_intent
    assert _parse_intent('{"keywords": ["sea"], "orientation": "landscape"}')["orientation"] == "landscape"
    assert _parse_intent('{"keywords": ["sea"], "orientation": "diagonal"}')["orientation"] is None
    assert _parse_intent('{"keywords": ["sea"]}')["orientation"] is None
