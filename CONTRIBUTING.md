# 기여 가이드

이 저장소는 **`KANGSIK-SEO/AITOOLLEARN-7-1`** 하나만 사용합니다. 모든 PR은 이 저장소의 `develop` 브랜치로 보냅니다.
(기본 브랜치가 `develop`입니다. 유지관리자: 서강식 — 리뷰 후 머지)

## 작업 흐름
1. 초대를 수락한 뒤 clone: `git clone https://github.com/KANGSIK-SEO/AITOOLLEARN-7-1.git`
2. `develop`에서 기능 브랜치 생성: `git checkout develop && git pull && git checkout -b feature/<이름>-<주제>`
   (버그 수정은 `fix/...`, 문서는 `docs/...`)
3. 작은 단위로 커밋 (팀원별 **유의미한 커밋 10회 이상**이 과제 조건입니다). 커밋 메시지는 `feat:`, `fix:`, `docs:`, `test:` 로 시작.
4. `git push -u origin <브랜치>` 후 GitHub에서 PR 생성 — **base가 `develop`인지 확인**.
5. 유지관리자가 리뷰하고 머지합니다. `develop`/`main`에 직접 push하지 않습니다.
   **머지 방식은 반드시 "Create a merge commit"입니다. "Squash and merge"는 쓰지 않습니다** — squash는 PR 안의 커밋 여러 개를 1개로 합쳐버려서, 팀원별 "유의미한 커밋 10회 이상" 요건이 develop 이력에서 사라집니다.

## 로컬 실행·테스트
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env      # GPT_ASTRA_API_KEY, SECRET_KEY 채우기 (TURSO_*는 비워두면 로컬 SQLite 사용)
.venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m pytest -q tests
```
- PR을 올리기 전에 테스트가 통과해야 합니다. 새 기능에는 테스트를 함께 추가해 주세요.
- **비밀 값(`.env`, API 키, 토큰)은 절대 커밋하지 않습니다.** 실수로 올렸다면 즉시 유지관리자에게 알리고 키를 폐기하세요.
- AI 모델은 OpenAI `gpt-6-astra`가 주 모델입니다 (`app/config.py`, `GPT_ASTRA_API_KEY`, 실제 과금됨). GPT 쪽이 429/401/403으로 실패할 때만 Upstage `solar-pro4`로 한 번 더 시도합니다(`UPSTAGE_API_KEY` 설정 시에만, `app/llm.py`). solar-pro4는 현재(2026-10) 무료·무제한이지만 **2027-04-01부터는 Upstage가 전 모델을 과금 전환**해 이 폴백도 끝난다 — 그 전에 유료 전환이 공지되면 다시 확인할 것. 다른 모델을 함부로 추가하거나 `reasoning_effort`를 올리지 마세요(비용 증가).
- `app/guardian.py`(가디언)가 장애·보안 사건을 `incidents` 테이블에 기록하고 1일 1회(Vercel Cron, `/api/guardian/daily-digest`) gpt-6-astra로 일괄 분석합니다. 요청마다 GPT를 부르지 않는 비용 보호 설계이므로, 새 엔드포인트에 대응 로직을 추가할 때도 이 패턴(결정적 규칙은 즉시, AI 분석은 배치)을 따라 주세요.
- 초대코드(프리미엄) 회원 로직은 `PREMIUM_CODE`/`app/auth.py`/`app/config.py`를 참고하세요. 일반 회원은 평생 무료 질문 수(`CHAT_LIFETIME_LIMIT_FREE`)가 있습니다.

## PR 작성 규칙
- 제목: `feat: 무엇을 왜` 한 줄. 본문: 변경 내용 / 확인 방법 / 스크린샷(화면 변경 시).
- PR 하나는 하나의 목적만 다룹니다 (개인당 3개 정도 권장).
- README의 "팀 구성원 역할 및 개인별 작업 요약" 표에 본인 작업을 실제 PR·커밋에 맞춰 적어 주세요.

## 개선 아이디어 (자유롭게 선택, 직접 찾은 불편이 있으면 그것을 우선)
- 답변이 "없다"고 하는데 관련 없는 작품 카드가 붙는 문제 (검색 관련도 필터)
- MET 데이터 추가 수집 (`scripts/collect_met.py`, 요청 속도 제한 주의)
- 모바일 화면·접근성, 로딩/오류 표시
- 내 이전 대화 목록 화면 (`GET /api/me/chats` 활용)
- 작품 저장/즐겨찾기, 라이선스·출처 표기 복사 버튼
- 검색 품질(동의어, 한국어 작가명 → 영문 변환), 테스트 보강
