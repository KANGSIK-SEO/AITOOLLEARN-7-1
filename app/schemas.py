"""요청/응답 스키마: API가 주고받는 데이터의 모양을 한곳에 모은다.

요청 스키마는 형식이 틀리면 FastAPI가 자동으로 422 INVALID_INPUT을 돌려준다(app/errors.py).
빈 질문·길이 초과처럼 사용자에게 구체적으로 안내해야 하는 검사는 라우터에서 한다 — 그래야
EMPTY_MESSAGE, MESSAGE_TOO_LONG 같은 알아보기 쉬운 오류 코드를 줄 수 있다.
응답 스키마는 /docs(자동 API 문서)에 응답 모양을 보여 주고, 실수로 다른 필드가 새어 나가지 않게 거른다.
"""
from pydantic import BaseModel


# ---- 요청 ----
class Credentials(BaseModel):
    email: str
    password: str
    private_code: str | None = None  # 회원가입 시에만 사용. 일치하면 프리미엄으로 가입된다.


class ChatRequest(BaseModel):
    message: str


class FavoriteRequest(BaseModel):
    artwork_id: int


class RecordRequest(BaseModel):
    artwork_id: int


class ExplainRequest(BaseModel):
    question: str
    secret: str


# ---- 응답 ----
class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """모든 오류 응답의 공통 모양: {"error": {"code": "...", "message": "..."}}"""
    error: ErrorBody


class User(BaseModel):
    id: int
    email: str
    is_premium: bool


class UserDetail(User):
    created_at: str


class AuthResponse(BaseModel):
    user: User
    token: str


class MeResponse(BaseModel):
    user: UserDetail


class ChatLog(BaseModel):
    id: int
    question: str
    answer: str | None
    status: str
    error_code: str | None
    latency_ms: int | None
    created_at: str


class ChatLogsResponse(BaseModel):
    chats: list[ChatLog]


class HealthResponse(BaseModel):
    status: str
