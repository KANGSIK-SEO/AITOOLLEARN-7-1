"""권리 판단 규칙 — docs/rights-policy.md를 그대로 옮긴 코드. 규칙을 바꿀 땐 문서부터 고친다.

- SOURCES: 공급원(기관)별 권리 데이터 (§1). enabled=False인 기관은 검색에 절대 나오지 않는다.
- evaluate(): 작품 하나에 R1~R6을 적용한 결과 (§2).
- certificate_number(): 확인서 번호 — 권리 데이터가 바뀌면 번호도 바뀐다 (§5).
"""
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from .config import get_secret_key

RECHECK_AFTER_DAYS = 365  # R5


@dataclass(frozen=True)
class Source:
    code: str
    name: str
    enabled: bool
    license: str             # 이 기관에서 허용하는 라이선스 (§3)
    basis: str               # 작품 단위 근거 필드와 값 (§1 S2)
    policy_url: str          # 기관 공식 정책 페이지 (§1 S1)
    image_hosts: tuple[str, ...]  # 원본 이미지 공식 도메인 (§1 S3)
    note: str = ""


SOURCES: dict[str, Source] = {s.code: s for s in (
    Source("met", "The Metropolitan Museum of Art", True, "CC0", "isPublicDomain = true",
           "https://www.metmuseum.org/hubs/open-access", ("images.metmuseum.org",)),
    Source("aic", "Art Institute of Chicago", True, "CC0", "is_public_domain = true",
           "https://www.artic.edu/open-access/open-access-images", ("www.artic.edu", "artic.edu")),
    Source("cma", "Cleveland Museum of Art", True, "CC0", 'share_license_status = "CC0"',
           "https://www.clevelandart.org/open-access", ("openaccess-cdn.clevelandart.org",)),
    # 보류 (§1 기관 현황) — 등록만 하고 검색에는 나오지 않는다
    Source("nga", "National Gallery of Art", False, "CC0", "open access 이미지 표시",
           "https://www.nga.gov/open-access-images.html", (), "데이터셋 수집 방식 설계 후 확인"),
    Source("si", "Smithsonian Open Access", False, "CC0", 'usage.access = "CC0"',
           "https://www.si.edu/openaccess", (), "API 키 필요, 박물관별 확인 후 추가"),
    Source("rijks", "Rijksmuseum", False, "CC0", "-",
           "https://www.rijksmuseum.nl/en/research/conduct-research/data", (), "PDM 표기 이미지 존재 — CC0 확인 전 보류"),
    Source("emuseum", "국립중앙박물관 e뮤지엄", False, "KOGL-1", "공공누리 유형",
           "https://www.emuseum.go.kr", (), "공공누리 1유형은 출처표시 의무 — 출처표시형 지원 후 검토"),
)}


def allowed_sources() -> list[str]:
    """검색에 쓸 기관 코드. ALLOWED_SOURCES(예: "met")로 파일럿 범위를 좁힐 수 있지만, 보류 기관을 켤 수는 없다."""
    enabled = [c for c, s in SOURCES.items() if s.enabled]
    raw = os.environ.get("ALLOWED_SOURCES", "").strip()
    if not raw:
        return enabled
    wanted = {c.strip() for c in raw.split(",") if c.strip()}
    return [c for c in enabled if c in wanted]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def evaluate(work: dict, now: datetime | None = None) -> dict:
    """work는 art.get_rights_record()의 결과(원본 image_url 포함). R1~R6 결과와 최종 판정을 돌려준다.
    status: ok(사용 가능) / recheck(R5만 실패 — 재확인 필요) / blocked(그 외 실패 — 제공하면 안 됨)."""
    now = now or datetime.now(timezone.utc)
    src = SOURCES.get(work.get("source") or "")
    checked = _parse_time(work.get("collected_at"))
    host = urlparse(work.get("image_url") or "").hostname or ""
    age_days = (now - checked).days if checked else None
    checks = [
        ("R1", "검증된 CC0 기관", bool(src and src.enabled and src.code in allowed_sources())),
        ("R2", "기관이 작품 단위로 퍼블릭 도메인이라고 밝힘", work.get("is_public_domain") == 1),
        ("R3", "라이선스 CC0", work.get("license") == "CC0" and bool(src and src.license == "CC0")),
        ("R4", "원본 이미지가 기관 공식 도메인", bool(src and host in src.image_hosts)),
        ("R5", f"권리 확인일이 {RECHECK_AFTER_DAYS}일 이내", age_days is not None and age_days <= RECHECK_AFTER_DAYS),
        ("R6", "기관 공식 상세 페이지 있음", bool((work.get("source_url") or "").startswith("https://"))),
    ]
    failed = [code for code, _, ok in checks if not ok]
    status = "ok" if not failed else "recheck" if failed == ["R5"] else "blocked"
    return {"status": status, "checks": [{"code": c, "label": l, "ok": ok} for c, l, ok in checks],
            "checked_at": checked.date().isoformat() if checked else None, "age_days": age_days}


def certificate_number(work: dict) -> str:
    payload = f"{work['source']}:{work['source_id']}:{work['license']}:{work.get('collected_at')}"
    digest = hmac.new(get_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()[:12].upper()
    return f"PD-{digest[:4]}-{digest[4:8]}-{digest[8:]}"
