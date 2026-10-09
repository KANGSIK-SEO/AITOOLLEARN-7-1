"""가디언 실시간 감시: 의심 행동이 쌓이면 IP를 바로 차단하고, 장애가 몰리면 즉시 분석·이슈를 낸다."""
import json
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
    monkeypatch.setattr(guardian, "open_github_issue", lambda title, body, labels=None: opened.append((title, body, labels)))
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


def test_scanner_is_blocked_and_its_paths_are_learned(issues):
    scanner = TestClient(app, headers={"x-vercel-forwarded-for": "203.0.113.50"})
    paths = [f"/old-backup-{i}" for i in range(15)]
    for path in paths:
        scanner.get(path)
    assert scanner.get("/").status_code == 403  # 없는 주소 15번 → 차단
    assert "PROBE_PATHS_LEARNED" in _codes()

    # 다른 IP가 배운 주소를 두드리면 처음부터 공격 경로로 취급된다
    other = TestClient(app, headers={"x-vercel-forwarded-for": "198.51.100.77"})
    for path in paths[:3]:
        assert other.get(path).status_code == 404
    assert other.get("/").status_code == 403


def test_real_routes_are_never_learned(issues):
    client = TestClient(app, headers={"x-vercel-forwarded-for": "203.0.113.60"})
    for i in range(20):
        client.get(f"/records/PD-0000-0000-{i:04d}")   # 앱이 404를 주는 진짜 경로
    assert "PROBE_PATHS_LEARNED" not in _codes()
    assert client.get("/").status_code == 200


def test_first_customer_facing_error_is_diagnosed_immediately(issues):
    guardian.record_incident("reliability", "AI_TIMEOUT", "고객 질문에 AI가 답하지 못함")
    assert len(issues) == 1 and "AI_TIMEOUT" in issues[0][0]


def test_same_problem_waits_but_a_different_problem_is_diagnosed(issues):
    guardian.record_incident("reliability", "AI_TIMEOUT", "x")
    guardian.record_incident("reliability", "AI_TIMEOUT", "x")
    assert len(issues) == 1                     # 같은 종류는 30분 동안 다시 진단하지 않는다
    db.execute("UPDATE runtime_flags SET value = '2000-01-01T00:00:00+00:00' WHERE key = 'triage_cooldown_until'")
    guardian.record_incident("reliability", "DB_ERROR", "x", severity="high")
    assert len(issues) == 2 and "DB_ERROR" in issues[1][0]   # 다른 문제는 (2분 간격 뒤) 바로 진단


def test_refusals_are_not_treated_as_outages(issues):
    guardian.record_incident("reliability", "AI_REFUSED", "x")
    assert not issues


def _verdict(monkeypatch, verdict: str, seen: list | None = None):
    def fake(messages, **kwargs):
        if seen is not None:
            seen.append((messages, kwargs))
        return verdict
    monkeypatch.setattr(llm, "chat_completion", fake)


def test_requests_are_logged_for_the_ai_watch(issues):
    client = TestClient(app)
    client.get("/?q=봄")
    client.get("/healthz")
    rows = db.execute("SELECT ip, method, path, status FROM access_log")
    assert [(r["method"], r["path"], r["status"]) for r in rows] == [("GET", "/?q=%EB%B4%84", 200)]


ODD = "/?q=%27%20or%20%271%27=%271"   # 쿼리에 숨긴 SQL 공격 문자열 — 규칙이 신호로 잡는다


def test_ai_watch_reads_only_new_logs_and_blocks_after_two_flags(issues, monkeypatch):
    client = TestClient(app)
    seen = []
    _verdict(monkeypatch, '{"suspicious": true, "severity": "medium", "ips": ["testclient", "6.6.6.6"], '
                          '"reason": "쿼리에 SQL 공격 문자열"}', seen)
    client.get(ODD)
    first = guardian.watch_traffic()
    assert first["ips"] == ["testclient"]  # 규칙에 걸리지 않은 IP(6.6.6.6)는 AI가 말해도 무시한다
    assert seen[0][1]["purpose"] == "watch" and seen[0][1]["json_schema"] is guardian.WATCH_SCHEMA
    sent = seen[0][0][1]["content"]
    assert "testclient" in sent and "signals" in sent  # 원본 줄 대신 IP별 요약만 보낸다
    assert guardian.watch_traffic() == {"watched": 0}  # 이미 본 기록은 다시 보내지 않는다
    assert not guardian.is_blocked("testclient")  # AI 한 번의 판단으로는 막지 않는다
    client.get(ODD)
    guardian.watch_traffic()
    guardian._blocks["loaded_at"] = 0
    assert guardian.is_blocked("testclient")
    assert _codes().count("AI_SUSPICIOUS_TRAFFIC") == 2


def test_ai_watch_judges_every_minute_even_without_rule_signals(issues, monkeypatch):
    """저장소 주인 요청: 새 기록이 있으면 1분마다 AI(Fable)가 모든 IP를 판단한다 (규칙 신호가 없어도)."""
    seen = []
    _verdict(monkeypatch, '{"suspicious": false, "severity": "low", "ips": [], "reason": ""}', seen)
    client = TestClient(app)
    for _ in range(5):
        client.get("/?q=봄 풍경")
    assert guardian.watch_traffic() == {"watched": 5, "suspicious": False}
    sent = json.loads(seen[0][0][1]["content"])
    assert sent["testclient"]["signals"] == [] and sent["testclient"]["requests"] == 5
    assert guardian.watch_traffic() == {"watched": 0} and len(seen) == 1   # 새 기록이 없으면 부르지 않는다


def test_rules_mode_skips_ai_when_rules_see_nothing(issues, monkeypatch):
    monkeypatch.setattr(guardian, "WATCH_MODE", "rules")   # 비용 절감 모드 (WATCH_MODE=rules)
    seen = []
    _verdict(monkeypatch, '{"suspicious": true, "severity": "high", "ips": ["testclient"], "reason": "x"}', seen)
    client = TestClient(app)
    for _ in range(5):
        client.get("/?q=봄 풍경")
    assert guardian.watch_traffic() == {"watched": 5, "suspicious": False, "ai": "skipped"}
    assert not seen and "AI_SUSPICIOUS_TRAFFIC" not in _codes()


def test_traffic_signals_catch_rule_dodging_patterns():
    def row(path, status=200, ua="Mozilla", ip="9.9.9.9"):
        return {"ip": ip, "path": path, "status": status, "user_agent": ua, "created_at": "t"}
    burst = [row("/api/artworks") for _ in range(60)]
    peeking = [row(f"/api/me/favorites/{i}", ip="8.8.8.8") for i in range(12)]
    scanner = [row("/", ua="sqlmap/1.7", ip="7.7.7.7")]
    normal = [row("/api/chat", ip="1.2.3.4") for _ in range(5)]
    flagged = guardian.traffic_signals(burst + peeking + scanner + normal)
    assert set(flagged) == {"9.9.9.9", "8.8.8.8", "7.7.7.7"}
    assert "요청 60건" in flagged["9.9.9.9"]["signals"]
    assert len(flagged["9.9.9.9"]["sample_paths"]) <= 12


def test_ai_watch_normal_traffic_records_nothing(issues, monkeypatch):
    _verdict(monkeypatch, '{"suspicious": false, "severity": "low", "ips": [], "reason": ""}')
    TestClient(app).get(ODD)
    assert guardian.watch_traffic() == {"watched": 1, "suspicious": False}
    assert "AI_SUSPICIOUS_TRAFFIC" not in _codes()


def test_ai_watch_high_severity_alerts_now(issues, monkeypatch):
    TestClient(app).get(ODD)
    issues.clear()
    _verdict(monkeypatch, '{"suspicious": true, "severity": "high", "ips": ["testclient"], "reason": "계정 돌려 막기"}')
    guardian.scan()
    assert issues and issues[0][0].startswith("[가디언] 실시간 경보")


def test_ai_watch_survives_ai_failure(issues, monkeypatch):
    def down(*a, **k):
        raise AIUnavailableError("AI_ERROR", "down")
    monkeypatch.setattr(llm, "chat_completion", down)
    TestClient(app).get(ODD)
    assert guardian.watch_traffic()["error"] == "ai"


def _fill_access_log(n: int, ms: int, status: int = 200):
    for _ in range(n):
        guardian.log_access("198.51.100.7", "POST", "/api/chat", status, "ua", ms)


def test_capacity_alert_when_most_requests_are_slow(issues):
    _fill_access_log(15, ms=12000)
    _fill_access_log(5, ms=300, status=504)
    result = guardian.check_capacity()
    assert result["alert"] and result["slow_5m"] == 15 and result["unavailable_5m"] == 5
    title, body, labels = issues[-1]
    assert title.startswith("[용량]") and "Vercel" in body and labels == ["capacity"]  # 자동 수정 대상 아님
    assert "alert" not in guardian.check_capacity()  # 같은 경보는 6시간에 한 번


def test_capacity_quiet_when_fast_or_too_few_requests(issues):
    _fill_access_log(5, ms=20000)
    assert "alert" not in guardian.check_capacity()  # 요청이 너무 적으면 판단하지 않는다
    _fill_access_log(40, ms=500)
    assert "alert" not in guardian.check_capacity()


def test_summary_endpoint_needs_secret_and_reports_latency(issues, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/guardian/summary").status_code == 401
    _fill_access_log(10, ms=1000)
    guardian.record_incident("reliability", "AI_TIMEOUT", "x")
    s = guardian.summary()
    assert s["api_requests"] == 10 and s["api_ms"]["p95"] == 1000
    assert {"category": "reliability", "code": "AI_TIMEOUT", "n": 1} in s["incidents"]


def test_visitor_stats_needs_secret_and_counts_by_day(issues):
    client = TestClient(app)
    assert client.get("/api/guardian/visitors").status_code == 401
    uid = db.execute("INSERT INTO users (email, password_hash, created_at) VALUES ('v@x.com', 'h', "
                     "'2026-10-01T09:00:00+00:00') RETURNING id")[0]["id"]
    for status in ("ok", "ok", "error"):
        db.execute("INSERT INTO chats (user_id, question, status, created_at) VALUES (?, 'q', ?, "
                   "'2026-10-02T10:00:00+00:00')", (uid, status))
    s = guardian.visitor_stats()
    days = {d["day"]: d for d in s["daily"]}
    assert days["2026-10-01"]["signups"] == 1
    assert days["2026-10-02"] == {"day": "2026-10-02", "chat_users": 1, "chats": 3, "chat_errors": 1}
    assert s["totals"]["users"] >= 1 and "v@x.com" not in str(s)


def test_ai_probe_ok_then_reuses_result_within_a_minute(issues, monkeypatch):
    seen = []
    _verdict(monkeypatch, "ok", seen)
    assert guardian.probe_ai()["status"] == "ok"
    assert guardian.probe_ai() == {"status": "ok", "checked": "recently"}   # 1분 안에 다시 묻지 않는다
    assert len(seen) == 1 and seen[0][1]["purpose"] == "probe"


def test_ai_probe_failure_alerts_once_as_outage(issues, monkeypatch):
    def down(*a, **k):
        raise AIUnavailableError("AI_KEY_MISSING", "크레딧 소진")
    monkeypatch.setattr(llm, "chat_completion", down)
    assert guardian.probe_ai() == {"status": "error", "code": "AI_KEY_MISSING"}
    assert "AI_PROBE_FAILED" in _codes()
    outage = [i for i in issues if i[2] == ["outage"]]
    assert len(outage) == 1 and "AI_KEY_MISSING" in outage[0][0]
    assert guardian.probe_ai()["status"] == "error"   # 1분 안 재확인은 마지막 결과(고장)를 그대로
    db.execute("DELETE FROM rate_counters WHERE bucket = 'probe:ai'")
    guardian.probe_ai()
    assert len([i for i in issues if i[2] == ["outage"]]) == 1   # 이슈는 30분에 한 번만


def test_scan_endpoint_get_reports_503_when_ai_is_down(issues, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "CRON_SECRET", "s3cret")
    client = TestClient(app)
    headers = {"Authorization": "Bearer s3cret"}
    r = client.get("/api/guardian/scan", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["ai"]["status"] == "ok"

    def down(*a, **k):
        raise AIUnavailableError("AI_ERROR", "down")
    monkeypatch.setattr(llm, "chat_completion", down)
    db.execute("DELETE FROM rate_counters WHERE bucket = 'probe:ai'")
    r = client.get("/api/guardian/scan", headers=headers)
    assert r.status_code == 503 and r.json()["ai"]["status"] == "error"
    assert client.get("/api/guardian/scan").status_code == 401


def test_cron_secret_tolerates_copied_whitespace_but_not_wrong_values(issues, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "CRON_SECRET", "s3cret\n")   # Vercel에 값을 넣을 때 줄바꿈이 딸려 온 경우
    client = TestClient(app)
    assert client.get("/api/guardian/scan", headers={"Authorization": "Bearer s3cret "}).status_code in (200, 503)
    assert client.get("/api/guardian/scan", headers={"Authorization": "bearer s3cret"}).status_code in (200, 503)
    assert client.get("/api/guardian/scan", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/guardian/scan", headers={"Authorization": "s3cret"}).status_code == 401
    monkeypatch.setattr(main, "CRON_SECRET", "  ")
    assert client.get("/api/guardian/scan", headers={"Authorization": "Bearer "}).status_code == 401


def test_one_broken_scan_step_does_not_crash_the_whole_check(issues, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "CRON_SECRET", "s3cret")

    def broken():
        raise KeyError("status sk-ant-abcdefghijklmnop")
    monkeypatch.setattr(guardian, "check_capacity", broken)
    r = TestClient(app).get("/api/guardian/scan", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 503   # 500(서버 오류)이 아니라 '일부 고장'으로 답한다
    body = r.json()
    assert body["failed_steps"] == ["capacity"] and body["capacity"]["error"] == "KeyError"
    assert "broken" in body["capacity"]["where"] and body["ai"]["status"] == "ok"   # 다른 단계는 계속 돈다
    alert = [i for i in issues if "'capacity' 단계 오류" in i[0]]
    assert len(alert) == 1 and "KeyError" in alert[0][1] and "sk-ant" not in alert[0][1]   # 비밀처럼 보이는 값은 가린다
    TestClient(app).get("/api/guardian/scan", headers={"Authorization": "Bearer s3cret"})
    assert len([i for i in issues if "'capacity' 단계 오류" in i[0]]) == 1   # 같은 단계 알림은 30분에 한 번


def test_scan_runs_traffic_watch_after_the_response(issues, monkeypatch):
    """Fable 판단은 수십 초 걸릴 수 있어 1분 점검 응답(25초 제한) 뒤에 돈다. 실패해도 위치와 함께 보고한다."""
    from app import main
    monkeypatch.setattr(main, "CRON_SECRET", "s3cret")
    ran = []
    monkeypatch.setattr(guardian, "watch_traffic", lambda: ran.append(1) or {"watched": 0})
    r = TestClient(app).get("/api/guardian/scan", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.json()["traffic"] == {"scheduled": "after_response"} and ran == [1]

    def broken():
        raise ValueError("bad verdict")
    monkeypatch.setattr(guardian, "watch_traffic", broken)
    TestClient(app).get("/api/guardian/scan", headers={"Authorization": "Bearer s3cret"})
    assert any("'traffic' 단계 오류" in i[0] and "ValueError" in i[1] for i in issues)


def test_scan_route_failure_outside_steps_is_reported_not_500(issues, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "CRON_SECRET", "s3cret")

    def boom():
        raise TypeError("unexpected")
    monkeypatch.setattr(main, "_dependency_checks", boom)
    r = TestClient(app).get("/api/guardian/scan", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 503 and r.json()["failed_steps"] == ["scan"]
    alert = [i for i in issues if "'scan' 단계 오류" in i[0]]
    assert alert and "TypeError" in alert[0][1] and "boom" in alert[0][1]


def test_non_ascii_cron_header_is_401_not_500(issues, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "CRON_SECRET", "s3cret")
    client = TestClient(app)
    # 설정 안내의 예시 글자를 그대로 넣은 경우 — 예전에는 compare_digest가 TypeError를 내 500이 났다
    assert client.get("/api/guardian/scan", headers={"Authorization": "Bearer 여기에CRON_SECRET값".encode()}).status_code == 401
    monkeypatch.setattr(main, "CRON_SECRET", "비밀값")
    assert client.get("/api/guardian/scan", headers={"Authorization": "Bearer wrong"}).status_code == 401
