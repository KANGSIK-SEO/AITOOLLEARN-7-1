"""운영 점검 라우트(/api/guardian/*): 스케줄러(Vercel Cron·GitHub Actions)만 CRON_SECRET으로 부른다."""
import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import guardian
from ..deps import require_cron
from . import health

router = APIRouter(prefix="/api/guardian", tags=["ops"], dependencies=[Depends(require_cron)])


@router.get("/daily-digest")
def guardian_daily_digest():
    """가디언의 일일 점검 (Vercel Cron 전용)."""
    return guardian.run_daily_digest()


@router.api_route("/scan", methods=["GET", "POST"])
def guardian_scan():
    """1분 실시간 점검 (monitor.yml이 1분마다 POST, 외부 점검 서비스는 GET).
    DB·작품 DB·챗봇 AI가 실제로 답하는지 확인하고 가디언 점검(접속 감시·부하·사건)을 돌린다.
    하나라도 고장이면 503 — 바깥 점검 서비스가 실패로 보고 알림을 보낸다."""
    try:
        checks = health.dependency_checks()
        result = guardian.scan()
        healthy = (all(c["status"] == "ok" for c in checks.values()) and result["ai"].get("status") == "ok"
                   and not result["failed_steps"])
        body = json.loads(json.dumps({"status": "ok" if healthy else "degraded", "checks": checks, **result},
                                     default=str))   # 응답으로 못 바꾸는 값이 섞여도 500이 나지 않게
    except Exception as e:  # noqa: BLE001 — 원인 모를 500 대신 위치를 남기고 503 (2026-10-09)
        failure = guardian.report_scan_failure("scan", e)
        return JSONResponse({"status": "degraded", "failed_steps": ["scan"], "scan": failure},
                            status_code=503, headers={"Cache-Control": "no-store"})
    return JSONResponse(body, status_code=200 if healthy else 503, headers={"Cache-Control": "no-store"})


@router.get("/summary")
def guardian_summary():
    """품질 점검용 운영 요약 (.github/workflows/quality-review.yml)."""
    return guardian.summary()


@router.get("/visitors")
def guardian_visitors():
    """앱을 연 날부터의 방문자 숫자 (.github/workflows/visitors.yml)."""
    return guardian.visitor_stats()
