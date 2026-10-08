"""[가디언] 실시간 경보 — SERVER_ERROR (/api/guardian/scan) 재현·수정 확인.

1분 점검(guardian.scan)의 한 단계가 DB·AI 오류가 아닌 예상 못 한 예외를 내면, 예전에는 점검 전체가 멈추고
/api/guardian/scan이 500(SERVER_ERROR)으로 끝나 '어느 단계가 왜' 실패했는지 사건에 남지 않았다.
수정 후에는 단계별로 격리되어 나머지 점검은 계속되고, 단계 이름·예외 종류가 사건(SCAN_STEP_FAILED)과 응답에 남는다.
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-autofix-scan-step-0123456789")
    from app import db
    db.reset_for_tests()
    yield
    db.reset_for_tests()


@pytest.fixture
def broken_probe(temp_db, monkeypatch):
    """AI 확인 단계가 예상 못 한 예외(RuntimeError)로 터지는 상황. AI·GitHub는 가짜로 바꾼다."""
    from app import guardian
    issues = []
    monkeypatch.setattr(guardian.llm, "chat_completion", lambda *a, **k: "요약: 테스트 진단\nURGENCY: low")
    monkeypatch.setattr(guardian, "open_github_issue", lambda *a, **k: issues.append(a))

    def exploding_probe():
        raise RuntimeError("probe exploded unexpectedly")

    monkeypatch.setattr(guardian, "probe_ai", exploding_probe)
    return issues


def test_scan_survives_unexpected_step_failure(broken_probe):
    from app import db, guardian

    result = guardian.scan()   # 수정 전: RuntimeError가 그대로 올라와 점검 전체가 실패했다

    assert result["ai"] == {"error": "RuntimeError"}
    assert result["traffic"] == {"watched": 0}            # 나머지 단계는 계속 돈다
    assert result["capacity"]["requests_5m"] == 0
    rows = db.execute("SELECT code, severity, context FROM incidents WHERE code = 'SCAN_STEP_FAILED'")
    assert len(rows) == 1
    assert rows[0]["severity"] == "high"
    ctx = json.loads(rows[0]["context"])
    assert ctx["step"] == "ai"
    assert ctx["error"] == "RuntimeError"
    assert "probe exploded" in ctx["detail"]


def test_scan_endpoint_reports_step_failure_without_server_error(broken_probe, monkeypatch):
    from app import db, main

    monkeypatch.setattr(main, "CRON_SECRET", "cron-secret-for-test")
    client = TestClient(main.app)
    res = client.get("/api/guardian/scan", headers={"Authorization": "Bearer cron-secret-for-test"})

    assert res.status_code == 503                          # 수정 전: 500 SERVER_ERROR
    body = res.json()
    assert body["status"] == "degraded"
    assert body["ai"] == {"error": "RuntimeError"}
    assert body["traffic"]["watched"] == 0
    codes = {r["code"] for r in db.execute("SELECT code FROM incidents")}
    assert "SCAN_STEP_FAILED" in codes
    assert "SERVER_ERROR" not in codes


def test_scan_endpoint_rejects_without_cron_secret(temp_db, monkeypatch):
    """수정이 크론 인증을 건드리지 않았는지 — 비밀 없이 부르면 여전히 401."""
    from app import main

    monkeypatch.setattr(main, "CRON_SECRET", "cron-secret-for-test")
    client = TestClient(main.app)
    res = client.get("/api/guardian/scan")
    assert res.status_code == 401
