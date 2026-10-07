---
title: 권리 판단 (어떤 작품을 보여주나)
sources: [docs/rights-policy.md, app/rights.py, app/art.py]
updated: 2026-10-07
---
# 권리 판단

**설계도는 `docs/rights-policy.md`**, 그걸 코드로 옮긴 게 `app/rights.py`다. 규칙을 바꾸려면 문서부터 고친다.

## 원칙 (`docs/rights-policy.md` §0)

1. **애매하면 넣지 않는다.** 한 작품이라도 틀리면 서비스 전체를 믿을 수 없다.
2. **우리가 판단하지 않는다.** 기관이 작품 단위로 밝힌 것만 옮긴다. "오래된 그림이니 아마 괜찮겠지" 추정 금지.
3. **근거를 남긴다.** 어떤 기관의 어떤 필드가 어떤 값이었는지, 언제 확인했는지.
4. **보증이 아니라 기록이다.** → [권리 근거 기록](records.md)

## 기관 허용 목록 (`SOURCES`, `app/rights.py`)

| 상태 | 기관 |
|---|---|
| ✅ 허용 | MET(`isPublicDomain`), AIC(`is_public_domain`), CMA(`share_license_status = "CC0"`) |
| ⏸ 보류 | NGA, Smithsonian, Rijksmuseum(PDM이라 CC0 아님), 국립중앙박물관 e뮤지엄(공공누리 1유형은 출처 표시 의무) |

보류 기관은 `enabled=False`라 검색에 **절대** 나오지 않는다.
환경변수 `ALLOWED_SOURCES`로 허용 기관을 더 좁힐 수 있다 (작게 검증하는 파일럿용, `allowed_sources()`).

## 작품 규칙 R1~R6 (`evaluate()`)

| # | 규칙 | 실패하면 |
|---|---|---|
| R1 | 기관이 허용 목록에 있다 | 제외 |
| R2 | 기관이 작품 단위로 퍼블릭 도메인이라고 밝혔다 | 제외 |
| R3 | 라이선스가 `CC0` | 제외 |
| R4 | 이미지가 기관 공식 도메인 | 제외 |
| R5 | 권리 확인일이 365일 이내 | 보여주되 **"재확인 필요"** 표시 |
| R6 | 기관 공식 상세 페이지 URL이 있다 | 제외 |

결과는 `ok` / `recheck` / `blocked` 셋 중 하나다.
