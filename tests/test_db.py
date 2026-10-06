import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import db  # noqa: E402


@pytest.fixture()
def local_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    db.ensure_schema()


def _slow_logs(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("db_slow_query")]


def test_fast_query_is_not_logged(local_db, monkeypatch, caplog):
    monkeypatch.setattr(db, "SLOW_QUERY_MS", 10_000)
    with caplog.at_level(logging.WARNING, logger="app.db"):
        db.execute("SELECT 1 AS x")
    assert _slow_logs(caplog) == []


def test_slow_query_is_logged_with_latency_and_compact_sql(local_db, monkeypatch, caplog):
    monkeypatch.setattr(db, "SLOW_QUERY_MS", 0)
    with caplog.at_level(logging.WARNING, logger="app.db"):
        db.execute("SELECT id,\n        email\n   FROM users WHERE email = ?", ("secret@x.com",))
    (msg,) = _slow_logs(caplog)
    assert "backend=local_sqlite ok=True" in msg
    assert "sql=SELECT id, email FROM users WHERE email = ?" in msg
    assert "latency_ms=" in msg


def test_slow_query_log_never_contains_params(local_db, monkeypatch, caplog):
    monkeypatch.setattr(db, "SLOW_QUERY_MS", 0)
    with caplog.at_level(logging.WARNING, logger="app.db"):
        db.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                   ("secret@x.com", "scrypt$salt$hash", "2026-10-06"))
    assert all("secret@x.com" not in m and "scrypt$" not in m for m in _slow_logs(caplog))


def test_failed_slow_query_is_logged_and_still_raises(local_db, monkeypatch, caplog):
    monkeypatch.setattr(db, "SLOW_QUERY_MS", 0)
    with caplog.at_level(logging.WARNING, logger="app.db"), pytest.raises(db.DbError):
        db.execute("SELECT * FROM no_such_table")
    assert any("ok=False" in m and "no_such_table" in m for m in _slow_logs(caplog))


def test_long_sql_is_truncated(local_db, monkeypatch, caplog):
    monkeypatch.setattr(db, "SLOW_QUERY_MS", 0)
    long_sql = "SELECT " + ", ".join(f"{i} AS c{i}" for i in range(100))
    with caplog.at_level(logging.WARNING, logger="app.db"):
        db.execute(long_sql)
    (msg,) = _slow_logs(caplog)
    assert msg.endswith("…") and len(msg.split("sql=", 1)[1]) == db._SQL_LOG_MAX + 1


def test_turso_backend_latency_is_measured(monkeypatch, caplog):
    """Turso HTTP 왕복이 느려지면 backend=turso로 기록된다."""
    import time
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setattr(db, "SLOW_QUERY_MS", 50)

    def slow_turso(base, sql, params):
        time.sleep(0.06)
        return [{"x": 1}]

    monkeypatch.setattr(db, "_turso_execute", slow_turso)
    with caplog.at_level(logging.WARNING, logger="app.db"):
        assert db._raw_execute("SELECT 1 AS x") == [{"x": 1}]
    (msg,) = _slow_logs(caplog)
    assert "backend=turso ok=True" in msg and int(msg.split("latency_ms=")[1].split()[0]) >= 50
