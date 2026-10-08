"""타임아웃 25초 통일: 요청 하나는 25초 안에 끝나고, 넘으면 '죄송합니다. 접속자가 많습니다.'로 안내한다."""
import os
import socket
import sys
import urllib.error
from pathlib import Path

import anthropic
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import claude_llm, config, db, llm, records, reqctx  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402

from tests.test_claude_llm import FakeMessages, _response  # noqa: E402


@pytest.fixture(autouse=True)
def no_deadline():
    reqctx.clear_deadline()
    yield
    reqctx.clear_deadline()


def test_every_timeout_is_25_seconds():
    assert config.TIMEOUT_SECONDS == 25
    assert config.LLM_TIMEOUT_SECONDS == 25 and config.LLM_CALL_BUDGET_SECONDS == 25
    assert records.ARCHIVE_REQUEST_SECONDS == 25 and records.ARCHIVE_CHECK_SECONDS == 25
    assert config.BUSY_MESSAGE.startswith("죄송합니다. 접속자가 많습니다.")


def test_remaining_follows_the_request_deadline():
    assert reqctx.remaining(25) == 25  # 요청 밖이면 그대로
    reqctx.start_deadline(10)
    assert 9 < reqctx.remaining(25) <= 10
    reqctx.clear_deadline()
    assert reqctx.remaining(25) == 25


def _fake_client(monkeypatch, messages):
    from types import SimpleNamespace
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(claude_llm, "_get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=messages)))


def test_claude_waits_only_for_what_is_left(monkeypatch):
    messages = FakeMessages(response=_response("답"))
    _fake_client(monkeypatch, messages)
    reqctx.start_deadline(12)
    claude_llm.complete([{"role": "user", "content": "q"}])
    assert 11 < messages.calls[0]["timeout"] <= 12


def test_no_time_left_means_busy_without_calling_ai(monkeypatch):
    messages = FakeMessages(response=_response("답"))
    _fake_client(monkeypatch, messages)
    monkeypatch.delenv("GPT_ASTRA_API_KEY", raising=False)
    reqctx.start_deadline(1)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "q"}])
    assert e.value.code == "AI_TIMEOUT" and str(e.value) == config.BUSY_MESSAGE and not messages.calls


def test_claude_timeout_is_busy_message(monkeypatch):
    messages = FakeMessages(error=anthropic.APITimeoutError(request=None))
    _fake_client(monkeypatch, messages)
    with pytest.raises(AIUnavailableError) as e:
        claude_llm.complete([{"role": "user", "content": "q"}])
    assert e.value.code == "AI_TIMEOUT" and str(e.value) == config.BUSY_MESSAGE


def test_gpt_budget_is_capped_by_request_deadline(monkeypatch):
    seen = []

    def slow(req, timeout):
        seen.append(timeout)
        raise urllib.error.URLError(socket.timeout())
    monkeypatch.setattr(llm.urllib.request, "urlopen", slow)
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "k")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    reqctx.start_deadline(8)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "q"}])
    assert e.value.code == "AI_TIMEOUT" and str(e.value) == config.BUSY_MESSAGE
    assert seen and seen[0] <= 8


def test_turso_timeout_shows_busy(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    def boom(*a, **k):
        raise db.DbTimeout("Turso 응답 시간 초과(25s)")
    monkeypatch.setattr(db, "execute", boom)
    monkeypatch.setattr(db, "execute_many", boom)
    r = TestClient(app).get("/api/me")
    if r.status_code == 503:
        assert r.json()["error"] == {"code": "BUSY", "message": config.BUSY_MESSAGE}
    else:  # /api/me가 DB 없이 끝나면, 예외 처리기를 직접 확인한다
        import asyncio
        from app.main import db_exc
        resp = asyncio.run(db_exc(None, db.DbTimeout("x")))
        assert resp.status_code == 503 and b"BUSY" in resp.body


def test_turso_socket_timeout_becomes_db_timeout(monkeypatch):
    def slow(req, timeout):
        assert timeout == 25
        raise TimeoutError()
    monkeypatch.setattr(db.urllib.request, "urlopen", slow)
    with pytest.raises(db.DbTimeout):
        db._turso_pipeline("https://x", [("SELECT 1", ())])


def test_background_work_is_not_bound_by_request_deadline():
    from app.main import _after_response
    seen = []
    reqctx.start_deadline(0)
    _after_response(lambda: seen.append(reqctx.remaining(25)))
    assert seen == [25]
