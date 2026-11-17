# Analysis dashboard 구현·검증 결과

## 1. 목적과 범위

승인된 카테고리·판매자 거래 분석과 배송·리뷰 심화 분석을 비개발자가 같은 정의로
반복 확인할 수 있도록 로컬 Streamlit dashboard를 구현했다. 새 mart·지표·통계 결과를
만들지 않고, 기존 분석의 검산을 통과한 집계만 화면 입력으로 사용한다.

화면은 다음 두 탭으로 제한한다.

- `거래 구성`: 승인 기간의 상품 거래액·배송비, 고정 Top 5 category+Other 구성,
  익명 판매자 Top 1·Top 10·상위 10% 집중도
- `배송·리뷰`: 전체 최종 분석 대상의 예정일 대비 배송 구간, 시간 순서 역전 포함·제외
  비교, 승인 기간의 월별 지연률과 지연·비지연 주문 리뷰 평균 차이

개별 판매자 조회, 주문·고객·상품 식별자, 리뷰 원문, 상세 위치, 사용자 업로드,
PostgreSQL runtime 연결은 범위에 포함하지 않았다.

## 2. 구현한 구조

### 검증 집계 exporter

[`scripts/export_dashboard_data.py`](../scripts/export_dashboard_data.py)는 기존 분석의
`load → validate → summarize → SQL reconciliation → fixed snapshot validation`을 다시
실행한다. Markdown 보고서의 숫자를 파싱하거나 수동으로 복사하지 않는다.

검증된 결과에서 다음 파일만 만든다.

- `trade_monthly_overview.csv`: 18행
- `category_mix.csv`: 108행
- `seller_concentration.csv`: 18행
- `delivery_timing_summary.csv`: 6행
- `delivery_monthly.csv`: 18행
- `delivery_sensitivity.csv`: 2행
- `manifest.json`: schema version과 각 CSV의 SHA-256·byte 수·행 수·key 범위

`build`는 임시 디렉터리의 전체 묶음을 먼저 검증한 후 CSV를 교체하고 manifest를
마지막에 교체한다. 교체 중 실패하면 기존 7개 산출물을 복구한다. `check`는 같은 입력으로
임시 묶음을 다시 만든 뒤 byte-identical 여부만 확인하며 커밋된 파일을 수정하지 않는다.

### 입력 검증과 계산 helper

[`dashboard/lib.py`](../dashboard/lib.py)는 app과 파일 사이의 fail-closed 경계다.
manifest·checksum·열 순서·행 수·key·월 범위·값 범위·비중 공식과 파일 간 합계를 모두
확인한 뒤에만 여섯 DataFrame을 반환한다.

기간 KPI는 표시용 평균을 다시 평균하지 않는다.

- 거래 금액·배송비·주문상품 행 수는 선택 월의 가산값을 합한다.
- 활동 판매자 수는 기간 합계가 아니라 마지막 선택 월 값을 사용한다.
- 지연률은 선택 기간의 `지연 주문 수 / 전체 주문 수`로 다시 계산한다.
- 두 리뷰 평균은 각 집단의 `주문 평균 리뷰 점수 합 / 주문 수`로 다시 계산한다.
- 분모가 0인 계산 helper 상태는 `N/A`를 반환한다. 현재 고정 집계의 각 승인 월에는
  지연·비지연 주문이 모두 있어 파일 자체에는 빈 파생값이 없다.

### Streamlit 화면

[`dashboard/app.py`](../dashboard/app.py)는 커밋된 `dashboard/data/`만 읽는다. DB,
`.env`, 원천 CSV와 행 단위 데이터에 접근하지 않는다. 두 탭의 필터는 서로 독립적이며,
일부 category만 표시해도 비중 분모는 선택 그룹 합이 아니라 같은 월 전체 상품 거래액으로
유지한다.

배송 구간 6개와 시간 순서 역전 포함·제외 결과 2개 집단에는 월 key가 없으므로 기간 필터를
적용하지 않는다. 기간 필터는 `delivery_monthly.csv`로 계산하는 월별 지연률과 리뷰 평균
차이에만 적용한다. 화면에 이 차이를 함께 표시했다.

거래 KPI는 긴 금액이 잘리지 않도록 2열·2행으로 배치한다. 배송 기간별 KPI에는
선택 기간의 전체·지연·비지연 주문 수를 함께 표시해 위쪽 전체 분석 대상과 분모를
구별할 수 있도록 했다.

## 3. 확인된 결과

### 집계와 공개 경계

- 거래 기본 기간은 2017-02~2018-07의 정확히 18개월이다.
- 기간 상품 거래액 12,230,652.13, 배송비 2,029,493.87, 주문상품 101,825행이 기존
  카테고리·판매자 분석과 일치한다.
- 배송 구간 6개의 주문 수 합은 전체 최종 분석 대상 95,824건, 네 지연 구간 합은
  6,381건이다.
- 시간 순서 역전 제외 집단은 94,458건이며 기존 심화 분석과 일치한다.
- 승인 18개월에 포함된 배송 월별 집계는 88,489건이다. 따라서 dashboard 기본 기간
  지연률 6.75%는 전체 최종 분석 대상의 6.66%와 분모·기간이 다르며, 두 수치를 같은
  지표로 혼동하지 않도록 화면 영역을 분리했다.
- 공개 집계 파일의 열과 값에서 order·seller·customer·product 식별자, 리뷰 원문,
  상세 위치, DB credential과 연결 문자열이 발견되지 않았다.
- 각 파일의 정확한 checksum과 byte 수는
  [`dashboard/data/manifest.json`](../dashboard/data/manifest.json)을 단일 근거로 둔다.

### 구현 중 발견해 수정한 오류

- 월 선택 option이 `YYYY-MM-DD`, 계산 helper가 `YYYY-MM`을 기대해 첫 화면이 중단될 수
  있던 형식 불일치를 `YYYY-MM` 하나로 통일했다.
- exporter와 loader가 배송 구간 및 시간 순서 역전 포함·제외 집단의 표시명을 서로 다른
  언어로 기대하던 문제를 공통 상수 하나를 사용하도록 수정했다.
- loader도 시간 순서 역전 제외 94,458건을 독립적으로 확인하도록 보강했다.
- 비율과 점수가 원시 소수로 보이던 표를 `%`, `점`, 천 단위 형식으로 바꾸고,
  공개 화면의 `final cohort` 같은 표현을 `최종 분석 대상`으로 풀어썼다.
- 파일 교체 중 세 번째 교체가 실패하는 합성 상황에서 기존 CSV 6개와 manifest가 모두
  byte-for-byte 복구되는 테스트를 추가했다.

## 4. 검증 결과

### 자동 검증

- 전체 dbt build: 모델 20개 + data test 245개 = 265개 node 통과
- 기본 Python test 실행: 81개 통과, PostgreSQL integration 7개 skip
- PostgreSQL 연동을 활성화한 전체 Python test: 88개 통과
- exporter `build` 후 `check`: CSV 6개, 18개월, 배송 주문 95,824건으로 통과
- AppTest: 기본 두 탭, 필터 option과 기본값, 기간 변경 재계산, 빈 다중 선택,
  시작 월>종료 월, 공개 문구와 해석 경계를 headless 환경에서 통과
- 로컬 Streamlit server를 `127.0.0.1`에서 기동하고 health endpoint의 `ok` 응답 확인
- 손상·누락 파일, checksum drift, 잘못된 schema·key·월·분모·파일 간 합계는 loader가
  화면을 열기 전에 실패하는 합성 테스트 통과
- 공개 집계 금지 문자열 검사 통과

최종 재검증에서는 dbt data test 245개와 위 Python test 88개를 다시 실행했다.
기존 분석의 빈 배송 구간에서 SQL `NULL`과 pandas `NaN`을 같은 결측으로 비교하도록
보완했으며, 결측을 실제 값이나 0과 혼동하지 않는 회귀 테스트 2개를 포함한다.

재현 명령은 다음과 같다.

```bash
.venv/bin/dbt build --profiles-dir . --threads 1

.venv/bin/python scripts/export_dashboard_data.py build
.venv/bin/python scripts/export_dashboard_data.py check

RUN_POSTGRES_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest discover -s tests -v

.venv/bin/streamlit run dashboard/app.py
```

승인 산출물을 검증할 때는 먼저 `check`를 사용한다. `build`는 기존 분석 결과가 바뀌어
집계 파일 갱신이 의도된 경우에만 실행하고 diff를 검토한다.

## 5. 해석과 한계

- 상품 거래액은 회사 매출·순매출·이익이 아니다.
- 거래 분석은 배송 완료 주문상품만 설명한다.
- Top 5 category는 승인된 18개월 전체를 기준으로 고정했고, 판매자 집중도 집단의
  구성원은 매월 달라질 수 있다.
- 배송·리뷰 결과는 배송일 비교 가능·리뷰 보유 배송 완료 주문의 관찰 관계다.
  배송 지연이 리뷰 점수 차이를 유발했다는 인과 효과가 아니다.
- 전체 배송 구간·시간 순서 역전 포함·제외 비교와 월별 분석은 기간·분모가 다르다.
- 2016~2018년 Olist 고정 공개 데이터 결과를 현재 시장이나 다른 서비스에 일반화하지
  않는다.
