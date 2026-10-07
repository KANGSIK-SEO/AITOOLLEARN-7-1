import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import config  # noqa: E402
from app.config import ConfigError  # noqa: E402

GOOD_SECRET = "x" * 32


@pytest.fixture()
def env(monkeypatch):
    """검증에 쓰이는 환경변수를 정상값으로 맞춰 두고, 테스트마다 하나씩 망가뜨린다."""
    monkeypatch.setenv("SECRET_KEY", GOOD_SECRET)
    monkeypatch.setenv("GPT_ASTRA_API_KEY", "sk-test")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.setattr(config, "CRON_SECRET", "cron")
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "low")
    return monkeypatch


def test_valid_env_has_no_errors_or_warnings(env):
    assert config.validate_env() == []


@pytest.mark.parametrize("value, expected", [
    ("", "SECRET_KEY가 없습니다"),
    ("short", r"SECRET_KEY가 너무 짧습니다 \(5자"),
])
def test_missing_or_short_secret_key(env, value, expected):
    env.setenv("SECRET_KEY", value)
    with pytest.raises(ConfigError, match=expected):
        config.validate_env()


def test_turso_url_without_token(env):
    env.setenv("TURSO_DATABASE_URL", "libsql://db.turso.io")
    with pytest.raises(ConfigError, match="TURSO_AUTH_TOKEN이 없습니다"):
        config.validate_env()
    env.setenv("TURSO_AUTH_TOKEN", "token")
    assert config.validate_env() == []


def test_invalid_reasoning_effort(env):
    env.setattr(config, "LLM_REASONING_EFFORT", "ultra")
    with pytest.raises(ConfigError, match="LLM_REASONING_EFFORT.*'ultra'"):
        config.validate_env()


def test_all_errors_are_reported_at_once(env):
    env.delenv("SECRET_KEY")
    env.setenv("TURSO_DATABASE_URL", "libsql://db.turso.io")
    with pytest.raises(ConfigError) as exc:
        config.validate_env()
    assert "SECRET_KEY" in str(exc.value) and "TURSO_AUTH_TOKEN" in str(exc.value)


def test_missing_ai_key_and_cron_secret_are_warnings(env):
    env.delenv("GPT_ASTRA_API_KEY")
    env.setattr(config, "CRON_SECRET", "")
    warnings = config.validate_env()
    assert len(warnings) == 2
    assert "GPT_ASTRA_API_KEY" in warnings[0] and "503" in warnings[0]
    assert "CRON_SECRET" in warnings[1]
    env.setenv("UPSTAGE_API_KEY", "up-test")
    assert "폴백으로 동작" in config.validate_env()[0]


@pytest.mark.parametrize("raw, cast, minimum, expected", [
    ("abc", int, None, "정수여야 합니다 \\(현재 값: 'abc'\\)"),
    ("1.5", int, None, "정수여야 합니다"),
    ("fast", float, None, "숫자여야 합니다"),
    ("-1", int, 0, "0 이상이어야 합니다"),
])
def test_env_number_rejects_bad_values_with_clear_message(monkeypatch, raw, cast, minimum, expected):
    monkeypatch.setenv("SOME_LIMIT", raw)
    with pytest.raises(ConfigError, match=f"SOME_LIMIT.*{expected}"):
        config._env_number("SOME_LIMIT", "10", cast, minimum)


def test_env_number_uses_default_when_empty(monkeypatch):
    monkeypatch.setenv("SOME_LIMIT", "  ")
    assert config._env_number("SOME_LIMIT", "10", int) == 10
    monkeypatch.setenv("SOME_LIMIT", "25")
    assert config._env_number("SOME_LIMIT", "10", int, minimum=1) == 25
