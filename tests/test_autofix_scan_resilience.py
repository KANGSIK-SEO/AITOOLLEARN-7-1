"""가디언 점검(/api/guardian/scan → guardian.scan)의 한 단계에서 예상 밖 오류가 나도 점검 전체가
500(SERVER_ERROR)으로 죽지 않고, 어느 단계가 실패했는지 사건으로 남기는지 확인한다.
실제 AI·DB는 부르지 않는다 (monkeypatch)."""
import pytest

from app import guardian


@pytest.fixture
def quiet_scan(monkeypatch):
    """scan()의 단계들을 가짜로 바꾸고, 기록된 사건을 모아서 돌려준다."""
    incidents = []

    def fake_record(category, code, message, context=None, severity="low", auto_action=None):
        incidents.append({"category": category, "code": code, "message": message,
                          "context": context or {}, "severity": severity})
        return len(incidents)

    monkeypatch.setattr(guardian, "record_incident", fake_record)
    monkeypatch.setattr(guardian, "probe_ai", lambda: {"status": "ok", "latency_ms": 1})
    monkeypatch.setattr(guardian, "watch_traffic", lambda: {"watched": 0})
    monkeypatch.setattr(guardian, "check_capacity", lambda: {"requests_5m": 0})
    # scan() 끝의 '최근 5분 사건 집계' 조회만 남는다 — 사건이 없다고 답한다
    monkeypatch.setattr(guardian.db, "execute", lambda sql, params=(): [{"errors": 0, "high": 0}])
    return incidents


def test_scan_survives_unexpected_error_in_ai_probe(monkeypatch, quiet_scan):
    def boom():
        raise RuntimeError("connection dropped while reading")

    monkeypatch.setattr(guardian, "probe_ai", boom)

    result = guardian.scan()   # 수정 전에는 RuntimeError가 그대로 올라와 500이 났다

    assert result["ai"]["status"] == "error"
    assert result["ai"]["code"] == guardian.SCAN_STEP_FAILED
    assert result["ai"]["step"] == "probe_ai"
    # 다른 단계 결과는 잃지 않는다
    assert result["traffic"] == {"watched": 0}
    assert result["capacity"] == {"requests_5m": 0}
    # 어느 단계가 왜 실패했는지 사건으로 남고, 심각도 high라 즉시 진단으로 이어진다
    failed = [i for i in quiet_scan if i["code"] == guardian.SCAN_STEP_FAILED]
    assert len(failed) == 1
    assert failed[0]["category"] == "reliability"
    assert failed[0]["severity"] == "high"
    assert failed[0]["context"] == {"step": "probe_ai", "error": "RuntimeError"}


def test_scan_isolates_unexpected_error_in_traffic_watch(monkeypatch, quiet_scan):
    def boom():
        raise KeyError("user_agent")

    monkeypatch.setattr(guardian, "watch_traffic", boom)

    result = guardian.scan()

    assert result["ai"] == {"status": "ok", "latency_ms": 1}
    assert result["traffic"]["code"] == guardian.SCAN_STEP_FAILED
    assert result["traffic"]["step"] == "watch_traffic"
    assert result["capacity"] == {"requests_5m": 0}
    assert [i["context"]["step"] for i in quiet_scan if i["code"] == guardian.SCAN_STEP_FAILED] == ["watch_traffic"]


def test_scan_db_error_handling_is_unchanged(monkeypatch, quiet_scan):
    """DB 장애는 예전 동작 그대로: 접속 감시는 {'error': 'db'}로 표시하고, AI 확인 단계의 DbError는 그대로 올린다."""
    def db_down():
        raise guardian.db.DbError("turso down")

    monkeypatch.setattr(guardian, "watch_traffic", db_down)
    result = guardian.scan()
    assert result["traffic"] == {"error": "db"}
    assert not [i for i in quiet_scan if i["code"] == guardian.SCAN_STEP_FAILED]

    monkeypatch.setattr(guardian, "watch_traffic", lambda: {"watched": 0})
    monkeypatch.setattr(guardian, "probe_ai", db_down)
    with pytest.raises(guardian.db.DbError):
        guardian.scan()
