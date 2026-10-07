"""LLM 위키(wiki/) 자동 점검 — wiki/AGENTS.md의 'lint' 작업.

사용: python3 scripts/wiki_lint.py      # 문제가 있으면 목록을 출력하고 종료 코드 1

점검 항목
1. 페이지 머리말(title·sources·updated)이 있는가
2. sources에 적은 원본 파일이 저장소에 실제로 있는가 (원본이 지워지면 페이지도 고쳐야 한다)
3. 위키 안의 상대 링크가 깨지지 않았는가
4. 모든 페이지가 index.md에 올라 있는가
5. 비밀 값처럼 보이는 문자열(API 키·토큰 모양)이 없는가
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SPECIAL = {"AGENTS.md", "index.md", "log.md"}  # 머리말 없이 쓰는 운영 파일
LINK_RE = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|eyJ[A-Za-z0-9_-]{30,})")


def front_matter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    meta = {}
    for line in text[4:end].splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def lint(wiki: Path = WIKI, root: Path = ROOT) -> list[str]:
    problems = []
    pages = sorted(p for p in wiki.glob("*.md"))
    index_text = (wiki / "index.md").read_text(encoding="utf-8") if (wiki / "index.md").exists() else ""
    for page in pages:
        text = page.read_text(encoding="utf-8")
        name = page.name
        if name not in SPECIAL:
            meta = front_matter(text)
            if meta is None or not all(meta.get(k) for k in ("title", "sources", "updated")):
                problems.append(f"{name}: 머리말(title·sources·updated)이 없거나 비어 있음")
            else:
                for src in (s.strip() for s in meta["sources"].strip("[]").split(",")):
                    if src and not (root / src).exists():
                        problems.append(f"{name}: sources의 '{src}' 파일이 저장소에 없음")
            if f"({name})" not in index_text:
                problems.append(f"{name}: index.md에 링크가 없음")
        for target in LINK_RE.findall(text):
            if "://" not in target and not (page.parent / target).exists():
                problems.append(f"{name}: 깨진 링크 '{target}'")
        if SECRET_RE.search(text):
            problems.append(f"{name}: 비밀 값처럼 보이는 문자열이 있음 — 이름만 적고 값은 지울 것")
    return problems


def main() -> None:
    problems = lint()
    for p in problems:
        print(f"✗ {p}")
    pages = len(list(WIKI.glob("*.md")))
    print(f"위키 {pages}개 파일 점검 — 문제 {len(problems)}개")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
