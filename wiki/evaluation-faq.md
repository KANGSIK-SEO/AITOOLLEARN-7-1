---
title: 평가 예상 질문과 답
sources: [README.md, app/main.py, app/chat.py, app/auth.py, app/guardian.py, CONTRIBUTING.md, docs/rights-policy.md]
updated: 2026-10-07
---
# 평가 예상 질문과 답

답은 짧게, 근거는 링크한 위키 페이지와 코드에 있다.

## 동작 이해

**Q. 질문 하나가 답이 되는 순서는?**
로그인 확인 → 입력 검사 → 사용량 확인 → AI가 검색 조건 추출 → DB 검색 → AI가 찾은 작품만 설명 → 저장. → [질문 처리 흐름](request-flow.md)

**Q. AI를 왜 두 번 부르나? AI가 없는 작품을 지어내면?**
AI는 조건 만들기·설명만 하고 작품은 DB에서 나온다. 답변은 넘겨준 번호 [n]만 쓰게 하고, 평가 스크립트가 없는 번호 인용을 잡는다. → [AI 호출](ai-llm.md)

**Q. 동기(`def`)로 짠 이유는?**
기다리는 작업(AI·DB)은 FastAPI가 스레드풀에서 돌려 준다. 서버리스라 요청마다 실행 단위가 따로라 `async`의 이득이 작다.

## 요구사항

**Q. 로그인 안 한 사람도 챗봇을 쓸 수 있나?**
아니다. `POST /api/chat`은 `current_session`이 막아 401. 테스트 `test_chat_requires_login`. → [로그인과 보안](auth.md)

**Q. 배포는 어느 브랜치에서?**
`main`에 들어갈 때만 자동 배포. → [배포와 CI](deploy-ci.md)

**Q. PR이 10/7에 한꺼번에 main으로 들어간 이유는?**
처음엔 main에 첫 커밋만 있고 다른 브랜치에서 배포했다. 요구 흐름과 달라서 main 배포로 바꾸고 develop을 PR로 올렸다. → [주요 결정](decisions.md)

## 보안·비용

**Q. 비밀번호 저장 방식은?** scrypt 해시. → [로그인과 보안](auth.md)
**Q. API 키는 어디에?** `.env`(커밋 안 함), GitHub Secrets, Vercel 환경변수.
**Q. AI 비용 폭주는?** 시간당 30회, 무료 100회, 429 반복 시 5분 쉬기, 요청마다 AI 분석 안 함. → [가디언](guardian.md)

## 권리

**Q. 정말 상업적으로 써도 되나? 근거 기록에 법적 효력이 있나?**
보증이 아니다. 기관이 그날 CC0라고 공개한 기록 + 인터넷 아카이브 보관본이다. → [권리 근거 기록](records.md), [권리 판단](rights.md)

## 팀·과정

**Q. 역할 분담은?** → [팀과 작업 방식](team-process.md)
**Q. squash 대신 merge commit을 쓴 이유는?** 팀원별 커밋 기록 보존.
**Q. AI 도구를 얼마나 썼나?** Claude Code를 썼고 README에 범위를 공개했다. 판단·검토는 사람이 했다.
**Q. 가장 어려웠던 문제는?** Vercel 프로젝트 토큰의 404(→ 프로젝트 ID 배포), MET 403(→ 속도 조절), 캐시로 옛 화면(→ 해시), 느린 로그인(→ DB 왕복 묶기). → [주요 결정](decisions.md)
**Q. 품질은 어떻게 쟀나?** 테스트 272개 + AI 평가 20문항. → [테스트와 품질 평가](testing-eval.md)
