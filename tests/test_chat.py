import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import chat, llm  # noqa: E402


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
