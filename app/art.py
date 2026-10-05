"""읽기 전용 미술 DB(data/art.db) 검색."""
import random
import re
import sqlite3

from . import rights
from .config import ROOT

ART_DB = ROOT / "data" / "art.db"
CARD_FIELDS = (
    "a.id, a.source, a.title, a.artist, a.date_display, a.medium, a.image_url, "
    "a.thumbnail_url, a.source_url, a.license, a.credit_line, a.is_highlight"
)

# 같은 질문이면 늘 똑같은 top-N만 보여주면(결정적 랭킹, PRP) 매칭 후보가 아무리 많아도
# 컬렉션의 일부만 영원히 노출된다. Tennenholtz & Kurland(CACM, 2019)가 보이듯, 약간의
# 무작위성을 섞으면 알고리즘/시스템 오버헤드 거의 없이 콘텐츠 다양성(content breadth)이
# 늘어난다. 가장 관련도 높은 GUARANTEED_TOP개는 항상 그대로 보장하고(정밀도 보호),
# 나머지 자리만 후보 풀에서 무작위로 채운다.
DIVERSITY_POOL_MULTIPLIER = 5
GUARANTEED_TOP = 2


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


def _diversify(pool: list[dict], limit: int) -> list[dict]:
    """pool은 이미 관련도순(best-first)으로 정렬돼 있다고 가정한다.
    상위 GUARANTEED_TOP개는 그대로 보장하고, 나머지 자리는 pool 전체에서 무작위로 뽑아
    원래 관련도 순서를 유지한 채 채운다. pool이 limit보다 작거나 같으면 그대로 반환한다."""
    if len(pool) <= limit:
        return pool
    guaranteed = pool[:min(GUARANTEED_TOP, limit)]
    rest_pool = pool[len(guaranteed):]
    need = limit - len(guaranteed)
    sampled_idx = sorted(random.sample(range(len(rest_pool)), min(need, len(rest_pool))))
    return guaranteed + [rest_pool[i] for i in sampled_idx]


def _source_filter() -> tuple[str, list]:
    """판단 규칙 R1·R3: 허용된 CC0 기관의 CC0 작품만 (docs/rights-policy.md)."""
    codes = rights.allowed_sources()
    if not codes:
        return "0", []
    return f"a.source IN ({', '.join('?' for _ in codes)}) AND a.license = 'CC0'", codes


def _filters(artist: str | None, year_from: int | None, year_to: int | None) -> tuple[list[str], list]:
    src_sql, src_params = _source_filter()
    where, params = ["a.is_public_domain = 1", src_sql], list(src_params)
    if artist:
        where.append("a.artist LIKE ?")
        params.append(f"%{artist}%")
    if year_from is not None:
        where.append("a.year_end >= ?")
        params.append(year_from)
    if year_to is not None:
        where.append("a.year_start <= ?")
        params.append(year_to)
    return where, params


def _ranked(conn: sqlite3.Connection, keywords: list[str], artist: str | None, year_from: int | None,
            year_to: int | None, limit: int, offset: int = 0) -> list[dict]:
    """관련도순(하이라이트 우선) 결정적 정렬. search()의 후보 풀과 browse()의 페이지가 같은 순서를 쓴다."""
    where, params = _filters(artist, year_from, year_to)
    fts = _fts_query(keywords)
    if fts:
        sql = (f"SELECT {CARD_FIELDS} FROM artworks_fts f JOIN artworks a ON a.id = f.rowid "
               f"WHERE artworks_fts MATCH ? AND {' AND '.join(where)} "
               "ORDER BY a.is_highlight DESC, bm25(artworks_fts), a.id LIMIT ? OFFSET ?")
        rows = conn.execute(sql, [fts, *params, limit, offset]).fetchall()
    else:
        sql = (f"SELECT {CARD_FIELDS} FROM artworks a WHERE {' AND '.join(where)} "
               "ORDER BY a.is_highlight DESC, a.id LIMIT ? OFFSET ?")
        rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    return [with_proxy_urls(dict(r)) for r in rows]


def search(keywords: list[str], artist: str | None = None,
           year_from: int | None = None, year_to: int | None = None, limit: int = 6) -> list[dict]:
    conn = _connect()
    try:
        pool = _ranked(conn, keywords, artist, year_from, year_to, limit * DIVERSITY_POOL_MULTIPLIER)
        return _diversify(pool, limit)
    finally:
        conn.close()


def browse(keywords: list[str], artist: str | None = None, year_from: int | None = None,
           year_to: int | None = None, offset: int = 0, limit: int = 24) -> tuple[list[dict], bool]:
    """'더 보기'용. AI 없이 같은 조건으로 관련도순 페이지를 넘긴다. 두 번째 값은 다음 페이지가 있는지."""
    conn = _connect()
    try:
        rows = _ranked(conn, keywords, artist, year_from, year_to, limit + 1, offset)
        return rows[:limit], len(rows) > limit
    finally:
        conn.close()


def get_by_ids(ids: list[int]) -> list[dict]:
    """주어진 순서대로 작품 카드를 돌려준다 (없는 id는 건너뜀). 즐겨찾기 목록에 쓴다."""
    if not ids:
        return []
    conn = _connect()
    try:
        marks = ", ".join("?" for _ in ids)
        src_sql, src_params = _source_filter()
        rows = conn.execute(f"SELECT {CARD_FIELDS} FROM artworks a WHERE a.id IN ({marks}) AND {src_sql}",
                            [*ids, *src_params]).fetchall()
        by_id = {r["id"]: with_proxy_urls(dict(r)) for r in rows}
        return [by_id[i] for i in ids if i in by_id]
    finally:
        conn.close()


def get_rights_record(artwork_id: int) -> dict | None:
    """권리 근거 기록용 데이터. 판단(R1~R6)은 rights.evaluate가 하므로 여기서는 기관 필터를 걸지 않는다.
    image_url은 프록시 주소가 아니라 기관 원본 주소 그대로 둔다 (R4 판단 근거)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT a.id, a.source, a.source_id, a.title, a.artist, a.date_display, a.medium, a.image_url, "
            "a.thumbnail_url, a.source_url, a.credit_line, a.license, a.is_public_domain, a.collected_at "
            "FROM artworks a WHERE a.id = ?", (artwork_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
