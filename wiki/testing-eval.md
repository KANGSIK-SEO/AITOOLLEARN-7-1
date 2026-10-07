---
title: 테스트와 AI 품질 평가
sources: [tests/test_api.py, tests/test_rights.py, tests/test_db.py, tests/test_cache_busting.py, scripts/eval_llm.py, docs/llm-eval.md, .github/workflows/llm-eval.yml]
updated: 2026-10-07
---
# 테스트와 AI 품질 평가

## 자동 테스트 (`tests/`)

실행: `python -m pytest -q tests` → **272개 통과** (2026-10-07). AI는 가짜 함수로 바꿔서 돈이 들지 않는다.

| 파일 | 무엇을 확인하나 |
|---|---|
| `test_api.py` | 가입·로그인, **비로그인 채팅 401**, 사용량 제한, DB 장애 시 503 |
| `test_rights.py` | 권리 규칙 R1~R6, 보류 기관 차단, 근거 기록 발급·스냅숏 유지·변조 감지 |
| `test_chat.py`, `test_llm.py` | 의도 추출 파싱, 재시도·폴백·시간 초과 |
| `test_db.py` | Turso 느린 쿼리 기록, **테이블 준비가 요청 1번인지** |
| `test_cache_busting.py` | 화면 파일 주소에 `?v=해시`가 붙는지 |
| `test_guardian*.py` | 로그인 잠금, AI 쉬기, 의심 입력 |
| `test_eval_llm.py` | 품질 채점기 자체 |

## AI 품질 평가 (`scripts/eval_llm.py`, 자세히 `docs/llm-eval.md`)

질문 **20개**(용도·비율·작가·잡담·영어)로 실제 AI를 돌려 자동 채점한다.

| 단계 | 채점 항목 |
|---|---|
| 의도 추출 | 잡담 구분, 비율, 용도, 키워드, 작가 → **정확도 %** |
| 답변 | 근거성(없는 번호 인용 금지), 한/영 병기, 금지어(보증·인증), 근거 기록 안내, 완화 안내 → **준수율 %** |

- `--dry-run`: 가짜 AI로 채점기만 점검 (비용 0).
- 결과는 `data/eval/llm-eval-<시각>.json`. 프롬프트를 바꿀 때마다 돌려서 비교한다.
- **아직 실제 점수는 없다** — GitHub에 `GPT_ASTRA_API_KEY` 시크릿을 넣고 llm-eval을 실행해야 한다 (2026-10-07 기준).
