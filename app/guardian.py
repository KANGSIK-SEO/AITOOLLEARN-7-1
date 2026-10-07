"""가디언 — 안정성 장애와 보안 위협을 함께 감시·대응한다.

- 실시간(매 요청): 비용이 들지 않는 결정적 규칙만 적용한다 (로그인 잠금, AI 백오프,
  악성 입력 차단, IP 레이트리밋). GPT를 요청마다 부르지 않는 이유는, 그렇게 하면
  공격자가 실패 요청을 반복시켜 AI 비용 자체를 디도스 벡터로 쓸 수 있기 때문이다.
- 배치(1일 1회, Vercel Cron): 쌓인 사건을 모아 gpt-6-astra로 한 번에 분석해
  원인 진단 + 추세 예측 + (필요 시) GitHub 이슈 생성까지 수행한다.

왜 GPT가 "진단만" 하고 코드를 고치거나 실행하지 않는가 (의도적 경계):
Sun, Zhu, Xu, Du, Li, Lo, "Toward Agentic Runtime Healing" (CACM, Oct 2026, 68.9)는
LLM이 에러 발생 시 소스코드가 아니라 "런타임 상태"만 즉석에서 고쳐 요청 하나를 살리는
HEALER를 제안한다 — GPT-4 기준 73%가 실행을 이어가고 39.6%는 정답까지 낸다. 하지만
저자들 스스로 결론 내리길, 진짜 장벽은 효과성이 아니라 신뢰성이다: LLM이 생성한 치유
코드의 75%만 "인식 가능한 패턴"이고, 화이트리스트·샌드박스 같은 안전장치가 아직
미성숙(underdeveloped)하다고 명시한다. 이들은 개입을 "comfort zone"(부작용이 허용되는
비핵심 영역)으로 한정해야 한다고도 제안한다.
우리는 이 논문의 결론을 그대로 받아들여, LLM이 생성한 코드를 실행하거나 커밋하는
어떤 경로도 만들지 않았다 — 진단(텍스트)과 사람이 보는 GitHub 이슈 생성까지만 자동화하고,
결정적 규칙(잠금/백오프/차단)만 "comfort zone"(상태값 변경, 되돌리기 쉬움)에서 즉시
자동 적용한다. 이 선택은 임의적 보수주의가 아니라, 같은 분야 최신 연구가 "아직은
이게 맞다"고 말하는 지점과 일치한다.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import db, llm
from .config import AIUnavailableError

log = logging.getLogger("app.guardian")

GITHUB_REPO = os.environ.get("GITHUB_REPO", "KANGSIK-SEO/AITOOLLEARN-7-1")

SUSPICIOUS_INPUT_RE = re.compile(
    r"<script|javascript:|onerror\s*=|union\s+select|;\s*drop\s+table|exec\s*\(", re.IGNORECASE
)

DIGEST_SYSTEM = (
    "너는 'AITOOLLEARN-7-1' 웹서비스의 가디언이다. 아래는 최근 미분석 사건 로그(JSON 배열)다.\n"
    "각 사건은 category(reliability|security), code, message, context, severity, created_at을 가진다.\n"
    "다음을 한국어로 간결히 작성하라:\n"
    "1. 요약: 지금 벌어지고 있는 일\n"
    "2. 패턴: 같은 code/identifier가 반복되거나 늘어나는 추세가 있는가 (디도스·크리덴셜 스터핑·버그 등)\n"
    "3. 예측: 지금 추세가 이어지면 다음에 어떤 장애·침해가 터질 가능성이 있는가\n"
    "4. 권장 조치: 코드 수정이 필요하면 구체적으로, 당장 조치가 필요없으면 '관찰 유지'라고 쓴다\n"
    "5. 마지막 줄에 'URGENCY: low' 또는 'URGENCY: medium' 또는 'URGENCY: high' 중 하나만 쓴다."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def looks_malicious(text: str) -> bool:
    return bool(SUSPICIOUS_INPUT_RE.search(text))


# ---- 사건 기록 ----

def record_incident(category: str, code: str, message: str, context: dict | None = None,
                    severity: str = "low", auto_action: str | None = None) -> int | None:
    try:
        row = db.execute(
            "INSERT INTO incidents (category, code, message, context, severity, auto_action, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (category, code, message, json.dumps(context or {}, ensure_ascii=False), severity, auto_action, _now())
        )[0]
        return row["id"]
    except db.DbError as e:
        log.error("incident_save_failure code=%s detail=%s", code, e)
        return None


# ---- Tier 1: 비용 없는 즉시 대응 (매 요청) ----

def check_rate(bucket: str, limit: int, window_seconds: int) -> bool:
    """bucket 단위 고정 윈도 카운터. True면 허용, False면 초과."""
    now = datetime.now(timezone.utc)
    try:
        rows = db.execute("SELECT count, window_start FROM rate_counters WHERE bucket = ?", (bucket,))
        if not rows:
            db.execute("INSERT INTO rate_counters (bucket, count, window_start) VALUES (?, 1, ?)",
                      (bucket, now.isoformat()))
            return True
        count, window_start = rows[0]["count"], datetime.fromisoformat(rows[0]["window_start"])
        if now - window_start > timedelta(seconds=window_seconds):
            db.execute("UPDATE rate_counters SET count = 1, window_start = ? WHERE bucket = ?",
                      (now.isoformat(), bucket))
            return True
        if count >= limit:
            return False
        db.execute("UPDATE rate_counters SET count = count + 1 WHERE bucket = ?", (bucket,))
        return True
    except db.DbError as e:
        log.error("rate_check_failure bucket=%s detail=%s", bucket, e)
        return True  # DB 장애로 사용자를 막지 않는다


def rate_used(bucket: str, window_seconds: int) -> int:
    """check_rate와 같은 카운터를 올리지 않고 읽기만 한다 (남은 체험 횟수 표시용)."""
    try:
        rows = db.execute("SELECT count, window_start FROM rate_counters WHERE bucket = ?", (bucket,))
    except db.DbError as e:
        log.error("rate_read_failure bucket=%s detail=%s", bucket, e)
        return 0
    if not rows:
        return 0
    if datetime.now(timezone.utc) - datetime.fromisoformat(rows[0]["window_start"]) > timedelta(seconds=window_seconds):
        return 0
    return rows[0]["count"]


def _set_flag(key: str, value: str) -> None:
    db.execute(
        "INSERT INTO runtime_flags (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, _now()),
    )


def _flag_active_until(key: str) -> bool:
    rows = db.execute("SELECT value FROM runtime_flags WHERE key = ?", (key,))
    return bool(rows) and datetime.now(timezone.utc) < datetime.fromisoformat(rows[0]["value"])


def is_ai_backed_off() -> bool:
    return _flag_active_until("ai_backoff_until")


def note_ai_failure(code: str) -> None:
    """같은 종류의 AI 실패(429)가 짧은 시간에 반복되면 자동으로 쉬어간다 (비용 보호)."""
    if code != "AI_RATE_LIMITED":
        return
    since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    recent = db.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE category = 'reliability' AND code = 'AI_RATE_LIMITED' "
        "AND created_at > ?", (since,))[0]["n"]
    if recent >= 3:
        until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        _set_flag("ai_backoff_until", until)
        record_incident("reliability", "AI_AUTO_BACKOFF", "429가 반복되어 5분간 AI 호출을 쉽니다.",
                        {"recent_429": recent}, "medium", "ai_backoff")


def check_login_lockout(identifier: str) -> bool:
    """True면 잠김(로그인 시도 거부)."""
    return _flag_active_until(f"lockout:{identifier}")


def note_login_failure(identifier: str) -> None:
    since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    recent = db.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE category = 'security' AND code = 'LOGIN_FAILED' "
        "AND context = ? AND created_at > ?",
        (json.dumps({"identifier": identifier}, ensure_ascii=False), since))[0]["n"]
    record_incident("security", "LOGIN_FAILED", "로그인 실패", {"identifier": identifier}, "low")
    if recent + 1 >= 5:
        until = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        _set_flag(f"lockout:{identifier}", until)
        record_incident("security", "BRUTE_FORCE_SUSPECTED", f"{identifier} 15분 잠금 (로그인 실패 {recent + 1}회)",
                        {"identifier": identifier, "failures": recent + 1}, "high", "login_lockout")


# ---- Tier 2: 배치 분석 (1일 1회, Vercel Cron) ----

def open_github_issue(title: str, body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        log.warning("github_issue_skipped reason=no_token title=%s", title)
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/issues",
        data=json.dumps({"title": title, "body": body}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "Content-Type": "application/json", "User-Agent": "guardian-agent"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            log.info("github_issue_created title=%s", title)
    except (urllib.error.URLError, TimeoutError) as e:
        log.error("github_issue_failed title=%s detail=%s", title, e)


def run_daily_digest() -> dict:
    rows = db.execute(
        "SELECT id, category, code, message, context, severity, created_at FROM incidents "
        "WHERE diagnosis IS NULL ORDER BY id DESC LIMIT 200")
    if not rows:
        return {"analyzed": 0}

    payload = json.dumps(rows, ensure_ascii=False)
    try:
        diagnosis = llm.chat_completion(
            [{"role": "system", "content": DIGEST_SYSTEM}, {"role": "user", "content": payload}],
            max_tokens=800,
        )
    except AIUnavailableError as e:
        log.error("digest_ai_failure detail=%s", e)
        return {"analyzed": 0, "error": str(e)}

    ids = [r["id"] for r in rows]
    db.execute(f"UPDATE incidents SET diagnosis = ? WHERE id IN ({','.join('?' * len(ids))})",
              [diagnosis, *ids])

    urgency = "low"
    m = re.search(r"URGENCY:\s*(low|medium|high)", diagnosis, re.IGNORECASE)
    if m:
        urgency = m.group(1).lower()
    if urgency in ("medium", "high"):
        open_github_issue(f"[가디언] 일일 점검 — 긴급도 {urgency} ({len(rows)}건)", diagnosis)

    log.info("digest_complete analyzed=%s urgency=%s", len(rows), urgency)
    return {"analyzed": len(rows), "urgency": urgency}
