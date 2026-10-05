"""MET Open Access에서 퍼블릭 도메인 + 이미지 있는 작품을 부서별로 수집한다.

사용: python3 scripts/collect_met.py [--limit N] [--departments 11,1,6]
기본 부서: 유럽 회화(11), 미국관(1), 아시아 미술(6), 드로잉·판화(9), 로버트 리먼 컬렉션(16), 사진(19).
작품 1건당 0.5초씩 쉬어 가므로 전체 수집은 몇 시간 걸린다 — 중간에 멈춰도 다시 실행하면 이어서 받는다.
API 키 불필요. 공식 제한(초당 80회)보다 훨씬 낮게 동시 요청 수를 제한한다.
"""
import argparse
import time
import urllib.error

from artdb import connect, get_json, upsert

BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
SEARCH_BASE = "https://collectionapi.metmuseum.org/public/collection/v1.1"
DEFAULT_DEPARTMENTS = "11,1,6,9,16,19"
SEARCH_PAGE_SIZE = 500  # v1.1/search 최대 limit


def to_row(o: dict) -> dict | None:
    if not o.get("isPublicDomain") or not o.get("primaryImage") or not o.get("title"):
        return None
    tags = [t["term"] for t in (o.get("tags") or []) if t.get("term")]
    return {
        "source": "met",
        "source_id": str(o["objectID"]),
        "title": o["title"],
        "artist": o.get("artistDisplayName") or None,
        "artist_bio": o.get("artistDisplayBio") or None,
        "date_display": o.get("objectDate") or None,
        "year_start": o.get("objectBeginDate"),
        "year_end": o.get("objectEndDate"),
        "medium": o.get("medium") or None,
        "classification": o.get("classification") or o.get("objectName") or None,
        "department": o.get("department") or None,
        "origin": o.get("culture") or o.get("artistNationality") or None,
        "style": o.get("period") or None,
        "subjects": ", ".join(tags) or None,
        "image_url": o["primaryImage"],
        "thumbnail_url": o.get("primaryImageSmall") or None,
        # MET이 www 서브도메인을 폐기해 API가 돌려주는 objectURL도 www 그대로라 깨짐 → apex 도메인으로 교정
        "source_url": (o.get("objectURL") or f"https://metmuseum.org/art/collection/search/{o['objectID']}")
            .replace("https://www.metmuseum.org", "https://metmuseum.org"),
        "credit_line": o.get("creditLine") or None,
        "is_public_domain": 1,
        "license": "CC0",
        "is_highlight": int(bool(o.get("isHighlight"))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0이면 전체")
    parser.add_argument("--departments", default=DEFAULT_DEPARTMENTS, help="쉼표로 구분한 MET 부서 ID")
    parser.add_argument("--max-minutes", type=float, default=0,
                        help="이 시간이 지나면 저장하고 멈춘다 (0이면 무제한). 다시 실행하면 이어서 받는다")
    args = parser.parse_args()
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None

    ids: list[int] = []
    for department_id in [int(d) for d in args.departments.split(",") if d.strip()]:
        offset = 0
        while True:
            page = get_json(f"{SEARCH_BASE}/search", {
                "departmentId": department_id, "isPublicDomain": "true", "hasImages": "true",
                "q": "*", "limit": SEARCH_PAGE_SIZE, "offset": offset,
            })
            page_ids = (page or {}).get("objectIDs") or []
            ids.extend(page_ids)
            total = (page or {}).get("total") or 0
            offset += SEARCH_PAGE_SIZE
            if not page_ids or offset >= total:
                break
        print(f"  부서 {department_id}: 누적 대상 {len(ids)}건")
    ids = list(dict.fromkeys(ids))
    if args.limit:
        ids = ids[: args.limit]
    print(f"MET 대상(전체) {len(ids)}건")

    conn = connect()
    done = {r[0] for r in conn.execute("SELECT source_id FROM artworks WHERE source='met'")}
    ids = [i for i in ids if str(i) not in done]
    print(f"이미 저장됨 {len(done)}건 제외, 남은 대상 {len(ids)}건 수집 시작")

    saved = skipped = failed = 0
    consecutive_403 = 0
    for n, obj_id in enumerate(ids, 1):
        if deadline and time.monotonic() > deadline:
            print(f"  시간 제한 도달 — {n - 1}/{len(ids)}건 처리 후 멈춤 (다시 실행하면 이어서 수집)")
            break
        time.sleep(0.5)  # WAF(레이트리밋) 회피용 완만한 스로틀, 단일 요청씩만 진행
        try:
            obj = get_json(f"{BASE}/objects/{obj_id}", retries=1)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                consecutive_403 += 1
                cooldown = min(20 * consecutive_403, 180)
                print(f"  403(차단 의심) objectID={obj_id}, {cooldown}초 쿨다운 후 재개 ({consecutive_403}연속)")
                time.sleep(cooldown)
                failed += 1
                continue
            print(f"  실패 objectID={obj_id}: {e}")
            failed += 1
            continue
        except Exception as e:
            print(f"  실패 objectID={obj_id}: {e}")
            failed += 1
            continue

        consecutive_403 = 0
        if obj is None:
            failed += 1
            continue
        row = to_row(obj)
        if row is None:
            skipped += 1
            continue
        upsert(conn, row)
        saved += 1
        if saved % 100 == 0:
            conn.commit()
            print(f"  {n}/{len(ids)} 진행, 저장 {saved}건…")
    conn.commit()
    conn.close()
    print(f"완료: 저장 {saved}, 제외 {skipped}, 실패 {failed}")


if __name__ == "__main__":
    main()
