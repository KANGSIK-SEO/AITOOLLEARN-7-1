# 명화 챗봇 TV 앱 (Tizen)

더 프레임을 포함한 삼성 스마트TV의 **Smart Hub(일반 앱 런처)**에서 실행되는 Tizen 웹앱입니다. 기존 FastAPI 백엔드(`https://art-chatbot-eight.vercel.app`)를 그대로 호출합니다.

> **더 프레임의 "아트 모드"(꺼져 있을 때 자동 배경화면)에는 들어갈 수 없습니다.** 그건 삼성과 공식 파트너십을 맺은 아트스토어 제공사만 등록 가능한 폐쇄 마켓입니다. 이 앱은 사용자가 리모컨으로 직접 실행하는 일반 앱입니다.

## 사전 준비 (사용자가 직접 — GUI 작업)

1. [Tizen Studio](https://developer.tizen.org/development/tizen-studio/download) 설치, Package Manager에서 **TV Extension** 패키지 설치
2. Tizen Studio → Certificate Manager에서 삼성 계정으로 로그인해 **Samsung 인증 프로필** 생성 (아래 `<profile-name>`)
3. 이 폴더(`tv-app/`)를 Tizen Studio로 "Import Project"하면, `config.xml`의 `XXXXXXXXXX` 부분(패키지 ID)을 선택한 인증 프로필에 맞는 10자리 ID로 **자동 교체**해 줍니다. 수동으로 바꾸지 마세요.

## 빌드·설치 (Tizen CLI, Tizen Studio 설치 후)

```sh
# 1. 빌드
tizen build-web -- tv-app

# 2. 서명된 .wgt로 패키징
tizen package -t wgt -s <profile-name> -- tv-app/.buildResult

# 3. TV 웹 시뮬레이터 실행 (Tizen Studio > Tools > TV Simulator, 물리 TV 없이 PC에서 실행됨)

# 4. 시뮬레이터(또는 실제 TV, sdb connect <TV IP> 이후)에 설치
tizen install -t <target-name> --name <AppName>.wgt -- tv-app/.buildResult

# 5. 실행
tizen run -t <target-name> -p <packageId>.ArtChatbotTV
```

실제 TV에 설치하려면 TV를 "개발자 모드"로 전환하고 같은 네트워크에서 `sdb connect <TV IP주소>`로 연결한 뒤 4~5번을 반복합니다.

## 리모컨 조작

| 키 | 동작 |
|---|---|
| 방향키 | 포커스 이동 (입력창/버튼/작품 카드) |
| 확인(Enter) | 선택 — 입력창은 자동으로 TV 가상 키보드가 뜸 |
| 돌아가기(Back) | 상세 화면 닫기, 최상위 화면이면 앱 종료 |

## 인증 방식

기존 웹은 쿠키(`SameSite=Lax`)로 인증하는데, 이 쿠키는 다른 오리진인 TV 앱에는 구조적으로 전달되지 않습니다. 그래서 백엔드(`app/main.py`)에 **Bearer 토큰 경로를 추가**했습니다 — 로그인/회원가입 응답에 포함된 `token`을 `localStorage`에 저장하고, 이후 모든 요청에 `Authorization: Bearer <token>` 헤더로 보냅니다. 웹 쿠키 인증은 전혀 영향받지 않습니다.

## 알려진 제한 (v1)

- 이메일/비밀번호를 TV 가상 키보드로 직접 입력해야 합니다. QR코드로 휴대폰에서 로그인하는 방식(디바이스 코드 페어링)은 아직 없습니다 — 추가하려면 백엔드에 별도 엔드포인트가 필요합니다.
- 토큰은 로그인 후 7일간 유효합니다(백엔드 `TOKEN_TTL_SECONDS`와 동일).
