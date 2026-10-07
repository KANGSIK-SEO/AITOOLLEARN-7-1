---
title: 설명 에이전트 (/explain)
sources: [app/explain.py, app/static/explain.html, app/main.py]
updated: 2026-10-07
---
# 설명 에이전트

평가 자리에서 동료가 프로젝트에 대해 물으면, **이 저장소의 코드를 근거로 AI가 대신 답하는 페이지**다 (`app/explain.py`).

- 주소: `/explain/{토큰}` → `explain.html`, 질문은 `POST /api/explain`
- `EXPLAIN_AGENT_SECRET` 환경변수로 보호한다. **비어 있으면 항상 401** (꺼진 상태). 평가가 끝나면 지워서 끈다.
- `CONTEXT_FILES`에 적힌 파일(README, schema, `app/*.py` 주요 파일, 화면 파일)을 통째로 AI에게 준다.
- 규칙: 코드에 근거해서만, 파일·함수 이름을 인용해서, 코드에 없으면 "명시돼 있지 않다"고 답한다.
- IP당 시간당 30회.

이 위키와 역할이 겹친다. 위키는 **사람과 LLM이 함께 쌓는 정리본**, 설명 에이전트는 **그때그때 코드를 읽어 답하는 창구**다.
