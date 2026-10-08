"""가디언 자동 수정안 안전 검사 — AI가 만든 변경이 PR로 올라가기 전과 배포 직전에 두 번 돈다.

사용: python3 scripts/autofix_guard.py <기준 브랜치나 커밋>     # 예: origin/main
결과: 위반이 없으면 종료 코드 0, 있으면 위반 목록을 출력하고 1.

AI가 읽은 장애 로그에는 공격자가 쓴 글이 섞일 수 있다. AI가 속아서 위험한 코드를 쓰더라도
여기서 기계적으로 걸러, 사람이 승인 버튼을 누르기 전에 무엇이 문제인지 보이게 한다.
검사 기준은 AI가 아니라 이 파일의 규칙이다 — 그래서 이 파일 자체도 AI가 고칠 수 없다(PROTECTED).
"""
import re
import subprocess
import sys

# AI가 고칠 수 없는 파일: 비밀 키·인증·DB 접속·배포 경로·검사 규칙 자신
PROTECTED = (
    ".github/", "app/auth.py", "app/config.py", "app/db.py", "app/llm.py", "app/claude_llm.py",
    "requirements", "vercel.json", "index.py", "Dockerfile", "deploy/", ".env", "data/",
    "scripts/autofix_", "scripts/quality_", "docs/review-checklist.md", "CONTRIBUTING.md",
)
# 새로 들어온 줄에 있으면 안 되는 것: 외부 통신, 명령 실행, 비밀 값 읽기, 코드 동적 실행
FORBIDDEN = [
    (r"\bsubprocess\b|\bos\.system\b|\bos\.popen\b|\bpty\b", "명령 실행"),
    (r"\beval\s*\(|\bexec\s*\(|\b__import__\b|\bcompile\s*\(|\bimportlib\b", "코드 동적 실행"),
    (r"\bos\.environ\b|\bgetenv\b|\bdotenv\b", "환경변수(비밀 키) 읽기"),
    (r"\burllib\b|\brequests\b|\bhttpx\b|\bsocket\b|\bhttp\.client\b|\baiohttp\b|\bfetch\s*\(|XMLHttpRequest",
     "외부 통신"),
    (r"\bpickle\b|\bmarshal\b|\bbase64\b|\bctypes\b", "숨김·직렬화 우회"),
    (r"\bshutil\.rmtree\b|\bos\.remove\b|\bos\.unlink\b|\bDROP\s+TABLE\b|\bDELETE\s+FROM\b", "삭제"),
    (r"(?i)(api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"]{8,}", "비밀 값처럼 보이는 글"),
]
MAX_CHANGED_LINES = 400
NEW_TEST_RE = re.compile(r"^tests/test_autofix_[a-z0-9_]+\.py$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def check(base: str) -> list[str]:
    problems = []
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
        if line.startswith("+") and not line.startswith("+++"):
            for pattern, label in FORBIDDEN:
                if re.search(pattern, line[1:]):
                    problems.append(f"{current}: {label} — {line[1:].strip()[:120]}")
    if changed > MAX_CHANGED_LINES:
        problems.append(f"바뀐 줄이 너무 많음 ({changed}줄 > {MAX_CHANGED_LINES}줄)")
    return problems


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("사용: python3 scripts/autofix_guard.py <기준 브랜치나 커밋>")
    problems = check(sys.argv[1])
    for p in problems:
        print(f"✗ {p}")
    print(f"안전 검사 — 위반 {len(problems)}개")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
