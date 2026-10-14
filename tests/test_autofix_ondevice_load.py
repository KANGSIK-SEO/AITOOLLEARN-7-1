"""온디바이스 추천: 작품 데이터(artworks.json)를 못 받았을 때(오프라인·서버 오류) 화면이
'작품 데이터를 불러오는 중…'에 영원히 멈추지 않고 실패 안내를 보여주는지 확인한다.

브라우저 없이 화면 파일(app/static/ondevice.js, app/static/app.js)의 내용을 읽어 검사한다.
외부 서비스·AI는 부르지 않는다.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
ONDEVICE_JS = (STATIC / "ondevice.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    """start 표시 뒤부터 end 표시 앞까지 (함수 하나의 본문을 잘라 보기 위함)."""
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


def _load_facts_body() -> str:
    return _between(ONDEVICE_JS, "async function loadFacts()", "function yearConds")


def test_load_facts_rejects_error_responses():
    """서버가 404·5xx를 주면 본문을 JSON으로 읽으려다 알 수 없는 오류가 나는 대신, 분명한 실패로 끝낸다."""
    body = _load_facts_body()
    assert "if (!res.ok) throw" in body


def test_load_facts_caches_only_after_success():
    """응답 확인 전에는 factsCache에 담지 않는다 → 실패 뒤 다시 열면 다시 받는다."""
    body = _load_facts_body()
    assert body.index("if (!res.ok)") < body.index("factsCache = ")


def test_open_lab_handles_load_failure():
    """창을 열 때 데이터 읽기가 실패하면 try/catch로 잡아 실패 문구를 보여주고, 준비 상태는 true로 바꾸지 않는다."""
    body = _between(APP_JS, "async function openLab()", "function parseOnDevice")
    assert "try {" in body and "catch" in body
    assert body.index("try {") < body.index("OnDevice.loadFacts()") < body.index("catch")
    assert "labLoadFail" in body or "showOnDeviceLoadFailure" in body
    # 실패 뒤(return) 준비 완료 표시가 오면 안 된다 — 성공 경로에서만 onDeviceReady = true
    assert body.index("catch") < body.index("state.onDeviceReady = true")


def test_run_on_device_handles_load_failure():
    body = _between(APP_JS, "async function runOnDevice()", "// 11. 상단 바")
    assert "try {" in body and "catch" in body
    assert body.index("try {") < body.index("OnDevice.loadFacts()") < body.index("catch")
    assert "labLoadFail" in body or "showOnDeviceLoadFailure" in body


def test_failure_helper_writes_preview_and_toast():
    body = _between(APP_JS, "function showOnDeviceLoadFailure()", "async function openLab()")
    assert 'od-rule-preview' in body
    assert 't("labLoadFail")' in body
    assert "toast(" in body


def test_i18n_has_load_fail_message_in_both_languages():
    ko = _between(APP_JS, "    ko: {", "    en: {")
    en = _between(APP_JS, "    en: {", "const CLIENT_TIMEOUT_MS")
    assert "labLoadFail:" in ko
    assert "labLoadFail:" in en
    assert "작품 데이터를 불러오지 못했어요" in ko
    assert "Couldn't load artwork data" in en
