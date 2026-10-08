# 위키 작업 기록

시간 순서로 맨 아래에 붙인다. 형식: `## [YYYY-MM-DD] 작업 | 내용` (작업 = ingest / query / lint)
`grep "^## \[" wiki/log.md | tail -5` 로 최근 작업을 볼 수 있다.

## [2026-10-07] ingest | 위키 첫 생성 — 코드·문서·PR 기록(#1~#54) 전체를 읽고 19개 페이지 작성
## [2026-10-08] ingest | 1분 감시(monitor.yml 1분 간격 5회), 진단 1분·자동 수정 10분 중복 방지, 하루 제한 해제 — guardian 갱신

## [2026-10-08] ingest | Claude Fable 연결(app/claude_llm.py)과 답변 스트리밍(/api/chat/stream) — ai-llm, request-flow 갱신
## [2026-10-08] ingest | 가디언 실시간 감시(IP 자동 차단, 즉시 분석, monitor.yml) — guardian 갱신
## [2026-10-08] ingest | 공격 주소 자동 학습, 가디언 자동 수정(autofix.yml·autofix-ship.yml, 승인 한 번) — guardian 갱신
## [2026-10-08] ingest | Claude 소진 시 solar-pro4가 바로 이어받도록 변경 — ai-llm 갱신
## [2026-10-08] ingest | 고객 오류 첫 발생 즉시 진단, 자동 수정 제한을 문제별 6시간·하루 8번으로 — guardian 갱신
## [2026-10-09] ingest | 프론트엔드 개편 반영 — frontend.md 다시 작성(화면 구성·코드 구조·다국어·테마), search.md 비율 필터 설명 수정
