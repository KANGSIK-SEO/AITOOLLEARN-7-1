---
title: 로그인과 보안
sources: [app/auth.py, app/main.py, app/guardian.py, app/config.py, .gitignore]
updated: 2026-10-07
---
# 로그인과 보안

## 비밀번호 (`app/auth.py`)

- **scrypt**로 해시해서 저장한다 (`hash_password`, n=2^14). 원래 비밀번호는 DB 어디에도 없다.
- 비교는 `hmac.compare_digest`처럼 시간 차이로 정보가 새지 않는 방식을 쓴다 (`verify_password`).

## 로그인 상태 유지

- 로그인하면 **서명된 토큰**을 준다 (`make_token`): 사용자 번호 + 프리미엄 여부 + 만료 시각(**7일**, `TOKEN_TTL_SECONDS`)에 HMAC 서명.
- 서버가 세션을 저장하지 않는다. 서버리스라 요청마다 다른 서버가 받을 수 있어서, 서명만 확인하면 되게 했다.
- 브라우저는 `session` **쿠키**(HttpOnly)로, TV 앱은 `Authorization: Bearer` 헤더로 보낸다 ([TV 앱](tv-app.md)).

## 로그인한 사람만

챗봇 질문(`POST /api/chat`)과 내 기록·즐겨찾기는 `current_session`이 막는다. 없으면 401.
> 한때 "가입 없이 3회 체험"이 있었지만 미션 요구사항("챗봇 질문/응답은 로그인한 사용자만")과 어긋나서 뺐다 → [주요 결정](decisions.md)

## 무차별 대입·남용 막기 ([가디언](guardian.md))

| 상황 | 제한 |
|---|---|
| 같은 이메일로 로그인 실패 | 10분 안에 5번 → **15분 잠금** |
| 같은 IP 로그인 시도 | 10분에 20번 |
| 같은 IP 가입 | 1시간에 10번 |

## 초대코드(프리미엄)

가입할 때 `PREMIUM_CODE` 환경변수와 같은 코드를 넣으면 프리미엄: 시간당 300회, 작품 100개, 평생 횟수 제한 없음 (`app/config.py`).

## 비밀 값

API 키·토큰은 `.env`(커밋 안 함, `.gitignore`), GitHub Secrets, Vercel 환경변수에만 둔다. 이름 목록은 `.env.example`.
