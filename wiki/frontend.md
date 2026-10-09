---
title: 화면 (웹·PWA·온디바이스·캐시)
sources: [app/static/index.html, app/static/app.js, app/static/style.css, app/static/sw.js, app/static/manifest.json, app/static/offline.html, app/static/ondevice.js, app/static/icons/favicon.svg, app/main.py]
updated: 2026-10-09
---
# 화면

프레임워크·빌드 도구 없이 HTML·CSS·JavaScript 세 파일로 만들었다 (`app/static/`). 서버가 `/`에서 `index.html`을 준다.
빌드 단계가 없어서 `app/main.py`의 캐시 무효화(아래)가 파일 내용만 보고 동작할 수 있다.

## 화면 구성

| 화면 | 내용 | 코드 |
|---|---|---|
| 상단 바 | 로고 · 대화 기록 · 즐겨찾기 · 온디바이스 · 이메일/로그아웃 · KO/EN · 테마. 아래로 스크롤하면 접힌다 | `index.html` `.topbar`, `app.js` 11절 `onPageScroll` |
| 랜딩(로그인 전) | 소개 문구, 로그인/회원가입 탭(초대코드는 가입 탭에만), **컬렉션 미리보기**(주제 칩), 푸터 | `app.js` 4·5절 |
| 대화(로그인 후) | 예시 질문 4개, 질문 → AI 답변 + 작품 카드. 질문 하나가 한 **턴**이고, 새 턴은 화면 맨 위로 올라간다 | `app.js` 8절 `startTurn` |
| 작품 카드 | 이미지(메이슨리 배치), 번호, 가로형/세로형 태그, ♡·다운로드. 누르면 **작품 상세 창** | `makeCard`, `openArtwork` |
| 결과 묶음 | 제목·개수, 비율 탭, **작품 더 보기** | `buildResultGroup`, `moreButton` |
| 대화 기록 | 넓은 화면(1180px 이상)은 왼쪽 사이드바, 좁은 화면은 오른쪽 서랍. `GET /api/me/chats` | `app.js` 9절 `loadHistoryInto` |
| 즐겨찾기 | 오른쪽 서랍. `GET /api/me/favorites` | `openFavorites` |

질문은 **스트리밍**으로 받는다 (`POST /api/chat/stream`, 한 줄에 이벤트 하나인 NDJSON — `readNdjson`).
검색이 끝나면 `meta`로 작품 카드부터 그리고, 답변 글은 `delta`가 올 때마다 이어 붙인다. 스트리밍을 못 쓰면 `/api/chat`으로 한 번에 받는다 (`receiveStream` → `receiveOnce`).
AI 답변의 `[1]`, `[2]`는 버튼이 되어, 누르면 같은 번호의 카드로 이동해 강조한다 (`richText`).
오류가 일시적이면(`AI_TIMEOUT` 등) 안내 상자에 **다시 시도** 버튼이 붙는다 (`ERRORS`의 `retry`, `addNotice`).

## 코드 구조 (`app.js`)

파일 맨 위 목차와 같은 12개 절로 나뉜다. 핵심 원칙:
- 모든 서버 호출은 `api()` 한 곳을 지난다. 네트워크 오류도 서버 오류와 같은 모양(`{ error: { code } }`)으로 돌려준다.
- 화면 상태는 `state` 객체 하나에 모은다 (로그인 여부, 언어, 즐겨찾기, 전송 중 여부 등).
- 사용자·AI 텍스트는 항상 `textContent`로 넣는다 (`el()`). `innerHTML`은 파일에 적힌 고정 문구에만 쓴다 → XSS 방지.
- 숫자 설정값(페이지 크기, 스크롤 시간 등)은 맨 위 상수로 모은다.

## 다국어 (한국어/영어)

화면 문구는 한 언어로만 보여주고 상단 KO/EN 버튼으로 바꾼다 (`I18N`, `t()`).
HTML은 `data-i18n` 속성으로, 동적으로 그린 글자는 `bindText()`로 문구 키를 요소에 적어 둔다 → 언어를 바꾸면 `applyI18n()`이 화면 전체를 다시 채운다.
서버 오류 문구는 오류 코드로 고른다 (`ERRORS`). AI 답변은 한국어 뒤에 `English:`가 오는데, 고른 언어를 본문으로 보여주고 다른 언어는 접어 둔다 ([AI 호출](ai-llm.md)).

## 디자인 (`style.css`)

- 색·글꼴·크기는 맨 위 **디자인 토큰**(`--bg`, `--accent` 등)으로만 쓴다.
- 다크 모드는 `light-dark(밝은 값, 어두운 값)`로 색을 한 번만 적는다. 기본은 시스템 설정, 테마 버튼을 누르면 `data-theme`으로 고정하고 `localStorage`에 기억한다.
- 비율 필터는 CSS가 숨긴다: `.result-group[data-filter] .card[data-orient]`.
- 파비콘·앱 아이콘은 상단 로고와 같은 미술관 마크다 (`icons/favicon.svg`, `icons/icon-*.png`).

## 앱으로 설치 (PWA)

`manifest.json` + 서비스워커(`sw.js`)로 휴대폰 홈 화면에 앱처럼 설치할 수 있다. 인터넷이 끊기면 `offline.html`을 보여준다.
설치 아이콘·오프라인 화면의 색은 메인 화면과 같은 종이색·테라코타 톤이다 (`manifest.json`은 밝은 값만 적을 수 있어 밝은 색을 쓰고, `offline.html`은 `style.css`를 못 받을 때를 대비해 색을 직접 적되 다크 모드를 따른다).
`/api/*`는 서비스워커가 건드리지 않는다 (로그인·대화는 항상 최신이어야 하니까).

## 캐시 무효화

**문제**: 서비스워커가 `app.js`를 캐시에 넣어 두면, 배포해도 사용자는 옛 화면을 계속 볼 수 있다.
**해결** (`app/main.py`): 서버가 켜질 때 화면 파일 내용으로 **해시(10자리)**를 만들어
- `index.html` 안의 `/static/app.js` → `/static/app.js?v=해시`
- `sw.js`의 캐시 이름 `__ASSET_VERSION__` → 해시
로 바꿔서 준다. 파일이 바뀌면 주소와 캐시 이름이 바뀌어 새 파일을 받는다. `index.html`과 `sw.js`는 `Cache-Control: no-cache`.

**개발 중 주의**: 해시는 서버가 켜질 때 한 번만 만든다. `--reload`는 `.py` 변경만 감지하므로, 화면 파일을 고친 뒤에는 **서버를 재시작**해야 새 해시가 붙는다.
재시작하지 않으면 같은 주소로 서비스워커 캐시의 옛 `app.js`가 나온다.

## 온디바이스 추천 (`ondevice.js`)

서버·AI 없이 브라우저에서 찾는 기능 (상단 "온디바이스" 버튼 → 창). `artworks.json`(작품 사실 데이터, 약 2MB)을 받아 **Datalog 스타일 규칙**으로 거른다:
```
candidate(W) :- style(W,"Impressionism"), subject(W,"landscape"), year(W,Y), Y>=1860, Y<=1900.
```
같은 머리의 규칙이 여러 줄이면 OR(합집합). `artworks.json`은 `scripts/export_artworks_json.py`로 만든다.
창을 실제로 열 때만 받는다 (모든 방문자가 2MB를 받지 않게).
