"""가디언 자동 수정안 안전 검사 — AI가 만든 변경이 PR로 올라가기 전과 배포 직전에 두 번 돈다.

사용: python3 scripts/autofix_guard.py <기준 브랜치나 커밋>     # 예: origin/main
결과: 위반이 없으면 종료 코드 0, 있으면 위반 목록을 출력하고 1.

AI가 읽은 장애 로그에는 공격자가 쓴 글이 섞일 수 있다. AI가 속아서 위험한 코드를 쓰더라도
여기서 기계적으로 걸러, 사람이 승인 버튼을 누르기 전에 무엇이 문제인지 보이게 한다.
검사 기준은 AI가 아니라 이 파일의 규칙이다 — 그래서 이 파일 자체도 AI가 고칠 수 없다(PROTECTED).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# AI가 고칠 수 없는 파일: 비밀 키·인증·DB 접속·배포 경로·검사 규칙 자신
PROTECTED = (
    ".github/", "app/auth.py", "app/deps.py", "app/config.py", "app/db.py", "app/llm.py", "app/claude_llm.py",
    "requirements", "vercel.json", "index.py", "Dockerfile", "deploy/", ".env", "data/",
    "scripts/autofix_", "scripts/quality_", "scripts/security_", "docs/review-checklist.md", "docs/security-",
    "CONTRIBUTING.md", "SECURITY.md",
)
# 새로 들어온 줄에 있으면 안 되는 것: 외부 통신, 명령 실행, 비밀 값 읽기, 코드 동적 실행
# (urllib.parse는 주소 문자열을 나누기만 해서 통신이 아니다, re.compile은 정규식 준비라 코드 실행이 아니다 — 허용)
FORBIDDEN = [
    (r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b|\bpty\b", "명령 실행"),
    (r"\beval\s*\(|\bexec\s*\(|\b__import__\b|(?<!re\.)\bcompile\s*\(|\bimportlib\b", "코드 동적 실행"),
    (r"\bos\.environ\b|\bgetenv\b|\bdotenv\b", "환경변수(비밀 키) 읽기"),
    (r"\burllib\b(?!\.parse\b)|\brequests\b|\bhttpx\b|\bsocket\b|\bhttp\.client\b|\baiohttp\b|\bfetch\s*\(|XMLHttpRequest",
     "외부 통신"),
    (r"\bpickle\b|\bmarshal\b|\bbase64\b|\bctypes\b", "숨김·직렬화 우회"),
    (r"\bshutil\.rmtree\b|\bos\.remove\b|\bos\.unlink\b|\bDROP\s+TABLE\b|\bDELETE\s+FROM\b", "삭제"),
    (r"(?i)(api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"]{8,}", "비밀 값처럼 보이는 글"),
]
# 보이지 않거나 글자 방향을 뒤집는 문자: 사람 눈에는 안 보이는 숨은 지시·코드를 끼워 넣는 수법(트로이 소스, 태그 문자 밀반입)
INVISIBLE_RE = re.compile("[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]")
# 앱 코드에서 비밀 값을 로그·응답·화면으로 내보내는 줄
SECRET_LEAK_RE = re.compile(
    r"\b(log(ger|ging)?\.\w+|print|return|yield|JSONResponse|HTMLResponse|PlainTextResponse|textContent|innerHTML|"
    r"console\.\w+|alert)\b.*(\b(password|passwd|password_hash|secret|secret_key|api_?key|auth_?token|access_?token|"
    r"authorization|cookie|CRON_SECRET|PREMIUM_CODE)\b|\b(ANTHROPIC|TURSO|GPT_ASTRA|UPSTAGE|IA_SECRET|IA_ACCESS)\w*)",
    re.IGNORECASE)
# 화면(JS·HTML)에서 몰래 밖으로 보내거나 남의 코드를 불러오는 줄
EXFIL_RE = re.compile(
    r"sendBeacon|document\.cookie|new\s+WebSocket|importScripts|new\s+Function|<iframe|"
    r"<script[^>]+src=|<img[^>]+src=[\"']https?:|<link[^>]+href=[\"']https?:|location\.(href|assign|replace)\s*[=(]",
    re.IGNORECASE)
URL_DOMAIN_RE = re.compile(r"https?://([a-z0-9.-]+)", re.IGNORECASE)
# 이 이름이 들어간 줄이 지워지기만 하면 보안 검사를 빼는 것으로 본다
SECURITY_NAMES = ("current_session", "check_rate", "is_blocked", "looks_malicious", "strike(", "note_login_failure",
                  "check_login_lockout", "CRON_SECRET", "verify_token", "compare_digest", "is_probe_path", "httponly")
# 보안 동향 학습(.github/workflows/security-intel.yml)이 더한 금지 문자열 — 더할 수만 있고 기준을 낮출 수는 없다
EXTRA_DENY_ENV = "AUTOFIX_EXTRA_DENY"
MAX_CHANGED_LINES = 400
NEW_TEST_RE = re.compile(r"^tests/test_autofix_[a-z0-9_]+\.py$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def reveal_invisible(text: str) -> str:
    """보이지 않는 문자를 <U+202E>처럼 보이게 바꾼다 — 사람도 AI도 숨은 글자를 볼 수 있게."""
    return INVISIBLE_RE.sub(lambda m: f"<U+{ord(m.group(0)):04X}>", text)


def visible(text: str) -> str:
    """PR·이슈에 올릴 AI 글을 '보이는 그대로' 만든다: 숨은 문자 표시 + HTML 주석·태그가 숨지 않게 글자로 바꿈."""
    return reveal_invisible(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def known_domains(base: str) -> set[str]:
    """기준 시점의 앱 코드에 이미 있던 외부 주소. 새로 생긴 주소만 문제로 본다."""
    files = [f for f in _git("ls-tree", "-r", "--name-only", base, "app").splitlines() if f.endswith((".py", ".js", ".html"))]
    domains = set()
    for f in files:
        domains |= {d.lower() for d in URL_DOMAIN_RE.findall(_git("show", f"{base}:{f}"))}
    return domains


def extra_deny() -> list[str]:
    """학습한 금지 문자열 (대소문자 무시, 정규식이 아닌 그냥 글자 — 학습 데이터로 검사를 느리게 만들 수 없게)."""
    path = os.environ.get(EXTRA_DENY_ENV, "")
    if not path or not Path(path).is_file():
        return []
    try:
        items = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        return []
    return [s.lower() for s in items if isinstance(s, str) and 6 <= len(s) <= 120][:500]


def check(base: str) -> list[str]:
    problems = []
    domains = known_domains(base)
    deny = extra_deny()
    removed_names: dict[str, int] = {}
    added_names: dict[str, int] = {}
    changes = [line.split("\t") for line in _git("diff", "--name-status", base).splitlines() if line]
    if not changes:
        return ["바뀐 파일이 없음"]
    added_test = False
    for status, *paths in changes:
        path = paths[-1]
        if path.startswith(PROTECTED):
            problems.append(f"{path}: 보호 파일은 자동 수정 대상이 아님")
        if path.startswith("tests/"):
            if status == "A" and NEW_TEST_RE.match(path):
                added_test = True
            else:
                problems.append(f"{path}: 기존 테스트는 고치거나 지울 수 없음 (새 tests/test_autofix_*.py만 추가 가능)")
        if status.startswith(("D", "R")):
            problems.append(f"{path}: 파일 삭제·이름 바꾸기는 허용하지 않음")
    if not added_test:
        problems.append("수정 내용을 확인하는 새 테스트(tests/test_autofix_*.py)가 없음")

    diff = _git("diff", "--unified=0", base)
    changed = 0
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
            continue
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            changed += 1
            counts = added_names if line.startswith("+") else removed_names
            for name in SECURITY_NAMES:
                if name.lower() in line.lower():
                    counts[name] = counts.get(name, 0) + 1
        if line.startswith("+") and not line.startswith("+++"):
            text = line[1:]
            shown = INVISIBLE_RE.sub("�", text).strip()[:120]
            for pattern, label in FORBIDDEN:
                if re.search(pattern, text):
                    problems.append(f"{current}: {label} — {shown}")
            if INVISIBLE_RE.search(text):
                problems.append(f"{current}: 보이지 않는 문자(숨은 지시·코드 의심) — {shown}")
            if current.startswith("app/") and SECRET_LEAK_RE.search(text):
                problems.append(f"{current}: 비밀 값 노출 의심(로그·응답·화면으로 내보냄) — {shown}")
            if current.startswith("app/") and EXFIL_RE.search(text):
                problems.append(f"{current}: 화면에서 밖으로 보내거나 외부 코드를 불러옴 — {shown}")
            for domain in URL_DOMAIN_RE.findall(text):
                if domain.lower() not in domains:
                    problems.append(f"{current}: 처음 보는 외부 주소 {domain} — {shown}")
            for item in deny:
                if item in text.lower():
                    problems.append(f"{current}: 보안 동향에서 배운 금지 문자열 '{item}' — {shown}")
    for name, removed in removed_names.items():
        if removed > added_names.get(name, 0):
            problems.append(f"보안 검사 제거 의심: '{name}'이 든 줄이 {removed - added_names.get(name, 0)}개 사라짐")
    if changed > MAX_CHANGED_LINES:
        problems.append(f"바뀐 줄이 너무 많음 ({changed}줄 > {MAX_CHANGED_LINES}줄)")
    return problems


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--visible":   # 표준 입력의 글을 PR에 올려도 안전하게 바꿔 출력
        sys.stdout.write(visible(sys.stdin.read()))
        return
    if len(sys.argv) != 2:
        sys.exit("사용: python3 scripts/autofix_guard.py <기준 브랜치나 커밋>")
    problems = check(sys.argv[1])
    for p in problems:
        print(f"✗ {p}")
    print(f"안전 검사 — 위반 {len(problems)}개")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
