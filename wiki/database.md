---
title: 데이터베이스 (작품 DB와 사용자 DB)
sources: [app/db.py, db/schema.sql, app/art.py, scripts/finalize_artdb.py]
updated: 2026-10-07
---
# 데이터베이스

DB가 **두 개**다. 성격이 달라서 나눴다.

| | 작품 DB | 사용자 DB |
|---|---|---|
| 파일/서비스 | `data/art.db` (저장소에 포함) | **Turso** (인터넷 SQLite). 로컬은 `data/app.db` |
| 쓰기 | 서버는 **읽기만**. 수집 스크립트만 쓴다 | 가입·대화·즐겨찾기 때마다 쓴다 |
| 크기 | 약 55MB (95MB 넘으면 수집이 멈춤, `scripts/finalize_artdb.py`) | 작다 |
| 코드 | `app/art.py` | `app/db.py` |

**왜 나눴나**: Vercel 서버리스는 파일에 쓴 게 다음 요청까지 남지 않는다. 그래서 바뀌는 데이터(사용자)는 바깥 DB(Turso)에 두고,
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
