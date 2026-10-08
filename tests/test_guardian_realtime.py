"""가디언 실시간 감시: 의심 행동이 쌓이면 IP를 바로 차단하고, 장애가 몰리면 즉시 분석·이슈를 낸다."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, guardian, llm  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def issues(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    opened = []
    monkeypatch.setattr(guardian, "open_github_issue", lambda title, body: opened.append((title, body)))
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: "요약: 공격 의심\nURGENCY: high")
    return opened


def _codes():
    return [r["code"] for r in db.execute("SELECT code FROM incidents ORDER BY id")]


def test_probing_attack_paths_blocks_ip_and_alerts_now(issues):
    client = TestClient(app)
    for path in ("/.env", "/wp-admin/", "/phpmyadmin/index.php"):
        assert client.get(path).status_code == 404
    assert client.get("/").status_code == 403  # 세 번째에 차단 → 이제 모든 요청이 막힌다
    assert client.get("/").json()["error"]["code"] == "BLOCKED"
    assert "IP_BLOCKED" in _codes()
    assert issues and issues[0][0].startswith("[가디언] 실시간 경보")  # 응답 뒤 즉시 분석 → 이슈


def test_normal_pages_are_not_treated_as_probes(issues):
    client = TestClient(app)
    for _ in range(5):
        assert client.get("/").status_code == 200
        client.get("/api/health")
    assert "PROBE" not in _codes() and not issues


def test_repeated_malicious_chat_input_blocks_ip(issues, monkeypatch):
    client = TestClient(app)
    client.post("/api/auth/signup", json={"email": "m@t.com", "password": "password123"})
    for _ in range(3):
        assert client.post("/api/chat", json={"message": "<script>alert(1)</script>"}).status_code == 400
    assert client.post("/api/chat", json={"message": "봄 풍경"}).status_code == 403


def test_one_ip_trying_many_accounts_is_blocked(issues):
    client = TestClient(app)
    for i in range(10):
        client.post("/api/auth/login", json={"email": f"user{i}@t.com", "password": "wrongpass1"})
    assert client.post("/api/auth/login", json={"email": "x@t.com", "password": "wrongpass1"}).status_code == 403


def test_block_expires(issues):
    guardian.block_ip("203.0.113.9", "test")
    assert guardian.is_blocked("203.0.113.9")
    db.execute("UPDATE runtime_flags SET value = '2000-01-01T00:00:00+00:00' WHERE key = 'ip_block:203.0.113.9'")
    guardian._blocks["loaded_at"] = 0  # 30초 기억을 건너뛰고 다시 읽게 한다
    assert not guardian.is_blocked("203.0.113.9")


def test_error_spike_triggers_one_triage_within_cooldown(issues):
    for _ in range(25):
        guardian.record_incident("reliability", "AI_TIMEOUT", "x")
    assert len(issues) == 1  # 10건째에 한 번, 이후 10분 동안은 다시 내지 않는다


def test_triage_still_alerts_when_ai_is_down(issues, monkeypatch):
    def down(*a, **k):
        raise AIUnavailableError("AI_ERROR", "down")
    monkeypatch.setattr(llm, "chat_completion", down)
    guardian.record_incident("reliability", "DB_ERROR", "x", severity="high")
    assert issues and "AI 진단 실패" in issues[0][0] and "reliability/DB_ERROR" in issues[0][1]


def test_scan_endpoint_requires_cron_secret(issues, monkeypatch):
    client = TestClient(app)
    assert client.post("/api/guardian/scan").status_code == 401


def test_scan_alerts_on_recent_high_incident(issues, monkeypatch):
    monkeypatch.setattr(guardian, "request_triage", lambda reason: None)  # 기록 순간의 분석은 빼고 scan만 본다
    guardian.record_incident("security", "BRUTE_FORCE_SUSPECTED", "x", severity="high")
    result = guardian.scan()
    assert result["high_5m"] == 1 and issues


def test_client_ip_prefers_vercel_header():
    from types import SimpleNamespace
    req = SimpleNamespace(headers={"x-vercel-forwarded-for": "198.51.100.1",
                                   "x-forwarded-for": "1.2.3.4"}, client=None)
    assert guardian.client_ip(req) == "198.51.100.1"
