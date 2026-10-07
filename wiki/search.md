---
title: 작품 검색 (FTS5·다양화·더 보기)
sources: [app/art.py, db/schema.sql, app/main.py, app/config.py, app/static/app.js]
updated: 2026-10-07
---
# 작품 검색

작품 DB는 `data/art.db` 한 파일이다. 서버는 **읽기만** 한다 (`file:...?mode=ro`, `app/art.py`의 `_connect`).
테이블 구조는 `db/schema.sql`: `artworks`(작품 정보) + `artworks_fts`(전문 검색 색인, SQLite **FTS5**).

## 검색 순서 (`art.search`)

1. **키워드 → FTS 질의**: AI가 준 영어 키워드를 `"spring" OR "landscape"`처럼 잇는다. 최대 20단어 (`FTS_MAX_TOKENS`).
2. **필터** (`_filters`, `_source_filter`): 작가, 연도, 그리고 **허용 기관(met·aic·cma)만**. 권리 규칙은 [권리 판단](rights.md).
3. **관련도 순 정렬** (`_ranked`): FTS 점수 순. FTS 질의가 깨지면(`OperationalError`) 일반 검색으로 대신한다.
4. **다양화** (`_diversify`): 상위 **2개**(`GUARANTEED_TOP`)는 그대로 두고, 나머지는 후보 중 무작위로 뽑는다.
   같은 질문을 해도 매번 똑같은 그림만 나오지 않게 하기 위해서다.

## 결과 개수

| 사용자 | 작품 수 | 설정 |
|---|---|---|
| 일반 | 6 | `ART_RESULTS_LIMIT` |
| 초대코드(프리미엄) | 100 | `ART_RESULTS_LIMIT_PREMIUM` |

AI 답변 본문에서 설명하는 건 어느 쪽이든 최대 6개 ([AI 호출](ai-llm.md)).

## 더 보기 (`GET /api/artworks`, `art.browse`)

- 챗봇 응답의 `search` 조건을 그대로 받아 **AI 없이 DB만** 다시 조회한다 → 빠르고 비용 0.
- 한 번에 24개 (`BROWSE_PAGE_SIZE`), IP당 시간당 600회 (`BROWSE_LIMIT_PER_HOUR`).
- 로그인 없이도 쓸 수 있다 (AI를 안 부르니 비용이 없다).

## 가로/세로/정사각은 어디서 거르나

DB에는 그림 크기 정보가 없다. 그래서 **브라우저가** 썸네일을 불러온 뒤 가로·세로 비율을 재서 카드에 `가로형/세로형/정사각` 표시를 붙이고,
결과 묶음 위의 선택 상자로 걸러 보여준다 (`app/static/app.js`). AI가 뽑은 `orientation`은 그 선택 상자의 처음 값이 된다.

## AIC 이미지 프록시

AIC 이미지 서버는 특정 헤더가 없으면 403을 준다. 그래서 `/api/img/aic/{id}`가 대신 받아서 전달한다
(`with_proxy_urls`, `app/main.py`의 `aic_image`). `download=1`이면 파일로 저장되게 `Content-Disposition`을 붙인다.

## 브라우저 안 검색 (온디바이스)

서버·AI 없이 브라우저에서 규칙으로 찾는 패널도 있다 → [화면](frontend.md)의 온디바이스 부분.
