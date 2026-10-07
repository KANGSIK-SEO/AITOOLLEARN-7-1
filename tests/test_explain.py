"""설명 에이전트(/api/explain) 오류 메시지 테스트."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, explain  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402
from app.main import app  # noqa: E402

SECRET = "peer-review-link"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setenv("EXPLAIN_AGENT_SECRET", SECRET)
    monkeypatch.setattr(explain, "_context_cache", "(코드)")
    db.reset_for_tests()
    return TestClient(app)


def ask(client, question="비밀번호는 어떻게 저장하나요?", secret=SECRET):
    return client.post("/api/explain", json={"question": question, "secret": secret})


def _fail_with(monkeypatch, code, message):
    def boom(*a, **k):
        raise AIUnavailableError(code, message)
    monkeypatch.setattr(explain, "chat_completion", boom)


def test_success_returns_answer(client, monkeypatch):
    monkeypatch.setattr(explain, "chat_completion", lambda *a, **k: "app/auth.py의 hash_password에서 scrypt로...")
    assert ask(client).json() == {"answer": "app/auth.py의 hash_password에서 scrypt로..."}


def test_missing_ai_key_does_not_leak_env_var_name(client, monkeypatch, caplog):
    import logging
    _fail_with(monkeypatch, "AI_KEY_MISSING", "GPT_ASTRA_API_KEY가 설정되지 않았습니다.")
    with caplog.at_level(logging.WARNING, logger="app"):
        r = ask(client)
    assert r.status_code == 503 and r.json()["error"]["code"] == "AI_KEY_MISSING"
    assert "GPT_ASTRA_API_KEY" not in r.text and "발표자에게 알려 주세요" in r.text
    assert any("GPT_ASTRA_API_KEY" in rec.getMessage() for rec in caplog.records)  # 원인은 로그에 남는다


@pytest.mark.parametrize("code, status, hint", [
    ("AI_TIMEOUT", 504, "구체적으로"),
    ("AI_RATE_LIMITED", 429, "1분쯤 뒤에"),
    ("AI_ERROR", 502, "한 번 더 보내"),
    ("SOMETHING_NEW", 502, "한 번 더 보내"),  # 모르는 코드도 기본 안내
])
def test_ai_errors_keep_code_and_status_but_explain_what_to_do(client, monkeypatch, code, status, hint):
    _fail_with(monkeypatch, code, "internal detail from provider")
    r = ask(client)
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert hint in r.json()["error"]["message"] and "internal detail" not in r.text


def test_context_read_failure_is_503_explain_unavailable(client, monkeypatch):
    monkeypatch.setattr(explain, "_context_cache", None)

    def unreadable(*a, **k):
        raise PermissionError("/var/task/app/main.py")

    monkeypatch.setattr(Path, "read_text", unreadable)
    r = ask(client)
    assert r.status_code == 503 and r.json()["error"]["code"] == "EXPLAIN_UNAVAILABLE"
    assert "/var/task" not in r.text


def test_wrong_link_message_mentions_link_not_password(client):
    r = ask(client, secret="wrong")
    assert r.status_code == 401 and "링크" in r.json()["error"]["message"]
    assert "암호" not in r.json()["error"]["message"]


def test_too_long_question_shows_current_length(client):
    r = ask(client, question="가" * 501)
    assert r.json()["error"]["code"] == "MESSAGE_TOO_LONG" and "501자" in r.json()["error"]["message"]


def test_rate_limit_message_states_the_limit(client, monkeypatch):
    from app import guardian
    monkeypatch.setattr(guardian, "check_rate", lambda *a, **k: False)
    r = ask(client)
    assert r.status_code == 429 and "1시간에 30개" in r.json()["error"]["message"]
