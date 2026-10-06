"""무료 질문 횟수 제한(평생 한도)과 남은 횟수 안내 테스트.

한도 판정은 app/main.py의 chat_endpoint에서 하고, "초대코드(프리미엄) 계정인가"는 app/auth.py가
서명한 세션 토큰의 premium 값으로 정해진다. 그래서 토큰 위조·구버전 토큰도 함께 확인한다.
"""
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

FREE = 5       # 테스트용 평생 무료 한도
WARN_AT = 2    # 남은 횟수가 이 값 이하이면 안내


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.setattr(main_module, "CHAT_LIFETIME_LIMIT_FREE", FREE)
    monkeypatch.setattr(main_module, "FREE_LIMIT_WARNING_THRESHOLD", WARN_AT)
    db.reset_for_tests()
    return TestClient(app)


@pytest.fixture()
def ai(monkeypatch):
    """AI 호출 횟수를 세고, fail에 코드를 넣으면 그 오류로 실패한다."""
    state = {"calls": 0, "fail": None}

    def fake(messages, **k):
        state["calls"] += 1
        if state["fail"]:
            raise AIUnavailableError(state["fail"], "x")
        if "검색 의도 추출기" in messages[0]["content"]:
            return '{"chitchat": false, "keywords": ["spring"], "artist": null, "year_from": null, "year_to": null}'
        return "[1] 답변"
    monkeypatch.setattr(llm, "chat_completion", fake)
    return state


def signup(client, email="free@x.com", code=None):
    body = {"email": email, "password": "password123"}
    if code:
        body["private_code"] = code
    return client.post("/api/auth/signup", json=body)


def ask(client, **kw):
    return client.post("/api/chat", json={"message": "봄 풍경"}, **kw)


def test_remaining_free_counts_down_and_warns_near_the_end(client, ai):
    signup(client)
    seen = [(b["remaining_free"], b["show_limit_warning"]) for b in (ask(client).json() for _ in range(FREE))]
    assert seen == [(4, False), (3, False), (2, True), (1, True), (0, True)]
    r = ask(client)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FREE_LIMIT_REACHED"
    assert f"{FREE}회" in r.json()["error"]["message"]


def test_blocked_request_does_not_call_ai_or_add_log(client, ai):
    signup(client)
    for _ in range(FREE):
        ask(client)
    calls, logged = ai["calls"], len(client.get("/api/me/chats?limit=100").json()["chats"])
    assert ask(client).status_code == 403
    assert ai["calls"] == calls  # 한도 초과 요청은 AI 비용을 쓰지 않는다
    assert len(client.get("/api/me/chats?limit=100").json()["chats"]) == logged


def test_failed_ai_calls_do_not_consume_free_quota(client, ai):
    """AI 장애로 답을 못 받은 질문(status=error)은 무료 횟수에서 빠진다."""
    signup(client)
    ai["fail"] = "AI_TIMEOUT"
    for _ in range(FREE + 2):
        assert ask(client).status_code == 504
    ai["fail"] = None
    assert ask(client).json()["remaining_free"] == FREE - 1


def test_free_quota_is_per_user(client, ai):
    signup(client, "heavy@x.com")
    for _ in range(FREE):
        ask(client)
    assert ask(client).status_code == 403
    other = TestClient(app)
    signup(other, "new@x.com")
    assert ask(other).json()["remaining_free"] == FREE - 1


def test_premium_has_no_remaining_count_or_warning(client, ai, monkeypatch):
    monkeypatch.setenv("PREMIUM_CODE", "vip-2026")
    signup(client, "vip@x.com", code="vip-2026")
    for _ in range(FREE + 1):
        body = ask(client).json()
        assert body["remaining_free"] is None and body["show_limit_warning"] is False


def test_free_limit_applies_to_bearer_token_clients(client, ai):
    token = signup(client).json()["token"]
    tv = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(FREE):
        assert ask(tv, headers=headers).status_code == 200
    assert ask(tv, headers=headers).json()["error"]["code"] == "FREE_LIMIT_REACHED"
