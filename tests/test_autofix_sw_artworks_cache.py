"""artworks.json 서비스워커 캐시 갱신 (품질 이슈: 작품 DB를 재수집해도 설치된 브라우저가 옛 데이터로 추천).

서비스워커(app/static/sw.js)는 정적 파일을 캐시 우선으로 돌려주고 캐시 이름(ASSET_VERSION)이 바뀔 때만 비운다.
artworks.json은 그 버전 계산에 들어가지 않으므로 네트워크 우선으로 받아야 한다 — 파일 내용을 읽어 확인한다.
(실제 AI·외부 서비스는 부르지 않는다.)
"""
from pathlib import Path

SW_PATH = Path(__file__).resolve().parent.parent / "app" / "static" / "sw.js"
ARTWORKS = "/static/artworks.json"


def _sw() -> str:
    return SW_PATH.read_text(encoding="utf-8")


def _fetch_handler(text: str) -> str:
    marker = "addEventListener('fetch'"
    assert marker in text, "sw.js에 fetch 처리기가 있어야 한다"
    return text[text.index(marker):]


def test_artworks_json_listed_as_network_first():
    text = _sw()
    assert "NETWORK_FIRST" in text, "네트워크 우선 목록이 없으면 artworks.json이 영원히 캐시본으로 남는다"
    definition = text[text.index("NETWORK_FIRST"):]
    definition = definition[:definition.index("\n")]
    assert f"'{ARTWORKS}'" in definition, "artworks.json이 네트워크 우선 목록에 들어 있어야 한다"
    # 목록은 처리기보다 먼저 정의돼 있어야 한다
    assert text.index("const NETWORK_FIRST") < text.index("addEventListener('fetch'")


def test_fetch_handler_skips_cache_for_network_first():
    handler = _fetch_handler(_sw())
    assert "NETWORK_FIRST.has(url.pathname)" in handler, "fetch 처리기가 네트워크 우선 목록을 봐야 한다"
    # 네트워크 우선이면 캐시를 먼저 보지 않는다 (캐시 우선 분기를 건너뛴다)
    branch = handler[handler.index("NETWORK_FIRST.has(url.pathname)"):]
    branch = branch[:branch.index("\n")]
    assert "Promise.resolve(undefined)" in branch and "caches.match(request)" in branch


def test_network_first_updates_cache_and_falls_back_offline():
    handler = _fetch_handler(_sw())
    tail = handler[handler.index("NETWORK_FIRST.has(url.pathname)"):]
    # 성공하면 새 내용으로 캐시를 갱신한다 → 다음 오프라인에도 최신 데이터를 쓴다
    assert "cache.put(request, copy)" in tail
    # 실패(오프라인)하면 캐시본으로 되돌아간다
    assert ".catch(" in tail and tail.index(".catch(") < tail.rindex("caches.match(request)")


def test_other_rules_unchanged():
    """API·외부 요청은 여전히 가로채지 않고, 문서는 네트워크 우선 + 오프라인 페이지 대체 그대로."""
    handler = _fetch_handler(_sw())
    assert "url.pathname.startsWith('/api/')" in handler
    assert "url.origin !== self.location.origin" in handler
    assert "request.mode === 'navigate'" in handler
    assert "caches.match(OFFLINE_URL)" in handler
