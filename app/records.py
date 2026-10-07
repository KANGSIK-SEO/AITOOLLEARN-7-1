"""권리 근거 기록 (docs/rights-policy.md §5).

이 서비스는 "써도 된다"를 보증하지 않는다. 기관이 공개한 권리 정보를 **발급 시점 그대로** 저장하고,
제3자(인터넷 아카이브)에 기관 페이지 보관본을 남겨, 나중에 "그날 이렇게 공개돼 있었다"를 보여줄 수 있게 한다.

- issue(): 판단 규칙을 통과한 작품의 스냅숏을 저장하고 기록 번호를 돌려준다 (이후 기관 데이터가 바뀌어도 기록은 그대로).
- archive_missing(): 기관 작품 페이지와 API 응답을 Wayback Machine에 보관한다 (실패하면 나중에 다시 시도).
- render(): 저장된 기록을 인쇄/PDF용 HTML로 보여준다.
"""
import hashlib
import hmac
import html
import json
import logging
import secrets
import socket
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import art, db, rights
from .config import get_secret_key

log = logging.getLogger("app.records")

ARCHIVE_SAVE = "https://web.archive.org/save/"
ARCHIVE_TIMEOUT_SECONDS = 25   # Vercel 함수 제한(60초) 안에 두 건을 병렬로 끝내기 위한 상한
ARCHIVE_UA = "AITOOLLEARN-7-1 rights-record (https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1)"

CAUTIONS = [
    "이 기록은 기관이 공개한 권리 정보를 발급 시점 그대로 옮긴 것입니다. 공식 인증서나 법률 자문이 아닙니다.",
    "작품에 사람의 얼굴·이름이 나오면 초상권·퍼블리시티권 문제가 따로 있을 수 있습니다.",
    "작품 속 상표·로고는 상표법으로 따로 보호될 수 있습니다.",
    "기관 이름·로고를 써서 기관이 보증·후원하는 것처럼 보이게 하면 안 됩니다.",
    "출처 표시는 의무가 아니지만 기관들은 권장합니다. 아래 출처 표기 예시를 써 주세요.",
    "중요한 상업 프로젝트는 사용 직전 기관 페이지를 다시 확인하세요.",
]
VERDICT = {
    "ok": ("✅ 기관이 CC0로 공개한 작품 — 기관 기준으로 조건 없이 상업적 이용·수정 가능", "#0a7d45"),
    "recheck": ("⚠️ 재확인 필요 — 권리 확인일이 오래되어 기관 페이지에서 다시 확인해야 합니다", "#a86400"),
    "blocked": ("⛔ 기록 발급 불가 — 판단 규칙을 통과하지 못한 작품입니다", "#b00020"),
}


class RecordNotAllowed(Exception):
    def __init__(self, failed: list[str]):
        super().__init__(", ".join(failed))
        self.failed = failed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def credit_example(work: dict, source_name: str) -> str:
    parts = [f'"{work["title"]}"', work.get("artist") or "Unknown artist"]
    if work.get("date_display"):
        parts.append(work["date_display"])
    return f'{", ".join(parts)}. {source_name}, CC0 (Public Domain). {work["source_url"]}'


def _sign(number: str, issued_at: str, snapshot_json: str) -> str:
    """저장된 기록이 발급 뒤에 바뀌지 않았는지 확인하는 서명. 아카이브 링크는 나중에 채워지므로 넣지 않는다."""
    payload = f"{number}|{issued_at}|{snapshot_json}".encode()
    return hmac.new(get_secret_key().encode(), payload, hashlib.sha256).hexdigest()


def _new_number() -> str:
    h = secrets.token_hex(6).upper()
    return f"PD-{h[:4]}-{h[4:8]}-{h[8:]}"


def issue(artwork_id: int, user_id: int | None) -> str:
    """판단 규칙을 통과한 작품만 발급한다. 없는 작품이면 LookupError, 규칙 미통과면 RecordNotAllowed."""
    work = art.get_rights_record(artwork_id)
    if not work:
        raise LookupError(artwork_id)
    result = rights.evaluate(work)
    if result["status"] == "blocked":
        raise RecordNotAllowed([c["code"] for c in result["checks"] if not c["ok"]])
    src = rights.SOURCES[work["source"]]
    snapshot = {
        "work": work,
        "source": {"code": src.code, "name": src.name, "basis": src.basis, "policy_url": src.policy_url},
        "evaluation": result,
        "credit": credit_example(work, src.name),
        "cautions": CAUTIONS,
    }
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    archives = [{"label": "기관 작품 페이지", "url": work["source_url"], "archived_url": None, "error": None}]
    if src.api_url:
        archives.append({"label": "기관 API 응답 (근거 필드 원문)", "url": src.api_url.format(id=work["source_id"]),
                         "archived_url": None, "error": None})
    number, issued_at = _new_number(), _now()
    db.execute(
        "INSERT INTO rights_records (number, artwork_id, user_id, snapshot, archives, signature, issued_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (number, artwork_id, user_id, snapshot_json, json.dumps(archives, ensure_ascii=False),
         _sign(number, issued_at, snapshot_json), issued_at))
    log.info("record_issued number=%s artwork_id=%s user_id=%s", number, artwork_id, user_id)
    return number


def get(number: str) -> dict | None:
    rows = db.execute("SELECT * FROM rights_records WHERE number = ?", (number,))
    return rows[0] if rows else None


def save_to_wayback(url: str) -> tuple[str | None, str | None]:
    """인터넷 아카이브에 지금 모습을 보관하고 보관본 주소를 돌려준다. 실패하면 (None, 이유)."""
    req = urllib.request.Request(ARCHIVE_SAVE + url, headers={"User-Agent": ARCHIVE_UA})
    try:
        with urllib.request.urlopen(req, timeout=ARCHIVE_TIMEOUT_SECONDS) as resp:
            final = resp.geturl()
            location = resp.headers.get("Content-Location")
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        return None, f"연결 실패: {getattr(e, 'reason', e)}"
    if "/web/" in final:
        return final, None
    if location and location.startswith("/web/"):
        return "https://web.archive.org" + location, None
    return None, "보관본 주소를 받지 못함"


def archive_missing(number: str) -> list[dict]:
    """아직 보관되지 않은 항목만 병렬로 보관한다 (발급 직후와 '다시 시도' 버튼에서 호출)."""
    row = get(number)
    if not row:
        raise LookupError(number)
    archives = json.loads(row["archives"])
    todo = [a for a in archives if not a["archived_url"]]
    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            for item, (archived, err) in zip(todo, pool.map(lambda a: save_to_wayback(a["url"]), todo)):
                item["archived_url"], item["error"] = archived, err
                if archived:
                    item["archived_at"] = _now()
        db.execute("UPDATE rights_records SET archives = ? WHERE number = ?",
                   (json.dumps(archives, ensure_ascii=False), number))
        log.info("record_archived number=%s ok=%s", number, sum(bool(a["archived_url"]) for a in archives))
    return archives


def render(row: dict) -> str:
    e = html.escape
    snap = json.loads(row["snapshot"])
    work, src, ev = snap["work"], snap["source"], snap["evaluation"]
    intact = hmac.compare_digest(row["signature"], _sign(row["number"], row["issued_at"], row["snapshot"]))
    verdict, color = VERDICT[ev["status"]]
    thumb = art.with_proxy_urls(work).get("thumbnail_url") or work["image_url"]

    # 발급 뒤 기관 데이터가 바뀌었는지 — 기록은 그대로 두고 현재 상태만 따로 알려준다
    current = art.get_rights_record(work["id"])
    now_status = rights.evaluate(current)["status"] if current else "blocked"
    changed = "" if now_status == ev["status"] else (
        f'<p class="note">참고: 오늘 다시 판단하면 "{e(VERDICT[now_status][0])}" 입니다. '
        "이 기록은 발급 당시 상태를 그대로 보여줍니다.</p>")

    rows = [("기관", src["name"]), ("기관 작품 ID", work["source_id"]),
            ("작품 단위 근거", f'{src["basis"]} (기관 API 값)'), ("라이선스", work["license"]),
            ("권리 확인일", ev["checked_at"] or "-")]
    links = [("기관 정책 페이지", src["policy_url"]), ("기관 작품 페이지", work["source_url"]), ("원본 이미지", work["image_url"])]
    table = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in rows)
    table += "".join(f'<tr><th>{e(k)}</th><td><a href="{e(v)}" target="_blank" rel="noopener">{e(v)}</a></td></tr>'
                     for k, v in links if v)
    checks = "".join(f"<li>{'✅' if c['ok'] else '❌'} <b>{c['code']}</b> {e(c['label'])}</li>" for c in ev["checks"])
    cautions = "".join(f"<li>{e(c)}</li>" for c in snap["cautions"])

    archives = json.loads(row["archives"])
    arch_items = []
    for a in archives:
        if a["archived_url"]:
            arch_items.append(f'<li>✅ {e(a["label"])}: <a href="{e(a["archived_url"])}" target="_blank" rel="noopener">'
                              f'{e(a["archived_url"])}</a></li>')
        else:
            arch_items.append(f'<li>⏳ {e(a["label"])}: 아직 보관되지 않음{" (" + e(a["error"]) + ")" if a.get("error") else ""}</li>')
    retry = "" if all(a["archived_url"] for a in archives) else (
        '<button class="ghost" id="retry">인터넷 아카이브에 다시 보관하기</button>')

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>권리 근거 기록 {e(row['number'])}</title>
<style>
body{{font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;color:#1a1a1a;background:#f4f4f7;margin:0;padding:16px}}
.doc{{max-width:760px;margin:0 auto;background:#fff;padding:32px;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.08)}}
h1{{font-size:1.4rem;margin:0 0 4px}} .sub{{color:#666;font-size:.85rem;margin:0 0 20px;line-height:1.5}}
.verdict{{border:2px solid {color};color:{color};padding:12px 14px;border-radius:8px;font-weight:700;margin:16px 0}}
.work{{display:flex;gap:16px;align-items:flex-start}} .work img{{width:160px;max-width:40%;border-radius:6px;background:#eee}}
table{{width:100%;border-collapse:collapse;font-size:.88rem;margin:12px 0}} th{{text-align:left;width:130px;color:#555;vertical-align:top}}
th,td{{padding:6px 4px;border-bottom:1px solid #eee;word-break:break-all}} h2{{font-size:1rem;margin:22px 0 6px}}
ul{{padding-left:20px;font-size:.88rem;line-height:1.6;word-break:break-all}}
.credit{{background:#f6f6f8;padding:10px;border-radius:6px;font-size:.85rem;word-break:break-all}}
.note{{background:#fff7e6;border-radius:6px;padding:8px 10px;font-size:.85rem}}
.foot{{display:flex;flex-wrap:wrap;gap:8px;justify-content:space-between;color:#666;font-size:.8rem;margin-top:24px;border-top:1px solid #eee;padding-top:10px}}
button{{margin:12px auto;display:block;padding:10px 18px;border:0;border-radius:20px;background:#0066ff;color:#fff;font-size:.9rem;cursor:pointer}}
button.ghost{{background:#fff;color:#0066ff;border:1px solid #0066ff;margin:8px 0}}
@media print{{body{{background:#fff;padding:0}} .doc{{box-shadow:none}} button{{display:none}}}}
</style></head><body><div class="doc">
<h1>권리 근거 기록</h1>
<p class="sub">Rights Evidence Record · 저작권 걱정 없는 퍼블릭 도메인 명화 찾기<br>
기관이 공개한 권리 정보를 <b>발급 시점 그대로</b> 저장한 기록입니다. 공식 인증서가 아닙니다.</p>
<div class="work"><img src="{e(thumb)}" alt="{e(work['title'])}"><div>
<h2 style="margin-top:0">{e(work['title'])}</h2>
<div>{e(work.get('artist') or '작가 미상')}{' · ' + e(work['date_display']) if work.get('date_display') else ''}</div>
<div style="color:#666;font-size:.85rem">{e(work.get('medium') or '')}</div>
<div style="color:#666;font-size:.85rem">{e(work.get('credit_line') or '')}</div></div></div>
<div class="verdict">{e(verdict)}</div>{changed}
<h2>권리 근거</h2><table>{table}</table>
<h2>제3자 보관본 (인터넷 아카이브)</h2>
<p class="sub" style="margin:0">우리가 아닌 인터넷 아카이브(archive.org)가 그날의 기관 페이지를 보관합니다.</p>
<ul>{''.join(arch_items)}</ul>{retry}
<h2>판단 결과 (판단 규칙 R1~R6)</h2><ul>{checks}</ul>
<h2>출처 표기 예시</h2><div class="credit">{e(snap['credit'])}</div>
<h2>주의사항</h2><ul>{cautions}</ul>
<div class="foot"><span>기록 번호 {e(row['number'])}</span><span>발급 {e(row['issued_at'].replace('T', ' ').replace('+00:00', ' UTC'))}</span>
<span>기록 무결성: {'확인됨 ✓' if intact else '⚠️ 변조 의심'}</span></div>
</div><button onclick="window.print()">인쇄 / PDF로 저장</button>
<script>
const r = document.getElementById("retry");
if (r) r.onclick = async () => {{
  r.disabled = true; r.textContent = "보관 중… (최대 30초)";
  await fetch("/api/records/{e(row['number'])}/archive", {{ method: "POST" }});
  location.reload();
}};
</script></body></html>"""
