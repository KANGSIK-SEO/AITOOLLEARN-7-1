import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import art, db, records, rights  # noqa: E402
from app.main import app  # noqa: E402

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def _work(**over):
    w = {"source": "met", "source_id": "1", "license": "CC0", "is_public_domain": 1,
         "image_url": "https://images.metmuseum.org/a.jpg", "source_url": "https://metmuseum.org/art/1",
         "collected_at": "2026-10-01 00:00:00"}
    w.update(over)
    return w


def test_evaluate_ok_for_verified_cc0_work():
    r = rights.evaluate(_work(), NOW)
    assert r["status"] == "ok" and all(c["ok"] for c in r["checks"])


@pytest.mark.parametrize("over, failed", [
    ({"source": "rijks"}, "R1"),                                  # 보류 기관
    ({"source": "unknown"}, "R1"),
    ({"is_public_domain": 0}, "R2"),
    ({"license": "CC-BY"}, "R3"),
    ({"image_url": "https://mirror.example.com/a.jpg"}, "R4"),    # 기관 공식 도메인 아님
    ({"source_url": ""}, "R6"),
])
def test_evaluate_blocks_when_any_rule_fails(over, failed):
    r = rights.evaluate(_work(**over), NOW)
    assert r["status"] == "blocked"
    assert [c["code"] for c in r["checks"] if not c["ok"]][0] == failed


def test_evaluate_old_check_date_needs_recheck():
    old = (NOW - timedelta(days=rights.RECHECK_AFTER_DAYS + 1)).strftime("%Y-%m-%d %H:%M:%S")
    assert rights.evaluate(_work(collected_at=old), NOW)["status"] == "recheck"


def test_pending_sources_can_never_be_enabled_by_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_SOURCES", "met,rijks,emuseum")
    assert rights.allowed_sources() == ["met"]


def test_pilot_mode_limits_search_to_met(monkeypatch):
    monkeypatch.setenv("ALLOWED_SOURCES", "met")
    works = art.search(["landscape"], limit=12)
    assert works and {w["source"] for w in works} == {"met"}
    page, _ = art.browse(["landscape"], limit=30)
    assert {w["source"] for w in page} == {"met"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    return TestClient(app)


@pytest.fixture()
def fake_archive(monkeypatch):
    calls = []

    def _save(url):
        calls.append(url)
        return f"https://web.archive.org/web/20261005000000/{url}", None
    monkeypatch.setattr(records, "save_to_wayback", _save)
    return calls


def _issue(client, artwork_id):
    return client.post("/api/records", json={"artwork_id": artwork_id})


def test_record_is_issued_stored_and_archived(client, fake_archive):
    work = art.search(["landscape"], limit=1)[0]
    r = _issue(client, work["id"])
    assert r.status_code == 200 and r.json()["archived"] is True
    number = r.json()["number"]
    assert number.startswith("PD-") and r.json()["url"] == f"/records/{number}"
    assert len(fake_archive) == 2  # 기관 작품 페이지 + 근거 필드가 담긴 API 응답
    body = client.get(f"/records/{number}").text
    assert "권리 근거 기록" in body and "확인서" not in body
    assert "공식 인증서가 아닙니다" in body and "초상권" in body
    assert "web.archive.org/web/20261005000000" in body and "R1" in body and "R6" in body
    assert "확인됨" in body  # 기록 무결성
    assert client.get("/records/PD-0000-0000-0000").status_code == 404


def test_record_keeps_issue_time_snapshot_when_source_data_changes(client, fake_archive, monkeypatch):
    work = art.search(["landscape"], limit=1)[0]
    number = _issue(client, work["id"]).json()["number"]
    real = art.get_rights_record

    def changed(artwork_id):  # 발급 뒤 기관이 퍼블릭 도메인 표시를 내렸다고 가정
        return {**real(artwork_id), "is_public_domain": 0, "title": "Changed Title"}
    monkeypatch.setattr(art, "get_rights_record", changed)
    body = client.get(f"/records/{number}").text
    assert work["title"] in body and "Changed Title" not in body   # 기록은 발급 당시 그대로
    assert "오늘 다시 판단하면" in body                                  # 현재 상태 변화는 참고로만


def test_tampered_record_is_flagged(client, fake_archive):
    work = art.search(["landscape"], limit=1)[0]
    number = _issue(client, work["id"]).json()["number"]
    row = records.get(number)
    db.execute("UPDATE rights_records SET snapshot = ? WHERE number = ?",
               (row["snapshot"].replace('"CC0"', '"CC-BY"', 1), number))
    assert "변조 의심" in client.get(f"/records/{number}").text


def test_archive_failure_keeps_record_and_can_retry(client, monkeypatch):
    monkeypatch.setattr(records, "save_to_wayback", lambda url: (None, "HTTP 520"))
    work = art.search(["landscape"], limit=1)[0]
    r = _issue(client, work["id"])
    assert r.status_code == 200 and r.json()["archived"] is False
    number = r.json()["number"]
    body = client.get(f"/records/{number}").text
    assert "아직 보관되지 않음" in body and "HTTP 520" in body and "다시 보관하기" in body
    monkeypatch.setattr(records, "save_to_wayback", lambda url: (f"https://web.archive.org/web/1/{url}", None))
    archives = client.post(f"/api/records/{number}/archive").json()["archives"]
    assert all(a["archived_url"] for a in archives)
    assert "다시 보관하기" not in client.get(f"/records/{number}").text


def test_record_refused_for_blocked_artwork(client, fake_archive, monkeypatch):
    aic = next(w for w in art.search(["landscape"], limit=30) if w["source"] == "aic")
    monkeypatch.setenv("ALLOWED_SOURCES", "met")
    r = _issue(client, aic["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "RECORD_NOT_ALLOWED"
    assert fake_archive == []  # 발급 안 하면 아카이브도 안 부른다
    assert _issue(client, 999999999).status_code == 404


def test_record_escapes_html(client, fake_archive, monkeypatch):
    work = art.search(["landscape"], limit=1)[0]
    real = art.get_rights_record
    monkeypatch.setattr(art, "get_rights_record",
                        lambda i: {**real(i), "title": "<script>alert(1)</script>"})
    number = _issue(client, work["id"]).json()["number"]
    body = client.get(f"/records/{number}").text
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body


def test_wayback_reads_archived_url_from_redirect(monkeypatch):
    class Resp:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def geturl(self): return "https://web.archive.org/web/20261005010203/https://metmuseum.org/art/1"
    monkeypatch.setattr(records.urllib.request, "urlopen", lambda req, timeout: Resp())
    assert records.save_to_wayback("https://metmuseum.org/art/1") == (
        "https://web.archive.org/web/20261005010203/https://metmuseum.org/art/1", None)


def test_cma_to_row_requires_cc0_and_official_image_host():
    import collect_cma
    base = {"id": 7, "title": "Water Lilies", "share_license_status": "CC0", "url": "https://clevelandart.org/art/1",
            "creators": [{"description": "Claude Monet (French, 1840–1926)"}],
            "images": {"web": {"url": "https://openaccess-cdn.clevelandart.org/a_web.jpg"},
                       "print": {"url": "https://openaccess-cdn.clevelandart.org/a_print.jpg"}}}
    row = collect_cma.to_row(base)
    assert row["artist"] == "Claude Monet" and row["artist_bio"] == "French, 1840–1926"
    assert row["image_url"].endswith("a_print.jpg") and row["license"] == "CC0"
    assert collect_cma.to_row({**base, "share_license_status": "Copyrighted"}) is None
    assert collect_cma.to_row({**base, "images": {"web": {"url": "https://elsewhere.com/x.jpg"}}}) is None
