"""권리 근거 기록 라우트 (docs/rights-policy.md §5). 로그인하지 않아도 발급할 수 있다(optional_session)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from .. import guardian, records
from ..config import RECORD_LIMIT_PER_HOUR
from ..deps import optional_session
from ..errors import error
from ..schemas import RecordRequest

router = APIRouter(tags=["records"])


@router.post("/api/records")
def issue_record(body: RecordRequest, request: Request, session_data: dict | None = Depends(optional_session)):
    """권리 근거 기록 발급: 스냅숏 저장 → 인터넷 아카이브 보관 시도 → 기록 번호."""
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"record:{ip}", limit=RECORD_LIMIT_PER_HOUR, window_seconds=3600):
        return error(429, "RATE_LIMITED", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
    try:
        number = records.issue(body.artwork_id, session_data["uid"] if session_data else None)
    except LookupError:
        return error(404, "ARTWORK_NOT_FOUND", "작품을 찾을 수 없습니다.")
    except records.RecordNotAllowed as e:
        return error(409, "RECORD_NOT_ALLOWED", f"판단 규칙({', '.join(e.failed)})을 통과하지 못해 기록을 발급할 수 없어요.")
    archives = records.archive_missing(number)  # 실패해도 기록은 이미 저장됨 — 기록 페이지에서 다시 시도 가능
    return {"number": number, "url": f"/records/{number}", "archived": all(a["archived_url"] for a in archives)}


@router.post("/api/records/{number}/archive")
def retry_archive(number: str, request: Request):
    ip = guardian.client_ip(request)
    if not guardian.check_rate(f"archive:{ip}", limit=120, window_seconds=3600):
        return error(429, "RATE_LIMITED", "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.")
    try:
        archives = records.archive_missing(number)
    except LookupError:
        return error(404, "RECORD_NOT_FOUND", "기록을 찾을 수 없습니다.")
    return {"archives": archives}


@router.get("/records/{number}", response_class=HTMLResponse)
def show_record(number: str):
    row = records.get(number)
    if not row:
        return HTMLResponse("<h1>기록을 찾을 수 없습니다.</h1>", status_code=404)
    return HTMLResponse(records.render(row))
