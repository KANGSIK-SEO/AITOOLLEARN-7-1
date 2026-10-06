"""가디언 장애·위협 감지 로직의 경계값·만료·오탐 단위 테스트.

기본 흐름(차단되는가)은 tests/test_guardian.py에 있고, 여기서는 "언제 차단되지 않아야 하는가"와
시간 창(window)이 지나면 풀리는지를 확인한다. 시간은 DB에 과거 시각을 직접 넣어 흉내 낸다.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import db, guardian, llm  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def _incident(code, category="reliability", created_at=None, context=None):
    db.execute("INSERT INTO incidents (category, code, message, context, severity, created_at) "
               "VALUES (?, ?, 'm', ?, 'low', ?)",
               (category, code, json.dumps(context or {}, ensure_ascii=False), created_at or _ago(seconds=1)))


def _codes():
    return [r["code"] for r in db.execute("SELECT code FROM incidents ORDER BY id")]


# ---- 악성 입력 감지 ----
@pytest.mark.parametrize("text", [
    "<SCRIPT>alert(1)</SCRIPT>",
    "javascript:alert(1)",
    '<img src=x onerror = "x()">',
    "1 union    select * from users",
    "'; DROP TABLE users; --",
    "exec (xp_cmdshell)",
])
def test_looks_malicious_detects_each_pattern(text):
    assert guardian.looks_malicious(text)


@pytest.mark.parametrize("text", [
    "모네의 수련 작품 보여줘",
    "Execute a search for sunflowers",   # exec 뒤에 괄호가 없으면 정상
    "the union of color and light",       # union만 있고 select가 없음
    "select a painting with drops of rain",
    "자바스크립트처럼 화려한 색감",
])
def test_looks_malicious_has_no_false_positive_on_normal_questions(text):
    assert not guardian.looks_malicious(text)


# ---- IP/버킷 레이트리밋 ----
def test_check_rate_resets_after_window(fresh_db):
    for _ in range(2):
        assert guardian.check_rate("b", limit=2, window_seconds=60)
    assert not guardian.check_rate("b", limit=2, window_seconds=60)
    db.execute("UPDATE rate_counters SET window_start = ? WHERE bucket = 'b'", (_ago(seconds=61),))
    assert guardian.check_rate("b", limit=2, window_seconds=60)  # 창이 지나면 다시 1부터
    assert db.execute("SELECT count FROM rate_counters WHERE bucket = 'b'")[0]["count"] == 1


def test_check_rate_buckets_are_independent(fresh_db):
    assert guardian.check_rate("login:1.1.1.1", limit=1, window_seconds=60)
    assert not guardian.check_rate("login:1.1.1.1", limit=1, window_seconds=60)
    assert guardian.check_rate("login:2.2.2.2", limit=1, window_seconds=60)


def test_check_rate_fails_open_on_db_error(monkeypatch, caplog):
    """DB 장애로 정상 사용자까지 막지 않는다 (가용성 우선)."""
    def broken(*a, **k):
        raise db.DbError("down")
    monkeypatch.setattr(db, "execute", broken)
    with caplog.at_level(logging.ERROR, logger="app.guardian"):
        assert guardian.check_rate("b", limit=1, window_seconds=60) is True
    assert any("rate_check_failure bucket=b" in r.getMessage() for r in caplog.records)


# ---- AI 429 반복 → 자동 백오프 ----
def test_ai_backoff_ignores_non_rate_limit_failures(fresh_db):
    for _ in range(5):
        _incident("AI_TIMEOUT")
        guardian.note_ai_failure("AI_TIMEOUT")
    assert not guardian.is_ai_backed_off()


def test_ai_backoff_needs_three_recent_429s(fresh_db):
    for _ in range(2):
        _incident("AI_RATE_LIMITED")
        guardian.note_ai_failure("AI_RATE_LIMITED")
    assert not guardian.is_ai_backed_off()
    _incident("AI_RATE_LIMITED")
    guardian.note_ai_failure("AI_RATE_LIMITED")
    assert guardian.is_ai_backed_off()


def test_ai_backoff_ignores_429s_older_than_five_minutes(fresh_db):
    for _ in range(5):
        _incident("AI_RATE_LIMITED", created_at=_ago(minutes=6))
    _incident("AI_RATE_LIMITED")
    guardian.note_ai_failure("AI_RATE_LIMITED")
    assert not guardian.is_ai_backed_off()


def test_ai_backoff_records_auto_action_and_expires(fresh_db):
    for _ in range(3):
        _incident("AI_RATE_LIMITED")
    guardian.note_ai_failure("AI_RATE_LIMITED")
    row = db.execute("SELECT severity, auto_action FROM incidents WHERE code = 'AI_AUTO_BACKOFF'")[0]
    assert row == {"severity": "medium", "auto_action": "ai_backoff"}
    db.execute("UPDATE runtime_flags SET value = ? WHERE key = 'ai_backoff_until'", (_ago(seconds=1),))
    assert not guardian.is_ai_backed_off()


# ---- 로그인 실패 반복 → 계정 잠금 ----
def test_login_lockout_needs_five_failures_within_ten_minutes(fresh_db):
    for _ in range(4):
        guardian.note_login_failure("a@b.com")
    assert not guardian.check_login_lockout("a@b.com")
    guardian.note_login_failure("a@b.com")
    assert guardian.check_login_lockout("a@b.com")
    assert _codes().count("BRUTE_FORCE_SUSPECTED") == 1


def test_login_lockout_ignores_old_failures(fresh_db):
    for _ in range(10):
        _incident("LOGIN_FAILED", "security", _ago(minutes=11), {"identifier": "a@b.com"})
    guardian.note_login_failure("a@b.com")
    assert not guardian.check_login_lockout("a@b.com")


def test_login_lockout_is_per_identifier(fresh_db):
    for _ in range(5):
        guardian.note_login_failure("victim@x.com")
    assert guardian.check_login_lockout("victim@x.com")
    assert not guardian.check_login_lockout("other@x.com")


def test_login_lockout_expires(fresh_db):
    for _ in range(5):
        guardian.note_login_failure("a@b.com")
    db.execute("UPDATE runtime_flags SET value = ? WHERE key = 'lockout:a@b.com'", (_ago(seconds=1),))
    assert not guardian.check_login_lockout("a@b.com")


# ---- 사건 기록 ----
def test_record_incident_returns_none_and_logs_on_db_error(monkeypatch, caplog):
    def broken(*a, **k):
        raise db.DbError("down")
    monkeypatch.setattr(db, "execute", broken)
    with caplog.at_level(logging.ERROR, logger="app.guardian"):
        assert guardian.record_incident("reliability", "AI_TIMEOUT", "x") is None
    assert any("incident_save_failure code=AI_TIMEOUT" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("headers, host, expected", [
    ({"x-forwarded-for": "203.0.113.5, 10.0.0.1"}, "10.0.0.1", "203.0.113.5"),  # 프록시 뒤 원래 IP
    ({}, "198.51.100.7", "198.51.100.7"),
    ({}, None, "unknown"),
])
def test_client_ip(headers, host, expected):
    request = SimpleNamespace(headers=headers, client=SimpleNamespace(host=host) if host else None)
    assert guardian.client_ip(request) == expected


# ---- 일일 점검: 긴급도 판정 ----
@pytest.mark.parametrize("diagnosis, urgency, opens_issue", [
    ("요약...\nURGENCY: high", "high", True),
    ("요약...\nurgency: Medium", "medium", True),
    ("요약...\nURGENCY: low", "low", False),
    ("요약만 있고 긴급도 줄이 없음", "low", False),  # 형식이 깨지면 이슈를 남발하지 않도록 low
])
def test_daily_digest_urgency_parsing(fresh_db, monkeypatch, diagnosis, urgency, opens_issue):
    _incident("AI_TIMEOUT")
    issues = []
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: diagnosis)
    monkeypatch.setattr(guardian, "open_github_issue", lambda title, body: issues.append(title))
    assert guardian.run_daily_digest() == {"analyzed": 1, "urgency": urgency}
    assert bool(issues) is opens_issue


def test_daily_digest_does_not_reanalyze(fresh_db, monkeypatch):
    _incident("AI_TIMEOUT")
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: "URGENCY: low")
    assert guardian.run_daily_digest()["analyzed"] == 1
    assert guardian.run_daily_digest() == {"analyzed": 0}  # 이미 diagnosis가 채워진 사건은 제외
