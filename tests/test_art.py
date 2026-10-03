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
