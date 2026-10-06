"""data/art.db -> app/static/artworks.json 생성.

온디바이스(Datalog) 추천 패널이 쓰는 정적 사실(fact) 번들. 서버 API를 거치지 않고
브라우저가 이 JSON을 한 번 받아 로컬에서 규칙 평가를 하므로, app/art.py의 search()와
같은 전제(is_public_domain = 1)로 거르고, AIC 이미지 프록시 URL 치환도 동일하게 적용한다.

사용: python3 scripts/export_artworks_json.py
data/art.db가 바뀔 때만(= scripts/collect_*.py 다시 돌렸을 때만) 다시 실행하면 된다.
"""
import json
import re

from artdb import DB_PATH

OUT_PATH = DB_PATH.parent.parent / "app" / "static" / "artworks.json"
AIC_IMAGE_RE = re.compile(r"/iiif/2/([0-9a-f-]{36})/")

FIELDS = (
    "id", "title", "artist", "date_display", "year_start", "year_end",
    "style", "subjects", "license", "source", "image_url", "thumbnail_url", "source_url",
)


def with_proxy_urls(row: dict) -> dict:
    """app/art.py의 with_proxy_urls()와 동일한 규칙 (AIC 이미지는 전용 헤더 없으면 403)."""
    if row.get("source") == "aic":
        m = AIC_IMAGE_RE.search(row.get("image_url") or "")
        if m:
            row = {**row,
                   "thumbnail_url": f"/api/img/aic/{m.group(1)}?w=400",
                   "image_url": f"/api/img/aic/{m.group(1)}?w=1686"}
    return row


def split_subjects(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def main() -> None:
    import sqlite3
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, artist, date_display, year_start, year_end, style, subjects, "
        "license, source, image_url, thumbnail_url, source_url "
        "FROM artworks WHERE is_public_domain = 1"
    ).fetchall()
    conn.close()

    works = []
    for r in rows:
        row = dict(r)
        row["subjects"] = split_subjects(row["subjects"])
        works.append(with_proxy_urls(row))

    OUT_PATH.write_text(json.dumps(works, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"saved: {OUT_PATH} ({len(works)}건, {size_kb:,.0f} KB)")


if __name__ == "__main__":
    main()
