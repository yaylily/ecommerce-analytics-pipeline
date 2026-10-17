# Model and metric contracts

> Status: Accepted / 2026-10-17
>
> 사용자가 grain·필터·지표·예외의 의미와 영향을 확인하고 승인했다. 이 계약은 구현의
> 기준이며 구현 완료를 의미하지 않는다. `[UNRESOLVED]` 항목에 의존하는 추가 정책은
> 해당 관찰과 승인이 끝나기 전까지 확정하지 않는다.

## 목적과 근거

이 계약은 다음 두 질문에 필요한 최소 모델과 지표를 정의한다.

1. 카테고리와 판매자별 주문·상품 거래 특성은 어떻게 다른가?
2. 약속한 배송일을 넘긴 주문과 리뷰 점수 사이에는 어떤 관계가 있는가?

원천의 행 의미, key, fan-out과 값 관찰 근거는 다음 보고서에 둔다.

- [`../reports/source-profile.md`](../reports/source-profile.md)
- [`../reports/source-value-profile.md`](../reports/source-value-profile.md)

같은 관찰 수치를 이 문서에 다시 복사하지 않고, 여기에는 채택할 의미와 검산 규칙만
기록한다.

## 공통 원칙 — Accepted

- raw와 staging은 원천 행을 보존한다. 업무 지표에서 제외할 행을 적재 단계에서
  삭제하거나 날짜를 임의로 교정하지 않는다.
- `price`, `freight_value`, `payment_value`는 PostgreSQL `numeric`으로 처리하며
  이진 부동소수점으로 금액을 계산하지 않는다.
- timezone 정보가 없는 원천 timestamp는 PostgreSQL `timestamp without time zone`으로
  적재하며, 별도의 timezone을 추정하거나 변환하지 않는다.
- 1:N 원천은 목표 grain으로 먼저 집계한 뒤 결합한다. 상품·결제·리뷰를 raw grain에서
  동시에 직접 조인하지 않는다.
- 확실한 schema·key·domain 위반은 fail, 원인이 확정되지 않은 원천 이상은
  warn과 품질 flag로 관리한다.
- 관찰 결과를 매출·이익 또는 인과 효과로 표현하지 않는다.

---

# 1. 거래 모델 계약 — Accepted

## 비즈니스 질문

배송 완료 주문을 기준으로 카테고리와 판매자별 상품 거래액, 배송비, 주문상품 행 수,
연결 주문 수와 상품 종류 수를 비교한다.

## 모델과 grain

| 모델 | 한 행의 의미 | key | 주요 정책 |
|---|---|---|---|
| `stg_orders` | 주문 1건 | `order_id` | 모든 주문 상태 보존 |
| `stg_order_items` | 주문상품 1행 | `(order_id, order_item_id)` | 원천 상품 금액·배송비 보존 |
| `stg_products` | 상품 1개 | `product_id` | 원문 카테고리와 NULL 보존 |
| `stg_sellers` | 판매자 1명 | `seller_id` | 원천 city/state만 사용 |
| `stg_category_translation` | 원문 카테고리 1개 | `product_category_name` | 영문명은 표시용 속성 |
| `stg_payments` | 원천 결제 1행 | `(order_id, payment_sequential)` | 주문당 여러 결제행 보존 |
| `dim_products` | 상품 1개 | `product_id` | `mapped`, `missing_source`, `unmapped_translation` 상태 보존 |
| `dim_sellers` | 판매자 1명 | `seller_id` | geolocation 직접 조인 금지 |
| `fct_order_items` | 원천 주문상품 1행 | `(order_id, order_item_id)` | status로 사전 필터하지 않고 각 item의 부모 주문 상태 보존 |
| `mart_category_trade_monthly` | 구매월×카테고리 1행 | `(purchase_month, category_key)` | `delivered` 주문만 집계 |
| `mart_seller_trade_monthly` | 구매월×판매자 1행 | `(purchase_month, seller_id)` | `delivered` 주문만 집계 |
| `int_order_item_amount_summary` | 상품행이 있는 주문 1건 | `order_id` | 상품 측 금액을 주문별 선집계 |
| `int_order_payment_summary` | 결제행이 있는 주문 1건 | `order_id` | 결제 측 금액·결제행 수를 주문별 선집계 |
| `audit_order_amount_reconciliation` | 전체 주문 기준 주문 1건 | `order_id` | 양쪽 존재 여부와 금액 차이 보존; core mart에는 미결합 |

`category_key`는 원문 카테고리를 기준으로 하며, 원문 NULL은 명시적인 missing 그룹으로
보존한다. mart에는 원문명·영문명·mapping status를 함께 노출하고 표시명은
`COALESCE(english_name, original_name, 'Unknown')`으로 만든다. 번역 누락을 카테고리
자체의 누락과 혼동하지 않는다.

## 안전한 join

```text
stg_order_items (many)
  ├─ stg_orders (one, order_id)
  ├─ stg_products (one, product_id)
  │    └─ stg_category_translation (zero/one, product_category_name)
  └─ stg_sellers (one, seller_id)
```

- fact 보존을 확인할 수 있도록 many 쪽인 `stg_order_items`를 기준으로 orders, products,
  sellers, category translation을 `LEFT JOIN`한다. items→orders/products/sellers orphan은
  core relationship fail로 막고, category translation 미연결은 상태로 보존한다.
- 결제 원천은 주문당 1:N 결제행 grain이다. 주문별로 선집계한 뒤에도 판매자·카테고리로
  나눌 근거가 없으므로 이 fact에 붙이지 않고 별도 대사 모델에서만 사용한다.
- 리뷰도 주문당 여러 행이므로 이 질문의 fact에 붙이지 않는다.
- geolocation은 zip prefix가 고유하지 않아 core에서 제외한다.

## 범위와 날짜

- `fct_order_items`: status로 사전 필터하지 않고 모든 원천 order item과 그 부모 주문
  상태를 보존한다. item이 없는 주문은 이 fact에 없으며 `stg_orders`에서 보존한다.
- primary category/seller mart: `order_status = 'delivered'`만 포함한다.
- 기준 월: `order_purchase_timestamp`의 calendar month.
- delivered는 완료된 배송 주문이라는 분석 범위일 뿐 매출 인식을 보장하지 않는다.

## 핵심 지표

| 지표 | 공식 | 해석 경계 |
|---|---|---|
| `gross_item_value` | `SUM(price)` | 상품 거래액 성격이며 매출·이익 아님 |
| `freight_amount` | `SUM(freight_value)` | 배송비 합계 |
| `item_side_amount` | `SUM(price + freight_value)` | 결제액과 동일하다고 가정하지 않음 |
| `ordered_item_row_count` | `COUNT(*)` | 별도 quantity가 없어 판매수량이 아니라 주문상품 행 수 |
| `distinct_product_count` | `COUNT(DISTINCT product_id)` | 상품 종류 수 |
| `associated_order_count` | `COUNT(DISTINCT order_id)` | 해당 그룹 상품이 포함된 주문 수 |

한 주문에 여러 판매자나 카테고리가 있을 수 있으므로 그룹별
`associated_order_count`는 비가산적이다. 판매자나 카테고리 행의 주문 수를 더해 전체
주문 수라고 표현하지 않는다.

## 검산과 테스트

- staging과 `fct_order_items`의 행 수, key 수, `price`, `freight_value` 합계가 같다.
- items→orders/products/sellers 결합 전후 fact 행 수가 같다.
- fact key는 unique·not null이다.
- category/seller mart의 `gross_item_value`, `freight_amount`, `item_side_amount`,
  `ordered_item_row_count` 합계는 delivered fact의 대응 합계와 같다.
- missing/unmapped category 그룹을 포함해야 category mart 금액 대사가 성립한다.
- category mart의 `SUM(associated_order_count)`는 delivered fact의
  `COUNT(DISTINCT (purchase_month, order_id, category_key))`와, seller mart의 합계는
  `COUNT(DISTINCT (purchase_month, order_id, seller_id))`와 각각 대사한다. 이 값들은
  전체 distinct 주문 수와 같을 필요가 없다.
- `distinct_product_count`와 `associated_order_count`는 그룹 간 비가산 지표이므로
  mart 행의 단순 합을 fact 전체 distinct 수와 비교하지 않는다.
- fixture에서 상품과 결제를 직접 조인하면 금액이 증가하고, 선집계 구조에서는 같은
  원천 금액이 유지되는 red→green 테스트를 둔다.

---

# 2. 배송·리뷰 모델 계약 — Accepted

## 비즈니스 질문

리뷰가 있는 배송 완료 주문에서 약속한 달력 날짜를 넘긴 주문과 넘기지 않은 주문의
주문별 평균 리뷰 점수를 비교한다.

이 결과는 관찰적 연관이며 배송 지연이 리뷰 점수를 변화시켰다는 인과로 해석하지 않는다.

## 모델과 grain

| 모델 | 한 행의 의미 | key | 주요 정책 |
|---|---|---|---|
| `stg_reviews` | 원천 리뷰 1행 | `(review_id, order_id)` | `order_id` 단독 unique 가정 금지 |
| `int_order_review_summary` | 리뷰가 있는 주문 1건 | `order_id` | 모든 리뷰의 count·sum·avg·min·max 보존 |
| `int_order_delivery_timing` | 주문 1건 | `order_id` | delivered에만 지연 상태 산출; 그 외는 `not_applicable` |
| `mart_delivery_review_orders` | 분석 가능한 배송 완료·리뷰 보유 주문 1건 | `order_id` | date 기준 배송 상태와 주문별 리뷰 요약 결합 |

## 복수 리뷰

- primary 정책은 한 주문의 모든 리뷰 점수를 평균한다.
- `review_count`, `review_score_sum`, `avg`, `min`, `max`를 함께 보존한다.
- 최초 또는 최신 리뷰를 대표값으로 임의 선택하지 않는다.
- raw review grain 분석이 필요하면 별도 보조 모델에서 수행하며 주문 단위 결과와 섞지 않는다.

## 배송 대상과 지연 정의

primary cohort 조건:

1. `order_status = 'delivered'`
2. 실제 고객 배송일과 예정 배송일이 모두 존재하고 변환 가능
3. 리뷰 요약이 존재

리뷰 점수의 변환과 1–5 domain은 staging에서 fail로 검증한다. 이상값을 final cohort에서
조용히 제외해 통과시키지 않는다.

```text
delivery_days_vs_estimate
  = DATE(order_delivered_customer_date)
  - DATE(order_estimated_delivery_date)

delivery_timing_status
  < 0  → early
  = 0  → promised_date
  > 0  → late
  NULL → unknown (delivered 주문만)
```

비-delivered 주문은 `not_applicable`로 두며 `unknown`에 포함하지 않는다. 현재 snapshot에서
예정일이 date-like 자정 시각으로 관찰되고 같은 날짜의 오후 배송이 timestamp상 지연으로
분류될 수 있으므로, core 지연 판단에는 calendar date를 쓴다. 같은 달력 날짜의 배송은
지연으로 분류하지 않는다.

## NULL과 시간 역전

- delivered인데 실제 배송일이 없는 주문은 삭제·대체하지 않고 `unknown`과
  `is_delivery_date_missing` flag로 보존한다.
- unknown은 primary late-vs-review 분모에서는 제외하고 제외 건수를 함께 대사한다.
- purchase/approval/carrier/customer 시간 역전은 원천을 수정하지 않고 boolean flag로
  보존한다.
- chronology 이상만을 이유로 주문 전체를 primary 분석에서 제거하지 않는다.
- `approval - purchase`, `carrier - purchase`, `customer - carrier`,
  `customer - purchase`처럼 논리적으로 음수가 될 수 없는 소요시간은 관련 timestamp의
  순서가 뒤집히면 그 duration만 NULL 처리하고 제외 건수를 검산한다.
- `customer_delivery_date - estimated_delivery_date`의 음수는 조기 배송이라는 정상 분석
  값이므로 chronology anomaly로 처리하거나 NULL로 바꾸지 않는다.

## 핵심 지표

| 지표 | 공식 | 해석 경계 |
|---|---|---|
| `eligible_reviewed_order_count` | `COUNT(*)` | date 비교 가능 delivered 중 리뷰 요약이 있는 주문 수 |
| `avg_order_review_score` | `AVG(order_avg_review_score)` | 주문별 평균을 다시 평균해 주문을 동일 가중 |
| `late_reviewed_order_count` | `COUNT(*) FILTER (WHERE is_late)` | date 기준 지연·리뷰 보유 주문 |
| `late_reviewed_order_rate` | `late_reviewed_order_count / eligible_reviewed_order_count` | final cohort 내부 비율 |
| `avg_score_difference` | `late 평균 - not-late 평균` | 기술적 차이이며 인과 효과 아님 |
| `review_coverage_rate` | date 비교 가능 delivered 중 리뷰 요약 보유 주문 / date 비교 가능 delivered 주문 | 리뷰 누락 규모·대표성 위험 확인용 |

## 검산과 테스트

- `stg_reviews`의 composite key는 unique·not null이며 `order_id`에는 unique test를 걸지 않는다.
- `int_order_review_summary`는 `order_id` unique·not null이다.
- review summary의 `SUM(review_count)`와 `SUM(review_score_sum)`은 staging과 같다.
- 주문별 `avg_score = review_score_sum / review_count`이며 조기 반올림하지 않는다.
  `min_score <= avg_score <= max_score`, `review_count >= 1`도 확인한다.
- delivered subset에서만 `early + promised_date + late + unknown`이 delivered 전체와
  대사되며, 비-delivered는 `not_applicable`과 대사된다.
- final mart의 inclusion funnel을 delivered 전체 → date 비교 가능 delivered
  → 그중 review summary 존재 순서로 대사하고 각 단계의 제외 건수를 기록한다.
- intermediate timing status는 `early`, `promised_date`, `late`, `unknown`,
  `not_applicable`만 허용한다. final mart는 `order_status = 'delivered'`, 두 배송 날짜
  not null, timing status가 `early`, `promised_date`, `late` 중 하나인지와
  `is_late = (delivery_days_vs_estimate > 0)`를 검증한다.
- final mart의 review count·score sum은 review summary의 해당 subset과 대사한다.
- not-late는 `early OR promised_date`다. late 또는 not-late가 0건이면 해당 평균과
  `avg_score_difference`는 NULL로 둔다.
- 복수 리뷰 fixture에서 raw join은 주문 중복 테스트가 실패하고, 리뷰 선집계 후에는
  주문 key unique 테스트가 통과해야 한다.
- 예정일 자정과 같은 날 오후 배송 fixture로 timestamp와 date 정의 차이를 재현한다.

---

# 3. 데이터 품질 정책 — Accepted

## Fail

- 핵심 primary/composite key의 not null·unique
- core relationship인 items→orders/products/sellers, orders→customers,
  payments→orders, reviews→orders의 orphan
- 계약 열의 non-null 원천값 cast 실패. not-null은 `price`, `freight_value`,
  `order_item_id`, `order_purchase_timestamp`, `order_estimated_delivery_date`,
  결제 열과 review score 등 실제 필수 열에만 적용한다. approval/carrier/customer date의
  NULL은 주문 상태에 따라 warn·flag로 다룬다.
- `order_status`: `approved`, `canceled`, `created`, `delivered`, `invoiced`,
  `processing`, `shipped`, `unavailable`과 not null
- `payment_type`: `boleto`, `credit_card`, `debit_card`, `not_defined`, `voucher`와
  not null. `not_defined`는 관찰된 값으로 보존한다.
- review row의 `review_score`: 정수 1–5와 not null
- `price > 0`, `freight_value >= 0`, `payment_value >= 0`
- `order_item_id > 0`, `payment_sequential > 0`, `payment_installments >= 0`

## Warn·flag·보존

- `freight_value = 0`: 허용
- `payment_value = 0`, `payment_installments = 0`: 보존하고 후속 조사
- chronology 역전: flag와 건수 대사, 원천 행 보존
- delivered 주문의 실제 배송일 NULL: flag, 지연 분모 제외 건수 대사
- 상품만 또는 결제만 있는 주문: 상태별 flag, global inner join 금지
- 상품 측·결제 측 금액 차이: 양쪽 measure와 차이를 보존하고 hard fail 금지
- `shipping_limit_date`의 극단값: 보존하고 purchase/status와의 관계를 적재 후 조사
- products→category translation 미연결: missing/unmapped 그룹으로 보존하고 건수 대사
- customers/sellers→geolocation: core relationship test 비범위이며 직접 join하지 않음

`accepted_values`는 현재 고정 Olist snapshot의 schema 계약이다. 다른 데이터셋이나 향후
새 snapshot에서 새로운 정상 상태가 생길 가능성까지 일반화한 규칙으로 표현하지 않는다.

---

# 4. 이번 계약의 비범위와 미정 항목

## 비범위

- payment 금액을 판매자·카테고리에 임의 배분
- 그룹 주문 수를 맞추기 위한 fractional allocation
- geolocation 원천을 zip prefix로 직접 조인
- 최초·최신 리뷰를 대표 리뷰로 단정
- 취소·환불·수수료·원가가 필요한 매출·순매출·이익
- 배송 지연과 리뷰 점수의 인과 효과

## `[UNRESOLVED]` — DB 적재 후 관찰

- `payment_value = 0`, `payment_installments = 0`의 상태·결제수단별 의미
- 상품 측·결제 측 금액 차이에 실제 tolerance를 둘지
- 큰 금액 차이 주문의 공통 특성
- `shipping_limit_date` 극단값의 주문별 맥락과 상한 규칙
- chronology anomaly flag의 중복과 sensitivity 결과
- review timestamp와 customer delivery timestamp의 교차소스 순서
- geolocation 대표값이 실제 core 질문에 필요한지와 대표 정책

## 사용자 승인 항목

- [x] 전체 상태 item fact를 보존하고 primary 거래 mart는 delivered만 사용한다.
- [x] 거래 기준 기간은 purchase calendar month를 사용한다.
- [x] category와 seller mart를 분리하고 그룹별 distinct 주문 수는 서로 더하지 않는다.
- [x] 상품 거래액은 `SUM(price)`, 배송비는 별도 지표로 둔다.
- [x] 배송·리뷰 final mart는 주문당 1행으로 만든다.
- [x] 복수 리뷰는 주문별 모든 리뷰 평균을 primary 값으로 사용한다.
- [x] 배송 지연은 delivered 주문의 calendar date 기준으로 정의한다.
- [x] 배송일 NULL과 chronology 역전은 삭제하지 않고 flag·warn·제외 수 대사로 관리한다.
- [x] 확실한 schema/domain만 fail로 두고 금액 tolerance 등은 적재 후 결정한다.
- [x] timezone 없는 원천 timestamp는 timezone 추정 없이 `timestamp without time zone`으로 다룬다.
- [x] 결제는 거래 fact에 배분하지 않고 주문별 지원 모델에서 상품 측 금액과 별도 대사한다.
- [x] core FK는 fail, category translation 누락은 보존, geolocation 관계는 core 비범위로 둔다.
