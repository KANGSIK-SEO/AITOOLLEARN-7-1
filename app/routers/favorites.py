"""작품 즐겨찾기 라우트 (로그인 필수, 상세: docs/track-c.md)."""
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from .. import art, repository
from ..deps import current_user
from ..errors import error
from ..schemas import FavoriteRequest

router = APIRouter(tags=["favorites"])
log = logging.getLogger("app")


def _artwork_or_404(artwork_id: int) -> None:
    try:
        exists = artwork_id in art.get_by_ids([artwork_id])
    except sqlite3.Error as e:
        log.error("art_db_failure path=/api/favorites detail=%s", e)
        raise HTTPException(503, {"code": "ART_DB_ERROR", "message": "작품 데이터베이스를 읽지 못했어요."})
    if not exists:
        raise HTTPException(404, {"code": "ARTWORK_NOT_FOUND", "message": "존재하지 않는 작품입니다."})


@router.post("/api/favorites")
def add_favorite(body: FavoriteRequest, user_id: int = Depends(current_user)):
    """이미 저장한 작품이면 200(created=false), 새로 저장하면 201. 같은 요청을 반복해도 안전하다."""
    _artwork_or_404(body.artwork_id)
    created = repository.add_favorite(user_id, body.artwork_id)
    log.info("favorite_add user_id=%s artwork_id=%s created=%s", user_id, body.artwork_id, created)
    return JSONResponse({"artwork_id": body.artwork_id, "created": created},
                        status_code=201 if created else 200)


@router.delete("/api/favorites/{artwork_id}")
def remove_favorite(artwork_id: int, user_id: int = Depends(current_user)):
    """저장하지 않은 작품을 지워도 오류가 아니다(removed=false)."""
    removed = repository.remove_favorite(user_id, artwork_id)
    log.info("favorite_remove user_id=%s artwork_id=%s removed=%s", user_id, artwork_id, removed)
    return {"artwork_id": artwork_id, "removed": removed}


@router.get("/api/me/favorites")
def my_favorites(limit: int = 20, offset: int = 0, user_id: int = Depends(current_user)):
    """최근 저장 순. 미술 DB에서 사라진 작품은 목록에서 빠진다."""
    rows = repository.list_favorites(user_id, max(1, min(limit, 100)), max(0, offset))
    try:
        cards = art.get_by_ids([r["artwork_id"] for r in rows])
    except sqlite3.Error as e:
        log.error("art_db_failure path=/api/me/favorites detail=%s", e)
        return error(503, "ART_DB_ERROR", "작품 데이터베이스를 읽지 못했어요.")
    return {"favorites": [{**cards[r["artwork_id"]], "favorited_at": r["created_at"]}
                          for r in rows if r["artwork_id"] in cards]}
