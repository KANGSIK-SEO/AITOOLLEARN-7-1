---
title: 삼성 TV 앱 (Tizen)
sources: [tv-app/README.md, tv-app/js/api.js, app/main.py]
updated: 2026-10-07
---
# 삼성 TV 앱

`tv-app/`은 삼성 스마트TV(더 프레임 포함)의 **Smart Hub**에서 실행되는 Tizen 웹앱이다.
같은 서버(`https://art-chatbot-eight.vercel.app`)를 그대로 부른다.

- 리모컨 방향키로 움직이는 화면 (`tv-app/js/focus.js`, `keys.js`), 로그인·채팅 화면 (`js/screens/`).
- TV 앱은 서버와 주소(오리진)가 달라 쿠키를 못 쓰므로, 로그인 응답의 `token`을 받아 `Authorization: Bearer`로 보낸다 → 서버의 `current_session`이 둘 다 받는다 ([로그인과 보안](auth.md)).
- **더 프레임의 "아트 모드"(꺼져 있을 때 배경 그림)에는 못 들어간다.** 삼성과 계약한 아트스토어 업체만 가능하다.
- 빌드·설치는 Tizen Studio와 삼성 인증서가 필요하다 (`tv-app/README.md`).
