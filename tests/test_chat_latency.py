"""chat_stage 로그: 단계별 소요시간이 request_id와 함께 남는지."""
import logging
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import art, chat, db, llm  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402
from app.main import app  # noqa: E402

STAGE_RE = re.compile(r"^chat_stage stage=(\w+) request_id=(\S+) latency_ms=(\d+) ok=(True|False)$")


def _stages(caplog):
    return [STAGE_RE.match(r.getMessage()).groups() for r in caplog.records
            if r.getMessage().startswith("chat_stage")]


def _intent(chitchat=False):
    return ('{"chitchat": %s, "keywords": ["spring"], "artist": null, "year_from": null, "year_to": null}'
            % ("true" if chitchat else "false"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    c = TestClient(app)
    c.post("/api/auth/signup", json={"email": "a@b.com", "password": "password123"})
    return c


def test_each_stage_logs_latency_with_the_response_request_id(client, monkeypatch, caplog):
    monkeypatch.setattr(llm, "chat_completion",
                        lambda m, **k: _intent() if "검색 의도 추출기" in m[0]["content"] else "[1] 답변")
    with caplog.at_level(logging.INFO, logger="app.chat"):
        r = client.post("/api/chat", json={"message": "봄 풍경"})
    rid = r.json()["request_id"]
    stages = _stages(caplog)
    assert [s[0] for s in stages] == ["intent", "search", "answer"]
    assert all(s[1] == rid and s[3] == "True" for s in stages)


def test_slow_stage_shows_up_in_its_own_latency(monkeypatch, caplog):
    """검색이 느리면 search 단계의 latency_ms가 커진다 (어디가 느린지 구분 가능)."""
    import time

    def slow_search(*a, **k):
        time.sleep(0.05)
        return [{"id": 1}]

    monkeypatch.setattr(art, "search", slow_search)
    with caplog.at_level(logging.INFO, logger="app.chat"):
        chat.find_artworks({"chitchat": False, "keywords": ["x"], "artist": None, "year_from": None, "year_to": None},
                           request_id="abcd1234")
    ((stage, rid, ms, ok),) = _stages(caplog)
    assert (stage, rid, ok) == ("search", "abcd1234", "True") and int(ms) >= 50


def test_failed_stage_is_logged_with_ok_false_and_reraises(monkeypatch, caplog):
    def timeout(*a, **k):
        raise AIUnavailableError("AI_TIMEOUT", "x")

    monkeypatch.setattr(llm, "chat_completion", timeout)
    with caplog.at_level(logging.INFO, logger="app.chat"), pytest.raises(AIUnavailableError):
        chat.extract_intent("질문", request_id="r1")
    assert _stages(caplog)[0][0::3] == ("intent", "False")


def test_chitchat_skips_search_stage(client, monkeypatch, caplog):
    monkeypatch.setattr(llm, "chat_completion",
                        lambda m, **k: _intent(chitchat=True) if "검색 의도 추출기" in m[0]["content"] else "안녕하세요")
    with caplog.at_level(logging.INFO, logger="app.chat"):
        client.post("/api/chat", json={"message": "안녕"})
    assert [s[0] for s in _stages(caplog)] == ["intent", "answer"]


def test_request_id_defaults_to_dash_when_called_directly(monkeypatch, caplog):
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: _intent())
    with caplog.at_level(logging.INFO, logger="app.chat"):
        chat.extract_intent("질문")
    assert _stages(caplog)[0][1] == "-"
