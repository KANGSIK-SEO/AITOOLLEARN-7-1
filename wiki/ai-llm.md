---
title: AI 호출 (의도 추출·답변·폴백)
sources: [app/llm.py, app/claude_llm.py, app/chat.py, app/config.py, CONTRIBUTING.md]
updated: 2026-10-08
---
# AI 호출

## 모델

| 상황 | 쓰는 순서 |
|---|---|
| `ANTHROPIC_API_KEY` 있음 | Claude `claude-haiku-5-5`(가장 저렴, 자동 코드 수정만 Fable) → (크레딧 소진·한도·인증·통신 문제) **Upstage `solar-pro4`** → (solar 키 없으면) OpenAI `gpt-6-astra` |
| Claude 키 없음 | OpenAI `gpt-6-astra` → (**429/401/403**, 한도 소진·키 문제) Upstage `solar-pro4` |

Anthropic은 크레딧을 다 쓰면 429가 아니라 400("credit balance is too low")을 준다. 이것도 소진으로 보고 solar로 넘긴다 (`claude_llm._credit_exhausted`).
OpenAI의 한도 소진은 429(`insufficient_quota`)로 와서 solar로 넘어간다. solar-pro4는 **2027-04-01부터 유료 전환** 예정이다.

Claude가 안전 규칙으로 답을 **거절**하면(`AI_REFUSED`) 다른 회사 모델로 우회하지 않는다. 대신 Claude 서버가 같은 회사의
다른 모델로 다시 시도하게 한다(`fallbacks="default"`, `app/claude_llm.py`).

### Claude 설정 (`app/claude_llm.py`)

- Fable은 생각(thinking)이 항상 켜져 있고 끌 수 없다. 깊이는 `CLAUDE_EFFORT`(기본 `low`)로 정한다 — 검색어 뽑기와 짧은 설명에는 `low`면 충분하고 빠르다.
- 검색 조건 뽑기는 **structured outputs**(JSON 스키마 `chat.INTENT_SCHEMA`)로 받아 형식이 깨지지 않는다.
- 검색 조건 뽑기만 더 빠르고 싼 모델로 돌리려면 `CLAUDE_INTENT_MODEL=claude-haiku-5-5`.
- 비용: Fable 5.1은 입력 100만 토큰당 $10, 출력 $50로 가장 비싼 모델이다. Haiku 5.5는 $0.10 / $0.50.

`reasoning_effort`는 기본 `low` (`LLM_REASONING_EFFORT`). 올리면 비용이 늘어서 함부로 바꾸지 않는다 (`CONTRIBUTING.md`).
solar-pro4는 2026-10 기준 무료지만 **2027-04-01부터 유료 전환** 공지가 있다 (`app/config.py` 주석).

## 시간 제한과 재시도 (`app/llm.py`)

- **사용량 절감**: effort `low` + 검색 조건·접속 감시는 생각 끔, 긴 지시문 캐시, 같은 질문 검색 조건 하루 기억, 접속 감시는 규칙으로 먼저 거름, 자동 수정은 Haiku 사전 확인 + 코드 1시간 캐시. 목적별 토큰은 `ai_usage` 표 → `/api/guardian/summary` → 매일 품질 점검.
- **모든 타임아웃은 25초** (`TIMEOUT_SECONDS`): AI(Claude·GPT·solar), Turso, 이미지, 인터넷 아카이브, GitHub 모두 같다.
- **요청 하나도 25초가 상한**: 미들웨어가 요청마다 마감 시각을 걸고(`reqctx.start_deadline`), AI를 두 번 불러도 남은 시간만큼만 기다린다. 남은 시간이 2초 미만이면 새로 부르지 않는다.
- 넘으면 오류 코드 `AI_TIMEOUT`(DB는 `BUSY`)과 **"죄송합니다. 접속자가 많습니다. 잠시 후 다시 시도해 주세요."** 화면도 30초 동안 아무 응답이 없으면 같은 안내를 띄운다(Vercel 504 포함).
- 5xx·연결 오류는 GPT·solar에서만 같은 곳에 **1번** 더 보낸다 (`LLM_MAX_RETRIES`). Claude SDK 자체 재시도는 껐다(시간이 두 배가 되므로) — 대신 다른 AI로 넘어간다. 시간 초과는 다시 보내지 않는다.
- 응답을 보낸 뒤의 일(가디언 진단, 접속 기록)은 사용자가 기다리지 않으므로 요청 마감에 묶지 않는다 (각 호출 25초 상한은 그대로).

## 두 번의 호출 (`app/chat.py`)

### 1) 의도 추출 `extract_intent` (최대 200토큰)
질문을 JSON으로 바꾼다: `chitchat`, `keywords`(영어, 최대 6개), `artist`, `year_from`, `year_to`, `orientation`(landscape/portrait/square), `purpose`(60자 이하).
AI가 이상한 값을 주면 `_parse_intent`가 걸러낸다 (예: 키워드가 문자열이 아니면 버림).

### 2) 답변 작성 `compose_answer` (최대 900토큰)
- 찾은 작품 중 최대 **6개**만 AI에게 넘긴다 (`ANSWER_NARRATION_LIMIT`, 토큰 비용 보호).
- 프롬프트 규칙: 넘겨준 작품만 [번호]로 언급, 한국어 뒤에 `English:` 요약, 용도에 맞는 이유 설명,
  상업 이용 전 **"근거 기록"** 발급 안내, **"보증·인증"이라는 말 금지** ([권리 근거 기록](records.md) 참고).
- 완화 검색이었으면 "조건을 빼고 찾았다"를 먼저 알린다.

## 스트리밍 (2026-10-08)

웹 화면은 `POST /api/chat/stream`을 쓴다. 검색이 끝나자마자 작품 카드를 먼저 보내고(`meta`), 답변 글은 만들어지는 대로 조각조각 보낸다(`delta`).
GPT 경로는 스트리밍이 없어 완성된 답을 한 조각으로 보낸다. 자세히: [질문 처리 흐름](request-flow.md).

## 품질은 어떻게 재나

`scripts/eval_llm.py`가 질문 20개로 의도 추출 정확도와 답변 규칙 준수율을 잰다 → [테스트와 품질 평가](testing-eval.md).
