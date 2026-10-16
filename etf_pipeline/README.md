# 한국 ETF 수집·검증 파이프라인

| 단계 | 내용 | 코드 |
|---|---|---|
| 1 | 운용사 홈페이지 찾기 + 접속/이름 검증 (후보 URL 순차 재조회) | `managers.py` |
| 2 | 운용사 사이트의 투자설명서(PDF/HTML) 수집·필드 추출 | `prospectus.py` |
| 3 | 테이블 정의 (SQLite `etf_products`) | `store.py` |
| 4 | 데이터 적재 + CSV 내보내기 | `store.py` |
| 5 | KRX 전종목 기본정보 CSV 다운로드 + 교차검증/재조회 | `krx.py`, `verify.py` |

## 실행
```
pip install -r etf_pipeline/requirements.txt
python -m etf_pipeline.run all                     # 전체
python -m etf_pipeline.run all --krx-csv KRX.csv   # KRX CSV 를 직접 받은 경우
python -m unittest etf_pipeline.tests.test_pipeline
```
결과: `data/etf/etf_products.csv`, `etf.sqlite`, `managers.csv`, `krx_etf.csv`, `verification_report.json`

## 테이블 컬럼
ETF 상품명, 자산운용코드(자체부여), 운용사, 거래소 단축코드, 표준코드(ISIN), 위험등급(1~6)·명칭,
상품구분(자산/전략), 상장일, 총보수, 기초지수, 근거 URL, 검증상태/메모.

## 검증·재조회 규칙
- 운용사: 접속 실패/운용사명 미포함 → 다음 후보 URL, 모두 실패면 `managers.csv` 에 사유 기록
- 설명서: ISIN 체크디지트, 코드 6자리, ISIN↔코드 일치, 위험등급 번호↔명칭 일치
- KRX 대조: ISIN·상품명·운용사·상장일·총보수. 불일치 시 캐시 무시 재다운로드 + 다른 PDF 엔진으로 재추출(최대 2회)
- 끝까지 불일치면 덮어쓰지 않고 `mismatch` 로 남김. KRX에만 있는 종목은 `krx_only`(설명서 미수집 → 재수집 대상)
- 한계: 위험등급은 KRX에 없어 교차검증 불가(설명서 내부 일관성만 확인)

## 현장 튜닝이 필요한 부분
운용사 사이트 구조는 제각각이라 범용 링크 크롤러로 못 찾는 곳은 `data/etf/managers_override.csv`
(`manager_name,homepage,list_urls,brand`; list_urls 는 `|` 구분)에 ETF 목록/설명서 URL 을 추가하세요.
KRX 가 자동 다운로드를 막으면 사이트에서 CSV 를 받아 `--krx-csv` 로 넘기세요.
