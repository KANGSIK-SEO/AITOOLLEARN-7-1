import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import art  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _work(i, highlight=0):
    return {"id": i, "source": "met", "title": f"Work {i}", "artist": "Artist",
            "date_display": "1900", "medium": "oil", "image_url": "https://x/img.jpg",
            "thumbnail_url": None, "source_url": "https://x", "license": "CC0",
            "credit_line": None, "is_highlight": highlight}


def test_diversify_returns_pool_as_is_when_not_larger_than_limit():
    pool = [_work(i) for i in range(4)]
    assert art._diversify(pool, 6) == pool


def test_diversify_always_keeps_guaranteed_top():
    pool = [_work(i) for i in range(30)]
    for _ in range(20):
        result = art._diversify(pool, 6)
        assert len(result) == 6
        assert result[:art.GUARANTEED_TOP] == pool[:art.GUARANTEED_TOP]


def test_diversify_surfaces_more_than_limit_distinct_items_over_many_calls():
    pool = [_work(i) for i in range(30)]
    seen_ids = set()
    for _ in range(40):
        for w in art._diversify(pool, 6):
            seen_ids.add(w["id"])
    assert len(seen_ids) > 6  # 결정적(top-6)이었다면 절대 6을 넘을 수 없다


@pytest.fixture()
def seeded_art_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_art.db"
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    conn.executescript(schema)
    for i in range(20):
        conn.execute(
            "INSERT INTO artworks (source, source_id, title, artist, image_url, source_url, "
            "subjects, is_public_domain, is_highlight) VALUES ('met', ?, ?, 'Spring Artist', "
            "'https://x/img.jpg', 'https://x', 'spring landscape', 1, ?)",
            (str(i), f"Spring Work {i}", 1 if i == 0 else 0),
        )
    conn.commit()
    conn.close()
    monkeypatch.setattr(art, "ART_DB", db_path)
    return db_path


def test_search_diversifies_candidates_over_many_calls(seeded_art_db):
    seen_ids = set()
    for _ in range(40):
        results = art.search(["spring", "landscape"], limit=6)
        assert len(results) == 6
        seen_ids.update(w["id"] for w in results)
    assert len(seen_ids) > 6


def test_search_always_includes_highlighted_work_first(seeded_art_db):
    for _ in range(10):
        results = art.search(["spring", "landscape"], limit=6)
        assert results[0]["is_highlight"] == 1


# ---- search: 연도·작가 필터, FTS 특수문자 ----
# (title, artist, year_start, year_end, is_public_domain)
FILTER_ROWS = [
    ("Sea A", "Claude Monet", 1870, 1872, 1),
    ("Sea B", "Claude Monet", 1890, 1890, 1),
    ("Sea C", "J. M. W. Turner", 1820, 1825, 1),
    ("Sea D", "Winslow Homer", 1899, 1901, 1),
    ("Sea E", "Claude Monet", 1880, 1880, 0),   # 퍼블릭 도메인 아님 → 항상 제외
]


@pytest.fixture()
def filter_art_db(tmp_path, monkeypatch):
    db_path = tmp_path / "filter_art.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    for i, (title, artist, y0, y1, pd) in enumerate(FILTER_ROWS):
        conn.execute(
            "INSERT INTO artworks (source, source_id, title, artist, year_start, year_end, image_url, "
            "source_url, subjects, is_public_domain) VALUES ('met', ?, ?, ?, ?, ?, 'https://x/i.jpg', "
            "'https://x', 'sea marine', ?)", (str(i), title, artist, y0, y1, pd))
    conn.commit()
    conn.close()
    monkeypatch.setattr(art, "ART_DB", db_path)


def _titles(results):
    return sorted(w["title"] for w in results)


def test_search_year_filter_uses_range_overlap(filter_art_db):
    # 제작 기간이 [year_from, year_to]와 겹치면 포함 (경계값 포함)
    assert _titles(art.search(["sea"], year_from=1872, year_to=1890, limit=50)) == ["Sea A", "Sea B"]
    assert _titles(art.search(["sea"], year_from=1900, limit=50)) == ["Sea D"]
    assert _titles(art.search(["sea"], year_to=1825, limit=50)) == ["Sea C"]
    assert art.search(["sea"], year_from=1950, limit=50) == []


def test_search_artist_filter_is_partial_case_insensitive_match(filter_art_db):
    assert _titles(art.search(["sea"], artist="monet", limit=50)) == ["Sea A", "Sea B"]
    assert _titles(art.search(["sea"], artist="Turner", limit=50)) == ["Sea C"]
    assert art.search(["sea"], artist="Rembrandt", limit=50) == []


def test_search_combines_artist_and_year_filters(filter_art_db):
    assert _titles(art.search(["sea"], artist="Monet", year_from=1885, limit=50)) == ["Sea B"]


def test_search_filters_work_without_keywords(filter_art_db):
    # 한국어만 있어 FTS 토큰이 없으면 필터만으로 검색한다
    assert _titles(art.search(["바다"], artist="Homer", limit=50)) == ["Sea D"]


def test_search_never_returns_non_public_domain(filter_art_db):
    assert "Sea E" not in _titles(art.search(["sea"], limit=50))
    assert "Sea E" not in _titles(art.search([], artist="Monet", year_from=1880, year_to=1880, limit=50))


@pytest.mark.parametrize("keywords", [
    ['"'], ['sea"'], ["sea*"], ["^sea"], ["NOT"], ["AND", "OR"], ["NEAR(sea"], ["sea:marine"],
    ["(sea)"], ["-sea"], ["sea'; DROP TABLE artworks; --"], [""], ["   "], [],
])
def test_search_fts_special_characters_never_raise(filter_art_db, keywords):
    results = art.search(keywords, limit=50)
    assert all(w["title"].startswith("Sea") for w in results)


@pytest.mark.parametrize("keywords, expected", [
    (['"sea"'], '"sea"'),
    (["sea*", "^marine"], '"sea" OR "marine"'),
    (["NEAR(sea, sky)"], '"NEAR" OR "sea" OR "sky"'),
    (["sea", "SEA", "sea"], '"sea" OR "SEA"'),
    (["봄", "!!!"], ""),
])
def test_fts_query_quotes_every_token(keywords, expected):
    assert art._fts_query(keywords) == expected
