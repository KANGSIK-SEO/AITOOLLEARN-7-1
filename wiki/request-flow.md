---
title: 질문 하나가 답이 되기까지
sources: [app/main.py, app/chat.py, app/art.py, app/guardian.py, app/db.py]
updated: 2026-10-07
---
# 질문 하나가 답이 되기까지

`POST /api/chat` (`app/main.py`의 `chat_endpoint`)이 하는 일을 순서대로 적었다.

```
브라우저 ──질문──▶ ① 로그인 확인 ─▶ ② 입력 검사 ─▶ ③ 사용량 확인(DB 1회)
                                                           │
   ◀──답+작품카드── ⑦ 대화 저장 ◀─ ⑥ AI 답변 작성 ◀─ ⑤ 작품 검색 ◀─ ④ AI 의도 추출
```

| 단계 | 하는 일 | 코드 |
|---|---|---|
| ① 로그인 확인 | 쿠키나 `Authorization: Bearer` 토큰이 없으면 **401**. 비로그인 체험은 없다 | `current_session` (`app/main.py`) |
| ② 입력 검사 | 빈 질문, 500자 초과, 악성 패턴(프롬프트 주입 등) 차단 | `CHAT_MAX_LENGTH` (`app/config.py`), `guardian.looks_malicious` |
| ③ 사용량 확인 | AI 쉬는 중인지 / 시간당 질문 수 / 평생 무료 횟수 / 최근 대화 5개를 **DB 왕복 한 번**으로 읽는다 | `db.execute_many` (`app/db.py`) |
| ④ 의도 추출 | AI가 질문을 검색 조건(JSON)으로 바꾼다: 잡담 여부, 영어 키워드, 작가, 연도, 가로/세로/정사각, 용도 | `chat.extract_intent` |
| ⑤ 작품 검색 | 작품 DB에서 찾는다. 작가·연도 조건 때문에 0개면 키워드만으로 다시 찾는다(완화) | `chat.find_artworks`, `art.search` |
| ⑥ 답변 작성 | AI에게 **찾은 작품 목록만** 주고 [1], [2] 번호로 설명하게 한다. 한국어 + English | `chat.compose_answer` |
| ⑦ 저장 | 질문·답·작품 번호·걸린 시간을 `chats` 테이블에 저장 | `_save_chat` |

## 왜 AI를 두 번 부르나

한 번에 "그림 추천해 줘"라고 시키면 AI가 **없는 작품을 지어낼 수 있다**.
그래서 AI는 ④ 검색 조건 만들기와 ⑥ 실제로 찾은 것 설명하기만 하고, 작품 자체는 항상 DB에서 나온다.
자세히: [AI 호출](ai-llm.md), [작품 검색](search.md).

## 실패하면

| 상황 | 응답 |
|---|---|
| 로그인 안 함 | 401 `UNAUTHENTICATED` |
| 시간당 30회 초과 (`CHAT_LIMIT_PER_HOUR`) | 429 `RATE_LIMITED` |
| 무료 100회 소진 (`CHAT_LIFETIME_LIMIT_FREE`) | 403 `FREE_LIMIT_REACHED` |
| AI 시간 초과/한도 초과 | `AI_TIMEOUT` / `AI_RATE_LIMITED` 등 (`app/llm.py`) |
| 사용자 DB 장애 | 503 `DB_ERROR` |

AI 실패는 [가디언](guardian.md)이 사건으로 기록한다.

## 응답에 함께 오는 것

`search`(검색 조건)를 같이 돌려줘서, 화면의 **더 보기** 버튼이 AI 없이 `GET /api/artworks`로 다음 페이지를 가져온다.
완화 검색이었다면 작가·연도를 비운 조건을 돌려준다.
