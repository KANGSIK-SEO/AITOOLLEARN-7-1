"""사용자·대화 로그 DB.

백엔드는 환경변수로 고른다 (위에서부터 먼저 있는 것):
1. DATABASE_URL — PostgreSQL (운영: Neon, 2026-10-11부터). 백업·시점 복구·권한 관리가 되는 회사용 DB.
2. TURSO_DATABASE_URL — Turso(HTTP API). Neon으로 옮기기 전 운영 DB, 데이터 옮기기(copy_from_turso)의 원본.
3. 둘 다 없으면 로컬 SQLite 파일(data/app.db) — 개발·테스트용.
모든 백엔드를 execute(sql, params) -> list[dict] 로 똑같이 쓴다. SQL은 SQLite 문법(? 자리표시자)으로 쓰고,
Postgres로 보낼 때 여기서 %s로 바꾼다. (INSERT는 RETURNING 사용)
"""
import atexit
import decimal
import json
import socket
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request

from .config import ROOT, TIMEOUT_SECONDS

log = logging.getLogger("app.db")

# 이 시간(ms) 이상 걸린 쿼리는 db_slow_query 경고로 남긴다. Turso는 HTTP 왕복이 있어 로컬보다 느리므로
# 평소 왕복(수십~200ms)보다 넉넉히 잡았다. 0이면 모든 쿼리를 기록한다(로컬 디버깅용).
SLOW_QUERY_MS = int(os.environ.get("DB_SLOW_QUERY_MS", "500") or 500)
_SQL_LOG_MAX = 160

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS chats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        question    TEXT NOT NULL,
        answer      TEXT,
        status      TEXT NOT NULL CHECK (status IN ('ok', 'error')),
        error_code  TEXT,
        latency_ms  INTEGER,
        artwork_ids TEXT,          -- JSON 배열 (artworks.id)
        created_at  TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_chats_user_time ON chats (user_id, created_at)",
    # artwork_id는 별도 파일인 미술 DB(data/art.db)의 artworks.id라 FOREIGN KEY를 걸 수 없다.
    # 존재 여부는 API(POST /api/favorites)에서 art.get_by_ids()로 검증한다.
    """CREATE TABLE IF NOT EXISTS favorites (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL REFERENCES users(id),
        artwork_id  INTEGER NOT NULL,
        created_at  TEXT NOT NULL,
        UNIQUE (user_id, artwork_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_favorites_user_time ON favorites (user_id, created_at)",
    # 가디언: 장애·보안 사건 로그 + 자동 대응용 상태값
    """CREATE TABLE IF NOT EXISTS incidents (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT NOT NULL CHECK (category IN ('reliability', 'security')),
        code        TEXT NOT NULL,
        message     TEXT NOT NULL,
        context     TEXT,              -- JSON
        severity    TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
        auto_action TEXT,               -- 자동으로 적용한 대응 (없으면 NULL)
        diagnosis   TEXT,               -- gpt-6-astra 일일 분석 결과 (분석 전 NULL)
        created_at  TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_incidents_time ON incidents (created_at)",
    # 접속 기록: 1분마다 AI가 읽고 규칙에 없는 수상한 움직임을 찾는다 (2일 지나면 지운다)
    """CREATE TABLE IF NOT EXISTS access_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ip          TEXT NOT NULL,
        method      TEXT NOT NULL,
        path        TEXT NOT NULL,     -- 쿼리 포함, 300자까지
        status      INTEGER NOT NULL,
        user_agent  TEXT,
        ms          INTEGER,
        created_at  TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_access_log_time ON access_log (created_at)",
    # Claude 토큰 사용량: 목적(answer·intent·watch·triage …)별로 얼마나 쓰는지 보고 줄인다 (30일 보관)
    """CREATE TABLE IF NOT EXISTS ai_usage (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        purpose       TEXT NOT NULL,
        model         TEXT NOT NULL,
        input_tokens  INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        cache_read    INTEGER NOT NULL DEFAULT 0,
        cache_write   INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_usage_time ON ai_usage (created_at)",
    """CREATE TABLE IF NOT EXISTS runtime_flags (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
    # 권리 근거 기록: 발급 시점 스냅숏을 그대로 보관한다 (기관 데이터가 바뀌어도 기록은 안 바뀜)
    """CREATE TABLE IF NOT EXISTS rights_records (
        number      TEXT PRIMARY KEY,      -- PD-XXXX-XXXX-XXXX
        artwork_id  INTEGER NOT NULL,
        user_id     INTEGER,               -- 비로그인 발급이면 NULL
        snapshot    TEXT NOT NULL,         -- JSON: 작품·기관·판정·출처 표기·주의사항
        archives    TEXT NOT NULL,         -- JSON: 인터넷 아카이브 보관본 (나중에 채워질 수 있음)
        signature   TEXT NOT NULL,         -- HMAC(number|issued_at|snapshot) — 변조 확인용
        issued_at   TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS rate_counters (
        bucket       TEXT PRIMARY KEY,
        count        INTEGER NOT NULL,
        window_start TEXT NOT NULL
    )""",
]

# SCHEMA는 신규 DB 기준. 이미 배포된 DB에 컬럼을 추가할 때는 여기 ALTER TABLE을 쓴다.
# SQLite ALTER TABLE ADD COLUMN은 IF NOT EXISTS를 지원하지 않으므로, 이미 존재하면 나는
# "duplicate column" 오류를 ensure_schema()에서 무시한다.
MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0",
]

# Postgres용 스키마: 자동 증가 키만 BIGSERIAL로 바꾸고 나머지(TEXT 시각, CHECK, UNIQUE)는 그대로 쓴다.
# Postgres는 ADD COLUMN IF NOT EXISTS를 지원해 오류를 무시할 필요가 없다.
PG_SCHEMA = [s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") for s in SCHEMA]
PG_MIGRATIONS = [m.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS") for m in MIGRATIONS]
# 외래키 순서대로 (users가 먼저). copy_from_turso가 이 순서로 옮긴다.
TABLES = ["users", "chats", "favorites", "incidents", "access_log", "ai_usage", "runtime_flags",
          "rights_records", "rate_counters"]
SERIAL_TABLES = ["users", "chats", "favorites", "incidents", "access_log", "ai_usage"]

_initialized = False


class DbError(RuntimeError):
    pass


class DbTimeout(DbError):
    """Turso가 25초(TIMEOUT_SECONDS) 안에 답하지 않음 — 화면에는 '접속자가 많습니다'로 안내한다."""


def _pg_url() -> str | None:
    return os.environ.get("DATABASE_URL", "").strip() or None


def _turso_url() -> str | None:
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    return url.replace("libsql://", "https://", 1) if url else None


def backend() -> str:
    if _pg_url():
        return "postgres"
    return "turso" if _turso_url() else "local_sqlite"


# ---- PostgreSQL (Neon) ----
# 서버리스 함수는 요청마다 새로 연결하면 TLS 왕복이 매번 들어 느리다 → 작은 연결 풀을 프로세스마다 하나 둔다.
# Neon의 pooled 주소(-pooler)는 PgBouncer라 서버 쪽 prepared statement를 쓰면 안 된다 → prepare_threshold=None.
PG_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "5") or 5)
_pg_pool = None
_pg_pool_url: str | None = None


def _get_pg_pool():
    global _pg_pool, _pg_pool_url
    url = _pg_url()
    if _pg_pool is None or _pg_pool_url != url:
        from psycopg_pool import ConnectionPool   # Postgres를 쓸 때만 불러온다 (로컬 SQLite는 의존성 불필요)
        if _pg_pool is not None:
            _pg_pool.close()
        _pg_pool = ConnectionPool(
            url, min_size=1, max_size=PG_POOL_MAX, timeout=TIMEOUT_SECONDS, open=True,
            check=ConnectionPool.check_connection,   # Neon이 쉬는 동안 끊긴 연결을 걸러 낸다
            kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": int(TIMEOUT_SECONDS)})
        _pg_pool_url = url
    return _pg_pool


def close_pool() -> None:
    global _pg_pool
    if _pg_pool is not None:
        _pg_pool.close()
        _pg_pool = None


atexit.register(close_pool)   # 프로세스가 끝날 때 연결을 정리한다 (풀의 작업 스레드가 종료를 막지 않게)


def _pg_sql(sql: str, has_params: bool) -> str:
    """SQLite 문법의 ? 자리표시자를 psycopg의 %s로 바꾼다. 따옴표 안의 ?는 그대로 두고,
    값이 있을 때는 글자 그대로의 %(LIKE 'ip_block:%')를 %%로 바꿔 자리표시자로 오해하지 않게 한다."""
    if not has_params:
        return sql
    out, quote = [], None
    for ch in sql:
        if ch == "%":
            out.append("%%")
            continue
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "?":
            out.append("%s")
            continue
        out.append(ch)
    return "".join(out)


def _pg_param(v):
    return int(v) if isinstance(v, bool) else v   # is_premium 같은 정수 열에 True/False가 와도 SQLite처럼 0/1로


def _pg_value(v):
    if isinstance(v, decimal.Decimal):   # SUM()은 numeric을 돌려준다 — SQLite처럼 정수/실수로 맞춘다 (JSON 응답용)
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _pg_error(e: Exception) -> DbError:
    import psycopg
    from psycopg_pool import PoolTimeout
    if isinstance(e, (PoolTimeout, psycopg.errors.QueryCanceled, psycopg.errors.ConnectionTimeout)):
        return DbTimeout(f"Postgres 응답 시간 초과({TIMEOUT_SECONDS:g}s)")
    return DbError(str(e).strip() or type(e).__name__)


def _pg_run(cur, sql: str, params) -> list[dict]:
    params = tuple(_pg_param(p) for p in params or ())
    cur.execute(_pg_sql(sql, bool(params)), params or None)
    if cur.description is None:
        return []
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, (_pg_value(v) for v in row))) for row in cur.fetchall()]


def _pg_many(stmts: list[tuple[str, tuple]]) -> list[list[dict] | DbError]:
    """연결 하나로 차례로 실행한다 (autocommit이라 한 문장이 실패해도 나머지는 실행된다 — Turso pipeline과 같음)."""
    import psycopg
    from psycopg_pool import PoolTimeout
    out: list[list[dict] | DbError] = []
    try:
        with _get_pg_pool().connection() as conn, conn.cursor() as cur:
            for sql, params in stmts:
                try:
                    out.append(_pg_run(cur, sql, params))
                except psycopg.errors.QueryCanceled as e:
                    raise _pg_error(e) from e
                except psycopg.DatabaseError as e:
                    if conn.broken:
                        raise
                    out.append(_pg_error(e))
    except (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout) as e:
        raise _pg_error(e) from e
    return out


def _pg_execute(sql: str, params) -> list[dict]:
    result = _pg_many([(sql, params)])[0]
    if isinstance(result, DbError):
        raise result
    return result


def _to_arg(v) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _from_value(v: dict):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    return v.get("value")


def _turso_pipeline(base: str, stmts: list[tuple[str, tuple]]) -> list[list[dict] | DbError]:
    """여러 문장을 HTTP 요청 한 번(pipeline)으로 보낸다. Turso는 문장마다 왕복 시간이 들므로
    묶어 보내면 그만큼 빨라진다. 문장별 결과는 행 목록, 실패한 문장은 DbError로 돌려준다
    (한 문장이 실패해도 나머지는 실행된다)."""
    body = {"requests": [
        *({"type": "execute", "stmt": {"sql": sql, "args": [_to_arg(p) for p in params]}} for sql, params in stmts),
        {"type": "close"},
    ]}
    req = urllib.request.Request(
        f"{base}/v2/pipeline",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ.get('TURSO_AUTH_TOKEN', '')}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
    except (TimeoutError, socket.timeout) as e:
        raise DbTimeout(f"Turso 응답 시간 초과({TIMEOUT_SECONDS:g}s)") from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise DbTimeout(f"Turso 응답 시간 초과({TIMEOUT_SECONDS:g}s)") from e
        raise DbError(f"Turso 연결 실패: {e}") from e
    out = []
    for item in data["results"][:len(stmts)]:
        if item["type"] == "error":
            out.append(DbError(item["error"].get("message", "Turso 오류")))
            continue
        result = item["response"]["result"]
        cols = [c["name"] for c in result["cols"]]
        out.append([dict(zip(cols, (_from_value(v) for v in row))) for row in result["rows"]])
    return out


def _turso_execute(base: str, sql: str, params) -> list[dict]:
    result = _turso_pipeline(base, [(sql, params)])[0]
    if isinstance(result, DbError):
        raise result
    return result


def _local_execute(sql: str, params) -> list[dict]:
    path = os.environ.get("LOCAL_DB_PATH") or str(ROOT / "data" / "app.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        conn.commit()
        return rows
    except sqlite3.Error as e:
        raise DbError(str(e)) from e
    finally:
        conn.close()


def _local_many(stmts: list[tuple[str, tuple]]) -> list[list[dict] | DbError]:
    out = []
    for sql, params in stmts:
        try:
            out.append(_local_execute(sql, params))
        except DbError as e:
            out.append(e)
    return out


def _raw_many(stmts: list[tuple[str, tuple]]) -> list[list[dict] | DbError]:
    kind, base = backend(), _turso_url()
    started = time.monotonic()
    ok = False
    try:
        if kind == "postgres":
            results = _pg_many(stmts)
        else:
            results = _turso_pipeline(base, stmts) if kind == "turso" else _local_many(stmts)
        ok = True
        return results
    finally:
        _log_if_slow(" ; ".join(sql for sql, _ in stmts), int((time.monotonic() - started) * 1000), kind, ok)


def execute_many(stmts: list[tuple[str, tuple]]) -> list[list[dict]]:
    """서로 의존하지 않는 조회 여러 개를 한 번의 왕복으로 실행한다. 하나라도 실패하면 DbError."""
    ensure_schema()
    results = _raw_many(stmts)
    for r in results:
        if isinstance(r, DbError):
            raise r
    return results


def execute(sql: str, params=()) -> list[dict]:
    ensure_schema()
    return _raw_execute(sql, params)


def _raw_execute(sql: str, params=()) -> list[dict]:
    kind, base = backend(), _turso_url()
    started = time.monotonic()
    ok = False
    try:
        if kind == "postgres":
            rows = _pg_execute(sql, params)
        else:
            rows = _turso_execute(base, sql, params) if kind == "turso" else _local_execute(sql, params)
        ok = True
        return rows
    finally:
        _log_if_slow(sql, int((time.monotonic() - started) * 1000), kind, ok)


def _log_if_slow(sql: str, latency_ms: int, backend: str, ok: bool) -> None:
    """실패한 쿼리도 기록한다 (Turso 타임아웃처럼 느려서 실패한 경우가 가장 중요하다).
    params에는 이메일·비밀번호 해시·질문 본문이 들어가므로 SQL 문장만 남긴다."""
    if latency_ms < SLOW_QUERY_MS:
        return
    compact = re.sub(r"\s+", " ", sql).strip()
    if len(compact) > _SQL_LOG_MAX:
        compact = compact[:_SQL_LOG_MAX] + "…"
    log.warning("db_slow_query latency_ms=%s backend=%s ok=%s sql=%s", latency_ms, backend, ok, compact)


def _migrate_favorites_id() -> None:
    """한때 배포된 다른 버전은 favorites를 id 없이 (user_id, artwork_id) 기본키로 만들었다.
    현재 코드는 id를 쓰므로(RETURNING id) 그 모양이면 데이터를 보존한 채 다시 만든다."""
    cols = {r["name"] for r in _raw_execute("PRAGMA table_info(favorites)")}
    if not cols or "id" in cols:
        return
    log.warning("db_migrate favorites: id 컬럼 추가를 위해 테이블을 다시 만듭니다")
    _raw_execute("ALTER TABLE favorites RENAME TO favorites_old")
    _raw_execute(next(stmt for stmt in SCHEMA if "TABLE IF NOT EXISTS favorites" in stmt))
    _raw_execute("INSERT OR IGNORE INTO favorites (user_id, artwork_id, created_at) "
                 "SELECT user_id, artwork_id, created_at FROM favorites_old")
    _raw_execute("DROP TABLE favorites_old")
    for stmt in SCHEMA:  # 예전 테이블과 함께 사라진 인덱스를 다시 만든다
        if "INDEX" in stmt and " favorites " in stmt:
            _raw_execute(stmt)


def ensure_schema() -> None:
    """서버가 새로 뜰 때 한 번 실행된다. 예전에는 문장마다 Turso 왕복(12번)을 해서 첫 요청(보통 로그인)이
    느렸다 — 이제 테이블 생성·컬럼 추가·favorites 모양 확인을 요청 한 번으로 묶는다."""
    global _initialized
    if _initialized:
        return
    if backend() == "postgres":
        _ensure_pg_schema()
        _initialized = True
        log.info("db_schema_ready backend=postgres")
        return
    stmts = [(stmt, ()) for stmt in SCHEMA] + [("PRAGMA table_info(favorites)", ())] + [(m, ()) for m in MIGRATIONS]
    results = _raw_many(stmts)
    for (sql, _), r in zip(stmts, results):
        if isinstance(r, DbError) and not (sql in MIGRATIONS and "duplicate column" in str(r).lower()):
            raise r
    favorites_cols = {row["name"] for row in results[len(SCHEMA)]}
    if favorites_cols and "id" not in favorites_cols:
        _migrate_favorites_id()
    _initialized = True
    log.info("db_schema_ready backend=%s", backend())


def _ensure_pg_schema() -> None:
    """서버 여러 대가 동시에 처음 떠도 괜찮게, 다른 서버가 먼저 만들어 생긴 '이미 있음' 오류는 무시한다."""
    stmts = [(stmt, ()) for stmt in PG_SCHEMA + PG_MIGRATIONS]
    for (sql, _), r in zip(stmts, _raw_many(stmts)):
        if isinstance(r, DbError) and "already exists" not in str(r) and "duplicate key" not in str(r):
            raise r
    if _turso_url():
        try:
            _bump_sequences_past_turso()
        except DbError as e:   # 옮기기 준비가 실패해도 서비스는 띄운다 (옮기기 때 다시 맞춘다)
            log.error("db_sequence_bump_failed detail=%s", e)


def _bump_sequences_past_turso() -> None:
    """옮기기 전에 새로 생기는 행이 Turso의 id를 먼저 차지하지 않게, 자동 증가 번호를 Turso 최대 id 뒤로 보낸다
    (안 그러면 옮길 때 같은 id의 Turso 행이 '이미 있음'으로 건너뛰어진다)."""
    stmts = [(f"SELECT COALESCE(MAX(id), 0) AS m FROM {t}", ()) for t in SERIAL_TABLES]
    results = _turso_pipeline(_turso_url(), stmts)
    for table, r in zip(SERIAL_TABLES, results):
        if isinstance(r, DbError):
            raise r
        _pg_execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"GREATEST(?, COALESCE((SELECT MAX(id) FROM {table}), 0)) + 1, false)", (r[0]["m"],))


def copy_from_turso(table: str | None = None, after: int = 0, budget_seconds: float = 40.0,
                    batch: int = 500) -> dict:
    """Turso(원본)의 표를 Postgres(DATABASE_URL)로 옮긴다. id를 그대로 옮기고, 이미 있는 행은 건너뛴다.
    Vercel 함수는 60초 한도라 budget_seconds가 지나면 멈추고 다음 위치(next: 표·rowid)를 돌려준다 —
    부른 쪽(.github/workflows/migrate-db.yml)이 그 위치로 다시 부른다. 여러 번 불러도 안전하다.
    운영에서는 /api/guardian/migrate-from-turso(CRON_SECRET 보호)로 부른다."""
    base = _turso_url()
    if not base or backend() != "postgres":
        raise DbError("DATABASE_URL(Postgres)과 TURSO_DATABASE_URL(원본)이 둘 다 있어야 옮길 수 있습니다.")
    if table is not None and table not in TABLES:
        raise DbError(f"모르는 표입니다: {table}")
    ensure_schema()
    _bump_sequences_past_turso()
    started = time.monotonic()
    copied: dict = {}
    for name in TABLES[TABLES.index(table) if table else 0:]:
        cursor = after if name == table else 0
        stats = copied.setdefault(name, {"read": 0, "inserted": 0})
        while True:
            if time.monotonic() - started > budget_seconds:
                return {"done": False, "next": {"table": name, "after": cursor}, "copied": copied}
            rows = _turso_execute(base, f"SELECT rowid AS _rowid, * FROM {name} WHERE rowid > ? ORDER BY rowid LIMIT ?",
                                  (cursor, batch))
            if not rows:
                break
            cols = [c for c in rows[0] if c != "_rowid"]
            one_row = f"({', '.join('?' * len(cols))})"   # 여러 행을 문장 하나로 — 왕복 횟수를 줄인다
            sql = (f"INSERT INTO {name} ({', '.join(cols)}) VALUES {', '.join([one_row] * len(rows))} "
                   "ON CONFLICT DO NOTHING RETURNING 1 AS x")
            stats["inserted"] += len(_pg_execute(sql, tuple(row[c] for row in rows for c in cols)))
            stats["read"] += len(rows)
            cursor = rows[-1]["_rowid"]
    _bump_sequences_past_turso()
    log.warning("db_copy_from_turso %s", json.dumps(copied))
    return {"done": True, "next": None, "copied": copied}


def reset_for_tests() -> None:
    global _initialized
    _initialized = False
