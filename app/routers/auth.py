"""인증 라우트: 회원가입·로그인·로그아웃·내 정보."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import auth, db, guardian, repository
from ..deps import COOKIE, current_user
from ..errors import error
from ..schemas import AuthResponse, Credentials, ErrorResponse, MeResponse

router = APIRouter(tags=["auth"])
log = logging.getLogger("app")


def _set_cookie(resp: JSONResponse, token: str, request: Request) -> None:
    resp.set_cookie(COOKIE, token, max_age=auth.TOKEN_TTL_SECONDS,
                    httponly=True, samesite="lax", secure=request.url.scheme == "https")


def _auth_response(user_id: int, email: str, is_premium: bool, request: Request, status_code: int) -> JSONResponse:
    token = auth.make_token(user_id, is_premium)
    resp = JSONResponse({"user": {"id": user_id, "email": email, "is_premium": is_premium}, "token": token},
                        status_code=status_code)
    _set_cookie(resp, token, request)
    return resp


@router.post("/api/auth/signup", status_code=201, response_model=AuthResponse,
             responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def signup(body: Credentials, request: Request):
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"signup:{ip}", limit=10, window_seconds=3600):
        guardian.record_incident("security", "SIGNUP_RATE_LIMITED", f"{ip} 가입 시도 과다", {"ip": ip}, "medium")
        return error(429, "RATE_LIMITED", "가입 시도가 너무 많아요. 잠시 후 다시 시도해 주세요.")
    email = body.email.strip().lower()
    if not auth.EMAIL_RE.match(email) or len(email) > 254:
        return error(400, "INVALID_EMAIL", "이메일 형식이 올바르지 않습니다.")
    if not 8 <= len(body.password) <= 128:
        return error(400, "INVALID_PASSWORD", "비밀번호는 8자 이상 128자 이하여야 합니다.")
    if repository.email_exists(email):
        return error(409, "EMAIL_TAKEN", "이미 가입된 이메일입니다.")
    is_premium = auth.check_premium_code(body.private_code)
    try:
        user_id = repository.create_user(email, auth.hash_password(body.password), is_premium)
    except db.DbError:  # 동시 가입으로 UNIQUE 충돌
        return error(409, "EMAIL_TAKEN", "이미 가입된 이메일입니다.")
    log.info("signup_success user_id=%s is_premium=%s", user_id, is_premium)
    return _auth_response(user_id, email, is_premium, request, 201)


@router.post("/api/auth/login", response_model=AuthResponse,
             responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def login(body: Credentials, request: Request):
    ip = guardian.client_ip(request)
    email = body.email.strip().lower()
    if guardian.check_login_lockout(email) or not guardian.check_rate(f"login:{ip}", limit=20, window_seconds=600):
        return error(429, "RATE_LIMITED", "로그인 시도가 너무 많아요. 잠시 후 다시 시도해 주세요.")
    user = repository.find_user_by_email(email)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        log.info("login_failed")
        guardian.note_login_failure(email, ip)
        return error(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
    is_premium = bool(user["is_premium"])
    log.info("login_success user_id=%s is_premium=%s", user["id"], is_premium)
    return _auth_response(user["id"], email, is_premium, request, 200)


@router.post("/api/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@router.get("/api/me", response_model=MeResponse, responses={401: {"model": ErrorResponse}})
def me(user_id: int = Depends(current_user)):
    user = repository.get_user(user_id)
    if not user:
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "로그인이 필요합니다."})
    return {"user": user}
