"""Art Institute of Chicago API에서 퍼블릭 도메인 작품(회화·판화·드로잉·사진)을 수집한다.

사용: python3 scripts/collect_aic.py [--limit N] [--classifications painting,print]
API 키 불필요. 이미지는 공식 IIIF 서버 URL로 저장한다.
"""
import argparse

from artdb import connect, get_json, upsert

BASE = "https://api.artic.edu/api/v1"
IIIF = "https://www.artic.edu/iiif/2"
FIELDS = ",".join([
    "id", "title", "artist_display", "artist_title", "date_display", "date_start", "date_end",
    "medium_display", "classification_title", "department_title", "place_of_origin",
    "style_title", "subject_titles", "image_id", "is_public_domain", "credit_line",
])
PAGE_SIZE = 100


def to_row(a: dict) -> dict | None:
    if not a.get("is_public_domain") or not a.get("image_id") or not a.get("title"):
        return None
    image_id = a["image_id"]
    return {
        "source": "aic",
        "source_id": str(a["id"]),
        "title": a["title"],
        "artist": a.get("artist_title") or None,
        "artist_bio": a.get("artist_display") or None,
        "date_display": a.get("date_display") or None,
        "year_start": a.get("date_start"),
        "year_end": a.get("date_end"),
        "medium": a.get("medium_display") or None,
        "classification": a.get("classification_title") or None,
        "department": a.get("department_title") or None,
        "origin": a.get("place_of_origin") or None,
        "style": a.get("style_title") or None,
        "subjects": ", ".join(a.get("subject_titles") or []) or None,
        "image_url": f"{IIIF}/{image_id}/full/1686,/0/default.jpg",
        "thumbnail_url": f"{IIIF}/{image_id}/full/400,/0/default.jpg",
        "source_url": f"https://www.artic.edu/artworks/{a['id']}",
        "credit_line": a.get("credit_line") or None,
        "is_public_domain": 1,
        "license": "CC0",
        "is_highlight": 0,
    }


# AIC 검색 API는 한 질의에서 1000건까지만 조회되므로(초과 시 403) 제작 시기 구간으로 나눠 수집한다.
# 판화처럼 작품이 많은 분류는 50년 구간도 1000건을 넘기 때문에, 넘으면 구간을 반으로 쪼개 다시 센다.
MAX_RESULTS = 1000
DEFAULT_CLASSIFICATIONS = "painting,print,drawing and watercolor,photograph"
YEAR_MIN, YEAR_MAX = -3000, 2030


def window_filters(classification: str, lo: int, hi: int) -> dict:
    return {
        "query[bool][must][0][term][is_public_domain]": "true",
        "query[bool][must][1][term][classification_titles.keyword]": classification,
        "query[bool][must][2][range][date_start][gte]": lo,
        "query[bool][must][3][range][date_start][lt]": hi,
    }


def split_windows(classification: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """[lo, hi) 구간을 결과가 1000건 이하가 될 때까지 반씩 나눈다."""
    data = get_json(f"{BASE}/artworks/search", {**window_filters(classification, lo, hi), "fields": "id", "limit": 1})
    total = ((data or {}).get("pagination") or {}).get("total", 0)
    if total == 0:
        return []
    if total <= MAX_RESULTS or hi - lo <= 1:
        if total > MAX_RESULTS:
            print(f"  경고: {classification} [{lo}~{hi}) {total}건 — 1년 구간도 1000건을 넘어 일부 누락")
        return [(lo, hi)]
    mid = (lo + hi) // 2
    return split_windows(classification, lo, mid) + split_windows(classification, mid, hi)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0이면 전체")
    parser.add_argument("--classifications", default=DEFAULT_CLASSIFICATIONS,
                        help="쉼표로 구분한 AIC 분류명 (기본: 회화·판화·드로잉·사진)")
    args = parser.parse_args()

    conn = connect()
    saved = skipped = 0
    for classification in [c.strip() for c in args.classifications.split(",") if c.strip()]:
        windows = split_windows(classification, YEAR_MIN, YEAR_MAX)
        print(f"[{classification}] 구간 {len(windows)}개로 나눠 수집")
        for lo, hi in windows:
            page = 1
            while True:
                data = get_json(f"{BASE}/artworks/search", {
                    **window_filters(classification, lo, hi), "fields": FIELDS, "limit": PAGE_SIZE, "page": page,
                })
                items = (data or {}).get("data") or []
                if not items:
                    break
                for item in items:
                    row = to_row(item)
                    if row is None:
                        skipped += 1
                        continue
                    upsert(conn, row)
                    saved += 1
                conn.commit()
                pg = data["pagination"]
                print(f"  {classification} [{lo}~{hi}) page {page}/{pg['total_pages']} 누적 {saved}")
                if args.limit and saved >= args.limit:
                    conn.close()
                    print(f"완료(limit): 저장 {saved}, 제외 {skipped}")
                    return
                if page >= pg["total_pages"]:
                    break
                page += 1
    conn.close()
    print(f"완료: 저장 {saved}, 제외 {skipped}")


if __name__ == "__main__":
    main()
