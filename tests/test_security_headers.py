"""보안 헤더와 CSP: 화면 안 스크립트 없이 우리 파일만 실행되게 (보안 점수·인증 준비)."""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

client = TestClient(main.app)
STATIC = Path(main.STATIC_DIR)


def test_every_response_has_security_headers():
    for path in ("/", "/healthz", "/api/health", "/static/app.js", "/does-not-exist"):
        h = client.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY", path
        assert "max-age=" in h["strict-transport-security"] and "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["referrer-policy"] and h["permissions-policy"] and h["cross-origin-opener-policy"] == "same-origin"


def test_csp_allows_only_our_scripts():
    csp = client.get("/").headers["content-security-policy"]
    script_src = re.search(r"script-src ([^;]+)", csp).group(1)
    assert script_src.strip() == "'self'"   # unsafe-inline·외부 스크립트 없음
    assert "object-src 'none'" in csp and "base-uri 'none'" in csp


def test_pages_have_no_inline_scripts_or_handlers():
    """CSP가 막으므로 화면 안에 직접 쓴 스크립트·onclick이 있으면 그 기능이 조용히 고장 난다."""
    pages = [STATIC / "index.html", STATIC / "explain.html", STATIC / "offline.html"]
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), page.name
        assert not re.search(r"\son[a-z]+\s*=", html), page.name
    records_src = (Path(main.__file__).parent / "records.py").read_text(encoding="utf-8")
    assert "<script>" not in records_src and "onclick=" not in records_src


def test_new_script_files_are_served():
    for name in ("boot.js", "explain.js", "record.js"):
        assert client.get(f"/static/{name}").status_code == 200
    assert f"/static/boot.js?v={main.ASSET_VERSION}" in client.get("/").text
