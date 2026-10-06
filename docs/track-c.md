# Track C — 작품 즐겨찾기 · 테스트 · 문서

담당: 오철호 · 관련 이슈 [#14](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/14), [#15](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/15), [#16](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/16)

## 1. 작품 즐겨찾기 (#14)

로그인한 사용자가 챗봇이 추천한 작품을 저장하고 다시 볼 수 있게 하는 API.
화면의 즐겨찾기 버튼은 이 트랙 범위가 아니며, 유지관리자가 아래 API에 연결한다.

### API 명세

모든 엔드포인트는 **로그인 필요**(세션 쿠키). 없으면 `401 UNAUTHENTICATED`.
오류 형식은 다른 API와 같다: `{"error": {"code": "...", "message": "..."}}`.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/favorites` | `{artwork_id}` 저장. 새로 저장 201, 이미 저장돼 있으면 200 |
| DELETE | `/api/favorites/{artwork_id}` | 저장 해제. 저장하지 않은 작품이어도 200 (`removed: false`) |
| GET | `/api/me/favorites?limit=20&offset=0` | 내 즐겨찾기, 최근 저장 순. `limit` 1~100 |

`POST /api/favorites`
```json
// 요청
{"artwork_id": 101}
// 응답 201 (새로 저장) / 200 (이미 저장됨 → "created": false)
{"artwork_id": 101, "created": true}
// 오류 예
{"error": {"code": "ARTWORK_NOT_FOUND", "message": "존재하지 않는 작품입니다."}}
```

`DELETE /api/favorites/101`
```json
// 응답 200
{"artwork_id": 101, "removed": true}
```

`GET /api/me/favorites`
```json
// 응답 200 — 각 항목은 /api/chat의 artworks 카드와 같은 필드 + favorited_at
{"favorites": [{"id": 101, "source": "aic", "title": "Spring in France", "artist": "Robert William Vonnoh",
                "date_display": "1890", "image_url": "/api/img/aic/...?w=1686", "thumbnail_url": "/api/img/aic/...?w=400",
                "source_url": "https://www.artic.edu/artworks/...", "license": "CC0", "credit_line": "...",
                "is_highlight": 0, "favorited_at": "2026-10-03T01:23:45+00:00"}]}
```

오류 코드: `UNAUTHENTICATED`(401) `ARTWORK_NOT_FOUND`(404, POST만) `INVALID_INPUT`(422, `artwork_id`가 정수가 아님)
`DB_ERROR`/`ART_DB_ERROR`(503)

**설계 결정**
- **중복 저장은 오류가 아니다.** 버튼을 두 번 누르거나 네트워크 재시도가 일어나도 같은 결과가 나오도록
  `INSERT ... ON CONFLICT DO NOTHING`으로 처리하고, 새로 저장됐는지만 `created`/상태 코드로 알려준다. 삭제도 같은 이유로 멱등이다.
- **작품 존재 검증은 POST에서만** 한다. 삭제는 이미 사라진 작품의 즐겨찾기도 지울 수 있어야 하기 때문이다.
- 목록 조회 시 미술 DB에서 사라진 작품은 결과에서 조용히 빠진다.

### DB 구조

`favorites`는 사용자 DB(Turso 또는 로컬 `data/app.db`)에 있고, 스키마는 `app/db.py`의 `SCHEMA`에 있다.

```sql
CREATE TABLE IF NOT EXISTS favorites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    artwork_id  INTEGER NOT NULL,          -- data/art.db의 artworks.id
    created_at  TEXT NOT NULL,             -- UTC ISO-8601
    UNIQUE (user_id, artwork_id)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user_time ON favorites (user_id, created_at);
```

- `artworks`는 별도 파일인 읽기 전용 미술 DB(`data/art.db`, 스키마 `db/schema.sql`)에 있어서 **FOREIGN KEY를 걸 수 없다.**
  그래서 `POST /api/favorites`에서 `art.get_by_ids()`로 존재 여부를 확인하고, 조회할 때도 같은 함수로 카드 정보를 붙인다.
- `UNIQUE (user_id, artwork_id)`가 중복 저장을 막고, 사용자별 격리는 모든 쿼리의 `WHERE user_id = ?`로 보장한다.
- 기존 배포 DB에도 `CREATE TABLE IF NOT EXISTS`로 자동 생성되므로 별도 마이그레이션은 필요 없다.

### 테스트 (`tests/test_api.py`)

| 테스트 | 확인 내용 |
|---|---|
| `test_favorites_require_login` | 로그인 없이 세 API 모두 401 |
| `test_favorite_add_list_remove` | 저장 → 최근 순 조회 → 삭제, 삭제 반복은 `removed: false` |
| `test_favorite_duplicate_is_idempotent` | 같은 작품 두 번 저장 시 201 → 200, 목록에는 1개 |
| `test_favorite_rejects_unknown_or_invalid_artwork` | 없는 작품 404, 잘못된 형식 422 |
| `test_favorites_are_isolated_between_users` | 다른 사용자의 저장·삭제가 내 목록에 영향 없음 |
