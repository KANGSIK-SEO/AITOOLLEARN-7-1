---
title: 가디언 (장애·보안 감시)
sources: [app/guardian.py, app/main.py, vercel.json, .github/workflows/monitor.yml, CONTRIBUTING.md]
updated: 2026-10-08
---
# 가디언

장애와 보안 위협을 함께 지키는 모듈 (`app/guardian.py`). 2026-10-08부터 **실시간 감시**가 더해졌다.

## 0) 실시간 감시 — 사건이 생기는 순간

| 무엇을 보면 | 바로 하는 일 |
|---|---|
| 공격 도구가 찾는 경로(`/.env`, `/wp-admin` 등) 3번 (10분 안) | 그 IP **1시간 차단** (모든 요청 403) |
| 악성 입력 3번 (10분 안) | 그 IP 1시간 차단 |
| 한 IP에서 로그인 실패 10번 (여러 계정 돌려 보기) | 그 IP 1시간 차단 |
| 장애 사건 5분에 10건, 또는 심각(high) 사건 | **즉시 AI 진단 + GitHub 이슈** (10분에 한 번) |
| 서버가 통째로 안 뜸 | `monitor.yml`이 5분마다 확인 → `outage` 이슈, 회복되면 닫음 |

- 차단은 시간이 지나면 저절로 풀린다. 회사처럼 여러 사람이 IP 하나를 쓰면 같이 막힐 수 있어서 1시간으로 짧게 잡았다.
- 차단 목록은 서버마다 30초씩 기억해서, 요청마다 DB를 읽지 않는다 (`BLOCK_CACHE_SECONDS`).
- 즉시 분석은 응답을 보낸 뒤에 돌아서 사용자를 기다리게 하지 않는다 (`app/main.py` 미들웨어).
- AI가 장애 원인일 수도 있어서, AI 진단이 실패해도 사건 종류별 건수로 이슈를 연다.
- IP는 Vercel이 직접 채우는 헤더(`x-vercel-forwarded-for`)를 먼저 본다. 사용자가 꾸민 헤더로 남의 IP를 차단시키지 못하게 하기 위해서다.

이하 두 단계는 원래 있던 구조다.

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
