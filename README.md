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
- `app/auth.py` — **문지기.** 비밀번호 해시(scrypt)와 로그인 쿠키(HMAC 서명) 검증. 서버에 세션을 저장하지 않음.
- `app/chat.py` — **지휘자.** "질문 → 검색조건 추출 → 검색 → 답변 생성" 파이프라인을 순서대로 지휘.
- `app/art.py` — **검색엔진.** `data/art.db`에서 SQLite FTS5로 작품을 찾음. AI 호출 없이 순수 DB 검색.
- `app/llm.py` — **AI 통신창구.** Upstage `solar-pro4`를 실제로 호출하는 유일한 곳. 타임아웃·에러를 통일된 형태로 반환.
- `app/db.py` — **저장소.** 사용자·대화 로그 저장(로컬 SQLite 또는 Turso 자동 선택).
- `app/config.py` — **규칙집.** 허용 모델(solar-pro4)과 만료일 등 정책을 고정.
- `app/static/*` — **화면.** 브라우저에 보이는 HTML/JS/CSS 전부.

```
브라우저 ─ /static (HTML/JS) ─┐
                              ├─ FastAPI (app/main.py, Vercel Function)
  POST /api/chat ─────────────┘    ├─ 인증: scrypt 해시 + HMAC 서명 쿠키 (app/auth.py)
                                   ├─ chat.extract_intent → solar-pro4 (검색 조건 JSON)
                                   ├─ art.search → data/art.db (읽기 전용 SQLite + FTS5)
                                   ├─ chat.compose_answer → solar-pro4 (근거 기반 한국어 답변)
                                   └─ db.execute → Turso(SQLite 호환): users, chats
```
| 컴포넌트 | 역할 |
|---|---|
| `app/main.py` | 라우팅, 입력 검증, 로그, 오류 응답 |
| `app/chat.py` | 질문 → 검색 의도 → DB 검색 → 답변 생성 파이프라인 |
| `app/llm.py` | Upstage solar-pro4 호출(서버 전용, 타임아웃 설정) |
| `app/config.py` | **solar-pro4만 허용, 2027-04-01 이후 모든 모델 차단** |
| `app/db.py` | 사용자·로그 DB (Turso 또는 로컬 SQLite 자동 선택) |
| `scripts/collect_*.py` | 공개 API → `data/art.db` 수집기 |

문맥 유지: 같은 사용자의 최근 `CONTEXT_TURNS`(5)개 Q/A를 답변 프롬프트에 포함한다.

## 3. API 명세
오류는 항상 `{"error": {"code": "...", "message": "..."}}`.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/signup` | `{email, password(8자+), private_code?}` → 201, 세션 쿠키 발급 (`private_code`가 `PREMIUM_CODE`와 일치하면 프리미엄 가입) |
| POST | `/api/auth/login` | 로그인 → 200, 세션 쿠키 |
| POST | `/api/auth/logout` | 쿠키 삭제 |
| GET | `/api/me` | 현재 사용자 |
| POST | `/api/chat` | **로그인 필요**. 질문 → 답변 + 작품 카드 |
| GET | `/api/me/chats?limit=20&offset=0` | 내 대화 로그 조회 |
| POST | `/api/favorites` | **로그인 필요**. `{artwork_id}` 작품 즐겨찾기 저장 (상세: `docs/track-c.md`) |
| DELETE | `/api/favorites/{artwork_id}` | **로그인 필요**. 즐겨찾기 해제 |
| GET | `/api/me/favorites?limit=20&offset=0` | 내 즐겨찾기 작품 카드 조회 |
| GET | `/api/health` | 상태 확인 |

`POST /api/chat`
```json
// 요청
{"message": "봄 느낌 풍경화 3개 찾아줘"}
// 응답 200
{"chat_id": 12, "saved": true, "request_id": "7489f728",
 "reply": "[1] Spring in France — ...",
 "artworks": [{"id": 101, "source": "aic", "title": "Spring in France", "artist": "Robert William Vonnoh",
               "date_display": "1890", "image_url": "https://...", "source_url": "https://www.artic.edu/artworks/...",
               "license": "CC0"}]}
// 오류 예
{"error": {"code": "AI_TIMEOUT", "message": "응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요."}}
```
오류 코드: `UNAUTHENTICATED`(401) `EMPTY_MESSAGE`/`MESSAGE_TOO_LONG`(400) `RATE_LIMITED`(429, 시간당 일반 30회·초대코드 300회)
`FREE_LIMIT_REACHED`(403, 초대코드 없는 계정의 평생 무료 질문 100회 소진) `AI_TIMEOUT`(504) `AI_ERROR`(502)
`AI_EXPIRED`/`AI_MODEL_NOT_ALLOWED`/`AI_KEY_MISSING`(503) `DB_ERROR`/`ART_DB_ERROR`(503)

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

**DB 확인 가이드** (택 1 이상)
1. 로그 조회 API: `curl -b cookies.txt https://<서비스>/api/me/chats`
2. 확인용 SQL: `scripts/check_logs.sql` (`turso db shell <db-name> < scripts/check_logs.sql`)
3. 서버 로그: `request_received`, `ai_call_start`, `ai_call_success|ai_call_failure`, `db_save_success|db_save_failure` 이벤트를 stdout(Vercel Logs)에 남긴다.

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
docker run --rm art-chatbot-ubuntu python -m pytest -q tests          # 14 passed (Ubuntu 24.04, Python 3.12)
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
| `UPSTAGE_API_KEY` | Upstage solar-pro4 키 |
| `SECRET_KEY` | 세션 서명 키 (32자 이상 랜덤) |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | Turso DB. **없으면 로컬 `data/app.db` 사용** |
| `LLM_TIMEOUT_SECONDS` | AI 호출 타임아웃(기본 20) |
| `PREMIUM_CODE` | 회원가입 시 입력받는 초대코드(선택, 비우면 초대코드 가입 비활성) |
| `CHAT_LIMIT_PER_HOUR_PREMIUM` | 초대코드 사용자 시간당 질문 상한(기본 300) |
| `CHAT_LIFETIME_LIMIT_FREE` | 초대코드 없는 사용자의 평생 무료 질문 수(기본 100) |
| `ART_RESULTS_LIMIT_PREMIUM` | 초대코드 사용자에게 보여줄 추천 작품 수(기본 100) |

**Vercel + Turso 배포**
```bash
turso db create art-chatbot && turso db show art-chatbot --url && turso db tokens create art-chatbot
vercel link && vercel env add UPSTAGE_API_KEY && vercel env add SECRET_KEY \
  && vercel env add TURSO_DATABASE_URL && vercel env add TURSO_AUTH_TOKEN
vercel deploy --prod
```

## 6. 협업 규칙
브랜치: `main` / `develop` / `feature/*`, 모든 병합은 PR. 팀원별 유의미한 커밋 10회 이상.

## 7. 팀 구성원 역할 및 개인별 작업 요약
| 이름 | 역할 | 담당 이슈 | 작업 요약 |
|---|---|---|---|
| 서강식 | AI/데이터 엔지니어 & 팀 리드 | [#8](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/8), [#9](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/9), [#10](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/10), [#17](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/17) | MVP 설계·구현, 검색·AI 파이프라인 고도화, 배포·통합·PR 머지 총괄 (작업 완료 후 PR 번호로 갱신) |
| 유영민 | 프론트엔드 개발자 | [#11](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/11), [#12](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/12), [#13](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/13) | 대화 UI, 모바일 반응형·접근성, 오류/로딩 UX (작성 예정) |
| 오철호 | 백엔드 개발자 | [#14](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/14), [#15](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/15), [#16](https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1/issues/16) | 즐겨찾기 API·DB, 테스트·로깅 보강, ERD/API 문서화 (작성 예정) |

## 8. 민감정보 관리
- 모든 키는 환경 변수로만 사용하고 `.env`는 `.gitignore`로 제외한다. 예시는 `.env.example`.
- AI 호출은 서버에서만 수행되며 키는 응답·로그에 노출되지 않는다.
- **모델 정책**: `solar-pro4` 외 모델 호출은 코드에서 차단, **2027-04 이후에는 모든 모델 호출이 차단**된다 (`app/config.py`).
