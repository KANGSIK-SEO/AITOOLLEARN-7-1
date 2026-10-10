---
title: 프로젝트 한눈에 보기
sources: [README.md, docs/rights-policy.md, app/config.py, data/art.db]
updated: 2026-10-07
---
# 프로젝트 한눈에 보기

**저작권 걱정 없이 상업적으로 쓸 수 있는 명화(CC0)를 찾아 주는 AI 챗봇**이다.
사이트: https://art-chatbot-eight.vercel.app (`main` 브랜치에서 자동 배포, [배포와 CI](deploy-ci.md))

## 누구를 위한 서비스인가

카페 포스터, 교재 삽화, PPT 배경, 인스타그램 게시물처럼 **그림을 써야 하는데 저작권이 걱정되는 사람**.
"명화 추천"이 아니라 **"용도에 맞는, 써도 되는 그림 찾기 + 근거 보관"**이 핵심이다 (`docs/rights-policy.md`).

## 무엇을 할 수 있나

| 기능 | 설명 | 자세히 |
|---|---|---|
| 회원가입·로그인 | 이메일+비밀번호. **챗봇은 로그인한 사람만** 쓸 수 있다 | [로그인과 보안](auth.md) |
| 챗봇 질문 | "카페 벽에 걸 세로형 포스터" → 조건에 맞는 작품 카드 + 설명 | [질문 처리 흐름](request-flow.md) |
| 더 보기 | AI를 다시 부르지 않고 같은 조건으로 작품을 더 본다 | [작품 검색](search.md) |
| 작품 카드 | 출처 표기 복사, 원본 다운로드, 즐겨찾기 | [화면](frontend.md) |
| 권리 근거 기록 | 그 시점 기관이 공개한 권리 정보를 저장하고 인터넷 아카이브에 보관 | [권리 근거 기록](records.md) |
| 내 대화 기록 | 이전 질문과 답 다시 보기 | [데이터베이스](database.md) |

## 작품은 어디서 오나

미국 미술관 3곳이 **작품 하나하나에 CC0라고 밝힌 것만** 모은다 (`data/art.db`, 2026-10-07 기준).

| 기관 | 코드 | 작품 수 |
|---|---|---|
| The Metropolitan Museum of Art | `met` | 30,589 |
| Art Institute of Chicago | `aic` | 30,271 |
| Cleveland Museum of Art | `cma` | 17,764 |
| **합계** | | **78,624** |

수집 방법은 [작품 수집](data-collection.md), 어떤 작품을 넣고 빼는지는 [권리 판단](rights.md).

## 기술 한 줄 요약

- 서버: Python **FastAPI** (`app/main.py`) → **Vercel** 서버리스 함수 (`index.py`, `vercel.json`)
- 작품 DB: 읽기 전용 **SQLite + FTS5 전문 검색** (`data/art.db`)
- 사용자 DB: **Neon PostgreSQL**(2026-10-11부터, 그 전엔 Turso), 로컬에서는 SQLite 파일 (`app/db.py`)
- AI: OpenAI **gpt-6-astra**, 장애 시 Upstage **solar-pro4** (`app/llm.py`) → [AI 호출](ai-llm.md)

## 팀

서강식(`KANGSIK-SEO`), 오철호(`chul5`), 유영민(`maebsy`) → [팀 작업 방식](team-process.md)
