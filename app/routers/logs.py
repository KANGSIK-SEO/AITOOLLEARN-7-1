"""대화 로그 조회 라우트: 로그인한 사용자는 자기 질문·답변·실패 기록만 최신순으로 본다.

대화 로그를 남기는 이유: 사용자는 지난 답변을 다시 보고(왼쪽 대화 기록 사이드바), 운영자는 실패한 질문의
error_code·latency_ms로 장애 원인을 추적하며, 쌓인 질문으로 검색·답변 품질을 개선한다.
"""
from fastapi import APIRouter, Depends

from .. import repository
from ..deps import current_user
from ..schemas import ChatLogsResponse, ErrorResponse

router = APIRouter(tags=["logs"])


@router.get("/api/me/chats", response_model=ChatLogsResponse, responses={401: {"model": ErrorResponse}})
def my_chats(limit: int = 20, offset: int = 0, user_id: int = Depends(current_user)):
    return {"chats": repository.list_chats(user_id, max(1, min(limit, 100)), max(0, offset))}
