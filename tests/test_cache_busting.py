import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

client = TestClient(main.app)


def test_index_links_versioned_assets_and_is_revalidated():
    r = client.get("/")
    assert r.headers["cache-control"] == "no-cache"
    for name in main.VERSIONED_ASSETS:
        assert f"/static/{name}?v={main.ASSET_VERSION}" in r.text


def test_service_worker_cache_name_follows_asset_version():
    r = client.get("/sw.js")
    assert r.headers["cache-control"] == "no-cache"
    assert f"art-chatbot-shell-{main.ASSET_VERSION}" in r.text
    assert "__ASSET_VERSION__" not in r.text
    assert f"/static/app.js?v={main.ASSET_VERSION}" in r.text  # 미리 캐싱하는 주소도 페이지와 같은 버전


def test_asset_version_changes_when_static_files_change(tmp_path, monkeypatch):
    import hashlib
    files = {name: (main.STATIC_DIR / name).read_bytes() for name in (*main.VERSIONED_ASSETS, "index.html", "sw.js")}
    files["app.js"] += b"\n// changed"
    changed = hashlib.sha256(b"".join(files[n] for n in (*main.VERSIONED_ASSETS, "index.html", "sw.js"))).hexdigest()[:10]
    assert changed != main.ASSET_VERSION
