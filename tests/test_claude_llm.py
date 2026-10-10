"""Claude 경로(app/claude_llm.py)와 스트리밍 엔드포인트(/api/chat/stream). 실제 API는 부르지 않는다."""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from fastapi.testclient import TestClient  # noqa: E402

from app import chat, claude_llm, db, llm  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402
from app.main import app  # noqa: E402


def _response(text="안녕", stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=[
        SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)])


class FakeMessages:
    def __init__(self, response=None, error=None, pieces=None):
        self.response, self.error, self.pieces, self.calls = response, error, pieces or [], []

    def create(self, **params):
        self.calls.append(params)
        if self.error:
            raise self.error
        return self.response

    def stream(self, **params):
        self.calls.append(params)
        outer = self

        class _Stream:
            text_stream = iter(outer.pieces)

            def __enter__(self):
                if outer.error:
                    raise outer.error
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return _response("".join(outer.pieces))
        return _Stream()


@pytest.fixture()
def fake_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_INTENT_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_EFFORT", raising=False)
    messages = FakeMessages(response=_response("[1] 봄 풍경"))
    monkeypatch.setattr(claude_llm, "_get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    return messages


def test_default_is_fable_with_low_effort(fake_claude):
    out = llm.chat_completion([{"role": "system", "content": "규칙"}, {"role": "user", "content": "질문"}])
    assert out == "[1] 봄 풍경"
    p = fake_claude.calls[0]
    # 저장소 주인 요청으로 모든 작업을 Fable로 (2026-10-11) — effort는 비용을 줄이려고 low를 직접 보낸다
    assert p["model"] == "claude-fable-5-1" and p["output_config"] == {"effort": "low"}
    assert p["system"] == "규칙" and p["messages"] == [{"role": "user", "content": "질문"}]
    assert p["fallbacks"] == "default"
    assert "thinking" not in p


def test_simple_extraction_turns_thinking_off_on_haiku(fake_claude, monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-haiku-5-5")   # 되돌렸을 때도 Haiku 규칙이 그대로 동작
    fake_claude.response = _response('{"chitchat": true, "keywords": [], "artist": null, "year_from": null, '
                                     '"year_to": null, "orientation": null, "purpose": null}')
    chat.extract_intent("안녕")
    assert fake_claude.calls[0]["thinking"] == {"type": "disabled"}


def test_long_system_prompt_is_cached_short_one_is_not(fake_claude):
    llm.chat_completion([{"role": "system", "content": "가" * 3000}, {"role": "user", "content": "q"}])
    system = fake_claude.calls[0]["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"} and system[0]["text"] == "가" * 3000
    llm.chat_completion([{"role": "system", "content": "짧음"}, {"role": "user", "content": "q"}])
    assert fake_claude.calls[1]["system"] == "짧음"


def test_usage_is_recorded_per_purpose(fake_claude, monkeypatch):
    saved = []
    monkeypatch.setattr("app.guardian.save_ai_usage", lambda rows: saved.extend(rows))
    fake_claude.response.usage = SimpleNamespace(input_tokens=120, output_tokens=30,
                                                  cache_read_input_tokens=100, cache_creation_input_tokens=0)
    llm.chat_completion([{"role": "user", "content": "q"}], purpose="probe")
    assert saved == [("probe", "claude-fable-5-1", 120, 30, 100, 0)]


def test_traffic_watch_uses_fable_unless_switched_back(fake_claude, monkeypatch):
    monkeypatch.delenv("WATCH_MODEL", raising=False)
    llm.chat_completion([{"role": "user", "content": "q"}], purpose="watch")
    assert fake_claude.calls[0]["model"] == "claude-fable-5-1" and "thinking" not in fake_claude.calls[0]
    monkeypatch.setenv("WATCH_MODEL", "claude-haiku-5-5")   # 비용이 크면 Vercel 환경변수 하나로 되돌린다
    llm.chat_completion([{"role": "user", "content": "q"}], purpose="watch")
    assert fake_claude.calls[1]["model"] == "claude-haiku-5-5"


def test_fable_gets_low_effort_with_server_fallback(fake_claude, monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-fable-5-1")
    llm.chat_completion([{"role": "user", "content": "질문"}])
    p = fake_claude.calls[0]
    assert p["model"] == "claude-fable-5-1" and p["output_config"] == {"effort": "low"}
    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in p and "temperature" not in p  # Fable: 생각은 항상 켜져 있고 샘플링 옵션은 400


def test_intent_uses_json_schema_and_its_own_model(fake_claude, monkeypatch):
    monkeypatch.setenv("CLAUDE_INTENT_MODEL", "claude-haiku-5-5")
    fake_claude.response = _response('{"chitchat": false, "keywords": ["landscape"], "artist": null, '
                                     '"year_from": null, "year_to": null, "orientation": "portrait", "purpose": "카페"}')
    intent = chat.extract_intent("카페 벽 세로 포스터")
    assert intent["orientation"] == "portrait" and intent["keywords"] == ["landscape"]
    p = fake_claude.calls[0]
    assert p["model"] == "claude-haiku-5-5" and "fallbacks" not in p  # Haiku에는 서버 폴백이 없다
    assert p["output_config"]["format"]["schema"] is chat.INTENT_SCHEMA


def test_refusal_is_not_sent_to_gpt(fake_claude, monkeypatch):
    fake_claude.response = _response("", stop_reason="refusal")
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt")
    monkeypatch.setattr(llm, "_gpt_chain", lambda *a: pytest.fail("거절은 다른 모델로 우회하지 않는다"))
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "x"}])
    assert e.value.code == "AI_REFUSED"


def test_claude_outage_falls_back_to_gpt(fake_claude, monkeypatch):
    fake_claude.error = anthropic.APIConnectionError(request=None)
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt")
    monkeypatch.setattr(llm, "_gpt_chain", lambda messages, max_tokens: "GPT 답")
    assert llm.chat_completion([{"role": "user", "content": "x"}]) == "GPT 답"


def test_claude_outage_without_gpt_key_reports_error(fake_claude, monkeypatch):
    fake_claude.error = anthropic.APIConnectionError(request=None)
    monkeypatch.delenv("GPT_ASTRA_API_KEY", raising=False)
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "x"}])
    assert e.value.code == "AI_ERROR"


def test_stream_yields_pieces(fake_claude):
    fake_claude.pieces = ["[1] ", "봄 ", "풍경"]
    assert list(llm.stream_completion([{"role": "user", "content": "x"}])) == ["[1] ", "봄 ", "풍경"]


def test_without_anthropic_key_gpt_path_is_unchanged(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_gpt_chain", lambda messages, max_tokens: "GPT 답")
    assert llm.chat_completion([{"role": "user", "content": "x"}]) == "GPT 답"
    assert list(llm.stream_completion([{"role": "user", "content": "x"}])) == ["GPT 답"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db.reset_for_tests()
    c = TestClient(app)
    c.post("/api/auth/signup", json={"email": "s@t.com", "password": "password123"})
    return c


def _events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_chat_stream_sends_cards_first_then_text_then_saves(client, monkeypatch):
    intent = '{"chitchat": false, "keywords": ["landscape"], "artist": null, "year_from": null, "year_to": null}'
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: intent)
    monkeypatch.setattr(llm, "stream_completion", lambda *a, **k: iter(["[1] 봄 ", "풍경입니다."]))
    resp = client.post("/api/chat/stream", json={"message": "봄 풍경"})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/x-ndjson")
    events = _events(resp)
    assert [e["type"] for e in events] == ["meta", "delta", "delta", "done"]
    assert events[0]["artworks"] and events[0]["search"]["keywords"] == ["landscape"]
    assert events[-1]["saved"] is True
    chats = client.get("/api/me/chats").json()
    assert chats["chats"][0]["answer"] == "[1] 봄 풍경입니다."


def test_chat_stream_requires_login(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "app.db"))
    db.reset_for_tests()
    assert TestClient(app).post("/api/chat/stream", json={"message": "봄"}).status_code == 401


def test_chat_stream_reports_error_mid_answer(client, monkeypatch):
    intent = '{"chitchat": false, "keywords": ["landscape"], "artist": null, "year_from": null, "year_to": null}'
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: intent)

    def broken(*a, **k):
        yield "[1] "
        raise AIUnavailableError("AI_TIMEOUT", "응답이 지연되고 있어요.")
    monkeypatch.setattr(llm, "stream_completion", broken)
    events = _events(client.post("/api/chat/stream", json={"message": "봄 풍경"}))
    assert events[-1] == {"type": "error", "code": "AI_TIMEOUT", "message": "응답이 지연되고 있어요."}


def test_chat_stream_intent_failure_returns_plain_error(client, monkeypatch):
    def boom(*a, **k):
        raise AIUnavailableError("AI_RATE_LIMITED", "잠시 제한")
    monkeypatch.setattr(llm, "chat_completion", boom)
    resp = client.post("/api/chat/stream", json={"message": "봄 풍경"})
    assert resp.status_code == 429 and resp.json()["error"]["code"] == "AI_RATE_LIMITED"


def _credit_error():
    import httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(400, request=req)
    return anthropic.BadRequestError("Your credit balance is too low to access the Anthropic API.",
                                     response=resp, body=None)


def test_claude_credit_exhausted_goes_straight_to_solar(fake_claude, monkeypatch):
    fake_claude.error = _credit_error()
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt")
    monkeypatch.setenv("UPSTAGE_API_KEY", "solar")
    monkeypatch.setattr(llm, "_gpt_chain", lambda *a: pytest.fail("Claude가 소진되면 GPT가 아니라 solar가 받는다"))
    monkeypatch.setattr(llm, "_upstage_chat_completion", lambda messages, max_tokens, deadline: "solar 답")
    assert llm.chat_completion([{"role": "user", "content": "x"}]) == "solar 답"
    assert list(llm.stream_completion([{"role": "user", "content": "x"}])) == ["solar 답"]


def test_claude_rate_limit_without_solar_key_uses_gpt(fake_claude, monkeypatch):
    fake_claude.error = anthropic.APIConnectionError(request=None)
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt")
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_gpt_chain", lambda messages, max_tokens: "GPT 답")
    assert llm.chat_completion([{"role": "user", "content": "x"}]) == "GPT 답"


def test_credit_error_is_reported_as_exhausted():
    assert claude_llm._as_unavailable(_credit_error()).code == "AI_KEY_MISSING"


def test_same_question_reuses_intent_without_calling_ai(fake_claude):
    fake_claude.response = _response('{"chitchat": false, "keywords": ["sunflower"], "artist": null, '
                                     '"year_from": null, "year_to": null, "orientation": null, "purpose": null}')
    first = chat.extract_intent("고흐 해바라기")
    first["keywords"].append("changed")   # 호출부가 고쳐도
    second = chat.extract_intent("  고흐   해바라기 ")
    assert len(fake_claude.calls) == 1 and second["keywords"] == ["sunflower"]
