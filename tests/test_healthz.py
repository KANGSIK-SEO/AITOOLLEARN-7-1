import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import art, db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    return TestClient(app)


def test_healthz_ok_when_all_dependencies_respond(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"db", "art_db"}
    assert all(c["status"] == "ok" and c["latency_ms"] >= 0 for c in body["checks"].values())


def test_healthz_503_when_user_db_fails(client, monkeypatch):
    def broken(*a, **k):
        raise db.DbError("Turso 연결 실패: https://secret-db.turso.io timed out")
    monkeypatch.setattr(db, "execute", broken)
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded",
                        "checks": {"db": {"status": "error"}, "art_db": r.json()["checks"]["art_db"]}}
    assert r.json()["checks"]["art_db"]["status"] == "ok"
    assert "turso.io" not in r.text  # 접속 주소를 노출하지 않는다


def test_healthz_503_when_art_db_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(art, "ART_DB", tmp_path / "missing.db")
    r = client.get("/healthz")
    assert r.status_code == 503 and r.json()["checks"]["art_db"] == {"status": "error"}
    assert r.json()["checks"]["db"]["status"] == "ok"
    assert "missing.db" not in r.text


def test_healthz_logs_failure_detail(client, monkeypatch, tmp_path, caplog):
    import logging
    monkeypatch.setattr(art, "ART_DB", tmp_path / "missing.db")
    with caplog.at_level(logging.ERROR, logger="app"):
        client.get("/healthz")
    assert any(r.getMessage().startswith("healthz_check_failed check=art_db") for r in caplog.records)


def test_healthz_needs_no_login_and_does_not_call_ai(client, monkeypatch):
    from app import llm
    def must_not_call(*a, **k):
        raise AssertionError("healthz는 AI를 호출하지 않아야 한다")
    monkeypatch.setattr(llm, "chat_completion", must_not_call)
    assert client.get("/healthz").status_code == 200


def test_api_health_is_unchanged(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_art_ping_raises_on_unreadable_db(monkeypatch, tmp_path):
    monkeypatch.setattr(art, "ART_DB", tmp_path / "missing.db")
    with pytest.raises(sqlite3.Error):
        art.ping()
