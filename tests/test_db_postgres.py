"""Postgres(Neon) 백엔드: SQLite 문법 바꾸기는 항상, 실제 DB 동작은 TEST_DATABASE_URL이 있을 때만 시험한다."""
import decimal
import os

import pytest

from app import db

needs_pg = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL 없음")


def test_placeholders_become_psycopg_style_but_quoted_text_is_kept():
    sql = "SELECT * FROM t WHERE a = ? AND b LIKE 'ip_block:%' AND c = '?' AND d IN (?, ?)"
    assert db._pg_sql(sql, True) == "SELECT * FROM t WHERE a = %s AND b LIKE 'ip_block:%%' AND c = '?' AND d IN (%s, %s)"
    assert db._pg_sql("SELECT 1 WHERE k LIKE 'x:%'", False) == "SELECT 1 WHERE k LIKE 'x:%'"  # 값이 없으면 그대로


def test_values_match_sqlite_types():
    assert db._pg_value(decimal.Decimal("12")) == 12 and isinstance(db._pg_value(decimal.Decimal("12")), int)
    assert db._pg_value(decimal.Decimal("1.5")) == 1.5
    assert db._pg_param(True) == 1 and db._pg_param(False) == 0 and db._pg_param("a") == "a"


def test_backend_order_prefers_postgres(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    assert db.backend() == "postgres"
    monkeypatch.delenv("DATABASE_URL")
    assert db.backend() == "turso"
    monkeypatch.delenv("TURSO_DATABASE_URL")
    assert db.backend() == "local_sqlite"


def test_copy_needs_both_databases(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    with pytest.raises(db.DbError, match="둘 다"):
        db.copy_from_turso()


@needs_pg
def test_postgres_schema_returning_and_sums():
    row = db.execute("INSERT INTO users (email, password_hash, is_premium, created_at) VALUES (?, ?, ?, ?) RETURNING id",
                     ("a@x.com", "h", True, "2026-10-11T00:00:00+00:00"))[0]
    assert isinstance(row["id"], int)
    with pytest.raises(db.DbError):   # UNIQUE(email) 위반은 DbError (동시 가입 처리에 쓰인다)
        db.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)", ("a@x.com", "h", "t"))
    db.execute("INSERT INTO ai_usage (purpose, model, input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?)",
               ("answer", "m", 10, 2, "t"))
    assert db.execute("SELECT SUM(input_tokens) AS n FROM ai_usage")[0]["n"] == 10


@needs_pg
def test_copy_from_turso_keeps_ids_resumes_and_moves_sequences(monkeypatch):
    """Turso 쪽은 가짜(rowid 순서로 잘라 주는)로 바꾸고, Postgres는 진짜로 넣는다."""
    source = {t: [] for t in db.TABLES}
    source["users"] = [{"_rowid": i, "id": i, "email": f"u{i}@x.com", "password_hash": "h", "created_at": "t",
                        "is_premium": 0} for i in (3, 7, 9)]
    source["favorites"] = [{"_rowid": 1, "id": 5, "user_id": 7, "artwork_id": 42, "created_at": "t"}]
    source["runtime_flags"] = [{"_rowid": 1, "key": "k", "value": "v", "updated_at": "t"}]

    def fake_turso(base, sql, params):
        table = sql.split(" FROM ")[1].split()[0]
        after, limit = params
        return [r for r in source[table] if r["_rowid"] > after][:limit]

    def fake_pipeline(base, stmts):
        return [[{"m": max((r["id"] for r in source[s.split(" FROM ")[1].split()[0]]), default=0)}] for s, _ in stmts]

    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    monkeypatch.setattr(db, "_turso_execute", fake_turso)
    monkeypatch.setattr(db, "_turso_pipeline", fake_pipeline)
    first = db.copy_from_turso(batch=2, budget_seconds=-1)   # 시간이 없으면 바로 다음 위치를 돌려준다
    assert first == {"done": False, "next": {"table": "users", "after": 0}, "copied": {"users": {"read": 0, "inserted": 0}}}
    done = db.copy_from_turso(batch=2)
    assert done["done"] and done["copied"]["users"] == {"read": 3, "inserted": 3}
    again = db.copy_from_turso()   # 다시 불러도 안전하다
    assert again["copied"]["users"] == {"read": 3, "inserted": 0}
    assert [r["id"] for r in db.execute("SELECT id FROM users ORDER BY id")] == [3, 7, 9]
    new_id = db.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?) RETURNING id",
                        ("new@x.com", "h", "t"))[0]["id"]
    assert new_id == 10   # 옮긴 id 뒤 번호부터
    assert db.execute("SELECT artwork_id FROM favorites WHERE user_id = ?", (7,)) == [{"artwork_id": 42}]
