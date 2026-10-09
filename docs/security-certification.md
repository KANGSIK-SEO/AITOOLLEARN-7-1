# 보안 인증 준비 (2026-10-09)

"보안 인증"은 세 단계로 나뉜다. **1단계는 코드로 자동으로 받고, 2단계는 저장소 주인이 설문만 쓰면 되고, 3단계는 사람·비용·심사가 필요하다.**

## 1단계 — 자동 보안 점수 (코드로 받음, 무료)

| 점수·배지 | 무엇을 보나 | 우리가 한 일 | 확인 주소 |
|---|---|---|---|
| **Mozilla HTTP Observatory** (A+ 목표) | 보안 헤더: CSP, HSTS, X-Frame-Options, nosniff, Referrer-Policy | `app/main.py` `SECURITY_HEADERS` — 모든 응답에. 화면 안 스크립트를 모두 파일로 빼서 CSP `script-src 'self'` (해커가 끼워 넣은 스크립트 실행 불가) | https://developer.mozilla.org/en-US/observatory/analyze?host=art-chatbot-eight.vercel.app |
| **securityheaders.com** (A 목표) | 같은 헤더 | 위와 같음 | https://securityheaders.com/?q=art-chatbot-eight.vercel.app&followRedirects=on |
| **SSL Labs** (A+ 목표) | https 암호 설정 | Vercel이 관리 (TLS 1.2+·자동 인증서), HSTS 2년 | https://www.ssllabs.com/ssltest/analyze.html?d=art-chatbot-eight.vercel.app |
| **OpenSSF Scorecard** (0~10점) | 저장소 보안 습관: 보안 정책, 의존성 자동 갱신, 위험한 워크플로, 토큰 권한, 정적 분석 | `SECURITY.md`, `.github/dependabot.yml`, `codeql.yml`, `scorecard.yml`, 워크플로 최소 권한 | https://scorecard.dev/viewer/?uri=github.com/KANGSIK-SEO/AITOOLLEARN-7-1 |
| **GitHub CodeQL** | 코드 속 취약 패턴(SQL 주입, XSS, 비밀 노출) | `.github/workflows/codeql.yml` (매주 + 모든 PR) | 저장소 Security → Code scanning |

## 2단계 — OpenSSF Best Practices 배지 (자가 인증, 무료, 저장소 주인이 약 1시간)

오픈소스 보안 재단의 공식 배지. 심사원 대신 질문에 답하고 근거 링크를 다는 방식이다.
1. https://www.bestpractices.dev 에서 **GitHub로 로그인** → "Get Your Badge Now" → 저장소 주소 입력
2. 아래 표를 보고 답한다 (대부분 Met)

| 질문 영역 | 답 | 근거 |
|---|---|---|
| 프로젝트 설명·사용법·기여 방법 | Met | README.md, CONTRIBUTING.md, wiki/ |
| 라이선스 | **주인 결정 필요** | 저장소에 LICENSE 파일이 없다 — MIT 등 하나를 고르면 Met |
| 변경 관리·버전 관리 | Met | Git, PR, develop→main 병합 커밋 |
| 버그·취약점 신고 절차 | Met | GitHub Issues, SECURITY.md(비공개 신고) |
| 자동 테스트·CI | Met | tests/ (400개), 모든 자동 수정에 전체 테스트 |
| 경고·정적 분석 | Met | CodeQL, actionlint |
| 보안 지식·안전한 설계 | Met | 비밀번호 scrypt, HMAC 쿠키, CSP, 가디언 (wiki/guardian.md) |
| 알려진 취약점 방치 금지 | Met | Dependabot, security-intel.yml(OSV 매시간) |
| 암호 사용 | Met | 표준 라이브러리 scrypt·HMAC-SHA256, 직접 만든 암호 없음 |

## 3단계 — 공식 인증 (사람·비용·심사 필요, 코드로는 받을 수 없음)

| 인증 | 누가 필요로 하나 | 비용·기간(대략) | 우리에게 필요한 시점 |
|---|---|---|---|
| **ISMS-P** (한국인터넷진흥원) | 매출·이용자 기준을 넘는 국내 서비스는 의무, B2B 영업에 신뢰 | 심사 수수료 수백만~수천만 원 + 컨설팅, 운영 증적 2개월 이상 + 심사 2~3개월 | 기업 교육 B2B로 고객 회사가 요구할 때 |
| **ISO/IEC 27001** | 해외·대기업 B2B 고객 | 인증기관 심사 수백만~수천만 원, 매년 사후 심사 | 해외·대기업 계약 때 |
| **SOC 2** | 미국 B2B SaaS 고객 | 미국 회계법인 감사 | 미국 시장 진출 때 |

### 공식 인증 전에 채워야 할 빈칸 (지금 서비스 기준)
- **개인정보 처리방침 페이지 없음** — 이메일을 받으므로 개인정보보호법상 공개 의무가 있다 (가장 먼저 필요)
- 라이선스 파일 없음 (오픈소스 배지에 필요)
- 관리자 계정(GitHub·Vercel·Turso·Anthropic) 2단계 인증(2FA) 확인 기록
- 백업·복구 절차 (Turso 백업 주기, 복구 연습 기록)
- 접근 권한 검토 기록 (누가 저장소·Vercel에 접근하는지 분기마다)
- 사고 대응 절차서 (가디언 경보 → 누가 무엇을 하는지, 고객 통지 기준)

### 이미 있는 통제 (심사 때 증적으로 쓸 것)
| 영역 | 우리 통제 | 증적 |
|---|---|---|
| 인증·접근 통제 | scrypt 비밀번호, HMAC 서명 쿠키(7일), 로그인 잠금, IP 차단 | app/auth.py, app/guardian.py, tests/ |
| 암호화 | https 전용(HSTS), 비밀 값은 Vercel·GitHub 비밀 저장소 | SECURITY_HEADERS, 설정 화면 |
| 로그·감시 | request_id 로그, incidents·access_log, 1분 외부 점검, AI 이상 탐지 | docs/logging.md, wiki/guardian.md |
| 취약점 관리 | CodeQL, Dependabot, OSV 매시간, 품질 점검 매일 | Actions 실행 기록 |
| 변경 관리 | PR·리뷰·테스트, AI 수정은 기계 검사 + AI 보안 검토 + 사람 승인, 실패 시 자동 되돌리기 | autofix*.yml, PR 기록 |
| 사고 대응 | 가디언 경보 이슈, 자동 진단, 학습 기록 | GitHub Issues (guardian, outage 라벨) |
