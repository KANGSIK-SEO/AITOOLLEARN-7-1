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


def test_my_chats_requires_login(client):
    r = client.get("/api/me/chats")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_guest_trial_allows_limited_questions_without_login(client, monkeypatch):
    monkeypatch.setattr(main_module, "GUEST_TRIAL_LIMIT", 2)
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    assert client.get("/api/guest").json()["remaining"] == 2
    r = client.post("/api/chat", json={"message": "봄 풍경화"})
    assert r.status_code == 200 and r.json()["artworks"] and r.json()["guest_remaining"] == 1
    assert r.json()["chat_id"] is None  # 체험 질문은 대화 로그에 남기지 않는다
    assert client.post("/api/chat", json={"message": "겨울 바다"}).json()["guest_remaining"] == 0
    r = client.post("/api/chat", json={"message": "세 번째"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "GUEST_LIMIT_REACHED"
    # 가입하면 체험 한도와 무관하게 계속 쓸 수 있다
    signup(client)
    assert client.post("/api/chat", json={"message": "가입 후 질문"}).status_code == 200


def test_guest_trial_does_not_count_failed_ai_calls(client, monkeypatch):
    monkeypatch.setattr(main_module, "GUEST_TRIAL_LIMIT", 1)

    def boom(*a, **k):
        raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요.")
    monkeypatch.setattr(llm, "chat_completion", boom)
    assert client.post("/api/chat", json={"message": "실패"}).status_code == 504
    assert client.get("/api/guest").json()["remaining"] == 1


def test_chat_returns_search_conditions_for_browse(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", fake_llm([]))
    body = client.post("/api/chat", json={"message": "봄 풍경화"}).json()
    assert body["search"]["keywords"] == ["landscape", "spring"]
    page = client.get("/api/artworks", params={"q": ",".join(body["search"]["keywords"]), "limit": 30}).json()
    assert len(page["artworks"]) == 30 and page["has_more"] is True
    nxt = client.get("/api/artworks", params={"q": "landscape,spring", "limit": 30, "offset": 30}).json()
    assert not {w["id"] for w in page["artworks"]} & {w["id"] for w in nxt["artworks"]}


def test_favorites_add_list_remove(client):
    assert client.get("/api/me/favorites").status_code == 401
    signup(client)
    ids = [w["id"] for w in client.get("/api/artworks", params={"q": "landscape", "limit": 2}).json()["artworks"]]
    for i in ids:
        assert client.post("/api/me/favorites", json={"artwork_id": i}).status_code == 200
    assert client.post("/api/me/favorites", json={"artwork_id": ids[0]}).status_code == 200  # 중복은 무시
    assert client.post("/api/me/favorites", json={"artwork_id": 999999999}).status_code == 404
    favs = client.get("/api/me/favorites").json()["artworks"]
    assert sorted(w["id"] for w in favs) == sorted(ids)
    client.delete(f"/api/me/favorites/{ids[0]}")
    assert [w["id"] for w in client.get("/api/me/favorites").json()["artworks"]] == [ids[1]]


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
