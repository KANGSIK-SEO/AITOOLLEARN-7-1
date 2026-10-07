"""Cleveland Museum of Art Open Access API에서 CC0 작품(회화·드로잉·판화·사진)을 수집한다.

사용: python3 scripts/collect_cma.py [--limit N] [--types Painting,Print]
API 키 불필요. 기관이 작품마다 주는 share_license_status가 "CC0"이고 이미지가 기관 CDN에 있는 것만 넣는다
(docs/rights-policy.md §1·§2 — 애매하면 넣지 않는다).
"""
import argparse
import time
from urllib.parse import urlparse

from artdb import connect, get_json, upsert

BASE = "https://openaccess-api.clevelandart.org/api/artworks/"
IMAGE_HOST = "openaccess-cdn.clevelandart.org"
DEFAULT_TYPES = "Painting,Drawing,Print,Photograph"
PAGE_SIZE = 500


def _split_creator(description: str | None) -> tuple[str | None, str | None]:
    """'Claude Monet (French, 1840–1926)' → ('Claude Monet', 'French, 1840–1926')"""
    if not description:
        return None, None
    name, _, rest = description.partition(" (")
    return name.strip() or None, rest.rstrip(")").strip() or None


def to_row(a: dict) -> dict | None:
    if a.get("share_license_status") != "CC0" or not a.get("title"):
        return None
    images = a.get("images") or {}
    big = (images.get("print") or images.get("web") or {}).get("url")
    small = (images.get("web") or {}).get("url")
    if not big or urlparse(big).hostname != IMAGE_HOST or not (a.get("url") or "").startswith("https://"):
        return None
    creators = a.get("creators") or []
    artist, bio = _split_creator(creators[0].get("description") if creators else None)
    subjects = [a.get("type"), a.get("collection"), a.get("department")]
    return {
        "source": "cma",
        "source_id": str(a["id"]),
        "title": a["title"],
        "artist": artist,
        "artist_bio": bio,
        "date_display": a.get("creation_date") or None,
        "year_start": a.get("creation_date_earliest"),
        "year_end": a.get("creation_date_latest"),
        "medium": a.get("technique") or None,
        "classification": a.get("type") or None,
        "department": a.get("department") or None,
        "origin": ", ".join(a.get("culture") or []) or None,
        "style": None,
        "subjects": ", ".join(s for s in subjects if s) or None,
        "image_url": big,
        "thumbnail_url": small if small and urlparse(small).hostname == IMAGE_HOST else None,
        "source_url": a["url"],
        "credit_line": a.get("creditline") or a.get("credit_line") or None,
        "is_public_domain": 1,
        "license": "CC0",
        "is_highlight": int(bool(a.get("is_highlight"))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0이면 전체")
    parser.add_argument("--types", default=DEFAULT_TYPES, help="쉼표로 구분한 CMA 작품 유형")
    args = parser.parse_args()

    conn = connect()
    saved = skipped = 0
    for kind in [t.strip() for t in args.types.split(",") if t.strip()]:
        skip = 0
        while True:
            time.sleep(0.5)
            data = get_json(BASE, {"cc0": 1, "has_image": 1, "type": kind, "limit": PAGE_SIZE, "skip": skip})
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
            total = ((data or {}).get("info") or {}).get("total", 0)
            skip += PAGE_SIZE
            print(f"  {kind}: {min(skip, total)}/{total}건 확인, 누적 저장 {saved}")
            if args.limit and saved >= args.limit:
                conn.close()
                print(f"완료(limit): 저장 {saved}, 제외 {skipped}")
                return
            if skip >= total:
                break
    conn.close()
    print(f"완료: 저장 {saved}, 제외 {skipped}")


if __name__ == "__main__":
    main()
