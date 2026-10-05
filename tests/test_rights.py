import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import art, db, rights  # noqa: E402
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


def test_certificate_number_changes_with_rights_data():
    a = rights.certificate_number(_work())
    assert a == rights.certificate_number(_work())
    assert a != rights.certificate_number(_work(collected_at="2026-10-02 00:00:00"))


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


def test_certificate_page_shows_evidence_and_cautions(client):
    work = art.search(["landscape"], limit=1)[0]
    r = client.get(f"/certificate/{work['id']}")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    body = r.text
    assert "퍼블릭 도메인 권리 확인서" in body and "R1" in body and "R6" in body
    assert "초상권" in body and "법률 자문이 아닙니다" in body
    assert "PD-" in body  # 확인서 번호
    assert client.get("/certificate/999999999").status_code == 404


def test_certificate_refuses_for_disabled_source_in_pilot(client, monkeypatch):
    aic = next(w for w in art.search(["landscape"], limit=30) if w["source"] == "aic")
    monkeypatch.setenv("ALLOWED_SOURCES", "met")
    body = client.get(f"/certificate/{aic['id']}").text
    assert "발급 불가" in body and 'class="credit"' not in body


def test_certificate_escapes_html(client, monkeypatch):
    evil = {**_work(), "id": 1, "title": "<script>alert(1)</script>", "artist": None, "date_display": None,
            "medium": None, "thumbnail_url": None, "credit_line": None, "collected_at": "2026-10-01 00:00:00"}
    monkeypatch.setattr(art, "get_rights_record", lambda _id: evil)
    body = client.get("/certificate/1").text
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body


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
