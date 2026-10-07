---
title: 가디언 (장애·보안 감시)
sources: [app/guardian.py, vercel.json, CONTRIBUTING.md]
updated: 2026-10-07
---
# 가디언

장애와 보안 위협을 함께 지키는 모듈 (`app/guardian.py`). **두 단계**로 나뉜다.

## 1) 즉시 대응 — 매 요청, 규칙만 (AI 안 씀)

| 규칙 | 함수 |
|---|---|
| 의심 입력 차단 (`<script`, `union select`, `; drop table` 등) | `looks_malicious` |
| IP별 횟수 제한 | `check_rate` |
| 로그인 5회 실패 → 15분 잠금 | `note_login_failure`, `check_login_lockout` |
| AI 429가 5분에 3번 → **5분간 AI 호출 쉬기** | `note_ai_failure`, `is_ai_backed_off` |
| 사건 기록 | `record_incident` → `incidents` 테이블 |

**왜 요청마다 AI를 안 부르나**: 그러면 공격자가 실패 요청을 반복해서 **AI 비용 자체를 공격 수단**으로 쓸 수 있다.

## 2) 하루 한 번 분석 — AI 사용

- Vercel Cron이 매일 23:00 UTC(한국 08:00)에 `/api/guardian/daily-digest`를 부른다 (`vercel.json`).
- 분석 안 된 사건 최대 200개를 gpt-6-astra가 요약·패턴·예측·권장 조치로 정리한다 (`run_daily_digest`).
- 긴급도가 medium/high면 **GitHub 이슈**를 연다.

## 의도적인 선 긋기

AI는 **진단(글)**만 하고 코드를 고치거나 실행하지 않는다. 자동으로 바꾸는 건 되돌리기 쉬운 상태값(잠금·쉬기)뿐이다.
근거로 든 논문(CACM, "Toward Agentic Runtime Healing")의 결론이 파일 머리 주석에 정리돼 있다.

새 기능을 넣을 때도 "규칙은 즉시, AI 분석은 배치" 패턴을 따른다 (`CONTRIBUTING.md`).
