import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, llm  # noqa: E402
from app import main as main_module  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    return TestClient(app)


def fake_llm(calls):
    def _fake(messages, max_tokens=700, temperature=0.3):
        calls.append(messages)
        if "검색 의도 추출기" in messages[0]["content"]:
            return '{"chitchat": false, "keywords": ["landscape", "spring"], "artist": null, "year_from": null, "year_to": null}'
        return "[1] 봄 풍경이 담긴 작품입니다."
    return _fake


def signup(client, email="a@b.com", pw="password123"):
    return client.post("/api/auth/signup", json={"email": email, "password": pw})


def test_chat_requires_login(client):
    r = client.post("/api/chat", json={"message": "안녕"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_signup_login_validation(client):
    assert signup(client, "not-an-email").status_code == 400
    assert signup(client, pw="short").status_code == 400
    assert signup(client).status_code == 201
    assert signup(client).status_code == 409
    assert client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@b.com", "password": "password123"}).status_code == 200


def test_chat_pipeline_saves_log_and_returns_artworks(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat_completion", fake_llm(calls))
    signup(client)
    r = client.post("/api/chat", json={"message": "봄 느낌 풍경화 보여줘"})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] and body["reply"].startswith("[1]")
    assert body["artworks"] and all(w["license"] == "CC0" for w in body["artworks"])
    chats = client.get("/api/me/chats").json()["chats"]
    assert len(chats) == 1 and chats[0]["status"] == "ok" and chats[0]["question"] == "봄 느낌 풍경화 보여줘"


def test_context_includes_previous_turn(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat_completion", fake_llm(calls))
    signup(client)
    client.post("/api/chat", json={"message": "첫 질문입니다"})
    client.post("/api/chat", json={"message": "내가 방금 뭘 물어봤지?"})
    last_answer_prompt = calls[-1][1]["content"]
    assert "첫 질문입니다" in last_answer_prompt


def test_input_validation(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    signup(client)
    assert client.post("/api/chat", json={"message": "   "}).json()["error"]["code"] == "EMPTY_MESSAGE"
    assert client.post("/api/chat", json={"message": "가" * 501}).json()["error"]["code"] == "MESSAGE_TOO_LONG"


def test_ai_timeout_returns_error_and_logs(client, monkeypatch):
    def boom(*a, **k):
        raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요.")
    monkeypatch.setattr(llm, "chat_completion", boom)
    signup(client)
    r = client.post("/api/chat", json={"message": "긴 글 요약해줘"})
    assert r.status_code == 504 and r.json()["error"]["code"] == "AI_TIMEOUT"
    chat = client.get("/api/me/chats").json()["chats"][0]
    assert chat["status"] == "error" and chat["error_code"] == "AI_TIMEOUT"


def test_users_cannot_see_others_logs(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    signup(client, "one@x.com")
    client.post("/api/chat", json={"message": "one"})
    other = TestClient(app)
    other.post("/api/auth/signup", json={"email": "two@x.com", "password": "password123"})
    assert other.get("/api/me/chats").json()["chats"] == []


def test_signup_with_valid_premium_code_raises_rate_limit(client, monkeypatch):
    monkeypatch.setenv("PREMIUM_CODE", "vip-2026")
    monkeypatch.setattr(main_module, "CHAT_LIMIT_PER_HOUR", 1)
    monkeypatch.setattr(main_module, "CHAT_LIMIT_PER_HOUR_PREMIUM", 2)
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))

    r = client.post("/api/auth/signup",
                    json={"email": "vip@x.com", "password": "password123", "private_code": "vip-2026"})
    assert r.status_code == 201 and r.json()["user"]["is_premium"] is True
    assert client.get("/api/me").json()["user"]["is_premium"] is True

    assert client.post("/api/chat", json={"message": "1"}).status_code == 200
    # 일반 한도(1)였다면 두 번째 호출에서 이미 429가 났어야 한다
    assert client.post("/api/chat", json={"message": "2"}).status_code == 200
    assert client.post("/api/chat", json={"message": "3"}).json()["error"]["code"] == "RATE_LIMITED"


def test_signup_with_wrong_premium_code_stays_regular(client, monkeypatch):
    monkeypatch.setenv("PREMIUM_CODE", "vip-2026")
    r = client.post("/api/auth/signup",
                    json={"email": "normal@x.com", "password": "password123", "private_code": "wrong-code"})
    assert r.status_code == 201 and r.json()["user"]["is_premium"] is False


def test_signup_without_premium_code_is_regular_when_code_unset(client, monkeypatch):
    monkeypatch.delenv("PREMIUM_CODE", raising=False)
    r = signup(client, "plain@x.com")
    assert r.status_code == 201 and r.json()["user"]["is_premium"] is False


def test_free_limit_blocks_after_lifetime_quota(client, monkeypatch):
    monkeypatch.setattr(main_module, "CHAT_LIFETIME_LIMIT_FREE", 2)
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    signup(client)
    assert client.post("/api/chat", json={"message": "1"}).status_code == 200
    assert client.post("/api/chat", json={"message": "2"}).status_code == 200
    r = client.post("/api/chat", json={"message": "3"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FREE_LIMIT_REACHED"


def test_premium_user_is_exempt_from_free_limit(client, monkeypatch):
    monkeypatch.setenv("PREMIUM_CODE", "vip-2026")
    monkeypatch.setattr(main_module, "CHAT_LIFETIME_LIMIT_FREE", 1)
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    client.post("/api/auth/signup",
                json={"email": "vip3@x.com", "password": "password123", "private_code": "vip-2026"})
    assert client.post("/api/chat", json={"message": "1"}).status_code == 200
    # 평생 무료 한도(1)를 넘겨도 초대코드 계정은 막히지 않아야 한다
    assert client.post("/api/chat", json={"message": "2"}).status_code == 200


def test_premium_users_get_more_recommended_artworks(client, monkeypatch):
    monkeypatch.setenv("PREMIUM_CODE", "vip-2026")
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    client.post("/api/auth/signup",
                json={"email": "vip4@x.com", "password": "password123", "private_code": "vip-2026"})
    r = client.post("/api/chat", json={"message": "봄 느낌 풍경화 보여줘"})
    assert r.status_code == 200 and len(r.json()["artworks"]) <= 100


def test_regular_users_get_capped_recommended_artworks(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    signup(client)
    r = client.post("/api/chat", json={"message": "봄 느낌 풍경화 보여줘"})
    assert r.status_code == 200 and len(r.json()["artworks"]) <= 6


def test_schema_migration_is_idempotent(tmp_path, monkeypatch):
    """재배포(새 서버리스 인스턴스)처럼 ensure_schema()가 다시 ALTER TABLE을 실행해도 죽지 않아야 한다."""
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    db.ensure_schema()
    db.reset_for_tests()
    db.ensure_schema()


def test_aic_image_urls_are_proxied(client):
    from app import art
    work = {"source": "aic", "image_url": "https://www.artic.edu/iiif/2/bda9058b-5be6-37d0-e5a6-926584540757/full/1686,/0/default.jpg"}
    out = art.with_proxy_urls(work)
    assert out["thumbnail_url"] == "/api/img/aic/bda9058b-5be6-37d0-e5a6-926584540757?w=400"
    assert out["image_url"].endswith("?w=1686")
    assert art.with_proxy_urls({"source": "met", "image_url": "https://images.metmuseum.org/x.jpg"})["image_url"].startswith("https://images")


def test_image_proxy_validates_and_sends_aic_header(client, monkeypatch):
    seen = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"\xff\xd8jpeg"

    def fake_urlopen(req, timeout=0):
        seen["url"], seen["hdr"] = req.full_url, dict(req.header_items())
        return FakeResp()

    monkeypatch.setattr("app.main.urllib.request.urlopen", fake_urlopen)
    ok = client.get("/api/img/aic/bda9058b-5be6-37d0-e5a6-926584540757?w=400")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert "immutable" in ok.headers["cache-control"]
    assert "Aic-user-agent" in seen["hdr"] and "@" not in seen["hdr"]["Aic-user-agent"]
    assert not seen["hdr"]["User-agent"].startswith("Python-urllib")
    assert client.get("/api/img/aic/not-a-uuid?w=400").status_code == 400
    assert client.get("/api/img/aic/bda9058b-5be6-37d0-e5a6-926584540757?w=999").status_code == 400


# ---- 작품 즐겨찾기 ----
def _artwork_ids(n=2):
    import sqlite3
    from app import art
    conn = sqlite3.connect(f"file:{art.ART_DB}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute("SELECT id FROM artworks ORDER BY id LIMIT ?", (n,))]
    finally:
        conn.close()


def test_favorites_require_login(client):
    assert client.post("/api/favorites", json={"artwork_id": 1}).status_code == 401
    assert client.delete("/api/favorites/1").status_code == 401
    assert client.get("/api/me/favorites").json()["error"]["code"] == "UNAUTHENTICATED"


def test_favorite_add_list_remove(client):
    a, b = _artwork_ids(2)
    signup(client)
    assert client.post("/api/favorites", json={"artwork_id": a}).status_code == 201
    assert client.post("/api/favorites", json={"artwork_id": b}).status_code == 201
    favs = client.get("/api/me/favorites").json()["favorites"]
    assert [f["id"] for f in favs] == [b, a]  # 최근 저장 순
    assert favs[0]["title"] and favs[0]["license"] and favs[0]["favorited_at"]

    r = client.delete(f"/api/favorites/{b}")
    assert r.status_code == 200 and r.json()["removed"] is True
    assert client.delete(f"/api/favorites/{b}").json()["removed"] is False
    assert [f["id"] for f in client.get("/api/me/favorites").json()["favorites"]] == [a]


def test_favorite_duplicate_is_idempotent(client):
    (a,) = _artwork_ids(1)
    signup(client)
    assert client.post("/api/favorites", json={"artwork_id": a}).json()["created"] is True
    r = client.post("/api/favorites", json={"artwork_id": a})
    assert r.status_code == 200 and r.json()["created"] is False
    assert len(client.get("/api/me/favorites").json()["favorites"]) == 1


def test_favorite_rejects_unknown_or_invalid_artwork(client):
    signup(client)
    r = client.post("/api/favorites", json={"artwork_id": 999_999_999})
    assert r.status_code == 404 and r.json()["error"]["code"] == "ARTWORK_NOT_FOUND"
    assert client.post("/api/favorites", json={"artwork_id": "abc"}).status_code == 422
    assert client.post("/api/favorites", json={}).status_code == 422
    assert client.get("/api/me/favorites").json()["favorites"] == []


def test_favorites_are_isolated_between_users(client):
    a, b = _artwork_ids(2)
    signup(client, "one@x.com")
    client.post("/api/favorites", json={"artwork_id": a})

    other = TestClient(app)
    signup(other, "two@x.com")
    assert other.get("/api/me/favorites").json()["favorites"] == []
    # 다른 사용자가 같은 작품을 저장하거나 지워도 내 즐겨찾기에는 영향이 없다
    assert other.post("/api/favorites", json={"artwork_id": a}).status_code == 201
    assert other.delete(f"/api/favorites/{a}").json()["removed"] is True
    assert [f["id"] for f in client.get("/api/me/favorites").json()["favorites"]] == [a]


# ---- TV 앱 등 다른 오리진 클라이언트를 위한 Bearer 토큰 인증 ----

def test_login_returns_bearer_token_in_body(client):
    signup(client)
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "password123"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert isinstance(token, str) and "." in token


def test_bearer_token_authenticates_chat_without_cookie(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat_completion", fake_llm(calls))
    token = signup(client).json()["token"]
    # 쿠키를 전혀 받지 않은 새 클라이언트로, 헤더만으로 인증되는지 확인한다.
    headerless = TestClient(app)
    r = headerless.post("/api/chat", json={"message": "봄 느낌 풍경화 보여줘"},
                        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["artworks"]


def test_bearer_token_works_for_get_me_and_my_chats(client):
    token = signup(client).json()["token"]
    other = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    assert other.get("/api/me", headers=headers).status_code == 200
    assert other.get("/api/me/chats", headers=headers).status_code == 200


def test_invalid_bearer_token_is_rejected(client):
    other = TestClient(app)
    r = other.get("/api/me", headers={"Authorization": "Bearer garbage.notavalidtoken"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_cookie_flow_still_works_unaffected(client, monkeypatch):
    """Bearer 경로 추가가 기존 쿠키 기반 웹 클라이언트 동작을 바꾸지 않는지 확인하는 회귀 테스트."""
    calls = []
    monkeypatch.setattr(llm, "chat_completion", fake_llm(calls))
    signup(client)  # client는 쿠키 저장소를 가진 TestClient라 이후 요청에 쿠키만 자동으로 붙는다.
    r = client.post("/api/chat", json={"message": "봄 느낌 풍경화 보여줘"})
    assert r.status_code == 200
    assert r.json()["artworks"]


def test_cors_preflight_allows_authorization_header(client):
    r = client.options("/api/chat", headers={
        "Origin": "http://example.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
