"""art.search / art._fts_query 입력 방어 테스트 (특수문자, 빈 검색어, 잘못된 타입, FTS 오류)."""
import logging
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-1234")

from app import art  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def art_db(tmp_path, monkeypatch):
    db_path = tmp_path / "art.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    for i, (title, artist) in enumerate([("Stormy Sea", "Turner"), ("Calm Sea", "Monet"), ("Sunflowers", "Gogh")]):
        conn.execute("INSERT INTO artworks (source, source_id, title, artist, image_url, source_url) "
                     "VALUES ('met', ?, ?, ?, 'https://x/i.jpg', 'https://x')", (str(i), title, artist))
    conn.commit()
    conn.close()
    monkeypatch.setattr(art, "ART_DB", db_path)


def _titles(rows):
    return sorted(r["title"] for r in rows)


@pytest.mark.parametrize("keywords", [
    [], [""], ["   "], ["!!!", "???"], ["\"", "*", "^", "(", ")", ":", "-"], ["봄", "바다"], None,
])
def test_empty_or_symbol_only_keywords_fall_back_to_filters(art_db, keywords):
    # FTS 토큰이 없으면 필터만으로 검색 (여기선 필터도 없으니 전체)
    assert _titles(art.search(keywords, limit=10)) == ["Calm Sea", "Stormy Sea", "Sunflowers"]
    assert _titles(art.search(keywords, artist="Monet", limit=10)) == ["Calm Sea"]


@pytest.mark.parametrize("keywords", [
    ['sea"'], ['"sea" OR "x"'], ["sea*"], ["NEAR(sea"], ["sea:title"], ["sea'; DROP TABLE artworks; --"],
    ["AND"], ["OR", "NOT"],
])
def test_fts_syntax_characters_never_raise(art_db, keywords):
    art.search(keywords, limit=10)  # 예외가 나지 않으면 통과


def test_special_characters_are_stripped_but_words_still_match(art_db):
    assert _titles(art.search(['"sea"*'], limit=10)) == ["Calm Sea", "Stormy Sea"]


@pytest.mark.parametrize("keywords", [[None], ["sea", None], [123, "sea"], [["sea"]], [{"k": "sea"}]])
def test_non_string_keywords_are_ignored(art_db, keywords):
    results = art.search(keywords, limit=10)
    assert all(r["title"] for r in results)


def test_single_string_is_treated_as_one_keyword():
    assert art._fts_query("sea") == '"sea"'  # 's' OR 'e' OR 'a'가 아니라


def test_fts_query_caps_token_count():
    q = art._fts_query([f"w{i}" for i in range(500)])
    assert q.count(" OR ") == art.FTS_MAX_TOKENS - 1


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_non_positive_limit_returns_empty(art_db, limit):
    assert art.search(["sea"], limit=limit) == []


def test_fts_operational_error_falls_back_to_filter_search(art_db, monkeypatch, caplog):
    monkeypatch.setattr(art, "_fts_query", lambda kws: "AND")  # FTS5 문법 오류를 일으키는 질의
    with caplog.at_level(logging.WARNING, logger="app.art"):
        results = art.search(["sea"], artist="Turner", limit=10)
    assert _titles(results) == ["Stormy Sea"]
    assert any(r.getMessage().startswith("fts_query_failed") for r in caplog.records)


def test_broken_database_still_raises(tmp_path, monkeypatch):
    """대체 검색까지 실패하면(파일 없음 등) 숨기지 않고 예외를 올려 ART_DB_ERROR로 드러나게 한다."""
    monkeypatch.setattr(art, "ART_DB", tmp_path / "missing.db")
    with pytest.raises(sqlite3.OperationalError):
        art.search(["sea"], limit=3)
