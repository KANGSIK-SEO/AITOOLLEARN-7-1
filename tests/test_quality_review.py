"""품질 자동 점검(scripts/quality_review.py): 판정을 보고서·수정 이슈로 바꾸는 부분과 AI 호출 형식을 확인한다."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import quality_review as q  # noqa: E402

RESULT = {
    "summary": "대체로 양호",
    "capacity": {"status": "ok", "reason": "요청이 적음"},
    "items": [
        {"section": "웹 표준", "question": "파비콘?", "status": "ok", "evidence": "index.html | icon", "action": "", "title": ""},
        {"section": "확장성", "question": "캐시?", "status": "fix", "evidence": "app.js에 캐시 헤더 없음",
         "action": "정적 파일에 Cache-Control", "title": "정적 파일 캐시 헤더 없음"},
        {"section": "확장성", "question": "플랜?", "status": "manual", "evidence": "-", "action": "Vercel 설정", "title": "x"},
        {"section": "LLM", "question": "?", "status": "fix", "evidence": "-", "action": "-", "title": ""},
    ],
}


def test_render_lists_every_item_and_only_titled_fixes_become_issues():
    report, fixes = q.render(RESULT, "claude-haiku-5-5")
    assert "✅ 괜찮음 1" in report and "🛠️ 자동 수정 대상 2" in report and "👤 사람 확인 1" in report
    assert "index.html \\| icon" in report  # 표가 깨지지 않게 | 를 바꾼다
    assert [f["title"] for f in fixes] == ["[품질] 정적 파일 캐시 헤더 없음"]  # 제목 없는 fix·manual은 이슈로 안 연다
    assert "정적 파일에 Cache-Control" in fixes[0]["body"]


def test_html_facts_finds_standards_evidence():
    html = ('<html lang="ko"><head><meta name="viewport" content="x"><meta property="og:title" content="t">'
            '<link rel="icon" href="/f.png"></head><body><img src="a.png"><button>보내기</button></body></html>')
    facts = q.html_facts(html)
    assert facts["lang"] == "ko" and facts["viewport"] and facts["favicon"]
    assert facts["og"] == ["og:title"] and facts["img_without_alt"] == 1 and facts["buttons"] == 1


def test_prompt_has_checklist_live_data_and_no_artwork_dump():
    prompt = q.build_prompt("체크리스트 본문", {"/": {"status": 200}}, {"api_requests": 3})
    assert "체크리스트 본문" in prompt and '"api_requests": 3' in prompt
    assert "===== app/static/artworks.json" not in prompt and "===== app/main.py" in prompt
    editable = prompt.split("<editable>")[1].split("</editable>")[0]
    assert "app/main.py" in editable and "app/auth.py" not in editable  # 보호 파일은 고칠 수 있는 목록에 없다


def test_ask_claude_uses_cheapest_model_and_json_schema(monkeypatch):
    monkeypatch.delenv("QUALITY_MODEL", raising=False)
    calls = []

    class Stream:
        def __init__(self, **params):
            calls.append(params)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=json.dumps(RESULT))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **p: Stream(**p))))
    assert q.ask_claude("p", client)["summary"] == "대체로 양호"
    assert calls[0]["model"] == "claude-haiku-5-5"
    assert calls[0]["output_config"]["format"]["schema"] is q.OUTPUT_SCHEMA
