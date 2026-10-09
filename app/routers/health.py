"""상태 점검 라우트: /api/health(프로세스 생존), /healthz(DB까지 실제 확인)."""
import logging
import sqlite3
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import art, db, repository
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])
log = logging.getLogger("app")


def dependency_checks() -> dict:
    checks = {}
    for name, probe, errors in (("db", repository.ping, db.DbError),
                                ("art_db", art.ping, sqlite3.Error)):
        started = time.monotonic()
        try:
            probe()
            checks[name] = {"status": "ok", "latency_ms": int((time.monotonic() - started) * 1000)}
        except errors as e:
            log.error("healthz_check_failed check=%s detail=%s", name, e)
            checks[name] = {"status": "error"}
    return checks


@router.get("/api/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


@router.get("/healthz")
def healthz():
    """의존성까지 확인하는 상태 점검 (업타임 모니터·배포 후 확인용).

    /api/health는 프로세스가 떠 있는지만 본다(항상 200). /healthz는 사용자 DB(Turso/로컬)와
    미술 DB(data/art.db)에 실제로 쿼리를 보내, 하나라도 실패하면 503을 돌려준다.
    AI는 호출마다 비용이 들고 외부 장애가 곧 우리 장애는 아니므로 확인하지 않는다.
    오류 상세(접속 주소·경로)는 응답에 넣지 않고 로그에만 남긴다.
    """
    checks = dependency_checks()
    healthy = all(c["status"] == "ok" for c in checks.values())
    return JSONResponse({"status": "ok" if healthy else "degraded", "checks": checks},
                        status_code=200 if healthy else 503, headers={"Cache-Control": "no-store"})
