import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import db, guardian  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()


def test_looks_malicious_flags_obvious_patterns():
    assert guardian.looks_malicious("<script>alert(1)</script>")
    assert guardian.looks_malicious("1 UNION SELECT password FROM users")
    assert not guardian.looks_malicious("봄 느낌 풍경화 보여줘")


def test_check_rate_blocks_after_limit(fresh_db):
    for _ in range(3):
        assert guardian.check_rate("bucket:x", limit=3, window_seconds=60)
    assert not guardian.check_rate("bucket:x", limit=3, window_seconds=60)


def test_login_lockout_after_repeated_failures(fresh_db):
    assert not guardian.check_login_lockout("a@b.com")
    for _ in range(5):
        guardian.note_login_failure("a@b.com")
    assert guardian.check_login_lockout("a@b.com")


def test_ai_backoff_after_repeated_rate_limit(fresh_db):
    assert not guardian.is_ai_backed_off()
    for _ in range(3):
        guardian.record_incident("reliability", "AI_RATE_LIMITED", "429", {}, "medium")
        guardian.note_ai_failure("AI_RATE_LIMITED")
    assert guardian.is_ai_backed_off()


def test_daily_digest_skips_when_no_incidents(fresh_db):
    assert guardian.run_daily_digest() == {"analyzed": 0}


def test_daily_digest_analyzes_and_marks_incidents(fresh_db, monkeypatch):
    guardian.record_incident("security", "LOGIN_FAILED", "로그인 실패", {"identifier": "a@b.com"}, "low")

    def fake_chat_completion(messages, max_tokens=700):
        return "요약: 테스트\nURGENCY: low"

    monkeypatch.setattr("app.llm.chat_completion", fake_chat_completion)
    result = guardian.run_daily_digest()
    assert result == {"analyzed": 1, "urgency": "low"}
    rows = db.execute("SELECT diagnosis FROM incidents")
    assert rows[0]["diagnosis"].startswith("요약")


def test_daily_digest_opens_issue_on_high_urgency(fresh_db, monkeypatch):
    guardian.record_incident("security", "BRUTE_FORCE_SUSPECTED", "잠금", {"identifier": "a@b.com"}, "high")

    def fake_chat_completion(messages, max_tokens=700):
        return "요약: 공격 의심\nURGENCY: high"

    opened = {}
    monkeypatch.setattr("app.llm.chat_completion", fake_chat_completion)
    monkeypatch.setattr(guardian, "open_github_issue", lambda title, body: opened.update(title=title, body=body))
    result = guardian.run_daily_digest()
    assert result["urgency"] == "high"
    assert "high" in opened["title"]


def test_daily_digest_handles_ai_failure(fresh_db, monkeypatch):
    guardian.record_incident("reliability", "AI_TIMEOUT", "타임아웃", {}, "low")

    def boom(messages, max_tokens=700):
        raise AIUnavailableError("AI_ERROR", "실패")

    monkeypatch.setattr("app.llm.chat_completion", boom)
    result = guardian.run_daily_digest()
    assert result["analyzed"] == 0 and "error" in result
