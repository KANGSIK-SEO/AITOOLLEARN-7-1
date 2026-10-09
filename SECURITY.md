# 보안 정책 (Security Policy)

## 취약점 신고 (Reporting a Vulnerability)
보안 문제를 발견하면 **공개 이슈로 올리지 말고** GitHub의 비공개 신고 기능을 써 주세요.
저장소 → **Security** 탭 → **Report a vulnerability** (Private vulnerability reporting).

- 3일 안에 받았다는 답을 드리고, 14일 안에 처리 계획을 알려 드립니다.
- 고친 뒤 신고자의 동의를 받아 공개하고 감사 인사를 남깁니다.

Please report vulnerabilities privately via GitHub **Security → Report a vulnerability**. We acknowledge within 3 days.

## 지원 버전
운영 중인 `main` 브랜치(https://art-chatbot-eight.vercel.app)만 지원합니다.

## 우리가 지키는 것 (요약)
- 비밀번호는 scrypt로 저장, 로그인은 HMAC 서명 쿠키(HttpOnly·SameSite), 비밀 값은 저장소가 아닌 Vercel·GitHub 비밀 저장소에
- 모든 응답에 보안 헤더(HSTS, CSP — 우리 서버의 스크립트만 실행, X-Frame-Options, nosniff 등)
- 가디언: 공격 경로·악성 입력·로그인 반복 실패·규칙 밖 수상한 접속(AI)을 감지해 IP 차단, 1분 외부 점검
- AI 자동 수정은 기계 검사 + 다른 AI 보안 검토 + 사람 승인 뒤에만 배포 (해커의 숨은 지시 방어)
- 의존성 취약점: Dependabot과 매시간 보안 동향 학습(OSV), 코드 정적 분석: CodeQL, 공개 보안 점수: OpenSSF Scorecard

자세한 내용: `docs/security-certification.md`, `wiki/guardian.md`
