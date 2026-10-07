# 저작권 걱정 없는 퍼블릭 도메인 명화 찾기 챗봇 (AITOOLLEARN-7-1)

"상업적으로 써도 되는 명화"를 한국어로 물어보면, MET·Art Institute of Chicago의 **CC0(퍼블릭 도메인) 작품 DB**에서
근거를 찾아 답하고 원본 이미지·출처 링크를 카드로 보여주는 웹 챗봇 (FastAPI).

**서비스 URL: https://art-chatbot-eight.vercel.app**

## 1. 프로젝트 개요
- **문제**: PPT·블로그·굿즈·썸네일 제작자는 "저작권 걱정 없는 명화"를 찾을 때 라이선스를 일일이 확인해야 한다.
  범용 챗봇은 라이선스·원본 이미지 링크를 보증하지 못한다.
- **타깃 사용자**: 디자이너, 콘텐츠 제작자, 학생, 미술 입문자
- **핵심 시나리오**: 로그인 → "봄 느낌 풍경화 3개, 상업적으로 써도 되는 걸로" → 작품 카드(썸네일·작가·연도·CC0·원본/출처 링크) + 한국어 설명
- **데이터**: [MET Open Access](https://metmuseum.github.io/), [Art Institute of Chicago API](https://api.artic.edu/docs/) (둘 다 CC0, API 키 불필요)

## 2. 시스템 구조

**한눈에 보기** (팀원 전원 필독 — 본인 담당 파일은 깊게, 나머지는 이 정도만 알면 충분합니다)
- `app/main.py` — **교통정리.** 모든 URL 경로(로그인/챗/내 로그)가 여기 모임. 요청 검증·로그·오류 응답 담당.
- `app/auth.py` — **문지기.** 비밀번호 해시(scrypt)와 로그인 쿠키(HMAC 서명) 검증. 초대코드(프리미엄) 여부도 이 쿠키에 담긴다. 서버에 세션을 저장하지 않음.
- `app/chat.py` — **지휘자.** "질문 → 검색조건 추출 → 검색 → 답변 생성" 파이프라인을 순서대로 지휘.
- `app/art.py` — **검색엔진.** `data/art.db`에서 SQLite FTS5로 작품을 찾음. AI 호출 없이 순수 DB 검색. 상위 2개(`GUARANTEED_TOP`)는 관련도순 고정, 나머지는 후보 풀에서 무작위로 섞어 같은 질문이라도 항상 똑같은 작품만 나오지 않게 한다.
- `app/llm.py` — **AI 통신창구.** OpenAI `gpt-6-astra`를 실제로 호출하는 유일한 곳(429/401/403이면 Upstage `solar-pro4`로 비상 폴백). 타임아웃·에러를 통일된 형태로 반환.
- `app/db.py` — **저장소.** 사용자·대화 로그·가디언 사건 저장(로컬 SQLite 또는 Turso 자동 선택).
- `app/config.py` — **규칙집.** 사용 모델(gpt-6-astra/폴백 solar-pro4)·초대코드·요금제 상한 등 설정을 고정.
- `app/guardian.py` — **가디언.** 장애·보안 사건을 즉시 기록·대응(잠금, AI 백오프, 악성 입력 차단)하고, 1일 1회 gpt-6-astra로 일괄 분석·GitHub 이슈까지 생성.
- `app/static/*` — **화면.** 브라우저에 보이는 HTML/JS/CSS 전부. 초대코드 회원은 화이트 테마(`body.light-theme`)로 바뀐다.

```
브라우저 ─ /static (HTML/JS) ─┐
                              ├─ FastAPI (app/main.py, Vercel Function)
  POST /api/chat ─────────────┘    ├─ 인증: scrypt 해시 + HMAC 서명 쿠키 (app/auth.py, is_premium 포함)
                                   ├─ chat.extract_intent → gpt-6-astra (검색 조건 JSON)
                                   ├─ art.search → data/art.db (읽기 전용 SQLite + FTS5)
                                   ├─ chat.compose_answer → gpt-6-astra (근거 기반 한국어 답변)
                                   ├─ guardian: 실패 시 즉시 기록·대응 (잠금/백오프/차단)
                                   └─ db.execute → Turso(SQLite 호환): users, chats, incidents
```
| 컴포넌트 | 역할 |
|---|---|
| `app/main.py` | 라우팅, 입력 검증, 로그, 오류 응답 |
| `app/chat.py` | 질문 → 검색 의도 → DB 검색 → 답변 생성 파이프라인 |
| `app/llm.py` | OpenAI gpt-6-astra 호출(서버 전용, 타임아웃 설정) + solar-pro4 비상 폴백 |
| `app/config.py` | 사용 모델(gpt-6-astra)·키 이름·초대코드/요금제 상한 등 설정 |
| `app/guardian.py` | **가디언** — 장애·보안 사건 즉시 대응 + 1일 1회 AI 일괄 분석 (`/api/guardian/daily-digest`) |
| `app/db.py` | 사용자·로그·사건 DB (Turso 또는 로컬 SQLite 자동 선택) |
| `scripts/collect_*.py` | 공개 API → `data/art.db` 수집기 |

문맥 유지: 같은 사용자의 최근 `CONTEXT_TURNS`(5)개 Q/A를 답변 프롬프트에 포함한다.

### 2.1 온디바이스 추천 (Datalog, 서버/AI 호출 없음)
채팅창 안 "🧠 온디바이스 추천" 패널은 서버나 gpt-6-astra를 전혀 거치지 않고, **브라우저 안에서만** 작품을 고른다.
- `scripts/export_artworks_json.py`가 `data/art.db`(CC0만, `is_public_domain = 1`)를 `app/static/artworks.json`으로 내보낸다. `data/art.db`가 바뀔 때만 다시 실행하면 된다.
- `app/static/ondevice.js`가 이 JSON을 최초 1회만 받아 메모리에 캐시하고, 사용자가 고른 화풍/주제/연도 조건을 **Datalog 스타일 규칙**으로 조합해 그 자리에서 배열 필터링한다 (예: `candidate(W) :- style(W, "Impressionism"), subject(W, "landscape").`). 주제어가 여러 개면 "같은 head를 가진 규칙이 여러 개면 합집합"이라는 실제 Datalog 의미론대로 규칙을 여러 줄로 나눠 OR로 평가한다. 재귀가 필요 없는 질의라 naive bottom-up 평가로 충분하다.
- **"AI 없이 이해하기"**: 자유 문장(예: "봄 느낌 풍경화")을 입력하면, LLM 없이 **한/영 키워드 사전 매칭**만으로 화풍/주제/연도를 추출해 위 규칙에 자동으로 채운다 — gpt-6-astra가 하는 자연어 이해를 훨씬 단순한 규칙 기반으로 대체한 버전. 사전에 없는 단어는 당연히 못 알아듣는다(의도된 한계이자 AI와의 핵심 차이점).
- 카드 렌더링은 채팅과 동일한 `addCards()`를 그대로 재사용 — 결과 화면이 100% 같은 스타일.
- Oxford Semantic Technologies(RDFox)가 갤럭시 기기에 Datalog 추론 엔진을 온디바이스로 넣은 것과 같은 설계 철학: 클라우드로 보내지 않고 기기에서 바로 추론한다.

## 3. API 명세
오류는 항상 `{"error": {"code": "...", "message": "..."}}`.
인증: 웹은 로그인 시 발급되는 `session` 쿠키(HttpOnly)로, TV 앱 등 다른 오리진 클라이언트는 응답의 `token`을
`Authorization: Bearer <token>` 헤더로 보낸다. 둘 다 있으면 쿠키가 우선한다. 토큰 유효기간은 7일.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/signup` | `{email, password(8~128자), private_code?}` → 201, `{user, token}` + 세션 쿠키 (`private_code`가 `PREMIUM_CODE`와 일치하면 프리미엄 가입) |
| POST | `/api/auth/login` | `{email, password}` → 200, `{user, token}` + 세션 쿠키 |
| POST | `/api/auth/logout` | 쿠키 삭제 → `{"ok": true}` |
| GET | `/api/me` | **로그인 필요**. 현재 사용자 |
| POST | `/api/chat` | **로그인 필요**. 질문 → 답변(한국어+영어) + 작품 카드 + 남은 무료 횟수 |
| GET | `/api/me/chats?limit=20&offset=0` | **로그인 필요**. 내 대화 로그 (최신순, `limit` 1~100) |
| POST | `/api/favorites` | **로그인 필요**. `{artwork_id}` 작품 즐겨찾기 저장 (상세: `docs/track-c.md`) |
| DELETE | `/api/favorites/{artwork_id}` | **로그인 필요**. 즐겨찾기 해제 |
| GET | `/api/me/favorites?limit=20&offset=0` | 내 즐겨찾기 작품 카드 조회 |
| GET | `/api/health` | 프로세스 생존 확인 (항상 200) |
| GET | `/healthz` | 의존성 상태 확인: 사용자 DB·미술 DB에 실제 쿼리 → 모두 정상 200, 하나라도 실패 503 (`{"status": "ok|degraded", "checks": {...}}`) |
| GET | `/api/guardian/daily-digest` | 가디언 일일 점검 (`CRON_SECRET` 필요, Vercel Cron 전용) |
| POST | `/api/explain` | 피어 리뷰용 설명 에이전트. `{question, secret}` → `{"answer": "..."}` (`EXPLAIN_AGENT_SECRET` 미설정 시 항상 401) |
| GET | `/explain/{token}` | 설명 에이전트 화면 (토큰이 틀리거나 비활성이면 404) |

아래 예시는 로컬 서버에 실제로 요청해 받은 응답의 형태 그대로다 (`token`은 줄였고, AI 답변 문장과 `latency_ms`는 예시 값).

`POST /api/auth/signup` · `POST /api/auth/login`
```json
// 요청
{"email": "a@b.com", "password": "password123"}
// 응답 201(가입) / 200(로그인) — Set-Cookie: session=...
{"user": {"id": 1, "email": "a@b.com", "is_premium": false}, "token": "eyJ1aWQiOiAx..."}
```

`GET /api/me`
```json
{"user": {"id": 1, "email": "a@b.com", "created_at": "2026-10-06T13:50:08+00:00", "is_premium": false}}
```

`POST /api/chat`
```json
// 요청
{"message": "봄 느낌 풍경화 3개 찾아줘"}
// 응답 200 (artworks는 1개만 표시)
{"chat_id": 1, "saved": true, "request_id": "d20def8c",
 "reply": "[1] Spring in Brittany — ...\n\nEnglish: [1] Spring in Brittany — ...",
 "artworks": [{"id": 4613, "source": "met", "title": "Spring in Brittany", "artist": "Paul Sébillot",
               "date_display": "1874", "medium": "Oil on wood",
               "image_url": "https://images.metmuseum.org/CRDImages/ep/original/DP-17429-001.jpg",
               "thumbnail_url": "https://images.metmuseum.org/CRDImages/ep/web-large/DP-17429-001.jpg",
               "source_url": "https://metmuseum.org/art/collection/search/437647", "license": "CC0",
               "credit_line": "Gift of Paul-Yves Sébillot, 1949", "is_highlight": 0}],
 "remaining_free": 99, "show_limit_warning": false}
// saved: 대화 로그 저장 성공 여부 (DB 저장에 실패해도 답변은 200으로 준다 → chat_id null, saved false)
// remaining_free: 이번 질문을 포함해 남은 평생 무료 질문 수. 초대코드(프리미엄) 사용자는 상한이 없어 항상 null.
// show_limit_warning: 남은 무료 질문이 FREE_LIMIT_WARNING_THRESHOLD(기본 10) 이하일 때만 true.
// AIC 작품의 image_url·thumbnail_url은 서버 프록시 주소(/api/img/aic/<id>?w=1686|400)로 바뀌어 나온다.
// 오류 예
{"error": {"code": "AI_TIMEOUT", "message": "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요."}}
```

`GET /api/me/chats?limit=1`
```json
{"chats": [{"id": 1, "question": "봄 느낌 풍경화 3개 찾아줘", "answer": "[1] Spring in Brittany — ...",
            "status": "ok", "error_code": null, "latency_ms": 2310, "created_at": "2026-10-06T13:50:08+00:00"}]}
// 실패한 질문은 status "error", answer null, error_code "AI_TIMEOUT" 등으로 남는다.
```

오류 코드:
- 공통: `UNAUTHENTICATED`(401) `INVALID_INPUT`(422 요청 형식 오류 / 400 의심스러운 입력 차단) `DB_ERROR`(503)
  `INTERNAL_ERROR`(500, 예상 못한 예외는 모두 여기로 모이고 가디언이 기록한다)
- 가입·로그인: `INVALID_EMAIL`/`INVALID_PASSWORD`(400) `EMAIL_TAKEN`(409) `INVALID_CREDENTIALS`(401)
  `RATE_LIMITED`(429, 같은 IP의 가입 시간당 10회·로그인 10분당 20회 초과 또는 같은 이메일 로그인 5회 실패 후 15분 잠금)
- 챗봇: `EMPTY_MESSAGE`/`MESSAGE_TOO_LONG`(400) `RATE_LIMITED`(429, 시간당 일반 30회·초대코드 300회)
  `FREE_LIMIT_REACHED`(403, 초대코드 없는 계정의 평생 무료 질문 100회 소진)
  `AI_TIMEOUT`(504) `AI_ERROR`(502) `AI_RATE_LIMITED`(429) `AI_BACKED_OFF`/`AI_KEY_MISSING`(503) `ART_DB_ERROR`(503)

**초대코드(프리미엄)**: 회원가입 시 `private_code`로 `PREMIUM_CODE`(서버 환경변수)와 일치하는 값을 보내면 해당 계정은
- 시간당 질문 한도가 `CHAT_LIMIT_PER_HOUR_PREMIUM`(기본 300)으로 상향되고, **평생 무료 질문 100회 제한이 적용되지 않는다**
  (일반 계정은 `CHAT_LIFETIME_LIMIT_FREE`(기본 100)회를 다 쓰면 `FREE_LIMIT_REACHED`로 막힌다).
- 추천 작품 수가 `ART_RESULTS_LIMIT_PREMIUM`(기본 100, 일반은 `ART_RESULTS_LIMIT`=6)으로 늘어난다. 답변 본문에서 번호로
  설명하는 작품은 `ANSWER_NARRATION_LIMIT`(6)개까지만이고 — 100개를 전부 LLM이 한 줄씩 설명하면 토큰 비용이 커지고
  응답이 잘릴 수 있어서다 — 나머지는 카드로만 보여주고 "그 외 N개를 더 찾았어요"를 한 줄 덧붙인다(`app/chat.py`).
- 화면 배경이 화이트 테마로 바뀐다(`body.light-theme`, `app/static/style.css`, `app/static/app.js`).

초대코드 여부는 서버 세션 없이 서명된 쿠키에 담기므로(`app/auth.py`) 가입/로그인 시점 기준이며, 코드 입력 UI는
로그인 화면이 아니라 **회원가입** 화면에만 있다(`app/static/index.html`).

## 4. DB 구조
- `data/art.db` (읽기 전용, 레포에 포함): `artworks`(source, source_id, title, artist, date_display, medium, subjects, image_url, source_url, license, is_public_domain …) + `artworks_fts`(FTS5). 스키마: `db/schema.sql`
- Turso/SQLite (쓰기): 
  - `users(id, email UNIQUE, password_hash, is_premium, created_at)`
  - `chats(id, user_id → users.id, question, answer, status[ok|error], error_code, latency_ms, artwork_ids(JSON), created_at)`
  - `favorites(id, user_id → users.id, artwork_id(art.db artworks.id), created_at, UNIQUE(user_id, artwork_id))`
  - `incidents(id, category[reliability|security], code, message, context(JSON), severity, auto_action, diagnosis, created_at)` — 가디언 사건 로그. `diagnosis`는 일일 배치 분석 전까지 NULL.
  - `runtime_flags(key, value, updated_at)` — AI 백오프·로그인 잠금 등 자동 대응 상태값 (예: `ai_backoff_until`, `lockout:<email>`)
  - `rate_counters(bucket, count, window_start)` — IP/이메일 단위 레이트리밋 카운터

**DB 확인 가이드** (택 1 이상)
1. 로그 조회 API: `curl -b cookies.txt https://<서비스>/api/me/chats`
2. 확인용 SQL: `scripts/check_logs.sql` (`turso db shell <db-name> < scripts/check_logs.sql`)
3. 서버 로그: `request_received`, `ai_call_start`, `ai_call_success|ai_call_failure`, `db_save_success|db_save_failure` 이벤트를 stdout(Vercel Logs)에 남긴다. 모든 줄 끝에 `request_id`가 붙는다. 한 요청 안의 단계별 소요시간은 `chat_stage stage=intent|search|answer request_id=… latency_ms=… ok=…`로 따로 남는다(`app/chat.py`). 전체 이벤트 목록: [`docs/logging.md`](docs/logging.md)

## 5. 실행·배포
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env         # 값 채우기
.venv/bin/uvicorn app.main:app --reload    # http://localhost:8000
.venv/bin/python -m pytest -q tests
```
**Linux(Ubuntu 24.04) 환경에서 실행·검증**

개발은 macOS에서 했고, 배포 전에 Ubuntu 24.04 컨테이너에서 동일 코드를 설치·테스트·실행해 검증했다.
```bash
docker build -t art-chatbot-ubuntu .
docker run --rm art-chatbot-ubuntu python -m pytest -q tests          # Ubuntu 24.04, Python 3.12
docker run -d --rm -p 8000:8000 --env-file .env art-chatbot-ubuntu    # http://localhost:8000
```
Vercel Functions도 Linux 런타임에서 실행되며, 배포는 Ubuntu 24.04 컨테이너(`deploy/Dockerfile`, Node + Vercel CLI)의 셸에서 실행했다.
```bash
docker build -t art-vercel-ubuntu deploy
docker run --rm -it -v vercel-auth:/root/.local/share -v vercel-auth-cfg:/root/.config -v "$PWD":/app art-vercel-ubuntu vercel login
docker run --rm -v vercel-auth:/root/.local/share -v vercel-auth-cfg:/root/.config -v "$PWD":/app art-vercel-ubuntu vercel deploy --prod --yes
```
서버 없이 Ubuntu 서버에 직접 올리는 경우에는 `apt install python3-venv` 후 위 "실행" 절차와 `uvicorn`을 systemd로 상시 실행하면 된다.

**환경 변수** (`.env.example` 참고, 값은 절대 커밋하지 않는다)

| 이름 | 설명 |
|---|---|
| `GPT_ASTRA_API_KEY` | OpenAI gpt-6-astra 키 (주 모델) |
| `UPSTAGE_API_KEY` (선택) | Upstage solar-pro4 키. GPT 쪽이 429/401/403일 때만 비상 폴백으로 사용 |
| `SECRET_KEY` | 세션 서명 키 (32자 이상 랜덤) |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | Turso DB. **없으면 로컬 `data/app.db` 사용** |
| `LLM_TIMEOUT_SECONDS` | AI 호출 타임아웃(기본 20) |
| `LLM_REASONING_EFFORT` | gpt-6-astra reasoning_effort (기본 low — 비용 보호) |
| `CRON_SECRET` | 가디언 일일 점검(`/api/guardian/daily-digest`)을 Vercel Cron만 호출하게 막는 값 |
| `GITHUB_TOKEN` (선택) | 긴급도 medium/high 사건 발생 시 GitHub 이슈 자동 생성 (issues:write) |
| `GITHUB_REPO` (선택) | 이슈를 열 저장소, 기본 `KANGSIK-SEO/AITOOLLEARN-7-1` |
| `PREMIUM_CODE` (선택) | 회원가입 시 입력받는 초대코드 (비우면 초대코드 가입 비활성) |
| `CHAT_LIMIT_PER_HOUR_PREMIUM` | 초대코드 사용자 시간당 질문 상한(기본 300) |
| `CHAT_LIFETIME_LIMIT_FREE` | 초대코드 없는 사용자의 평생 무료 질문 수(기본 100) |
| `ART_RESULTS_LIMIT_PREMIUM` | 초대코드 사용자에게 보여줄 추천 작품 수(기본 100) |

**Vercel + Turso 배포**
```bash
turso db create art-chatbot && turso db show art-chatbot --url && turso db tokens create art-chatbot
vercel link && vercel env add GPT_ASTRA_API_KEY && vercel env add SECRET_KEY \
  && vercel env add TURSO_DATABASE_URL && vercel env add TURSO_AUTH_TOKEN \
  && vercel env add CRON_SECRET && vercel env add GITHUB_TOKEN
vercel deploy --prod
```
**가디언 (장애 대응 + 보안)**: `app/guardian.py`. 로그인 폭주·AI 429 반복·악성 입력 패턴은
요청마다 비용 없이 즉시 차단/잠금(`incidents`, `runtime_flags` 테이블). 쌓인 사건은 Vercel Cron이
하루 한 번(Hobby 플랜 제한) `/api/guardian/daily-digest`를 호출해 gpt-6-astra로 한 번에 분석하고,
긴급도가 medium/high면 GitHub 이슈를 자동으로 연다. 로컬에서 수동 실행:
```bash
curl -H "Authorization: Bearer $CRON_SECRET" http://localhost:8000/api/guardian/daily-digest
```

## 6. 협업 규칙
브랜치: `main` / `develop` / `feature/*`, 모든 병합은 PR. 팀원별 유의미한 커밋 10회 이상.

## 7. 팀 구성원 역할 및 개인별 작업 요약
| 이름 | 역할 | 담당 이슈 | 작업 요약 |
|---|---|---|---|
| 서강식 | AI/데이터 엔지니어 & 팀 리드 | [#8](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/8), [#9](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/9), [#10](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/10), [#17](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/17) | MVP 설계·구현, 검색·AI 파이프라인 고도화, 배포·통합·PR 머지 총괄 (작업 완료 후 PR 번호로 갱신) |
| 유영민 | 프론트엔드 개발자 | [#11](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/11), [#12](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/12), [#13](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/13) | 채팅 UI 스크린리더 접근성([#31](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/31)), 시스템 다크/라이트 테마 지원([#32](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/32)), AI 응답 대기 인디케이터([#33](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/33)), 모바일 작은 화면 레이아웃 개선([#34](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/34)), 온디바이스 패널 전환 애니메이션([#35](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/35)), PWA 오프라인 캐싱 전략 개선([#36](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/36)), 설명 페이지 공통 스타일 적용([#37](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/37)), 채팅 메시지 타임스탬프([#38](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/38)), 상태 메시지 공통 컴포넌트화([#39](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/39)), SEO·공유 미리보기 메타데이터([#40](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/40)) |
| 오철호 | 백엔드 개발자 | [#14](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/14), [#15](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/15), [#16](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/16) | 즐겨찾기 API([#19](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/19)), 환경변수 검증([#21](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/21)), DB 슬로우쿼리 로깅([#22](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/22)), LLM 재시도·타임아웃([#23](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/23)), FTS5 입력 예외처리([#26](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/26)), 단계별 요청 레이턴시 로깅([#27](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/27)), `/healthz` 의존성 상태 점검([#28](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/28)), 설명 에이전트 에러 메시지 개선([#29](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/29)), 가디언·무료한도 단위 테스트 보강([#20](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/20), [#24](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/24), [#25](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/25)), README API 문서 최신화([#30](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/pull/30)) |

## 8. 민감정보 관리
- 모든 키는 환경 변수로만 사용하고 `.env`는 `.gitignore`로 제외한다. 예시는 `.env.example`.
- AI 호출은 서버에서만 수행되며 키는 응답·로그에 노출되지 않는다.
- **모델**: 주 모델은 `gpt-6-astra` (`app/config.py`, `app/llm.py`). GPT 쪽이 429/401/403으로
  실패할 때만 Upstage `solar-pro4`로 한 번 더 시도한다(`UPSTAGE_API_KEY` 설정 시에만 활성, 없으면
  폴백 없이 원래 에러 반환). gpt-6-astra는 실제 과금, solar-pro4는 2026-10 기준 무료·무제한이지만
  **2027-04-01부터 Upstage가 전 모델을 과금 전환**하면서 이 폴백도 끝난다. 호출 비용 보호를 위해
  시간당 질문 상한(`CHAT_LIMIT_PER_HOUR`/`CHAT_LIMIT_PER_HOUR_PREMIUM`), 429 반복 시 자동 백오프,
  요청당 GPT 호출 금지(배치 분석만)로 방어한다.

## 9. 가디언
`app/guardian.py`가 **장애 대응과 보안 위협 탐지를 함께** 담당한다.
- **즉시(매 요청, GPT 미사용)**: 로그인 5회 실패 시 15분 잠금, AI 429가 5분 내 3회면 5분 백오프,
  `<script>`/`UNION SELECT` 등 명백한 악성 입력 차단, 가입/로그인/이미지 프록시 IP 레이트리밋.
  요청마다 GPT를 부르면 공격자가 실패 요청을 반복시켜 AI 비용 자체를 디도스 벡터로 쓸 수 있어 피한다.
- **배치(1일 1회, Vercel Cron → `/api/guardian/daily-digest`, `CRON_SECRET`으로 보호)**: 그동안 쌓인
  `incidents`를 한 번에 gpt-6-astra에 보내 "무슨 일이 있었는지 / 반복·증가 추세가 있는지 / 다음에
  뭐가 터질 수 있는지"를 진단하고, 긴급도가 medium/high면 GitHub 이슈를 자동으로 연다.
  코드는 수정하지 않는다(유지관리자 리뷰·머지 원칙 유지) — 사람이 볼 이슈를 만드는 것까지만 자동화한다.

**"왜 자동 코드수정은 안 하는가"**는 최근 연구와도 일치한다. Sun et al., "Toward Agentic
Runtime Healing"(CACM, Oct 2026)은 LLM이 런타임 상태만 즉석에서 고쳐 요청을 살리는
HEALER를 제안하는데(GPT-4 기준 73% 실행 지속, 39.6% 정답), 저자들 스스로 "진짜 장벽은
효과성이 아니라 신뢰성"이라며 안전장치가 아직 미성숙하다고 결론짓는다. 가디언이 LLM 생성
코드를 실행/커밋하는 경로를 만들지 않은 건 그래서다 — 진단과 이슈 생성까지만 자동화한다.
