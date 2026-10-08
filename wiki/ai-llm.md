---
title: AI 호출 (의도 추출·답변·폴백)
sources: [app/llm.py, app/claude_llm.py, app/chat.py, app/config.py, CONTRIBUTING.md]
updated: 2026-10-08
---
# AI 호출

## 모델

| 순서 | 모델 | 언제 | 키 이름 |
|---|---|---|---|
| 1 | Claude `claude-fable-5-1` (`CLAUDE_MODEL`로 바꿀 수 있음) | `ANTHROPIC_API_KEY`가 있으면 항상 먼저 | `ANTHROPIC_API_KEY` |
| 2 | OpenAI `gpt-6-astra` | Claude 키가 없거나, Claude가 한도·인증·통신 문제로 실패할 때 | `GPT_ASTRA_API_KEY` |
| 3 | Upstage `solar-pro4` | GPT가 **429/401/403**(한도·키 문제)일 때만 | `UPSTAGE_API_KEY` (없으면 폴백 없음) |

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

- 한 번 요청 최대 **20초** (`LLM_TIMEOUT_SECONDS`)
- 재시도·폴백을 모두 합쳐 **25초** 안에서만 시도 (`LLM_CALL_BUDGET_SECONDS`)
- 5xx·연결 오류는 같은 곳에 **1번** 더 보낸다 (`LLM_MAX_RETRIES`). 시간 초과는 다시 보내지 않는다 — 이미 20초를 기다렸으니까.

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
