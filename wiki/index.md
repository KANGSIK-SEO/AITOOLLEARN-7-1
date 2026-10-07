# 위키 목차

명화 챗봇(AITOOLLEARN-7-1)의 LLM 위키. **처음이면 [프로젝트 한눈에 보기](overview.md)부터.**
운영 규칙은 [AGENTS.md](AGENTS.md), 작업 기록은 [log.md](log.md).

## 시작
- [프로젝트 한눈에 보기](overview.md) — 무엇을, 누구를 위해, 작품 몇 점, 어떤 기술
- [질문 하나가 답이 되기까지](request-flow.md) — `/api/chat` 7단계

## 기능별
- [AI 호출](ai-llm.md) — gpt-6-astra/solar-pro4, 의도 추출·답변 프롬프트, 시간 제한
- [작품 검색](search.md) — FTS5, 다양화, 더 보기, 가로/세로 판별
- [권리 판단](rights.md) — 허용 기관, R1~R6
- [권리 근거 기록](records.md) — 스냅숏, 서명, Wayback 보관
- [데이터베이스](database.md) — 작품 DB vs 사용자 DB, 테이블, Turso 왕복 묶기
- [로그인과 보안](auth.md) — scrypt, 토큰, 잠금, 초대코드
- [가디언](guardian.md) — 즉시 규칙 + 하루 한 번 AI 분석
- [화면](frontend.md) — 카드, PWA, 캐시 무효화, 온디바이스 Datalog
- [설명 에이전트](explain-agent.md) — 평가용 `/explain`
- [삼성 TV 앱](tv-app.md) — Tizen, Bearer 토큰

## 운영
- [작품 수집](data-collection.md) — MET·AIC·CMA 스크립트, GitHub Actions
- [배포와 CI](deploy-ci.md) — main → Vercel, 워크플로 3개, Docker
- [테스트와 품질 평가](testing-eval.md) — pytest 272개, AI 평가 20문항

## 팀·배경
- [팀과 작업 방식](team-process.md) — 팀원, 브랜치, merge commit
- [주요 결정과 그 이유](decisions.md) — 날짜별 결정 기록
- [용어 사전](glossary.md) — CC0, FTS5, HMAC 등
- [평가 예상 질문과 답](evaluation-faq.md)
