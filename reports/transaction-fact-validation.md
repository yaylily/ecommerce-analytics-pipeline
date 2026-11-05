# 거래 dimension과 주문상품 fact 검증

검증일: 2026-11-05 (Asia/Seoul)

## 1. 목적과 범위

이번 단계의 목적은 카테고리·판매자별 거래 mart를 만들기 전에 원천 주문상품의
한 행 의미와 금액을 잃지 않는 분석 기반을 만드는 것이다.

구현 범위는 다음 세 모델이다.

- `dim_products`: 원천 상품 1개당 1행
- `dim_sellers`: 원천 판매자 1명당 1행
- `fct_order_items`: 원천 주문상품 1행당 1행

이번 단계에서는 월별 category·seller mart를 만들거나 거래 특성을 해석하지 않는다.
결제·리뷰·geolocation도 주문상품 fact에 결합하지 않는다. 배송 완료 상태 필터는
후속 mart에만 적용하며 fact에는 모든 원천 주문상품 상태를 보존한다.

## 2. 적용한 계약

기준 문서는 [`../docs/model-metric-contracts.md`](../docs/model-metric-contracts.md)의
거래 모델 계약과 D-007이다.

- fact grain: `(order_id, order_item_id)`로 식별되는 원천 주문상품 1행
- 상품 dimension grain: `product_id` 1개
- 판매자 dimension grain: `seller_id` 1명
- 기준 월: `order_purchase_timestamp`의 calendar month
- fact 금액: 원천 `price`, `freight_value`와 두 값의 합인 `item_side_amount`
- 상품·주문·판매자 결합: 주문상품을 기준으로 한 `LEFT JOIN`
- 제외: 결제 배분, 리뷰 결합, geolocation 직접 결합, delivered 사전 필터

`price` 합계는 상품 거래액 성격의 값이며 회사 매출·순매출·이익으로 해석하지 않는다.

## 3. 구현 내용

### 3.1 `dim_products`

원문 카테고리와 선택적인 영문 번역을 별도 열로 유지했다. 다음 세 상태를 구분한다.

- `mapped`: 원문 카테고리와 사용할 수 있는 영문 번역이 모두 존재
- `missing_source`: 원문 카테고리 자체가 NULL
- `unmapped_translation`: 원문 카테고리는 있지만 사용할 수 있는 영문 번역이 없음

표시명은 영문명, 원문명, `Unknown` 순으로 선택한다. 원문 누락과 번역 누락을 하나의
상태로 합치지 않았으며 translation을 `INNER JOIN`해 상품을 삭제하지 않았다.

현재 `dim_products`는 승인된 질문에 필요한 상품 ID와 카테고리 매핑 열만 선택한다.
모든 물리 속성을 분석형으로 변환한 범용 상품 dimension은 아니다.

### 3.2 `dim_sellers`

원천 판매자의 zip prefix, city와 state를 그대로 보존했다. zip prefix는 geolocation에서
고유하지 않으므로 geolocation을 결합하지 않았다. 이 모델은 위치 분석 모델이 아니라
주문상품 fact가 참조할 판매자 dimension이다.

### 3.3 `fct_order_items`

`stg_order_items`를 기준으로 주문, 상품 dimension과 판매자 dimension을 `LEFT JOIN`했다.
다음 값을 추가했다.

- 부모 주문의 `order_status`
- 부모 주문의 `order_purchase_timestamp`
- 구매 timestamp에서 계산한 `purchase_month`
- 상품 dimension의 `category_key`
- `price + freight_value`인 `item_side_amount`

`shipping_limit_date`는 원천 값을 보존하지만 극단값 상한이나 제외 규칙을 추가하지
않았다. 이 정책은 여전히 `[UNRESOLVED]`다.

## 4. 확인된 데이터 사실

아래 수치는 PostgreSQL의 구축된 모델에서 식별자를 출력하지 않고 집계한 결과다.

### 4.1 상품 카테고리 매핑 상태

| 매핑 상태 | 상품 수 |
|---|---:|
| `mapped` | 32,328 |
| `missing_source` | 610 |
| `unmapped_translation` | 13 |
| 합계 | 32,951 |

상품 dimension의 32,951행은 staging 상품 행 수와 같다. 관찰된 세 상태는 오류 등급이
아니라 후속 집계에서 누락을 보존하기 위한 분류다.

### 4.2 판매자 dimension

- 판매자 행 수: 3,095
- staging 판매자와 행별 zip prefix·city·state가 모두 일치
- geolocation 결합으로 인한 행 증폭 없음

### 4.3 주문상품 fact 전체 대사

| 항목 | 검증 결과 |
|---|---:|
| 주문상품 행 수 | 112,650 |
| distinct 복합 key 수 | 112,650 |
| 연결 주문 수 | 98,666 |
| `SUM(price)` | 13,591,643.70 |
| `SUM(freight_value)` | 2,251,909.54 |
| `SUM(item_side_amount)` | 15,843,553.24 |
| 첫 구매월 | 2016-09-01 |
| 마지막 구매월 | 2018-09-01 |

행 수와 distinct 복합 key 수가 같고, staging과 fact의 각 주문상품 값과 세 금액 합계가
일치했다. 이는 조인 후 주문상품 행이 누락되거나 복제되지 않았다는 현재 snapshot의
검증 근거다. 원천 값 자체가 업무적으로 정확하다는 보장은 아니다.

### 4.4 fact에 보존된 주문 상태

| 주문 상태 | 주문상품 행 수 | 연결 주문 수 |
|---|---:|---:|
| `approved` | 3 | 2 |
| `canceled` | 542 | 461 |
| `delivered` | 110,197 | 96,478 |
| `invoiced` | 359 | 312 |
| `processing` | 357 | 301 |
| `shipped` | 1,185 | 1,106 |
| `unavailable` | 7 | 6 |

이 표는 fact가 delivered 주문만 사전 선택하지 않았음을 확인하기 위한 것이다. 후속
primary 거래 mart는 승인 계약대로 `delivered`만 사용한다. 상태별 건수를 거래 성과로
해석하지 않는다.

### 4.5 매핑 상태를 보존한 주문상품

| 상품 매핑 상태 | 주문상품 행 수 | `item_side_amount` |
|---|---:|---:|
| `mapped` | 111,023 | 15,629,890.34 |
| `missing_source` | 1,603 | 207,705.09 |
| `unmapped_translation` | 24 | 5,957.81 |
| 합계 | 112,650 | 15,843,553.24 |

missing·unmapped 그룹을 제거하면 fact 전체 금액 대사가 깨진다. 이 때문에 후속 category
mart에서도 두 그룹을 명시적으로 유지해야 한다.

## 5. 검산과 테스트

### 5.1 dimension 검산

- 상품·판매자 dimension과 각 staging의 행 수 일치
- `product_id`, `seller_id` unique·not null
- 상품 mapping status의 세 값과 상태 조건 검사
- 상품은 원문명·영문명·표시명·상태를, 판매자는 위치 속성을 행별로 대사
- expected와 actual을 `FULL OUTER JOIN`해 누락·초과·값 변경을 함께 탐지

### 5.2 fact 검산

- staging과 fact의 행 수 일치
- `(order_id, order_item_id)` 복합 key unique·not null
- 주문·상품·판매자 relationship 검사
- `price > 0`, `freight_value >= 0`
- `item_side_amount = price + freight_value`
- `purchase_month`가 구매 timestamp의 calendar month와 일치
- expected와 actual을 복합 key로 `FULL OUTER JOIN`해 모든 전달·계산 열을 행별 대사
- 행 수, distinct key 수와 세 금액 합계를 별도로 전체 대사

전체 합계만 비교하면 한 주문상품의 누락과 다른 주문상품의 초과가 상쇄될 수 있다.
따라서 행별 검산과 전체 합계 검산을 함께 사용했다.

### 5.3 합성 fixture

가상의 mapped·source missing·translation unmapped 상품을 각각 만들었다. `LEFT JOIN` 뒤
세 상품이 모두 남고 세 상태로 정확히 분류되는지 확인했다. fixture에는 실제 상품 ID나
원천 행을 사용하지 않았다.

## 6. 실행 결과

```text
dbt parse: 성공
dbt build --threads 1:
  17 table models + 167 data tests = 184 nodes
  PASS=184 WARN=0 ERROR=0 SKIP=0

Python unittest including PostgreSQL integration:
  24 tests passed
```

dbt adapter는 precision·scale을 지정하지 않은 PostgreSQL `numeric` 열에 일반 경고 문구를
출력했다. 이는 기존 승인 계약에서 원천 decimal 값을 임의 반올림하지 않기 위해 선택한
unbounded `numeric`과 관련된 메시지다. 위 `WARN=0`은 dbt 실행 노드의 최종 상태이며,
해당 adapter 로그 문구가 없었다는 뜻은 아니다.

## 7. 사용자 검토 항목

### `[승인 필요]` missing category의 내부 key 표현

현재 구현안은 원문 카테고리가 NULL인 상품에 `category_key = '__missing_source__'`를
사용한다. 표시명은 계약대로 `Unknown`이다.

이 방식의 목적은 다음과 같다.

- SQL `GROUP BY` 결과에서 missing 그룹을 명시적인 key로 유지
- 번역 누락 카테고리와 원문 누락 상품을 구분
- 후속 category mart에서 금액을 잃지 않고 대사

원천 카테고리에 같은 문자열이 나타나면 충돌하므로 이를 실패시키는 테스트도 두었다.
이 exact 문자열은 기존 Accepted 계약에 없던 구현 표현이므로 사용자 승인 전에는 계약
문서에 확정하지 않는다.

## 8. 가정과 한계

- 이번 결과는 고정된 Olist snapshot의 검증 결과이며 새 snapshot을 자동 보장하지 않는다.
- `price`, `freight_value`, `item_side_amount`는 매출·순매출·이익이 아니다.
- 연결 주문 수와 상품 수는 후속 그룹 간 단순 합산할 수 없는 비가산 지표다.
- 상품 카테고리 상태는 데이터 보존을 위한 분류이며 정상·오류 판정이 아니다.
- 판매자 위치는 원천 city/state만 보존하며 geolocation 분석을 구현하지 않았다.
- `shipping_limit_date` 이상치의 의미나 상한을 정하지 않았다.
- 성능 튜닝, 증분 적재, production 배포나 운영 경험을 검증한 단계가 아니다.
- category·seller별 거래 특성은 후속 mart가 완성되기 전에는 결론 내리지 않는다.

## 9. 재현 방법

로컬 PostgreSQL이 실행 중이고 `.env`가 준비된 상태에서 다음을 실행한다.

```bash
.venv/bin/dbt parse --profiles-dir .
.venv/bin/dbt build --profiles-dir . --threads 1
RUN_POSTGRES_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
```

검증 대상 핵심 파일은 다음과 같다.

- `models/marts/olist/dim_products.sql`
- `models/marts/olist/dim_sellers.sql`
- `models/marts/olist/fct_order_items.sql`
- `models/marts/olist/_olist__transaction_models.yml`
- `dbt_tests/assert_dim_products_reconciles.sql`
- `dbt_tests/assert_dim_sellers_reconciles.sql`
- `dbt_tests/assert_fct_order_items_reconciles.sql`
- `dbt_tests/assert_fct_order_items_totals_reconcile.sql`
- `dbt_tests/category_mapping_fixture_preserves_all_states.sql`
