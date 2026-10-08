---
title: 가디언 (장애·보안 감시)
sources: [app/guardian.py, app/main.py, vercel.json, .github/workflows/monitor.yml, .github/workflows/autofix.yml, .github/workflows/autofix-ship.yml, scripts/autofix_guard.py, scripts/autofix_propose.py, CONTRIBUTING.md]
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
| 고객이 겪는 오류 첫 발생(AI 응답 실패·DB·서버 오류), 장애 5분에 10건, 심각(high) 사건 | **즉시 AI 진단 + GitHub 이슈** (같은 종류 1분에 한 번, 다른 문제는 간격 없이 바로, 횟수 제한 없음) |
| 규칙에 없는 수상한 접속 (대량 요청, 계정 돌려 막기, 번호 바꿔 보기 등) | 1분마다 Claude Haiku가 새 접속 기록을 읽고 판단 → `AI_SUSPICIOUS_TRAFFIC` 사건, 10분 안 두 번이면 IP 1시간 차단, 심각하면 즉시 이슈 |
| 서버가 통째로 안 뜸 | `monitor.yml`이 **1분마다** 확인(5분마다 시작해 안에서 1분 간격 5번) → `outage` 이슈, 회복되면 닫음 |

- **AI는 한 번의 판단으로 막지 않는다.** 접속 기록에는 공격자가 쓴 글(경로·user_agent)이 섞이므로, 기록에 실제로 있는 IP만 받아들이고 두 번 걸려야 차단한다.
- **모델 역할**: 챗봇 답변·진단·접속 감시는 가장 저렴한 `claude-haiku-5-5`, 코드 수정안은 `claude-fable-5-1`.
- 차단은 시간이 지나면 저절로 풀린다. 회사처럼 여러 사람이 IP 하나를 쓰면 같이 막힐 수 있어서 1시간으로 짧게 잡았다.
- 차단 목록은 서버마다 30초씩 기억해서, 요청마다 DB를 읽지 않는다 (`BLOCK_CACHE_SECONDS`).
- 즉시 분석은 응답을 보낸 뒤에 돌아서 사용자를 기다리게 하지 않는다 (`app/main.py` 미들웨어).
- AI가 장애 원인일 수도 있어서, AI 진단이 실패해도 사건 종류별 건수로 이슈를 연다.
- IP는 Vercel이 직접 채우는 헤더(`x-vercel-forwarded-for`)를 먼저 본다. 사용자가 꾸민 헤더로 남의 IP를 차단시키지 못하게 하기 위해서다.

## 0-1) 스스로 배우기와 자동 수정 (승인 한 번)

```
공격·장애 ─▶ 가디언: 즉시 차단 + 이슈 ─▶ autofix.yml: Claude가 수정안·테스트 작성
                                              │ (비밀 값 없는 곳에서) 안전 검사 + 전체 테스트
                                              ▼
              휴대폰 알림 ◀─ PR (주인에게 리뷰 요청) ─▶ Approve
                                              ▼
              autofix-ship.yml: 다시 검사 → main 병합 → Vercel 배포 → /healthz 확인
                                              │ 이상하면 되돌리기 + 재배포
                                              ▼
                              결과를 '학습 기록' 이슈에 남김 → 다음 수정안이 참고
```

- **데이터로 배우기 (승인 없음)**: 없는 주소를 15번 찾은 스캐너는 차단되고, 그 IP가 찾던 주소는 30일 동안 공격 경로로 기억한다 (`learn_paths_from`). `/api/`, `/static/` 같은 진짜 경로는 배우지 않는다.
- **횟수 제한**: 하루 총횟수 제한 없음(organization 지원으로 비용 무관). 같은 문제는 10분에 한 번, 같은 문제의 수정 PR이 이미 열려 있으면 새로 만들지 않는다 — 같은 장애로 PR이 쏟아지는 것만 막는다. (`AUTOFIX_DAILY_MAX`, `AUTOFIX_SAME_PROBLEM_MINUTES`로 조정)
- **코드로 고치기 (승인 필요)**: AI는 파일 내용만 돌려주고, 허용된 파일과 새 테스트(`tests/test_autofix_*.py`)에만 써진다 (`scripts/autofix_propose.py`).
- **사람 대신 기계가 먼저 거르는 것** (`scripts/autofix_guard.py`): 보호 파일(인증·비밀 키·DB·배포·검사 규칙 자신), 외부 통신, 명령 실행, 환경변수 읽기, eval/exec, 삭제, 기존 테스트 수정, 400줄 넘는 변경, 새 테스트 없음.
- **왜 승인 한 번은 남겼나**: 로그에는 공격자가 쓴 글이 섞인다. AI가 속아도 마지막에 사람이 한 번 보게 하려는 것이다. 완전 자동은 이 작업 환경의 보안 장치도 막았다.
- 학습 기록 이슈에는 워크플로가 정해진 칸(날짜·이슈·결과·이유·파일)만 남기고, AI는 봇이 쓴 댓글만 읽는다.

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
