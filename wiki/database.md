---
title: 데이터베이스 (작품 DB와 사용자 DB)
sources: [app/db.py, db/schema.sql, app/art.py, scripts/finalize_artdb.py, .github/workflows/migrate-db.yml]
updated: 2026-10-11
---
# 데이터베이스

DB가 **두 개**다. 성격이 달라서 나눴다.

| | 작품 DB | 사용자 DB |
|---|---|---|
| 파일/서비스 | `data/art.db` (저장소에 포함) | **Neon PostgreSQL** (2026-10-11부터, 그 전엔 Turso). 로컬은 `data/app.db` |
| 쓰기 | 서버는 **읽기만**. 수집 스크립트만 쓴다 | 가입·대화·즐겨찾기 때마다 쓴다 |
| 크기 | 약 55MB (95MB 넘으면 수집이 멈춤, `scripts/finalize_artdb.py`) | 작다 |
| 코드 | `app/art.py` | `app/db.py` |

**왜 나눴나**: Vercel 서버리스는 파일에 쓴 게 다음 요청까지 남지 않는다. 그래서 바뀌는 데이터(사용자)는 바깥 DB(Neon)에 두고,
안 바뀌는 데이터(작품)는 배포 파일에 넣어 빠르게 읽는다.

## 사용자 DB 테이블 (`app/db.py`의 `SCHEMA`)

| 테이블 | 내용 |
|---|---|
| `users` | 이메일, 비밀번호 해시, 프리미엄 여부 |
| `chats` | 질문, 답, 상태(ok/error), 걸린 시간, 추천 작품 번호 |
| `favorites` | 즐겨찾기 (사용자+작품 조합은 하나만) |
| `rights_records` | [권리 근거 기록](records.md) 스냅숏·서명·아카이브 링크 |
| `incidents` | [가디언](guardian.md)이 남긴 장애·보안 사건 |
| `runtime_flags` | 로그인 잠금, AI 쉬기 같은 "언제까지" 표시 |
| `rate_counters` | IP별 요청 횟수 (가입·로그인·더 보기 등) |

## Turso 왕복 줄이기 (2026-10-07)

Turso는 SQL 한 문장마다 HTTP 왕복이 생긴다. 서버가 새로 뜰 때 테이블 준비가 **12번**, 채팅 전 확인이 **4번** 왕복해서 느렸다.
`_turso_pipeline`으로 여러 문장을 **요청 한 번**에 묶어 보내고, `execute_many()`를 만들어 둘 다 1번으로 줄였다
(KANGSIK-SEO/AITOOLLEARN-7-1#53). → [주요 결정](decisions.md)

## 스키마 변경

- 새 컬럼은 `MIGRATIONS`에 `ALTER TABLE`로 추가한다. 이미 있으면 나는 "duplicate column" 오류는 무시한다.
- 예전 배포본의 `favorites`에 `id` 컬럼이 없으면 `_migrate_favorites_id()`가 데이터를 보존한 채 다시 만든다 (팀원 코드와 병합하며 생긴 차이).

## Neon PostgreSQL로 옮김 (2026-10-11)

저장소 주인 요청으로 사용자 DB를 회사에서 쓰는 PostgreSQL(Neon)로 바꿨다. 백업·시점 복구·권한 관리가 된다.
- **고르는 순서** (`app/db.py`의 `backend()`): `DATABASE_URL`(Postgres) → `TURSO_DATABASE_URL`(Turso) → 로컬 SQLite 파일.
- **SQL은 그대로**: 코드의 SQL은 SQLite 문법(`?`)으로 쓰고, Postgres로 보낼 때 `_pg_sql`이 `%s`로 바꾼다. 자동 증가 키만 `BIGSERIAL`로 바꾼 `PG_SCHEMA`를 쓴다.
- **연결 풀**: 서버리스라도 요청마다 새로 연결하면 느려서 작은 풀(`DB_POOL_MAX`, 기본 5)을 둔다. Neon pooled 주소(PgBouncer)라 prepared statement는 끈다.
- **데이터 옮기기**: `.github/workflows/migrate-db.yml` → `/api/guardian/migrate-from-turso` → `copy_from_turso()`. id를 그대로 옮기고, 40초씩 나눠(Vercel 60초 한도) 이어 부르며, 이미 옮긴 행은 건너뛴다.
- **Postgres만의 차이 하나**: `ON CONFLICT DO UPDATE` 안에서 열 이름만 쓰면 모호하다고 거부해서 `rate_counters.window_start`처럼 표 이름을 붙였다 (`app/guardian.py`).
- **테스트**: `TEST_DATABASE_URL`을 주면 모든 테스트가 진짜 Postgres에서 돈다 (`tests/conftest.py`, `tests/test_db_postgres.py`).
