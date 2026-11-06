# 카테고리·판매자 월별 거래 mart 검증

검증일: 2026-11-06 (Asia/Seoul)

## 1. 목적과 범위

이번 단계의 목적은 검증된 주문상품 fact를 비즈니스 질문에 반복 사용할 수 있는
월별 분석 table로 집계하는 것이다.

구현 범위는 다음 두 모델이다.

- `mart_category_trade_monthly`: 구매월×카테고리 1행
- `mart_seller_trade_monthly`: 구매월×판매자 1행

두 mart는 배송 완료 주문의 상품 측 금액과 주문상품 행 수를 비교하기 위한 구조다.
결제·리뷰·geolocation은 결합하지 않았고, 거래 결과의 원인이나 인과 효과도 분석하지
않는다. 카테고리·판매자별 상세 해석과 배송·리뷰 분석은 별도 분석 산출물의 범위다.

## 2. 적용한 계약

기준 문서는 [`../docs/model-metric-contracts.md`](../docs/model-metric-contracts.md)의
거래 mart 계약과 D-007이다.

- 분석 cohort: `order_status = 'delivered'`인 주문상품
- 기준 월: `order_purchase_timestamp`에서 만든 `purchase_month`
- 카테고리 grain/key: `(purchase_month, category_key)`
- 판매자 grain/key: `(purchase_month, seller_id)`
- 상품 거래액: `SUM(price)`
- 배송비: `SUM(freight_value)`
- 상품 측 합계: `SUM(item_side_amount)`
- 주문상품 행 수: `COUNT(*)`
- 상품 종류 수: `COUNT(DISTINCT product_id)`
- 연결 주문 수: `COUNT(DISTINCT order_id)`

상품 거래액과 상품 측 합계는 회사 매출·순매출·이익이 아니다. `ordered_item_row_count`도
수량 열의 합이 아니라 원천 주문상품 행 수다.

## 3. 구현 내용

### 3.1 카테고리 mart

`fct_order_items`의 delivered 행을 상품 dimension과 `product_id`로 결합한 뒤
구매월과 카테고리 단위로 집계했다. 다음 속성을 결과에 함께 보존한다.

- 원문 카테고리명
- 선택적인 영문 카테고리명
- 분석용 `category_key`
- 사람이 읽을 `category_display_name`
- `mapped`, `missing_source`, `unmapped_translation` 매핑 상태

원문 누락이나 번역 미연결 상품을 필터링하지 않았다. 따라서 이 그룹의 주문상품과
금액도 mart 전체 대사에 포함된다.

### 3.2 판매자 mart

같은 delivered fact를 판매자 dimension과 `seller_id`로 결합한 뒤 구매월과 판매자
단위로 집계했다. 원천의 zip prefix, city와 state를 설명 속성으로 유지하되, 중복 가능성이
있는 geolocation 원천은 결합하지 않았다.

### 3.3 의도적으로 추가하지 않은 처리

- 결제 금액을 상품·카테고리·판매자에 배분하지 않음
- 리뷰를 주문상품에 직접 결합하지 않음
- missing·unmapped 카테고리를 제거하지 않음
- 금액을 반올림하거나 임의 tolerance를 적용하지 않음
- 판매자 위치를 geolocation 좌표와 직접 결합하지 않음

## 4. 확인된 결과

아래 수치는 PostgreSQL의 구축된 모델에서 식별자나 원천 행을 출력하지 않고 집계한
결과다.

### 4.1 delivered 기준 집계 모집단

| 항목 | 결과 |
|---|---:|
| 주문상품 행 수 | 110,197 |
| distinct 주문 수 | 96,478 |
| distinct 상품 수 | 32,216 |
| 첫 구매월 | 2016-09-01 |
| 마지막 구매월 | 2018-08-01 |
| 상품 거래액 | 13,221,498.11 |
| 배송비 | 2,198,275.64 |
| 상품 측 합계 | 15,419,773.75 |

이 값은 두 mart가 공통으로 보존해야 할 delivered fact의 기준 합계다.

### 4.2 카테고리 월별 mart

| 항목 | 결과 |
|---|---:|
| mart 행 수 | 1,273 |
| 관찰된 category key 수 | 74 |
| 주문상품 행 수 합 | 110,197 |
| 상품 거래액 합 | 13,221,498.11 |
| 배송비 합 | 2,198,275.64 |
| 상품 측 합계 | 15,419,773.75 |
| 카테고리별 연결 주문 수 합 | 97,276 |
| 카테고리별 상품 종류 수 합 | 60,881 |

금액과 주문상품 행 수는 delivered fact 전체와 정확히 일치했다. 연결 주문 수와 상품
종류 수의 그룹별 합은 전체 distinct 주문·상품 수와 같지 않다. 같은 주문이나 상품이
여러 카테고리에 연결될 수 있는 비가산 지표이기 때문이다.

카테고리별 연결 주문 수 합 97,276은 전체 주문 수 96,478이 아니라
`(purchase_month, order_id, category_key)` 조합의 distinct 수와 대사했다.
두 값의 차이 798을 여러 카테고리에 걸친 주문의 건수로 해석할 수는 없다. 한 주문이
세 카테고리에 연결되면 합계에 2의 초과분을 만들 수 있기 때문이다.

### 4.3 카테고리 매핑 상태 보존

| 매핑 상태 | mart 행 수 | 주문상품 행 수 | 상품 측 합계 |
|---|---:|---:|---:|
| `mapped` | 1,243 | 108,638 | 15,216,419.91 |
| `missing_source` | 21 | 1,537 | 197,695.69 |
| `unmapped_translation` | 9 | 22 | 5,658.15 |
| 합계 | 1,273 | 110,197 | 15,419,773.75 |

missing·unmapped 그룹을 포함했기 때문에 category mart의 전체 금액과 주문상품 행 수가
delivered fact와 일치한다. 이 상태는 정상·오류 등급이 아니라 데이터 보존 상태다.

### 4.4 판매자 월별 mart

| 항목 | 결과 |
|---|---:|
| mart 행 수 | 16,068 |
| 관찰된 판매자 수 | 2,970 |
| 주문상품 행 수 합 | 110,197 |
| 상품 거래액 합 | 13,221,498.11 |
| 배송비 합 | 2,198,275.64 |
| 상품 측 합계 | 15,419,773.75 |
| 판매자별 연결 주문 수 합 | 97,819 |
| 판매자별 상품 종류 수 합 | 61,359 |

판매자별 연결 주문 수 합 97,819는 전체 주문 수가 아니라
`(purchase_month, order_id, seller_id)` 조합의 distinct 수와 대사했다. 한 주문에 여러
판매자의 상품이 있으면 그 주문은 각 판매자 그룹에서 한 번씩 세어진다.
마찬가지로 97,819와 96,478의 차이는 여러 판매자가 연결된 주문 건수 자체가 아니다.

## 5. 검산과 테스트

### 5.1 모델 계약 검사

- 각 mart의 복합 key unique·not null
- 구매월이 calendar month 시작일인지 검사
- `gross_item_value > 0`, `freight_amount >= 0`
- `item_side_amount = gross_item_value + freight_amount`
- 세 count가 not null이고 가능한 행 수 범위 안에 있는지 검사
- 카테고리 key·표시명·매핑 상태의 조건 일치 검사
- 판매자 key가 판매자 dimension에 존재하는지 relationship 검사

### 5.2 그룹별 exact 대사

delivered fact에서 기대 결과를 독립적으로 다시 집계하고 실제 mart와 복합 key로
`FULL OUTER JOIN`했다. 다음을 함께 비교했다.

- 기대 그룹만 있거나 실제 그룹만 있는 누락·초과
- 카테고리·판매자 설명 속성
- 세 금액
- 주문상품 행 수, 상품 종류 수, 연결 주문 수

전체 합계만 맞는 경우에도 그룹 간 값이 서로 뒤바뀔 수 있으므로 그룹별 exact 대사를
별도로 수행했다.

### 5.3 전체 합계와 비가산 지표 대사

- 두 mart의 가산 금액과 주문상품 행 수 합을 delivered fact 전체와 대사
- 카테고리별 연결 주문 수 합을 월×주문×카테고리 distinct 조합과 대사
- 판매자별 연결 주문 수 합을 월×주문×판매자 distinct 조합과 대사
- 그룹별 distinct 상품 수 합을 전체 distinct 상품 수와 비교하는 잘못된 검산은 하지 않음

## 6. 실행 결과

```text
dbt parse: 성공
dbt build --threads 1:
  19 table models + 212 data tests = 231 nodes
  PASS=231 WARN=0 ERROR=0 SKIP=0

Python unittest including PostgreSQL integration:
  24 tests passed
```

dbt adapter는 precision·scale을 지정하지 않은 PostgreSQL `numeric` 열에 일반 경고 문구를
출력했다. 이는 기존 승인 계약에서 원천 decimal 값을 임의 반올림하지 않기 위해 선택한
unbounded `numeric`과 관련된 메시지다. 위 `WARN=0`은 실행 node의 최종 상태를 뜻한다.

## 7. 사용자 검토 항목

이번 구현은 이미 승인된 grain, cohort와 공식 안에서 완료되어 새로운 의미 결정은
필요하지 않다. 결과 검토에서는 다음을 구분해 확인한다.

- 금액·주문상품 행 수는 두 mart에서 delivered fact와 같아야 한다.
- 카테고리·판매자별 연결 주문 수 합은 전체 distinct 주문 수보다 클 수 있다.
- 카테고리 missing·unmapped 그룹은 대사를 위해 보존한다.
- 이 결과만으로 높은 거래액이나 배송비의 원인을 설명하지 않는다.

## 8. 가정과 한계

- 이번 결과는 고정된 Olist snapshot의 검증 결과다.
- delivered 필터는 분석 cohort이며 회계상 매출 인식 기준이 아니다.
- 상품 거래액과 상품 측 합계는 회사 매출·순매출·이익이 아니다.
- 주문상품 행 수는 판매 수량이 아니다.
- 연결 주문 수와 상품 종류 수는 그룹 간 비가산 지표다.
- 판매자 city/state는 원천 값을 보존하며 위치 정규화나 좌표 분석을 하지 않았다.
- 카테고리·판매자별 차이는 기술통계이며 원인이나 인과 효과를 뜻하지 않는다.
- 증분 적재, 성능 튜닝, production 운영이나 cloud 배포를 검증한 단계가 아니다.

## 9. 재현 방법

로컬 PostgreSQL이 실행 중이고 `.env`가 준비된 상태에서 다음을 실행한다.

```bash
.venv/bin/dbt parse --profiles-dir .
.venv/bin/dbt build --profiles-dir . --threads 1
RUN_POSTGRES_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
```

검증 대상 핵심 파일은 다음과 같다.

- `models/marts/olist/mart_category_trade_monthly.sql`
- `models/marts/olist/mart_seller_trade_monthly.sql`
- `models/marts/olist/_olist__trade_marts.yml`
- `dbt_tests/assert_category_trade_monthly_reconciles.sql`
- `dbt_tests/assert_category_trade_monthly_totals_reconcile.sql`
- `dbt_tests/assert_seller_trade_monthly_reconciles.sql`
- `dbt_tests/assert_seller_trade_monthly_totals_reconcile.sql`
