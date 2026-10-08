"""[품질] 본문 건너뛰기 링크 — 키보드(Tab) 사용자가 헤더 버튼을 거치지 않고 로그인 폼/채팅 입력으로 바로 갈 수 있어야 한다.

정적 파일만 읽어 확인한다 (서버·AI·외부 서비스 호출 없음)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


def _first_body_element() -> str:
    """<body> 다음에 오는 첫 번째 요소 태그 (주석은 건너뛴다)."""
    after_body = INDEX.split("<body", 1)[1].split(">", 1)[1]
    after_body = re.sub(r"<!--.*?-->", "", after_body, flags=re.DOTALL)
    m = re.search(r"<[a-zA-Z][^>]*>", after_body)
    assert m, "<body> 아래에 요소가 없다"
    return m.group(0)


def test_skip_link_is_first_element_in_body():
    first = _first_body_element()
    assert first.startswith("<a "), f"body의 첫 요소가 건너뛰기 링크(a)가 아니다: {first}"
    assert 'class="skip-link"' in first
    assert 'id="skip-link"' in first
    href = re.search(r'href="([^"]+)"', first).group(1)
    assert href in ("#chat-panel", "#auth-panel"), href


def test_skip_link_has_bilingual_label():
    m = re.search(r'<a[^>]*class="skip-link"[^>]*>(.*?)</a>', INDEX, flags=re.DOTALL)
    assert m
    label = m.group(1)
    assert "건너뛰기" in label and "Skip" in label


def test_skip_targets_exist_and_can_receive_focus():
    """목적지 패널이 실제로 있고 tabindex="-1"이라 건너뛴 뒤 포커스가 그 안으로 이어진다."""
    for panel_id in ("auth-panel", "chat-panel"):
        m = re.search(rf'<section[^>]*id="{panel_id}"[^>]*>', INDEX)
        assert m, f"{panel_id} 섹션이 없다"
        assert 'tabindex="-1"' in m.group(0), f"{panel_id}에 tabindex=-1이 없다"


def test_skip_link_hidden_until_focused_in_css():
    base = re.search(r"\.skip-link\s*\{([^}]*)\}", CSS)
    assert base, "style.css에 .skip-link 규칙이 없다"
    assert "position: absolute" in base.group(1)
    assert re.search(r"left:\s*-\d+px", base.group(1)), "평소에는 화면 밖(left 음수)에 있어야 한다"
    focus = re.search(r"\.skip-link:focus\s*\{([^}]*)\}", CSS)
    assert focus, "style.css에 .skip-link:focus 규칙이 없다"
    assert re.search(r"left:\s*\d+px", focus.group(1)), "포커스되면 화면 안으로 들어와야 한다"
    assert "outline" in focus.group(1), "포커스 표시(outline)가 있어야 한다"


def test_js_points_skip_link_at_visible_panel():
    """로그인 전에는 로그인 폼(#auth-panel), 후에는 채팅(#chat-panel)으로 — 숨겨진 패널로 보내지 않는다."""
    show_fn = JS.split("function show(", 1)[1].split("\nasync function api(", 1)[0]
    assert 'skip-link' in show_fn
    assert '"#chat-panel"' in show_fn and '"#auth-panel"' in show_fn
