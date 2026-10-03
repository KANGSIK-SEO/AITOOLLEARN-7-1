"""읽기 전용 미술 DB(data/art.db) 검색."""
import re
import sqlite3

from .config import ROOT

ART_DB = ROOT / "data" / "art.db"
CARD_FIELDS = (
    "a.id, a.source, a.title, a.artist, a.date_display, a.medium, a.image_url, "
    "a.thumbnail_url, a.source_url, a.license, a.credit_line, a.is_highlight"
)


AIC_IMAGE_RE = re.compile(r"/iiif/2/([0-9a-f-]{36})/")


def with_proxy_urls(work: dict) -> dict:
    """AIC 이미지는 전용 헤더가 없으면 403이라 브라우저가 직접 못 받는다 → 우리 서버 프록시 주소로 바꾼다."""
    if work.get("source") == "aic":
        m = AIC_IMAGE_RE.search(work.get("image_url") or "")
        if m:
            work = {**work,
                    "thumbnail_url": f"/api/img/aic/{m.group(1)}?w=400",
                    "image_url": f"/api/img/aic/{m.group(1)}?w=1686"}
    return work


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{ART_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _fts_query(keywords: list[str]) -> str:
    """키워드를 안전한 FTS5 OR 질의로 바꾼다 (영문/숫자 토큰만, 각각 따옴표로 감쌈)."""
    tokens = []
    for kw in keywords:
        tokens += re.findall(r"[A-Za-z0-9]+", kw)
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens))


def get_by_ids(ids: list[int]) -> dict[int, dict]:
    """작품 id 목록 → {id: 카드}. 없는 id는 결과에 빠진다 (즐겨찾기 검증·조회용)."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT {CARD_FIELDS} FROM artworks a WHERE a.id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {r["id"]: with_proxy_urls(dict(r)) for r in rows}
    finally:
        conn.close()


def search(keywords: list[str], artist: str | None = None,
           year_from: int | None = None, year_to: int | None = None, limit: int = 6) -> list[dict]:
    where, params = ["a.is_public_domain = 1"], []
    if artist:
        where.append("a.artist LIKE ?")
        params.append(f"%{artist}%")
    if year_from is not None:
        where.append("a.year_end >= ?")
        params.append(year_from)
    if year_to is not None:
        where.append("a.year_start <= ?")
        params.append(year_to)

    fts = _fts_query(keywords)
    conn = _connect()
    try:
        if fts:
            sql = (f"SELECT {CARD_FIELDS} FROM artworks_fts f JOIN artworks a ON a.id = f.rowid "
                   f"WHERE artworks_fts MATCH ? AND {' AND '.join(where)} "
                   "ORDER BY a.is_highlight DESC, bm25(artworks_fts) LIMIT ?")
            rows = conn.execute(sql, [fts, *params, limit]).fetchall()
        else:
            sql = (f"SELECT {CARD_FIELDS} FROM artworks a WHERE {' AND '.join(where)} "
                   "ORDER BY a.is_highlight DESC, a.id LIMIT ?")
            rows = conn.execute(sql, [*params, limit]).fetchall()
        return [with_proxy_urls(dict(r)) for r in rows]
    finally:
        conn.close()
