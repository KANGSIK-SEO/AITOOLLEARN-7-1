"""모든 오류가 {"error": {"code", "message"}} 한 모양인지 (app/errors.py).

FastAPI 기본 처리기는 없는 주소·깨진 요청 본문에 {"detail": ...}을 돌려줘 README의 약속과 어긋났다.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    return TestClient(app)


def test_broken_json_body_uses_common_error_shape(client):
    r = client.post("/api/chat", content=b'{"message": "\xba', headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)
    assert set(r.json()) == {"error"} and r.json()["error"]["code"] == "INVALID_INPUT"


def test_wrong_method_uses_common_error_shape(client):
    r = client.delete("/api/me/chats")
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in r.headers.get("allow", "")


def test_chat_without_login_is_401_in_common_shape(client):
    r = client.post("/api/chat", json={"message": "봄 풍경"})
    assert r.status_code == 401 and r.json() == {"error": {"code": "UNAUTHENTICATED", "message": "로그인이 필요합니다."}}
