"""[품질] 정적 파일 캐시 헤더 — 버전(?v=)이 붙은 정적 파일은 1년 immutable 캐시, 나머지는 기존 그대로."""
import pytest
from fastapi.testclient import TestClient

from app import main

IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.mark.parametrize("name", main.VERSIONED_ASSETS)
def test_versioned_asset_gets_long_immutable_cache(client, name):
    res = client.get(f"/static/{name}?v={main.ASSET_VERSION}")
    assert res.status_code == 200
    assert res.headers.get("cache-control") == IMMUTABLE


@pytest.mark.parametrize("name", main.VERSIONED_ASSETS)
def test_unversioned_asset_keeps_default_revalidation(client, name):
    res = client.get(f"/static/{name}")
    assert res.status_code == 200
    cache = res.headers.get("cache-control", "")
    assert "immutable" not in cache
    assert "max-age=31536000" not in cache


def test_wrong_version_does_not_get_long_cache(client):
    res = client.get("/static/app.js?v=0000000000")
    assert res.status_code == 200
    assert "immutable" not in res.headers.get("cache-control", "")


def test_non_versioned_static_file_unchanged(client):
    # manifest.json은 VERSIONED_ASSETS가 아니므로 ?v=를 붙여도 장기 캐시를 주지 않는다
    res = client.get(f"/static/manifest.json?v={main.ASSET_VERSION}")
    assert res.status_code == 200
    assert "immutable" not in res.headers.get("cache-control", "")


def test_index_and_service_worker_stay_no_cache(client):
    assert client.get("/").headers.get("cache-control") == "no-cache"
    assert client.get("/sw.js").headers.get("cache-control") == "no-cache"


def test_index_links_use_current_version_so_long_cache_applies(client):
    html = client.get("/").text
    for name in main.VERSIONED_ASSETS:
        assert f"/static/{name}?v={main.ASSET_VERSION}" in html


def test_helper_ignores_error_responses():
    """404 같은 실패 응답에는 장기 캐시 헤더를 붙이지 않는다 (오류가 1년간 캐시되면 안 된다)."""
    client = TestClient(main.app)
    res = client.get(f"/static/does-not-exist.js?v={main.ASSET_VERSION}")
    assert res.status_code == 404
    assert "immutable" not in res.headers.get("cache-control", "")
