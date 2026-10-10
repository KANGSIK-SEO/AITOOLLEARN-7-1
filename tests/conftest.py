"""모든 테스트 공통: 진짜 외부 서비스에 닿지 않게 한다.

테스트는 '심각한 사건'을 일부러 만들어 가디언 즉시 분석을 흉내 낸다. 실행하는 컴퓨터에 GITHUB_TOKEN이나
AI 키가 있으면 진짜 GitHub 이슈가 열리고(→ 자동 수정 워크플로까지 깨움) 진짜 AI가 불린다.
2026-10-08 실제로 그렇게 이슈 수십 개가 열린 일이 있어, 여기서 모든 테스트에 대해 막는다.
"""
import os

import pytest

from app import chat, db, guardian

# TEST_DATABASE_URL을 주면 모든 테스트를 진짜 Postgres에서 돌린다 (CI의 postgres 서비스, 로컬은 PGlite 등).
# 없으면 테스트마다 임시 SQLite 파일을 쓴다. 개발 PC에 운영 DATABASE_URL이 있어도 테스트는 절대 닿지 않는다.
_TEST_PG = os.environ.get("TEST_DATABASE_URL", "").strip()

_REAL_KEYS = ("GITHUB_TOKEN", "ANTHROPIC_API_KEY", "GPT_ASTRA_API_KEY", "UPSTAGE_API_KEY",
              "IA_ACCESS_KEY", "IA_SECRET_KEY")


@pytest.fixture(autouse=True)
def no_real_outside_calls(monkeypatch):
    for key in _REAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(guardian, "open_github_issue", lambda title, body, labels=None: None)
    chat.clear_intent_cache()   # 테스트마다 가짜 AI가 다르므로 기억해 둔 검색 조건을 비운다


@pytest.fixture(autouse=True)
def database_backend(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if _TEST_PG:
        monkeypatch.setenv("DATABASE_URL", _TEST_PG)
        db.reset_for_tests()
        guardian._blocks["source"] = None   # 주소가 테스트마다 같으므로 차단 목록 기억을 비운다
        db._raw_execute("DROP SCHEMA IF EXISTS public CASCADE")
        db._raw_execute("CREATE SCHEMA public")
    yield
    db.reset_for_tests()
