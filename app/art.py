"""읽기 전용 미술 DB(data/art.db) 검색."""
import logging
import random
import re
import sqlite3

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


log = logging.getLogger("app.art")

FTS_MAX_TOKENS = 20  # OR로 잇는 검색어 상한 (LLM이 키워드를 수백 개 뱉어도 질의가 커지지 않게)


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


def _fts_query(keywords) -> str:
    """키워드를 안전한 FTS5 OR 질의로 바꾼다 (영문/숫자 토큰만, 각각 따옴표로 감쌈).
    문자열 하나만 와도 받아주고, None·숫자 등 문자열이 아닌 값은 건너뛴다. 남는 토큰이 없으면 ""."""
    if isinstance(keywords, str):
        keywords = [keywords]
    tokens = []
    for kw in keywords or []:
        if isinstance(kw, str):
            tokens += re.findall(r"[A-Za-z0-9]+", kw)
    return " OR ".join(f'"{t}"' for t in list(dict.fromkeys(tokens))[:FTS_MAX_TOKENS])


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


def _diversify(pool: list[dict], limit: int) -> list[dict]:
    """pool은 이미 관련도순(best-first)으로 정렬돼 있다고 가정한다.
    상위 GUARANTEED_TOP개는 그대로 보장하고, 나머지 자리는 pool 전체에서 무작위로 뽑아
    원래 관련도 순서를 유지한 채 채운다. pool이 limit보다 작거나 같으면 그대로 반환한다."""
    if len(pool) <= limit:
        return pool
    guaranteed = pool[:GUARANTEED_TOP]
    rest_pool = pool[GUARANTEED_TOP:]
    need = limit - len(guaranteed)
    sampled_idx = sorted(random.sample(range(len(rest_pool)), min(need, len(rest_pool))))
    return guaranteed + [rest_pool[i] for i in sampled_idx]


def search(keywords: list[str], artist: str | None = None,
           year_from: int | None = None, year_to: int | None = None, limit: int = 6) -> list[dict]:
    """빈 검색어·특수문자만 있는 검색어는 FTS 없이 필터(작가·연도)만으로 찾는다.
    FTS 질의가 그래도 실패하면(색인 손상 등) 사용자 입력 때문에 503을 내지 않도록 필터 검색으로 대신한다."""
    if limit <= 0:
        return []
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

    pool_size = limit * DIVERSITY_POOL_MULTIPLIER
    fts = _fts_query(keywords)
    conn = _connect()
    try:
        rows = None
        if fts:
            sql = (f"SELECT {CARD_FIELDS} FROM artworks_fts f JOIN artworks a ON a.id = f.rowid "
                   f"WHERE artworks_fts MATCH ? AND {' AND '.join(where)} "
                   "ORDER BY a.is_highlight DESC, bm25(artworks_fts) LIMIT ?")
            try:
                rows = conn.execute(sql, [fts, *params, pool_size]).fetchall()
            except sqlite3.OperationalError as e:
                log.warning("fts_query_failed query=%r detail=%s", fts[:200], e)
        if rows is None:
            sql = (f"SELECT {CARD_FIELDS} FROM artworks a WHERE {' AND '.join(where)} "
                   "ORDER BY a.is_highlight DESC, a.id LIMIT ?")
            rows = conn.execute(sql, [*params, pool_size]).fetchall()
        pool = [with_proxy_urls(dict(r)) for r in rows]
        return _diversify(pool, limit)
    finally:
        conn.close()


def ping() -> None:
    """미술 DB 파일을 열고 읽을 수 있는지 확인한다 (/healthz). 실패하면 sqlite3.Error."""
    conn = _connect()
    try:
        conn.execute("SELECT 1 FROM artworks LIMIT 1").fetchall()
    finally:
        conn.close()
