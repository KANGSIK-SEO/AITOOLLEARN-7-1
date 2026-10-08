"""/api/guardian/scan이 한 단계의 예상 못 한 오류로 통째로 500(SERVER_ERROR)이 되던 문제 (가디언 실시간 경보).

점검(scan)은 AI 확인 → 접속 감시 → 부하 확인 → 사건 집계 순서인데, 그중 하나가 '알려진 AI 오류'나
'DB 오류'가 아닌 예외를 내면 점검 전체가 무너졌다. 이제 각 단계는 따로 실패로 표시되고 기록되며,
AI 상태 확인은 분류되지 않은 예외도 AI_ERROR로 처리한다. 실제 AI·DB·외부 서비스는 부르지 않는다.
"""
from app import guardian
from app.db import DbError


def _final_count_rows(*_args, **_kwargs):
    """scan() 마지막의 사건 집계 질의에 대한 가짜 응답 (사건 없음)."""
    return [{"errors": 0, "high": 0}]


def _patch_scan_basics(monkeypatch, incidents):
    monkeypatch.setattr(guardian.db, "execute", _final_count_rows)
    monkeypatch.setattr(guardian, "record_incident",
                        lambda category, code, message, context=None, severity="low", auto_action=None:
                        incidents.append((category, code, severity, context)) or 1)
    monkeypatch.setattr(guardian, "run_triage", lambda reason: {"skipped": "test"})


def test_scan_survives_unexpected_error_in_one_step(monkeypatch):
    incidents = []
    _patch_scan_basics(monkeypatch, incidents)
    monkeypatch.setattr(guardian, "probe_ai", lambda: {"status": "ok", "latency_ms": 1})

    def broken_watch():
        raise RuntimeError("응답 도중 연결 끊김")

    monkeypatch.setattr(guardian, "watch_traffic", broken_watch)
    monkeypatch.setattr(guardian, "check_capacity", lambda: {"requests_5m": 0})

    result = guardian.scan()   # 수정 전에는 RuntimeError가 그대로 올라와 SERVER_ERROR(500)가 됐다

    assert result["ai"]["status"] == "ok"
    assert result["traffic"]["error"] == "RuntimeError"
    assert result["capacity"] == {"requests_5m": 0}
    assert result["errors_5m"] == 0 and result["high_5m"] == 0
    codes = [(code, severity) for _, code, severity, _ in incidents]
    assert ("SCAN_STEP_FAILED", "high") in codes   # 숨기지 않고 사건으로 남겨 알림은 그대로 간다
    ctx = next(c for _, code, _, c in incidents if code == "SCAN_STEP_FAILED")
    assert ctx["step"] == "traffic"


def test_scan_marks_db_failure_step_and_continues(monkeypatch):
    incidents = []
    _patch_scan_basics(monkeypatch, incidents)

    def db_broken_probe():
        raise DbError("Turso 연결 실패")

    monkeypatch.setattr(guardian, "probe_ai", db_broken_probe)
    monkeypatch.setattr(guardian, "watch_traffic", lambda: {"watched": 0})
    monkeypatch.setattr(guardian, "check_capacity", lambda: {})

    result = guardian.scan()

    assert result["ai"] == {"status": "error", "error": "db"}   # 엔드포인트가 보는 status 키는 항상 있다
    assert result["traffic"] == {"watched": 0}


def test_scan_result_shape_unchanged_when_everything_ok(monkeypatch):
    incidents = []
    _patch_scan_basics(monkeypatch, incidents)
    monkeypatch.setattr(guardian, "probe_ai", lambda: {"status": "ok", "latency_ms": 3})
    monkeypatch.setattr(guardian, "watch_traffic", lambda: {"watched": 2, "suspicious": False, "ai": "skipped"})
    monkeypatch.setattr(guardian, "check_capacity", lambda: {"requests_5m": 2, "slow_5m": 0, "unavailable_5m": 0})

    result = guardian.scan()

    assert set(result) == {"ai", "errors_5m", "high_5m", "traffic", "capacity"}
    assert result["ai"] == {"status": "ok", "latency_ms": 3}
    assert incidents == []


def test_probe_ai_treats_unclassified_exception_as_ai_error(monkeypatch):
    incidents = []
    flags = {}
    monkeypatch.setattr(guardian, "check_rate", lambda bucket, limit, window_seconds: True)
    monkeypatch.setattr(guardian, "_set_flag", lambda key, value: flags.__setitem__(key, value))
    monkeypatch.setattr(guardian, "_flag_active_until", lambda key: True)   # 이슈 열기(외부 통신)는 건너뛴다
    monkeypatch.setattr(guardian, "open_github_issue", lambda *a, **k: None)
    monkeypatch.setattr(guardian, "record_incident",
                        lambda category, code, message, context=None, severity="low", auto_action=None:
                        incidents.append((code, context)) or 1)

    def dropped(*_args, **_kwargs):
        raise ConnectionResetError("Connection reset by peer")

    monkeypatch.setattr(guardian.llm, "chat_completion", dropped)

    result = guardian.probe_ai()   # 수정 전에는 ConnectionResetError가 그대로 올라왔다

    assert result == {"status": "error", "code": "AI_ERROR"}
    assert "ai_probe_down_until" in flags
    assert incidents == [("AI_PROBE_FAILED", {"code": "AI_ERROR"})]


def test_probe_ai_known_ai_error_still_reported_with_its_code(monkeypatch):
    incidents = []
    monkeypatch.setattr(guardian, "check_rate", lambda bucket, limit, window_seconds: True)
    monkeypatch.setattr(guardian, "_set_flag", lambda key, value: None)
    monkeypatch.setattr(guardian, "_flag_active_until", lambda key: True)
    monkeypatch.setattr(guardian, "open_github_issue", lambda *a, **k: None)
    monkeypatch.setattr(guardian, "record_incident",
                        lambda category, code, message, context=None, severity="low", auto_action=None:
                        incidents.append(code) or 1)

    def timed_out(*_args, **_kwargs):
        raise guardian.AIUnavailableError("AI_TIMEOUT", "busy")

    monkeypatch.setattr(guardian.llm, "chat_completion", timed_out)

    assert guardian.probe_ai() == {"status": "error", "code": "AI_TIMEOUT"}
    assert incidents == ["AI_PROBE_FAILED"]
