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


# ---- 재시도·시간 예산 ----
@pytest.fixture()
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "gpt-key")
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    return slept


def _flaky(errors, final="ok"):
    """errors를 순서대로 던진 뒤 성공하는 urlopen. 호출된 timeout도 기록한다."""
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(timeout)
        if len(calls) <= len(errors):
            err = errors[len(calls) - 1]
            raise err(req) if callable(err) else err
        return FakeResp(_reply(final))
    return fake_urlopen, calls


def _http(code):
    return lambda req: urllib.error.HTTPError(req.full_url, code, "err", {}, None)


@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_retries_once_on_server_error_then_succeeds(monkeypatch, no_sleep, code):
    fake, calls = _flaky([_http(code)])
    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake)
    assert llm.chat_completion([{"role": "user", "content": "hi"}]) == "ok"
    assert len(calls) == 2 and no_sleep == [llm.RETRY_BACKOFF_SECONDS]


def test_retries_on_connection_error(monkeypatch, no_sleep):
    fake, calls = _flaky([urllib.error.URLError(ConnectionResetError("reset"))])
    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake)
    assert llm.chat_completion([{"role": "user", "content": "hi"}]) == "ok"
    assert len(calls) == 2


def test_gives_up_after_max_retries(monkeypatch, no_sleep):
    fake, calls = _flaky([_http(503), _http(503), _http(503)])
    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "hi"}])
    assert e.value.code == "AI_ERROR" and len(calls) == 1 + llm.LLM_MAX_RETRIES


@pytest.mark.parametrize("err, code", [
    (_http(400), "AI_ERROR"),
    (_http(401), "AI_KEY_MISSING"),
    (_http(429), "AI_RATE_LIMITED"),
    (TimeoutError(), "AI_TIMEOUT"),
    (urllib.error.URLError(TimeoutError()), "AI_TIMEOUT"),
])
def test_does_not_retry_non_transient_errors(monkeypatch, no_sleep, err, code):
    fake, calls = _flaky([err, err])
    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "hi"}])
    assert e.value.code == code and len(calls) == 1 and no_sleep == []


def test_socket_timeout_is_capped_by_remaining_budget(monkeypatch, no_sleep):
    monkeypatch.setattr(llm, "LLM_CALL_BUDGET_SECONDS", 5)
    fake, calls = _flaky([])
    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake)
    llm.chat_completion([{"role": "user", "content": "hi"}])
    assert calls[0] <= 5  # LLM_TIMEOUT_SECONDS(20)가 아니라 남은 예산


def test_no_new_attempt_when_budget_is_exhausted(monkeypatch, no_sleep):
    """예산이 부족하면 재시도를 시작하지 않고 AI_TIMEOUT으로 끝낸다."""
    clock = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])

    def slow_503(req, timeout=0):
        clock[0] += 24  # 예산 25초 중 24초를 쓰고 503
        raise urllib.error.HTTPError(req.full_url, 503, "err", {}, None)

    monkeypatch.setattr(llm, "LLM_CALL_BUDGET_SECONDS", 25)
    monkeypatch.setattr("app.llm.urllib.request.urlopen", slow_503)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "hi"}])
    assert e.value.code == "AI_TIMEOUT" and no_sleep == []


def test_fallback_shares_the_same_budget(monkeypatch, no_sleep):
    """OpenAI 429에 시간을 다 쓰면 Upstage 폴백도 시작하지 않는다."""
    monkeypatch.setenv("UPSTAGE_API_KEY", "up-key")
    clock = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])
    urls = []

    def fake(req, timeout=0):
        urls.append(req.full_url)
        clock[0] += 24
        raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, None)

    monkeypatch.setattr(llm, "LLM_CALL_BUDGET_SECONDS", 25)
    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake)
    with pytest.raises(AIUnavailableError) as e:
        llm.chat_completion([{"role": "user", "content": "hi"}])
    assert e.value.code == "AI_TIMEOUT" and len(urls) == 1 and "openai" in urls[0]


def test_retry_is_logged(monkeypatch, no_sleep, caplog):
    import logging
    fake, _ = _flaky([_http(502)])
    monkeypatch.setattr("app.llm.urllib.request.urlopen", fake)
    with caplog.at_level(logging.WARNING, logger="app.llm"):
        llm.chat_completion([{"role": "user", "content": "hi"}])
    assert any(r.getMessage().startswith("llm_retry provider=openai attempt=1 reason=http_502") for r in caplog.records)
