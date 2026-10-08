"""모든 테스트 공통: 진짜 외부 서비스에 닿지 않게 한다.

테스트는 '심각한 사건'을 일부러 만들어 가디언 즉시 분석을 흉내 낸다. 실행하는 컴퓨터에 GITHUB_TOKEN이나
AI 키가 있으면 진짜 GitHub 이슈가 열리고(→ 자동 수정 워크플로까지 깨움) 진짜 AI가 불린다.
2026-10-08 실제로 그렇게 이슈 수십 개가 열린 일이 있어, 여기서 모든 테스트에 대해 막는다.
"""
import pytest

from app import guardian

_REAL_KEYS = ("GITHUB_TOKEN", "ANTHROPIC_API_KEY", "GPT_ASTRA_API_KEY", "UPSTAGE_API_KEY",
              "IA_ACCESS_KEY", "IA_SECRET_KEY")


@pytest.fixture(autouse=True)
def no_real_outside_calls(monkeypatch):
    for key in _REAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(guardian, "open_github_issue", lambda title, body: None)
