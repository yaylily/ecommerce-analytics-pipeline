# 원천 데이터 값 프로파일

집계 관찰 결과이며 승인된 데이터 제약이나 지표 정의가 아닙니다.
핵심 질문에 필요한 계약 지정 15개 열만 선택 검사했으며 9개 파일의 모든 열을 검사한 결과가 아닙니다.
계약에 공개를 허용한 도메인 값만 표시하며 기타 값, 원천 행, 식별자와 샘플은 표시하지 않습니다.
타입 변환 가능성은 Python 파서 기준의 사전 점검이며 PostgreSQL 변환 성공을 보장하지 않습니다.
원천 timestamp에는 timezone 정보가 없어 별도의 timezone을 추정하지 않습니다.
상품 측 금액과 결제 측 금액의 비교는 원천 간 대사 관찰이며 매출·이익을 뜻하지 않습니다.
금액 차이 구간은 분포 설명용이며 통과 기준이 아닙니다.
정확히 같은 키는 별도 집계하며 절대 차이 구간에는 포함하지 않습니다.

- Dataset: `olistbr/brazilian-ecommerce`
- Manifest SHA-256: `041d600393762a8894f995816d71f805ac09672b8ce2ea7d134ce3a0669f71bb`

## 타입 변환 가능성

| 테이블 | 열 | 대상 타입 | 전체 | NULL | 변환 가능 | 변환 실패 | 0 | 음수 | 최소 | 최대 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `order_items` | `freight_value` | `decimal` | 112650 | 0 | 112650 | 0 | 383 | 0 | 0.00 | 409.68 |
| `order_items` | `order_item_id` | `integer` | 112650 | 0 | 112650 | 0 | 0 | 0 | 1 | 21 |
| `order_items` | `price` | `decimal` | 112650 | 0 | 112650 | 0 | 0 | 0 | 0.85 | 6735.00 |
| `order_items` | `shipping_limit_date` | `timestamp` | 112650 | 0 | 112650 | 0 | N/A | N/A | 2016-09-19 00:15:34 | 2020-04-09 22:35:08 |
| `orders` | `order_approved_at` | `timestamp` | 99441 | 160 | 99281 | 0 | N/A | N/A | 2016-09-15 12:16:38 | 2018-09-03 17:40:06 |
| `orders` | `order_delivered_carrier_date` | `timestamp` | 99441 | 1783 | 97658 | 0 | N/A | N/A | 2016-10-08 10:34:01 | 2018-09-11 19:48:28 |
| `orders` | `order_delivered_customer_date` | `timestamp` | 99441 | 2965 | 96476 | 0 | N/A | N/A | 2016-10-11 13:46:32 | 2018-10-17 13:22:46 |
| `orders` | `order_estimated_delivery_date` | `timestamp` | 99441 | 0 | 99441 | 0 | N/A | N/A | 2016-09-30 00:00:00 | 2018-11-12 00:00:00 |
| `orders` | `order_purchase_timestamp` | `timestamp` | 99441 | 0 | 99441 | 0 | N/A | N/A | 2016-09-04 21:15:19 | 2018-10-17 17:30:18 |
| `payments` | `payment_installments` | `integer` | 103886 | 0 | 103886 | 0 | 2 | 0 | 0 | 24 |
| `payments` | `payment_sequential` | `integer` | 103886 | 0 | 103886 | 0 | 0 | 0 | 1 | 29 |
| `payments` | `payment_value` | `decimal` | 103886 | 0 | 103886 | 0 | 9 | 0 | 0.00 | 13664.08 |
| `reviews` | `review_answer_timestamp` | `timestamp` | 99224 | 0 | 99224 | 0 | N/A | N/A | 2016-10-07 18:32:28 | 2018-10-29 12:27:35 |
| `reviews` | `review_creation_date` | `timestamp` | 99224 | 0 | 99224 | 0 | N/A | N/A | 2016-10-02 00:00:00 | 2018-08-31 00:00:00 |
| `reviews` | `review_score` | `integer` | 99224 | 0 | 99224 | 0 | 0 | 0 | 1 | 5 |

최소·최대는 해당 열에서 변환 가능한 값의 범위이며 데이터셋 전체 기간이나 범위를 뜻하지 않습니다.
`shipping_limit_date`의 최대값이 2020년으로 관찰되는 이유는 후속 원천·모델 계약에서 확인합니다.

## 공개 가능한 도메인 분포

명시된 값은 관찰을 위해 공개한 값이며 업무상 허용값으로 승인된 것은 아닙니다.

| 테이블 | 프로파일 | 값 | 행 | NULL | 기타 행 | 기타 고유값 수 |
|---|---|---|---:|---:|---:|---:|
| `orders` | `order_status` | `approved` | 2 | 0 | 0 | 0 |
| `orders` | `order_status` | `canceled` | 625 | 0 | 0 | 0 |
| `orders` | `order_status` | `created` | 5 | 0 | 0 | 0 |
| `orders` | `order_status` | `delivered` | 96478 | 0 | 0 | 0 |
| `orders` | `order_status` | `invoiced` | 314 | 0 | 0 | 0 |
| `orders` | `order_status` | `processing` | 301 | 0 | 0 | 0 |
| `orders` | `order_status` | `shipped` | 1107 | 0 | 0 | 0 |
| `orders` | `order_status` | `unavailable` | 609 | 0 | 0 | 0 |
| `payments` | `payment_type` | `boleto` | 19784 | 0 | 0 | 0 |
| `payments` | `payment_type` | `credit_card` | 76795 | 0 | 0 | 0 |
| `payments` | `payment_type` | `debit_card` | 1529 | 0 | 0 | 0 |
| `payments` | `payment_type` | `not_defined` | 3 | 0 | 0 | 0 |
| `payments` | `payment_type` | `voucher` | 5775 | 0 | 0 | 0 |
| `reviews` | `review_score` | `1` | 11424 | 0 | 0 | 0 |
| `reviews` | `review_score` | `2` | 3151 | 0 | 0 | 0 |
| `reviews` | `review_score` | `3` | 8179 | 0 | 0 | 0 |
| `reviews` | `review_score` | `4` | 19142 | 0 | 0 | 0 |
| `reviews` | `review_score` | `5` | 57328 | 0 | 0 | 0 |

## 날짜·시간 비교

왼쪽과 오른쪽의 선후 관계를 집계하며 chronology와 delivery_timing을 구분합니다.
전체표에는 주문 상태 필터를 적용하지 않았으며, 상태별 표를 함께 확인해야 결측과 역전을 오류로 오해하지 않습니다.
timestamp 비교와 date 비교는 다릅니다. 예정일이 자정이면 같은 달력 날짜의 배송도 timestamp상 늦게 보일 수 있습니다.
`review_creation↔customer_delivery`와 `shipping_limit↔purchase`는 서로 다른 파일을 연결해야 하므로 후속 모델 계약 검토 항목입니다.

| 비교 | 왼쪽 열 | 오른쪽 열 | 종류 | 단위 | 비교 가능 | NULL로 비교 불가 | 변환 실패로 비교 불가 | 왼쪽 < 오른쪽 | 같음 | 왼쪽 > 오른쪽 | 왼쪽 NULL/실패 | 오른쪽 NULL/실패 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `approval_vs_carrier` | `order_approved_at` | `order_delivered_carrier_date` | `chronology` | `timestamp` | 97644 | 1797 | 0 | 96285 | 0 | 1359 | 160/0 | 1783/0 |
| `carrier_vs_customer` | `order_delivered_carrier_date` | `order_delivered_customer_date` | `chronology` | `timestamp` | 96475 | 2966 | 0 | 96443 | 9 | 23 | 1783/0 | 2965/0 |
| `delivered_vs_estimated_date` | `order_delivered_customer_date` | `order_estimated_delivery_date` | `delivery_timing` | `date` | 96476 | 2965 | 0 | 88649 | 1292 | 6535 | 2965/0 | 0/0 |
| `delivered_vs_estimated_timestamp` | `order_delivered_customer_date` | `order_estimated_delivery_date` | `delivery_timing` | `timestamp` | 96476 | 2965 | 0 | 88649 | 0 | 7827 | 2965/0 | 0/0 |
| `purchase_vs_approval` | `order_purchase_timestamp` | `order_approved_at` | `chronology` | `timestamp` | 99281 | 160 | 0 | 97985 | 1296 | 0 | 0/0 | 160/0 |
| `purchase_vs_carrier` | `order_purchase_timestamp` | `order_delivered_carrier_date` | `chronology` | `timestamp` | 97658 | 1783 | 0 | 97492 | 0 | 166 | 0/0 | 1783/0 |
| `purchase_vs_customer` | `order_purchase_timestamp` | `order_delivered_customer_date` | `chronology` | `timestamp` | 96476 | 2965 | 0 | 96476 | 0 | 0 | 0/0 | 2965/0 |
| `purchase_vs_estimated` | `order_purchase_timestamp` | `order_estimated_delivery_date` | `chronology` | `timestamp` | 99441 | 0 | 0 | 99441 | 0 | 0 | 0/0 | 0/0 |
| `review_creation_vs_answer` | `review_creation_date` | `review_answer_timestamp` | `chronology` | `timestamp` | 99224 | 0 | 0 | 99224 | 0 | 0 | 0/0 | 0/0 |

같은 달력 날짜지만 timestamp 기준으로 배송 시각이 예정 시각보다 늦은 행은 1292건입니다.

### `approval_vs_carrier` 상태별

| 주문 상태 | 전체 | 비교 가능 | NULL로 비교 불가 | 변환 실패로 비교 불가 | 왼쪽 < 오른쪽 | 같음 | 왼쪽 > 오른쪽 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `approved` | 2 | 0 | 2 | 0 | 0 | 0 | 0 |
| `canceled` | 625 | 75 | 550 | 0 | 75 | 0 | 0 |
| `created` | 5 | 0 | 5 | 0 | 0 | 0 | 0 |
| `delivered` | 96478 | 96462 | 16 | 0 | 95112 | 0 | 1350 |
| `invoiced` | 314 | 0 | 314 | 0 | 0 | 0 | 0 |
| `processing` | 301 | 0 | 301 | 0 | 0 | 0 | 0 |
| `shipped` | 1107 | 1107 | 0 | 0 | 1098 | 0 | 9 |
| `unavailable` | 609 | 0 | 609 | 0 | 0 | 0 | 0 |
| 기타(값 비공개) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NULL | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

### `carrier_vs_customer` 상태별

| 주문 상태 | 전체 | 비교 가능 | NULL로 비교 불가 | 변환 실패로 비교 불가 | 왼쪽 < 오른쪽 | 같음 | 왼쪽 > 오른쪽 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `approved` | 2 | 0 | 2 | 0 | 0 | 0 | 0 |
| `canceled` | 625 | 6 | 619 | 0 | 6 | 0 | 0 |
| `created` | 5 | 0 | 5 | 0 | 0 | 0 | 0 |
| `delivered` | 96478 | 96469 | 9 | 0 | 96437 | 9 | 23 |
| `invoiced` | 314 | 0 | 314 | 0 | 0 | 0 | 0 |
| `processing` | 301 | 0 | 301 | 0 | 0 | 0 | 0 |
| `shipped` | 1107 | 0 | 1107 | 0 | 0 | 0 | 0 |
| `unavailable` | 609 | 0 | 609 | 0 | 0 | 0 | 0 |
| 기타(값 비공개) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NULL | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

### `delivered_vs_estimated_date` 상태별

| 주문 상태 | 전체 | 비교 가능 | NULL로 비교 불가 | 변환 실패로 비교 불가 | 왼쪽 < 오른쪽 | 같음 | 왼쪽 > 오른쪽 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `approved` | 2 | 0 | 2 | 0 | 0 | 0 | 0 |
| `canceled` | 625 | 6 | 619 | 0 | 5 | 0 | 1 |
| `created` | 5 | 0 | 5 | 0 | 0 | 0 | 0 |
| `delivered` | 96478 | 96470 | 8 | 0 | 88644 | 1292 | 6534 |
| `invoiced` | 314 | 0 | 314 | 0 | 0 | 0 | 0 |
| `processing` | 301 | 0 | 301 | 0 | 0 | 0 | 0 |
| `shipped` | 1107 | 0 | 1107 | 0 | 0 | 0 | 0 |
| `unavailable` | 609 | 0 | 609 | 0 | 0 | 0 | 0 |
| 기타(값 비공개) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NULL | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

### `purchase_vs_carrier` 상태별

| 주문 상태 | 전체 | 비교 가능 | NULL로 비교 불가 | 변환 실패로 비교 불가 | 왼쪽 < 오른쪽 | 같음 | 왼쪽 > 오른쪽 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `approved` | 2 | 0 | 2 | 0 | 0 | 0 | 0 |
| `canceled` | 625 | 75 | 550 | 0 | 75 | 0 | 0 |
| `created` | 5 | 0 | 5 | 0 | 0 | 0 | 0 |
| `delivered` | 96478 | 96476 | 2 | 0 | 96311 | 0 | 165 |
| `invoiced` | 314 | 0 | 314 | 0 | 0 | 0 | 0 |
| `processing` | 301 | 0 | 301 | 0 | 0 | 0 | 0 |
| `shipped` | 1107 | 1107 | 0 | 0 | 1106 | 0 | 1 |
| `unavailable` | 609 | 0 | 609 | 0 | 0 | 0 | 0 |
| 기타(값 비공개) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NULL | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## 주문 기준 상품 측·결제 측 금액 대사

### `items_vs_payments_by_order`

- 비교 범위: 기준 키 중 상품·결제 양쪽이 존재하고 선택한 금액값이 모두 변환 가능한 키
- 상품 측 계산: 주문별 `SUM(price + freight_value)`
- 결제 측 계산: 주문별 `SUM(payment_value)`
- 주문 상태 필터: 적용하지 않음
- 전체 기준 키: 99441
- 양쪽 존재 / 비교 가능 / 값 불완전: 98665 / 98665 / 0
- 상품 측만 / 결제 측만 / 양쪽 없음: 1 / 775 / 0
- 정확히 같음 / 상품 측 큼 / 결제 측 큼: 98089 / 209 / 367
- 상품 측 합계: 15843409.78
- 결제 측 합계: 15846280.17
- 순차이(결제 측-상품 측): 2870.39
- 순차이는 양수·음수 주문이 서로 상쇄될 수 있어 품질 통과 기준으로 사용하지 않음
- 절대 차이 합계 / 키별 최대 절대 차이: 3271.95 / 182.81
- 0이 아닌 절대 차이 구간(0 < |차이| ≤ 0.01 / >0.01–1 / >1–10 / >10): 273 / 54 / 151 / 98

#### 주문 상태별 비교 범위와 방향

| 주문 상태 | 기준 주문 | 양쪽 있음 | 비교 가능 | 금액 불완전 | 상품만 | 결제만 | 둘 다 없음 | 같음 | 상품 측 큼 | 결제 측 큼 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `approved` | 2 | 2 | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |
| `canceled` | 625 | 461 | 461 | 0 | 0 | 164 | 0 | 459 | 0 | 2 |
| `created` | 5 | 0 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| `delivered` | 96478 | 96477 | 96477 | 0 | 1 | 0 | 0 | 95908 | 207 | 362 |
| `invoiced` | 314 | 312 | 312 | 0 | 0 | 2 | 0 | 311 | 0 | 1 |
| `processing` | 301 | 301 | 301 | 0 | 0 | 0 | 0 | 301 | 0 | 0 |
| `shipped` | 1107 | 1106 | 1106 | 0 | 0 | 1 | 0 | 1102 | 2 | 2 |
| `unavailable` | 609 | 6 | 6 | 0 | 0 | 603 | 0 | 6 | 0 | 0 |
| 기타(값 비공개) | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| NULL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## 후속 계약에서 결정할 항목

- 어떤 주문 상태를 각 지표에 포함할지
- 배송 예정일 초과를 timestamp와 calendar date 중 어느 단위로 판단할지
- 시간 순서가 뒤집힌 원천 행을 보존·경고·제외 중 어떻게 처리할지
- 상품 측 금액과 결제 측 금액의 차이에 허용 기준을 둘지와 예외 처리 방식
- 관찰된 도메인을 dbt accepted-values 테스트에서 fail 또는 warn으로 관리할지
