"""미술 DB 공용 유틸: DB 연결/스키마 초기화, upsert, HTTP GET(재시도)."""
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "art.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"

COLUMNS = (
    "source", "source_id", "title", "artist", "artist_bio", "date_display",
    "year_start", "year_end", "medium", "classification", "department", "origin",
    "style", "subjects", "image_url", "thumbnail_url", "source_url", "credit_line",
    "is_public_domain", "license", "is_highlight",
)


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    _migrate_source_check(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _migrate_source_check(conn: sqlite3.Connection) -> None:
    """예전 DB는 source CHECK 제약이 ('met','aic')뿐이라 새 기관을 넣을 수 없다 → 같은 데이터로 테이블을 다시 만든다."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='artworks'").fetchone()
    if not row or "'cma'" in row[0]:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(artworks)")]
    conn.executescript("""
        DROP TRIGGER IF EXISTS artworks_ai; DROP TRIGGER IF EXISTS artworks_ad; DROP TRIGGER IF EXISTS artworks_au;
        DROP INDEX IF EXISTS idx_artworks_artist; DROP INDEX IF EXISTS idx_artworks_year; DROP INDEX IF EXISTS idx_artworks_pd;
        ALTER TABLE artworks RENAME TO artworks_old;
    """)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    col_list = ", ".join(cols)
    conn.execute(f"INSERT INTO artworks ({col_list}) SELECT {col_list} FROM artworks_old")
    conn.execute("DROP TABLE artworks_old")
    conn.execute("INSERT INTO artworks_fts (artworks_fts) VALUES ('rebuild')")  # 트리거로 생긴 중복 없이 색인을 새로 만든다
    conn.commit()
    print("art.db source 제약을 새 기관 목록으로 갱신했습니다.")


def upsert(conn: sqlite3.Connection, row: dict) -> None:
    placeholders = ", ".join("?" for _ in COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in COLUMNS if c not in ("source", "source_id"))
    updates += ", collected_at=datetime('now')"  # 다시 받았다 = 기관 권리 표시를 오늘 재확인했다 (판단 규칙 R5)
    conn.execute(
        f"INSERT INTO artworks ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
        f"ON CONFLICT(source, source_id) DO UPDATE SET {updates}",
        [row.get(c) for c in COLUMNS],
    )


def get_json(url: str, params: dict | None = None, retries: int = 4, timeout: int = 30):
    """GET 후 JSON 반환. 404는 None, 그 외 실패는 지수 백오프로 재시도."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers={"User-Agent": "AITOOLLEARN-7-1 art-db-collector"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)
