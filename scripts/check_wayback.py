"""인터넷 아카이브 보관이 실제로 되는지 점검한다 (권리 근거 기록, app/records.py).

사용: python3 scripts/check_wayback.py
진짜 기관 페이지 1개와 API 주소 1개를 app/records.py와 같은 함수로 보관해 보고 결과를 출력한다.
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

URLS = [
    "https://www.metmuseum.org/art/collection/search/436535",
    "https://collectionapi.metmuseum.org/public/collection/v1/objects/436535",
]


def main() -> None:
    print(f"인증 키 사용: {'예' if records.ia_keys() else '아니오 (익명 저장)'}")
    failed = 0
    for url in URLS:
        started = time.monotonic()
        archived, err = records.save_to_wayback(url)
        took = time.monotonic() - started
        print(f"{'✅' if archived else '❌'} {url}\n   → {archived or err}  ({took:.1f}초)")
        failed += not archived
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
