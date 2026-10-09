"""사용자 DB 접근(리포지토리): users·chats·favorites 테이블을 읽고 쓰는 SQL을 한곳에 모은다.

라우터는 SQL을 모르고 이 함수들만 부른다. 접속(Turso/로컬 SQLite 선택)·타임아웃은 app/db.py가 맡는다.
작품 DB(data/art.db, 읽기 전용) 검색은 app/art.py, 가디언 표(incidents 등)는 app/guardian.py가 맡는다.
"""
import json
import logging
from datetime import datetime, timezone

from . import db

log = logging.getLogger("app")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ping() -> None:
    db.execute("SELECT 1 AS ok")


# ---- users ----
def email_exists(email: str) -> bool:
    return bool(db.execute("SELECT 1 AS x FROM users WHERE email = ?", (email,)))


def create_user(email: str, password_hash: str, is_premium: bool) -> int:
    """새 사용자 번호. 같은 이메일이 동시에 가입하면 UNIQUE 충돌로 db.DbError."""
    return db.execute(
        "INSERT INTO users (email, password_hash, is_premium, created_at) VALUES (?, ?, ?, ?) RETURNING id",
        (email, password_hash, int(is_premium), now()))[0]["id"]


def find_user_by_email(email: str) -> dict | None:
    rows = db.execute("SELECT id, password_hash, is_premium FROM users WHERE email = ?", (email,))
    return rows[0] if rows else None


def get_user(user_id: int) -> dict | None:
    rows = db.execute("SELECT id, email, created_at, is_premium FROM users WHERE id = ?", (user_id,))
    if not rows:
        return None
    user = rows[0]
    user["is_premium"] = bool(user["is_premium"])
    return user


# ---- chats (대화 로그) ----
def save_chat(user_id, question, answer, status, error_code, latency_ms, artwork_ids) -> int | None:
    """질문·답변을 남긴다. 저장에 실패해도 답변은 사용자에게 가야 하므로 예외 대신 None을 돌려준다."""
    try:
        row = db.execute(
            "INSERT INTO chats (user_id, question, answer, status, error_code, latency_ms, artwork_ids, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (user_id, question, answer, status, error_code, latency_ms, json.dumps(artwork_ids), now()))[0]
        log.info("db_save_success user_id=%s chat_id=%s status=%s", user_id, row["id"], status)
        return row["id"]
    except db.DbError as e:
        log.error("db_save_failure user_id=%s detail=%s", user_id, e)
        return None


def chat_precheck(user_id: int, since: str, context_turns: int) -> tuple[list, list, list, list]:
    """질문 전 확인 4가지(AI 쉬는 중인지·이번 시간 사용량·누적 사용량·최근 대화)를 DB 왕복 한 번으로 읽는다."""
    return db.execute_many([
        ("SELECT value FROM runtime_flags WHERE key = 'ai_backoff_until'", ()),
        ("SELECT COUNT(*) AS n FROM chats WHERE user_id = ? AND created_at > ?", (user_id, since)),
        ("SELECT COUNT(*) AS n FROM chats WHERE user_id = ? AND status = 'ok'", (user_id,)),
        ("SELECT question, answer FROM chats WHERE user_id = ? AND status = 'ok' ORDER BY id DESC LIMIT ?",
         (user_id, context_turns)),
    ])


def list_chats(user_id: int, limit: int, offset: int) -> list[dict]:
    return db.execute(
        "SELECT id, question, answer, status, error_code, latency_ms, created_at FROM chats "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?", (user_id, limit, offset))


# ---- favorites ----
def add_favorite(user_id: int, artwork_id: int) -> bool:
    """새로 저장했으면 True, 이미 저장돼 있었으면 False."""
    return bool(db.execute(
        "INSERT INTO favorites (user_id, artwork_id, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT (user_id, artwork_id) DO NOTHING RETURNING id",
        (user_id, artwork_id, now())))


def remove_favorite(user_id: int, artwork_id: int) -> bool:
    return bool(db.execute("DELETE FROM favorites WHERE user_id = ? AND artwork_id = ? RETURNING id",
                           (user_id, artwork_id)))


def list_favorites(user_id: int, limit: int, offset: int) -> list[dict]:
    return db.execute(
        "SELECT artwork_id, created_at FROM favorites WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (user_id, limit, offset))
