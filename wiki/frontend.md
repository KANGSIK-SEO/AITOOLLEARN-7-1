---
title: 화면 (웹·PWA·온디바이스·캐시)
sources: [app/static/index.html, app/static/app.js, app/static/style.css, app/static/sw.js, app/static/ondevice.js, app/main.py]
updated: 2026-10-07
---
# 화면

프레임워크 없이 HTML·CSS·JavaScript 세 파일로 만들었다 (`app/static/`). 서버가 `/`에서 `index.html`을 준다.

## 주요 부분

| 부분 | 내용 | 코드 |
|---|---|---|
| 로그인/가입 | 이메일·비밀번호, 초대코드(선택) | `index.html`, `app.js` |
| 예시 버튼 | "카페 벽에 걸 세로형 포스터" 등 4개 — 누르면 바로 질문 | `index.html`의 칩 |
| 작품 카드 | 이미지, 가로형/세로형 표시, **출처 표기 복사 · 다운로드 · 근거 기록 · ☆즐겨찾기** | `makeCard` (`app.js`) |
| 결과 묶음 | 비율 선택 상자 + **더 보기** | `addResultGroup` |
| 즐겨찾기 목록 | 머리말의 ★ 버튼 | `loadFavorites` |

## 앱으로 설치 (PWA)

`manifest.json` + 서비스워커(`sw.js`)로 휴대폰 홈 화면에 앱처럼 설치할 수 있다. 인터넷이 끊기면 `offline.html`을 보여준다.
`/api/*`는 서비스워커가 건드리지 않는다 (로그인·대화는 항상 최신이어야 하니까).

## 캐시 무효화 (2026-10-07)

**문제**: 서비스워커가 `app.js`를 캐시에 넣고 이름이 `v3`로 고정이라, 배포해도 사용자는 옛 화면을 계속 봤다.
**해결** (`app/main.py`): 서버가 켜질 때 화면 파일 내용으로 **해시(10자리)**를 만들어
- `index.html` 안의 `/static/app.js` → `/static/app.js?v=해시`
- `sw.js`의 캐시 이름 `__ASSET_VERSION__` → 해시
로 바꿔서 준다. 파일이 바뀌면 주소와 캐시 이름이 바뀌어 새 파일을 받는다. `index.html`과 `sw.js`는 `Cache-Control: no-cache`.

## 온디바이스 추천 (`ondevice.js`)

서버·AI 없이 브라우저에서 찾는 패널. `artworks.json`(작품 사실 데이터, 약 2MB)을 받아 **Datalog 스타일 규칙**으로 거른다:
```
candidate(W) :- style(W,"Impressionism"), subject(W,"landscape"), year(W,Y), Y>=1860, Y<=1900.
```
같은 머리의 규칙이 여러 줄이면 OR(합집합). `artworks.json`은 `scripts/export_artworks_json.py`로 만든다.
패널을 실제로 열 때만 받는다 (모든 방문자가 2MB를 받지 않게).

## 이중 언어

화면 문구는 대부분 "한국어 / English"로 함께 쓴다. AI 답변도 한국어 뒤에 `English:` 요약 ([AI 호출](ai-llm.md)).
