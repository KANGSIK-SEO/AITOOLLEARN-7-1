"""설명 페이지(app/static/explain.html)의 질문 입력창과 전송 버튼에 보조 기기가 읽을 이름(aria-label)이 있는지 확인한다.

품질 점검 이슈: 입력창에 placeholder만 있고 label·aria-label이 없어 스크린리더가 이름을 읽지 못했다
(WCAG 1.3.1/4.1.2). 전송 버튼도 title만 있고 aria-label이 없었다.
파이썬 표준 HTML 파서로 정적 파일만 읽는다 — 서버·AI·외부 서비스를 부르지 않는다.
"""
from html.parser import HTMLParser
from pathlib import Path

EXPLAIN_HTML = Path(__file__).resolve().parent.parent / "app" / "static" / "explain.html"


class _ElementsById(HTMLParser):
    """id가 있는 요소를 {id: (태그, 속성 dict)}로 모은다."""

    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, tuple[str, dict]] = {}

    def handle_starttag(self, tag, attrs):
        attributes = {name: (value or "") for name, value in attrs}
        element_id = attributes.get("id")
        if element_id:
            self.by_id[element_id] = (tag, attributes)


def _elements() -> dict[str, tuple[str, dict]]:
    parser = _ElementsById()
    parser.feed(EXPLAIN_HTML.read_text(encoding="utf-8"))
    return parser.by_id


def test_question_input_has_accessible_name():
    elements = _elements()
    assert "question-input" in elements, "explain.js가 쓰는 입력창 id가 사라지면 안 된다"
    tag, attrs = elements["question-input"]
    assert tag == "input"
    assert attrs.get("aria-label", "").strip(), "입력창에 aria-label이 있어야 스크린리더가 이름을 읽는다"
    # placeholder는 그대로 두어 눈으로 보는 안내도 유지된다
    assert attrs.get("placeholder", "").strip()


def test_send_button_has_accessible_name():
    elements = _elements()
    assert "send-btn" in elements, "explain.js가 쓰는 전송 버튼 id가 사라지면 안 된다"
    tag, attrs = elements["send-btn"]
    assert tag == "button"
    assert attrs.get("aria-label", "").strip(), "전송 버튼은 title만으로는 부족하다 — aria-label이 있어야 한다"
    assert attrs.get("type") == "submit"


def test_input_is_not_required():
    """빈 입력은 explain.js가 이미 막는다 — required를 넣으면 브라우저 기본 풍선이 겹치므로 그대로 둔다."""
    _, attrs = _elements()["question-input"]
    assert "required" not in attrs
