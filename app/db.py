"""사용자·대화 로그 DB.

TURSO_DATABASE_URL이 있으면 Turso(HTTP API), 없으면 로컬 SQLite 파일(data/app.db)을 쓴다.
두 백엔드 모두 execute(sql, params) -> list[dict] 로 동일하게 사용한다. (INSERT는 RETURNING 사용)
"""
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request

from .config import ROOT

log = logging.getLogger("app.db")

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
    """CREATE TABLE IF NOT EXISTS runtime_flags (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS favorites (
        user_id     INTEGER NOT NULL REFERENCES users(id),
        artwork_id  INTEGER NOT NULL,      -- data/art.db artworks.id
        created_at  TEXT NOT NULL,
        PRIMARY KEY (user_id, artwork_id)
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

_initialized = False


class DbError(RuntimeError):
    pass


def _turso_url() -> str | None:
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    return url.replace("libsql://", "https://", 1) if url else None


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


def _turso_execute(base: str, sql: str, params) -> list[dict]:
    body = {"requests": [
        {"type": "execute", "stmt": {"sql": sql, "args": [_to_arg(p) for p in params]}},
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError) as e:
        raise DbError(f"Turso 연결 실패: {e}") from e
    first = data["results"][0]
    if first["type"] == "error":
        raise DbError(first["error"].get("message", "Turso 오류"))
    result = first["response"]["result"]
    cols = [c["name"] for c in result["cols"]]
    return [dict(zip(cols, (_from_value(v) for v in row))) for row in result["rows"]]


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


def execute(sql: str, params=()) -> list[dict]:
    ensure_schema()
    return _raw_execute(sql, params)


def _raw_execute(sql: str, params=()) -> list[dict]:
    base = _turso_url()
    return _turso_execute(base, sql, params) if base else _local_execute(sql, params)


def ensure_schema() -> None:
    global _initialized
    if _initialized:
        return
    for stmt in SCHEMA:
        _raw_execute(stmt)
    for stmt in MIGRATIONS:
        try:
            _raw_execute(stmt)
        except DbError as e:
            if "duplicate column" not in str(e).lower():
                raise
    _initialized = True
    log.info("db_schema_ready backend=%s", "turso" if _turso_url() else "local_sqlite")


def reset_for_tests() -> None:
    global _initialized
    _initialized = False
