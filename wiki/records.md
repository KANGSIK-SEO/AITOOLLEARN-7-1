---
title: 권리 근거 기록 (발급·보관·검증)
sources: [app/records.py, docs/rights-policy.md, app/main.py, app/chat.py]
updated: 2026-10-07
---
# 권리 근거 기록

## 무엇인가

작품 카드의 **근거 기록** 버튼을 누르면 만들어지는 문서. 번호는 `PD-XXXX-XXXX-XXXX` 꼴 (`_new_number`).
**"써도 된다는 보증서"가 아니다.** "그날 기관이 이렇게 공개해 두었다"는 기록이다.
그래서 화면·AI 답변 어디서도 **보증·인증·확인서**라는 말을 쓰지 않는다 (`app/chat.py` 프롬프트 규칙 8).

> 처음 이름은 "확인서"였다. 공신력 있는 기관의 직인이 없는 문서를 확인서라고 부르면 오해를 산다는 지적으로 바꿨다 → [주요 결정](decisions.md)

## 만들어지는 과정 (`app/records.py`)

1. `issue()`: 작품이 [권리 판단](rights.md)을 통과했는지 다시 확인하고, 그 순간의 권리 정보를 **스냅숏**으로 저장한다.
   나중에 기관 데이터가 바뀌어도 기록은 그대로다.
2. `_sign()`: 번호·발급 시각·스냅숏으로 **HMAC 서명**을 만든다. 누가 DB를 고치면 기록 화면에 "⚠️ 변조 의심"으로 보인다.
3. `save_to_wayback()`: 기관 작품 페이지와 API 주소를 **인터넷 아카이브(Wayback Machine)**에 보관 요청한다.
   우리 직인보다 제3자 보관본이 더 믿을 만하다는 원칙 (`docs/rights-policy.md` §0-5).
4. 보관이 실패한 링크는 `POST /api/records/{번호}/archive`로 나중에 다시 시도한다 (`archive_missing`).

## 보는 곳

`GET /records/{번호}` → `render()`가 HTML로 그린다: 작품 정보, 근거 필드와 값, 확인일, 서명 확인 결과, 아카이브 링크, 출처 표기 예시.

## 제한

IP당 시간당 60건 (`RECORD_LIMIT_PER_HOUR`), 아카이브 재시도는 20건. 로그인 없이도 발급할 수 있다 (`optional_session`).
