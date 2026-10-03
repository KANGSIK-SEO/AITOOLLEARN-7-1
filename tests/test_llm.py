import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import llm  # noqa: E402
from app.config import AIUnavailableError  # noqa: E402


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def _reply(text):
    return {"choices": [{"message": {"content": text}}]}


def test_uses_openai_when_it_succeeds(monkeypatch):
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt-key")
    monkeypatch.setenv("UPSTAGE_API_KEY", "up-key")

    def fake_urlopen(req, timeout=0):
        assert "api.openai.com" in req.full_url
        return FakeResp(_reply("gpt said hi"))

    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake_urlopen)
    assert llm.chat_completion([{"role": "user", "content": "hi"}]) == "gpt said hi"


def test_falls_back_to_upstage_on_429(monkeypatch):
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt-key")
    monkeypatch.setenv("UPSTAGE_API_KEY", "up-key")
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if "api.openai.com" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 429, "rate limited", {}, None)
        return FakeResp(_reply("solar said hi"))

    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake_urlopen)
    assert llm.chat_completion([{"role": "user", "content": "hi"}]) == "solar said hi"
    assert any("api.openai.com" in c for c in calls) and any("api.upstage.ai" in c for c in calls)


def test_no_fallback_without_upstage_key(monkeypatch):
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt-key")
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 429, "rate limited", {}, None)

    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "hi"}])
    assert e.value.code == "AI_RATE_LIMITED"


def test_no_fallback_on_plain_timeout(monkeypatch):
    """타임아웃은 '소진' 신호가 아니므로 폴백하지 않는다."""
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt-key")
    monkeypatch.setenv("UPSTAGE_API_KEY", "up-key")
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        raise TimeoutError()

    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "hi"}])
    assert e.value.code == "AI_TIMEOUT" and len(calls) == 1
