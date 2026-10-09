"""서비스 품질 자동 점검 — docs/review-checklist.md의 질문마다 Claude가 코드와 운영 사이트를 보고 판정한다.

사용 (GitHub Actions quality-review.yml 안에서):
    python3 scripts/quality_review.py <보고서 파일.md> <수정할 항목 파일.json> <용량 판정 파일.json>
필요: ANTHROPIC_API_KEY. 선택: SITE_URL(운영 주소), CRON_SECRET(운영 요약 읽기), QUALITY_MODEL(기본 claude-haiku-5-5).

판정:
- ok: 이미 잘 되어 있음
- fix: 고칠 수 있는 파일(app/*.py, app/routers/*.py, app/static/*.js|css|html) 안에서 코드로 고칠 수 있음 → 워크플로가 [품질] 이슈를 열고
  자동 수정(Claude Fable)을 부른다. 수정 PR은 주인이 승인해야 배포된다.
- manual: 사람이 해야 함(Vercel 설정·플랜, 비밀 값, 보호 파일, 발표용 설명) → 보고서에만 남긴다.
용량 판정이 upgrade면 워크플로가 [용량] 이슈를 연다 (Vercel 플랜 결제는 사람이 한다).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from autofix_propose import EDITABLE_RE  # noqa: E402
from autofix_guard import PROTECTED  # noqa: E402

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_SITE = "https://art-chatbot-eight.vercel.app"
CONTEXT_FILES = ("app/*.py", "app/routers/*.py", "app/static/*.js", "app/static/*.html", "app/static/*.css", "app/static/*.json",
                 "vercel.json", "db/schema.sql", "requirements.txt", "README.md", "docs/llm-eval.md")
SKIP_FILES = {"app/static/artworks.json"}  # 작품 데이터 2MB — 코드가 아니다
PROBE_PATHS = ("/", "/static/app.js", "/static/style.css", "/sw.js", "/static/manifest.json", "/healthz")
STATUSES = ("ok", "fix", "manual")

SYSTEM = """너는 웹서비스 'AITOOLLEARN-7-1'(퍼블릭 도메인 명화 찾기 챗봇, FastAPI + Vercel)의 품질 점검관이다.
<checklist>의 질문마다 <source>(코드), <live>(운영 사이트에 실제로 요청한 결과), <ops>(최근 24시간 운영 요약)를 근거로 판정한다.

판정 기준:
- ok: 코드나 운영 결과에 근거가 있고 문제가 없다. evidence에 파일·함수·헤더 같은 구체적 근거를 쓴다.
- fix: 문제가 있고, <editable>에 있는 파일만 고쳐서 해결할 수 있다. action에 무엇을 어떻게 고칠지 구체적으로 쓴다.
- manual: 문제가 있지만 사람이 해야 한다 (보호 파일 <protected> 수정, Vercel 설정·플랜, 비밀 값, 외부 서비스 계약).
- 설명형 질문(무엇을 해결하는가, await란 무엇인가, UI와 UX의 차이 등)은 코드에 근거가 있으면 ok로 두고
  evidence에 발표 때 쓸 수 있는 짧은 답을 쓴다.
- 확실한 문제만 fix로 둔다. 취향 차이·대규모 재설계는 fix가 아니다. 한 항목의 fix는 400줄 이하로 고칠 수 있어야 한다.
- title은 같은 문제면 매번 똑같이 나오도록 짧고 구체적으로 쓴다 (예: "정적 파일 캐시 헤더 없음"). fix가 아니면 빈 문자열.

capacity: <ops>와 <live>의 응답 시간·오류로 서버 부하를 판정한다.
- ok: 여유 있음 / watch: 지켜볼 필요 / upgrade: 플랜 한도 때문에 사용자가 실제로 느려지거나 실패한다는 근거가 있음.
- 요청 수가 적거나 근거가 없으면 upgrade로 두지 않는다.

모든 글은 한국어로, 코드를 모르는 사람도 이해하게 쓴다."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},
                    "question": {"type": "string"},
                    "status": {"type": "string", "enum": list(STATUSES)},
                    "evidence": {"type": "string"},
                    "action": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["section", "question", "status", "evidence", "action", "title"],
                "additionalProperties": False,
            },
        },
        "capacity": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok", "watch", "upgrade"]},
                           "reason": {"type": "string"}},
            "required": ["status", "reason"],
            "additionalProperties": False,
        },
    },
    "required": ["summary", "items", "capacity"],
    "additionalProperties": False,
}


def _get(url: str, headers: dict | None = None) -> dict:
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "quality-review", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(200_000).decode("utf-8", "replace")
            status, hdrs = resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body, status, hdrs = "", e.code, dict(e.headers)
    except (urllib.error.URLError, TimeoutError) as e:
        return {"error": str(e)[:200]}
    keep = {k: v for k, v in hdrs.items() if k.lower() in (
        "cache-control", "etag", "last-modified", "content-type", "content-encoding", "age", "x-vercel-cache",
        "strict-transport-security", "content-security-policy", "x-content-type-options", "x-frame-options",
        "referrer-policy")}
    return {"status": status, "ms": int((time.monotonic() - started) * 1000), "headers": keep, "body": body}


def html_facts(html: str) -> dict:
    """첫 화면 HTML에서 웹 표준·오픈그래프·파비콘 근거를 뽑는다."""
    def has(pattern: str) -> bool:
        return bool(re.search(pattern, html, re.IGNORECASE))
    return {
        "lang": (re.search(r"<html[^>]*\blang=\"([^\"]+)\"", html, re.IGNORECASE) or [None, None])[1],
        "viewport": has(r"<meta[^>]+name=\"viewport\""),
        "description": has(r"<meta[^>]+name=\"description\""),
        "og": sorted(set(re.findall(r"property=\"(og:[a-z_:]+)\"", html, re.IGNORECASE))),
        "twitter": sorted(set(re.findall(r"name=\"(twitter:[a-z_:]+)\"", html, re.IGNORECASE))),
        "favicon": has(r"<link[^>]+rel=\"[^\"]*icon[^\"]*\""),
        "manifest": has(r"<link[^>]+rel=\"manifest\""),
        "img_without_alt": len(re.findall(r"<img(?![^>]*\balt=)[^>]*>", html, re.IGNORECASE)),
        "buttons": len(re.findall(r"<button\b", html, re.IGNORECASE)),
        "clickable_divs": len(re.findall(r"<(div|span)[^>]*\bonclick=", html, re.IGNORECASE)),
        "aria_live": has(r"aria-live="),
        "skip_link": has(r"href=\"#(main|content)"),
    }


def probe(site: str, cron_secret: str) -> tuple[dict, dict]:
    live: dict = {}
    for path in PROBE_PATHS:
        r = _get(site + path)
        if path == "/" and "body" in r:
            live["html"] = html_facts(r["body"])
        r.pop("body", None)
        live[path] = r
    live["healthz_ms"] = [_get(site + "/healthz").get("ms") for _ in range(5)]
    ops: dict = {"note": "CRON_SECRET이 없어 운영 요약을 읽지 못함"}
    if cron_secret:
        r = _get(site + "/api/guardian/summary", {"Authorization": f"Bearer {cron_secret}"})
        try:
            ops = json.loads(r.get("body") or "{}") if r.get("status") == 200 else {"error": r.get("status")}
        except ValueError:
            ops = {"error": "invalid json"}
    return live, ops


def build_prompt(checklist: str, live: dict, ops: dict) -> str:
    files = sorted({p for g in CONTEXT_FILES for p in ROOT.glob(g)} - {ROOT / s for s in SKIP_FILES})
    source = "\n\n".join(f"===== {p.relative_to(ROOT)} =====\n{p.read_text(encoding='utf-8')}" for p in files)
    rels = [str(p.relative_to(ROOT)) for p in files]
    editable = "\n".join(r for r in rels if EDITABLE_RE.match(r) and not r.startswith(PROTECTED))
    tests = "\n".join(sorted(p.name for p in (ROOT / "tests").glob("test_*.py")))
    workflows = "\n".join(sorted(p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")))
    return (f"<checklist>\n{checklist}\n</checklist>\n\n<live>\n{json.dumps(live, ensure_ascii=False)}\n</live>\n\n"
            f"<ops>\n{json.dumps(ops, ensure_ascii=False)}\n</ops>\n\n<editable>\n{editable}\n</editable>\n\n"
            f"<protected>\n{', '.join(PROTECTED)}\n</protected>\n\n<tests>\n{tests}\n</tests>\n\n"
            f"<workflows>\n{workflows}\n</workflows>\n\n<source>\n{source}\n</source>")


def ask_claude(prompt: str, client: anthropic.Anthropic | None = None) -> dict:
    client = client or anthropic.Anthropic()
    model = os.environ.get("QUALITY_MODEL", "").strip() or DEFAULT_MODEL
    params = {
        "model": model, "max_tokens": 32000, "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }
    with client.beta.messages.stream(**params) as stream:
        message = stream.get_final_message()
    if message.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"AI 점검이 끝나지 않았습니다 (stop_reason={message.stop_reason}).")
    return json.loads(next(b.text for b in message.content if b.type == "text"))


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def render(result: dict, model: str) -> tuple[str, list[dict]]:
    items = [i for i in result.get("items", []) if i.get("status") in STATUSES]
    counts = {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}
    icon = {"ok": "✅", "fix": "🛠️", "manual": "👤"}
    lines = [f"**점검 모델** `{model}` · ✅ 괜찮음 {counts['ok']} · 🛠️ 자동 수정 대상 {counts['fix']} · 👤 사람 확인 {counts['manual']}",
             "", _cell(result.get("summary", "")), "",
             f"**서버 용량**: {result['capacity']['status']} — {_cell(result['capacity']['reason'])}", "",
             "| | 영역 | 질문 | 근거 | 할 일 |", "|---|---|---|---|---|"]
    for i in items:
        lines.append(f"| {icon[i['status']]} | {_cell(i['section'])} | {_cell(i['question'])} | "
                     f"{_cell(i['evidence'])} | {_cell(i['action'])} |")
    lines += ["", "체크리스트: `docs/review-checklist.md` · 🛠️ 항목은 `[품질]` 이슈 → 자동 수정 PR(승인 필요)로 이어집니다."]
    fixes = []
    for i in items:
        title = _cell(i.get("title", ""))[:80]
        if i["status"] != "fix" or not title:
            continue
        fixes.append({"title": f"[품질] {title}", "body": (
            f"품질 점검(`scripts/quality_review.py`)이 찾은 문제입니다.\n\n- 영역: {i['section']}\n- 질문: {i['question']}\n"
            f"- 근거: {i['evidence']}\n- 고칠 일: {i['action']}\n\n체크리스트: docs/review-checklist.md")})
    return "\n".join(lines), fixes


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit("사용: python3 scripts/quality_review.py <보고서.md> <수정 항목.json> <용량.json>")
    site = (os.environ.get("SITE_URL", "").strip() or DEFAULT_SITE).rstrip("/")
    live, ops = probe(site, os.environ.get("CRON_SECRET", "").strip())
    checklist = (ROOT / "docs" / "review-checklist.md").read_text(encoding="utf-8")
    result = ask_claude(build_prompt(checklist, live, ops))
    model = os.environ.get("QUALITY_MODEL", "").strip() or DEFAULT_MODEL
    report, fixes = render(result, model)
    Path(sys.argv[1]).write_text(report, encoding="utf-8")
    Path(sys.argv[2]).write_text(json.dumps(fixes, ensure_ascii=False), encoding="utf-8")
    Path(sys.argv[3]).write_text(json.dumps(result["capacity"], ensure_ascii=False), encoding="utf-8")
    print(f"점검 항목 {len(result.get('items', []))}개, 자동 수정 대상 {len(fixes)}개, 용량 {result['capacity']['status']}")


if __name__ == "__main__":
    main()
