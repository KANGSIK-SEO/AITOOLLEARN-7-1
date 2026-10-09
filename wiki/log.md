# 위키 작업 기록

시간 순서로 맨 아래에 붙인다. 형식: `## [YYYY-MM-DD] 작업 | 내용` (작업 = ingest / query / lint)
`grep "^## \[" wiki/log.md | tail -5` 로 최근 작업을 볼 수 있다.

## [2026-10-09] ingest | 1분 감시를 cron-job.org 대신 monitor.yml 이어 달리기(5시간 50분 실행 + 자기 재실행)로, 비밀값 불일치 알림 — guardian 갱신

## [2026-10-09] ingest | 보안 헤더·CSP(화면 안 스크립트 제거), SECURITY.md, Dependabot, CodeQL, OpenSSF Scorecard, 인증 준비 문서 — guardian 참고

## [2026-10-07] ingest | 위키 첫 생성 — 코드·문서·PR 기록(#1~#54) 전체를 읽고 19개 페이지 작성
## [2026-10-08] ingest | GitHub 예약 실행 지연 확인 → 1분 점검은 cron-job.org가 /api/guardian/scan(GET) 호출, 챗봇 AI 답변 확인 추가 — guardian 갱신

## [2026-10-08] ingest | 해커 숨은 지시 방어(기계 검사 강화·AI 보안 검토·PR 글 정리·원본 patch) + 매시간 보안 동향 학습 — guardian 갱신

## [2026-10-08] ingest | Claude 사용량 절감(effort low·생각 끔·캐시·규칙 선별·Haiku 사전 확인·문제 열쇠) + 목적별 사용량 기록 — ai-llm 갱신

## [2026-10-08] ingest | 모든 타임아웃 25초 통일, 요청 25초 마감, 넘으면 '죄송합니다. 접속자가 많습니다.' — ai-llm 갱신

## [2026-10-08] ingest | 매일 품질 자동 점검(체크리스트 → 보고서·[품질] 자동 수정), 서버 용량 경보, 자동 수정 이슈별 동시 실행 — guardian 갱신

## [2026-10-08] ingest | 기본 모델 claude-haiku-5-5로(Fable은 자동 수정만), 1분마다 AI 접속 기록 감시 추가 — guardian·ai-llm 갱신

## [2026-10-08] ingest | 1분 감시(monitor.yml 1분 간격 5회), 진단 1분·자동 수정 10분 중복 방지, 하루 제한 해제 — guardian 갱신

## [2026-10-08] ingest | Claude Fable 연결(app/claude_llm.py)과 답변 스트리밍(/api/chat/stream) — ai-llm, request-flow 갱신
## [2026-10-08] ingest | 가디언 실시간 감시(IP 자동 차단, 즉시 분석, monitor.yml) — guardian 갱신
## [2026-10-08] ingest | 공격 주소 자동 학습, 가디언 자동 수정(autofix.yml·autofix-ship.yml, 승인 한 번) — guardian 갱신
## [2026-10-08] ingest | Claude 소진 시 solar-pro4가 바로 이어받도록 변경 — ai-llm 갱신
## [2026-10-08] ingest | 고객 오류 첫 발생 즉시 진단, 자동 수정 제한을 문제별 6시간·하루 8번으로 — guardian 갱신
## [2026-10-09] ingest | 프론트엔드 개편 반영 — frontend.md 다시 작성(화면 구성·코드 구조·다국어·테마), search.md 비율 필터 설명 수정
## [2026-10-09] ingest | 설치 색·오프라인 화면을 새 디자인 톤으로 맞춤, request-flow의 함수명 정정(receiveStream) — frontend·request-flow 갱신
