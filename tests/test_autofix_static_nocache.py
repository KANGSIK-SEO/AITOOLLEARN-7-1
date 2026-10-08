"""정적 파일 캐시 정책 — 버전(?v=) 붙은 자산은 immutable, 그 외 /static/ 응답은 no-cache로 통일.

품질 점검 이슈: 라이브에서 /static/app.js, /static/style.css 등을 버전 없이 요청하면
Cache-Control이 명시되지 않아 배포 환경 기본값(max-age=0, must-revalidate)이 나갔다.
수정 후에는 서버가 /static/ 아래 모든 정상 응답에 정책을 직접 붙인다. AI·외부 서비스를 부르지 않는다.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "t" * 48)
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    from app import db, main
    db.reset_for_tests()
    with TestClient(main.app) as c:
        yield c


def test_versioned_asset_gets_immutable_cache(client):
    from app import main
    res = client.get(f"/static/app.js?v={main.ASSET_VERSION}")
    assert res.status_code == 200
    assert res.headers["cache-control"] == main.IMMUTABLE_CACHE


def test_unversioned_static_assets_get_no_cache(client):
    for path in ("/static/app.js", "/static/style.css", "/static/ondevice.js", "/static/offline.html"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["cache-control"] == "no-cache", path


def test_wrong_version_is_not_cached_long(client):
    from app import main
    res = client.get("/static/app.js?v=0000000000")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"
    assert res.headers["cache-control"] != main.IMMUTABLE_CACHE


def test_index_links_versioned_assets(client):
    """정상 경로(index.html)는 ?v=현재버전으로 링크해 장기 캐시 경로를 탄다."""
    from app import main
    res = client.get("/")
    assert res.status_code == 200
    assert f"/static/app.js?v={main.ASSET_VERSION}" in res.text
    assert f"/static/style.css?v={main.ASSET_VERSION}" in res.text
