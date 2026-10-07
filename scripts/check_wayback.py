"""인터넷 아카이브 보관이 실제로 되는지 점검한다 (권리 근거 기록, app/records.py).

사용: python3 scripts/check_wayback.py
허용 기관마다 작품 1점의 기관 페이지와 API 주소를 app/records.py와 같은 함수로 보관해 보고 결과를 출력한다.
GitHub Actions(archive-check.yml)에서 돌린다 — 개발 컨테이너는 archive.org 접속이 막혀 있을 수 있다.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "check-only-secret-key-check-only-secret")

from app import records  # noqa: E402

def sample_urls() -> list[tuple[str, str]]:
    """허용 기관마다 작품 1점의 (기관 작품 페이지, 근거 API 주소) — 실제 기록 발급과 같은 주소."""
    from app import art, rights
    conn = art._connect()
    try:
        out = []
        for code in rights.allowed_sources():
            row = conn.execute("SELECT source_id, source_url FROM artworks WHERE source = ? AND is_public_domain = 1 "
                               "ORDER BY id LIMIT 1", (code,)).fetchone()
            if row:
                out.append((f"{code} 작품 페이지", row["source_url"]))
                if rights.SOURCES[code].api_url:
                    out.append((f"{code} API", rights.SOURCES[code].api_url.format(id=row["source_id"])))
        return out
    finally:
        conn.close()


def main() -> None:
    print(f"인증 키 사용: {'예 (공식 저장 API)' if records.ia_keys() else '아니오 (익명 저장)'}\n")
    saved = fallback = missing = 0
    for label, url in sample_urls():
        started = time.monotonic()
        archived, err = records.save_to_wayback(url)
        took = time.monotonic() - started
        if archived:
            saved += 1
            print(f"✅ {label}: {archived}  ({took:.1f}초)")
            continue
        found = records.latest_snapshot(url)
        if found:
            fallback += 1
            print(f"📁 {label}: 새 보관 실패({err}) → 기존 보관본 {found[1][:8]} {found[0]}")
        else:
            missing += 1
            print(f"❌ {label}: 새 보관 실패({err}), 기존 보관본도 없음 — {url}")
    print(f"\n새로 보관 {saved} · 기존 보관본 {fallback} · 근거 없음 {missing}")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
