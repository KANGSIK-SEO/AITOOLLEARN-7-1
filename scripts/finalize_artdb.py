"""수집 후 data/art.db 정리: 검색 인덱스 최적화 + VACUUM으로 용량을 줄이고, 깃허브 파일 한도를 넘지 않는지 확인한다."""
import sqlite3
import sys

from artdb import DB_PATH

GITHUB_SAFE_BYTES = 95 * 1024 * 1024  # 깃허브 단일 파일 한도 100MB에 여유를 둔다


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO artworks_fts (artworks_fts) VALUES ('optimize')")
    conn.commit()
    conn.execute("VACUUM")
    for source, n in conn.execute("SELECT source, COUNT(*) FROM artworks GROUP BY source"):
        print(f"{source}: {n}건")
    conn.close()
    size = DB_PATH.stat().st_size
    print(f"art.db {size / 1024 / 1024:.1f}MB")
    if size > GITHUB_SAFE_BYTES:
        sys.exit("art.db가 95MB를 넘어 커밋할 수 없습니다. 수집 범위(--departments/--classifications)를 줄이세요.")


if __name__ == "__main__":
    main()
