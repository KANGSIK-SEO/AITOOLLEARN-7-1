# 서버 로그 이벤트

서버는 stdout(Vercel Logs)에 한 줄에 한 이벤트를 `key=value` 형식으로 남긴다.

```
LEVEL <event> key=value ... request_id=<id>
INFO ai_call_success latency_ms=812 artworks=6 request_id=71732be3
```

## request_id

- 모든 줄 끝에 `request_id`가 자동으로 붙는다(`app/reqctx.py`). 메시지에 직접 쓰지 않는다.
- 요청마다 새로 만들고(8자리 hex), `POST /api/chat` 응답 body의 `request_id`도 같은 값이다.
- 요청 밖에서 남는 로그(서버 시작 등)는 `request_id=-`.
- 사용자가 오류를 신고하면 응답의 request_id로 Vercel Logs를 검색해 그 요청의 로그를 한 번에 모아 본다.

## 이벤트 목록

| 이벤트 | 레벨 | 필드 | 언제 |
|---|---|---|---|
| `signup_success` | INFO | `user_id` `is_premium` | 회원가입 성공 |
| `login_success` | INFO | `user_id` `is_premium` | 로그인 성공 |
| `login_failed` | INFO | — | 이메일/비밀번호 불일치 (어느 쪽이 틀렸는지·이메일은 남기지 않음) |
| `request_received` | INFO | `user_id` `path` | `/api/chat` 진입 |
| `rate_limited` | WARNING | `user_id` `is_premium` | 시간당 질문 한도 초과 → 429 |
| `free_limit_reached` | WARNING | `user_id` | 일반 계정 평생 무료 질문 소진 → 403 |
| `ai_call_start` | INFO | `user_id` | 의도 추출·검색·답변 생성 시작 |
| `ai_call_success` | INFO | `latency_ms` `artworks` | 답변 생성 완료 |
| `ai_call_failure` | ERROR | `code` `latency_ms` | AI 호출 실패 (`AI_TIMEOUT`, `AI_ERROR`, `AI_RATE_LIMITED` …) |
| `llm_fallback_to_upstage` | WARNING | `reason` | 1차 모델 실패로 Upstage로 전환 |
| `art_db_failure` | ERROR | `detail` | 미술 DB(`data/art.db`) 읽기 실패 → 503 `ART_DB_ERROR` |
| `db_save_success` | INFO | `user_id` `chat_id` `status` | 대화 로그 저장 |
| `db_save_failure` | ERROR | `user_id` `detail` | 대화 로그 저장 실패 (답변은 그대로 반환, `saved=false`) |
| `db_error` | ERROR | `detail` | 사용자 DB 오류 → 503 `DB_ERROR` |
| `unhandled_exception` | ERROR | `detail` + traceback | 처리되지 않은 예외 → 500 |
| `db_schema_ready` | INFO | `backend` (`turso`/`local_sqlite`) | 인스턴스의 첫 DB 접근 시 스키마 확인 완료 |
| `image_proxy_failure` | WARNING | `image_id` `status` 또는 `detail` | AIC 이미지 프록시 실패 |
| `incident_save_failure` | ERROR | `code` `detail` | guardian incident 기록 실패 |
| `rate_check_failure` | ERROR | `bucket` `detail` | guardian 속도 제한 카운터 조회 실패 |
| `github_issue_created` / `github_issue_skipped` / `github_issue_failed` | INFO / WARNING / ERROR | `title` (`reason`, `detail`) | 일일 점검 결과로 GitHub 이슈 생성 시도 |
| `digest_complete` / `digest_ai_failure` | INFO / ERROR | `analyzed` `urgency` / `detail` | 일일 점검(`/api/guardian/daily-digest`) |

## 한 요청의 흐름 예 (`POST /api/chat`)

```
INFO request_received user_id=1 path=/api/chat request_id=71732be3
INFO ai_call_start user_id=1 request_id=71732be3
INFO ai_call_success latency_ms=3 artworks=6 request_id=71732be3
INFO db_save_success user_id=1 chat_id=1 status=ok request_id=71732be3
```

## 남기지 않는 것

비밀번호, 세션 토큰, 이메일, 질문/답변 본문, 쿼리스트링은 로그에 쓰지 않는다. 질문/답변은 사용자 DB의 `chats`에만 저장한다.

## 테스트

`tests/test_api.py`의 `test_every_log_line_in_a_request_shares_request_id` 외 2개가
한 요청 안의 request_id 일관성, 요청마다 다른 값, 요청 밖 기본값을 확인한다.
