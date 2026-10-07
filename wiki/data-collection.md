---
title: 작품 수집 (미술관 API → art.db)
sources: [scripts/collect_met.py, scripts/collect_aic.py, scripts/collect_cma.py, scripts/artdb.py, scripts/finalize_artdb.py, scripts/export_artworks_json.py, .github/workflows/collect-and-deploy.yml]
updated: 2026-10-07
---
# 작품 수집

## 어디서 돌리나

수집은 몇 시간이 걸려서 개인 컴퓨터를 켜 두지 않도록 **GitHub Actions**(`collect-and-deploy.yml`)에서 수집하고 결과 `data/art.db`를 커밋한다.
실행: Actions 탭 → collect-and-deploy → **Run workflow** (손으로만 실행, 자동 실행 없음). 최대 340분.

## 기관별 스크립트

| 기관 | 스크립트 | 무엇을 | 특이점 |
|---|---|---|---|
| AIC | `collect_aic.py` | 회화·판화·드로잉·사진 중 `is_public_domain=true` | 검색 결과가 1,000건까지만 나와서 **연도 구간을 반씩 쪼개** 1,000건 이하로 만든다 (`split_windows`) |
| CMA | `collect_cma.py` | `share_license_status = "CC0"`이고 이미지가 기관 CDN에 있는 것 | API 키 불필요 |
| MET | `collect_met.py` | 6개 부서(`DEFAULT_DEPARTMENTS`)의 `isPublicDomain` 작품 | 빨리 보내면 **403**으로 막혀서 0.5~1초씩 쉬고, 403이면 기다렸다 재시도. `--max-minutes`로 시간 제한 |

## 공통 (`scripts/artdb.py`)

- `upsert`: 같은 작품이면 갱신하고 **확인일(`collected_at`)도 새로** 적는다 → [권리 판단](rights.md)의 R5(365일).
- 예전 DB의 기관 목록 제약에 `cma`가 없으면 `_migrate_source_check`가 고친다.
- `finalize_artdb.py`: 정리 후 파일이 **95MB**를 넘으면 멈춘다 (GitHub 파일 한도 100MB).
- `export_artworks_json.py`: 온디바이스 패널용 `artworks.json`을 만든다 ([화면](frontend.md)).
