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
```
브라우저 ─ /static (HTML/JS) ─┐
                              ├─ FastAPI (app/main.py, Vercel Function)
  POST /api/chat ─────────────┘    ├─ 인증: scrypt 해시 + HMAC 서명 쿠키 (app/auth.py)
                                   ├─ chat.extract_intent → solar-pro3 (검색 조건 JSON)
                                   ├─ art.search → data/art.db (읽기 전용 SQLite + FTS5)
                                   ├─ chat.compose_answer → solar-pro3 (근거 기반 한국어 답변)
                                   └─ db.execute → Turso(SQLite 호환): users, chats
```
| 컴포넌트 | 역할 |
|---|---|
| `app/main.py` | 라우팅, 입력 검증, 로그, 오류 응답 |
| `app/chat.py` | 질문 → 검색 의도 → DB 검색 → 답변 생성 파이프라인 |
| `app/llm.py` | Upstage solar-pro3 호출(서버 전용, 타임아웃 설정) |
| `app/config.py` | **solar-pro3만 허용, 2027-04-01 이후 모든 모델 차단** |
| `app/db.py` | 사용자·로그 DB (Turso 또는 로컬 SQLite 자동 선택) |
| `scripts/collect_*.py` | 공개 API → `data/art.db` 수집기 |

문맥 유지: 같은 사용자의 최근 `CONTEXT_TURNS`(5)개 Q/A를 답변 프롬프트에 포함한다.

## 3. API 명세
오류는 항상 `{"error": {"code": "...", "message": "..."}}`.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/signup` | `{email, password(8자+)}` → 201, 세션 쿠키 발급 |
| POST | `/api/auth/login` | 로그인 → 200, 세션 쿠키 |
| POST | `/api/auth/logout` | 쿠키 삭제 |
| GET | `/api/me` | 현재 사용자 |
| POST | `/api/chat` | **로그인 필요**. 질문 → 답변 + 작품 카드 |
| GET | `/api/me/chats?limit=20&offset=0` | 내 대화 로그 조회 |
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
오류 코드: `UNAUTHENTICATED`(401) `EMPTY_MESSAGE`/`MESSAGE_TOO_LONG`(400) `RATE_LIMITED`(429, 시간당 30회)
`AI_TIMEOUT`(504) `AI_ERROR`(502) `AI_EXPIRED`/`AI_MODEL_NOT_ALLOWED`/`AI_KEY_MISSING`(503) `DB_ERROR`/`ART_DB_ERROR`(503)

## 4. DB 구조
- `data/art.db` (읽기 전용, 레포에 포함): `artworks`(source, source_id, title, artist, date_display, medium, subjects, image_url, source_url, license, is_public_domain …) + `artworks_fts`(FTS5). 스키마: `db/schema.sql`
- Turso/SQLite (쓰기): 
  - `users(id, email UNIQUE, password_hash, created_at)`
  - `chats(id, user_id → users.id, question, answer, status[ok|error], error_code, latency_ms, artwork_ids(JSON), created_at)`

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
| `UPSTAGE_API_KEY` | Upstage solar-pro3 키 |
| `SECRET_KEY` | 세션 서명 키 (32자 이상 랜덤) |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | Turso DB. **없으면 로컬 `data/app.db` 사용** |
| `LLM_TIMEOUT_SECONDS` | AI 호출 타임아웃(기본 20) |

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
| 이름 | 역할 | 작업 요약 |
|---|---|---|
| 서강식 | 기획·백엔드·DB·배포 | (작성 중) |
| 팀원 4명 | (합의 후 기입) | (각자 실제 작업을 Git 이력에 맞춰 기입) |

## 8. 민감정보 관리
- 모든 키는 환경 변수로만 사용하고 `.env`는 `.gitignore`로 제외한다. 예시는 `.env.example`.
- AI 호출은 서버에서만 수행되며 키는 응답·로그에 노출되지 않는다.
- **모델 정책**: `solar-pro3` 외 모델 호출은 코드에서 차단, **2027-04 이후에는 모든 모델 호출이 차단**된다 (`app/config.py`).
