---
title: 배포와 CI (GitHub Actions → Vercel)
sources: [.github/workflows/deploy.yml, .github/workflows/collect-and-deploy.yml, .github/workflows/llm-eval.yml, vercel.json, index.py, Dockerfile, deploy/Dockerfile]
updated: 2026-10-07
---
# 배포와 CI

## 흐름

```
기능 브랜치 ─PR─▶ develop ─PR─▶ main ─(자동)─▶ deploy.yml ─▶ Vercel 운영 사이트
```

**운영 사이트는 `main`에 들어간 것만 배포된다** (`deploy.yml`의 `on: push: branches: [main]`).
처음에는 기능 브랜치에서 직접 배포했었는데, 요구사항 흐름과 달라서 2026-10-07에 바꿨다 (PR #51~#54) → [주요 결정](decisions.md).

## 워크플로 3개 (`.github/workflows/`)

| 파일 | 언제 | 하는 일 |
|---|---|---|
| `deploy.yml` | main에 push | Vercel 운영 배포 |
| `collect-and-deploy.yml` | 손으로 실행 | 작품 수집 → 테스트 → 커밋 → 배포 ([작품 수집](data-collection.md)) |
| `llm-eval.yml` | main에서 `app/chat.py`, `app/llm.py`, `scripts/eval_llm.py`가 바뀔 때 + 손으로 | AI 품질 평가. `GPT_ASTRA_API_KEY` 시크릿이 없으면 건너뛴다 ([테스트와 품질 평가](testing-eval.md)) |

## Vercel 배포 방식

- 필요한 시크릿: `VERCEL_TOKEN`, `VERCEL_SCOPE`(팀 이름). 저장소 Settings → Secrets and variables → Actions.
- 프로젝트 전용 토큰은 `vercel link`가 "User not found(404)"로 실패해서, **API로 프로젝트 ID를 조회해 바로 배포**한다
  (`VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`).
- `vercel.json`: 함수 최대 60초, 매일 가디언 점검 Cron ([가디언](guardian.md)). 함수 입구는 `index.py`.

## Docker (Ubuntu 24.04)

| 파일 | 용도 |
|---|---|
| `Dockerfile` | 누구 컴퓨터든 같은 환경(Ubuntu + Python)에서 앱 실행·테스트 |
| `deploy/Dockerfile` | Vercel CLI로 배포하는 환경 (Node.js) |

운영 서버(Vercel)는 Docker를 쓰지 않는다. Docker는 **팀원 간 실행 환경을 똑같이 맞추기 위한 것**이다.
