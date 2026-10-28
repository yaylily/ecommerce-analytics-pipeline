# 주문 단위 intermediate·audit 모델 검증

## 목적과 범위

주문상품·결제·리뷰처럼 주문에 여러 행이 연결되는 원천을 그대로 결합하면 행과 금액이
증폭될 수 있다. 이번 단계에서는 승인된
[model/metric contract](../docs/model-metric-contracts.md)에 따라 각 원천을 먼저 주문
단위로 집계하고, 금액 차이·배송일 결측·시간 역전을 삭제하거나 교정하지 않은 채
검토 가능한 상태로 보존한다.

구현 범위는 다음 5개 model이다.

- `int_order_item_amount_summary`: 주문상품 행이 있는 주문 1건
- `int_order_payment_summary`: 결제 행이 있는 주문 1건
- `audit_order_amount_reconciliation`: 전체 주문 기준 주문 1건
- `int_order_review_summary`: 리뷰가 있는 주문 1건
- `int_order_delivery_timing`: 전체 주문 기준 주문 1건

이번 범위에는 product/seller dimension, item fact, 최종 mart, 배송·리뷰 관계 분석과
pandas 산출물이 포함되지 않는다. Category mapping, `shipping_limit_date` 극단값과
금액 차이 tolerance도 아직 확정하지 않는다.

## 구현 원칙

### 1. 주문 단위 선집계

주문상품·결제·리뷰는 서로 직접 결합하지 않는다. 각각 `order_id`로 먼저 집계한 뒤
필요한 model에서만 주문과 결합한다. 상품 측 금액은 다음 세 값으로 나눠 보존한다.

- `gross_item_value = SUM(price)`
- `freight_amount = SUM(freight_value)`
- `item_side_amount = SUM(price + freight_value)`

결제 측은 `payment_side_amount = SUM(payment_value)`로 별도 보존한다. 결제액을 상품,
카테고리나 판매자에게 임의로 배분하지 않는다.

### 2. NULL과 0의 구분

금액 audit는 전체 주문을 기준으로 두 summary를 `LEFT JOIN`한다. 한쪽 원천 행이 없는
주문의 measure와 count를 0으로 바꾸지 않고 NULL로 남긴다. 따라서 “실제 0원”과
“그 측의 행 자체가 없음”을 구분할 수 있다.

0원 결제와 0회 할부는 오류로 판정하거나 삭제하지 않는다. 주문별 행 수와 존재 flag로
보존해 후속 조사가 가능하게 했다.

### 3. exact 차이 보존

양쪽 금액이 있는 주문에만 다음 값을 계산한다.

```text
payment_minus_item_amount = payment_side_amount - item_side_amount
absolute_amount_difference = ABS(payment_minus_item_amount)
```

`equal`, `item_side_greater`, `payment_side_greater`는 관찰된 정확 비교 방향이다. 현재
tolerance가 승인되지 않았으므로 작은 차이도 실패나 허용으로 판정하지 않는다. 한쪽이
없으면 `not_comparable`로 두고 차이는 NULL로 남긴다.

### 4. 리뷰와 배송 날짜

복수 리뷰는 최초·최신 하나를 고르지 않고 주문별 count·sum·평균·최솟값·최댓값을 모두
보존한다. 평균은 조기 반올림하지 않는다.

배송 지연은 `delivered` 주문에만 다음 달력 날짜 차이로 계산한다.

```text
DATE(order_delivered_customer_date) - DATE(order_estimated_delivery_date)
```

- 음수: `early`
- 0: `promised_date`
- 양수: `late`
- delivered이지만 날짜 비교 불가: `unknown`
- 비-delivered: `not_applicable`

같은 날짜의 오후 배송을 예정일 자정보다 늦은 timestamp라는 이유로 지연 처리하지 않는다.

### 5. 시간 역전과 duration

구매·승인·출고·고객 배송 timestamp를 원천 그대로 유지한다. 두 시각을 비교할 수 없으면
chronology flag는 NULL, 비교 가능하고 정상 순서이면 false, 역전이면 true다. Duration은
관련 시각이 모두 있고 순서가 정상일 때만 계산하며, 역전된 값을 양수로 보정하지 않는다.

조기 배송에서 `고객 배송일 - 예정 배송일`이 음수인 것은 정상 분석값이므로 chronology
오류로 취급하지 않는다.

## 검증 결과

### 주문상품·결제 선집계

- Item summary: 98,666개 주문
- 원천 주문상품 행 수 대사: 112,650행
- 상품 거래액 성격 합계: 13,591,643.70
- 배송비 합계: 2,251,909.54
- 상품 측 금액 합계: 15,843,553.24
- Payment summary: 99,440개 주문
- 원천 결제 행 수 대사: 103,886행
- 결제 측 금액 합계: 16,008,872.12
- 0원 결제: 9행, 8개 주문
- 0회 할부: 2행, 2개 주문

상품 측 금액은 회사 매출·순매출·이익이 아니다. 결제 측 금액과 서로 다른 원천에서
관찰한 measure이며, 둘이 항상 같다고 가정하지 않는다.

### 전체 주문 금액 audit

전체 99,441개 주문이 다음과 같이 빠짐없이 나뉘었다.

- 상품·결제 양쪽 존재: 98,665
- 상품만 존재: 1
- 결제만 존재: 775
- 양쪽 모두 없음: 0

양쪽이 있는 주문 98,665개 중 exact 비교 결과는 다음과 같다.

- 금액 동일: 98,089
- 상품 측이 큼: 209
- 결제 측이 큼: 367
- `payment - item` 순차이 합: 2,870.39
- 절대 차이 합: 3,271.95

이 차이는 현재 snapshot의 관찰 결과다. 반올림 오류, 환불, 수수료 등 원인을 이
model만으로 확정하지 않으며, 절대 차이 구간도 테스트 합격 기준으로 사용하지 않는다.

### 리뷰 선집계

- 리뷰 summary: 98,673개 주문
- `SUM(review_count)`: 99,224행으로 staging 리뷰 행 수와 일치
- `SUM(review_score_sum)`: 405,471로 staging 점수 합과 일치
- 주문별 리뷰 수 범위: 1~3
- 평균 공식, `min <= avg <= max`, key 규칙 위반: 0

리뷰 원문, 실제 review ID와 order ID는 test fixture와 보고서에 포함하지 않았다.

### 배송 timing

전체 99,441개 주문이 다음 5개 상태와 대사됐다.

- `early`: 88,644
- `promised_date`: 1,292
- `late`: 6,534
- `unknown`: 8
- `not_applicable`: 2,963

`unknown` 8개는 delivered이지만 실제 고객 배송일이 없는 주문이다. 이를 지연·비지연
어느 쪽에도 넣지 않는다. 비-delivered 주문은 날짜가 있더라도 core 지연 상태를 계산하지
않고 `not_applicable`로 둔다.

### 결측과 chronology flag

- 승인 timestamp 없음: 160
- 출고 timestamp 없음: 1,783
- delivered 주문의 실제 고객 배송일 없음: 8
- 승인 시각이 구매보다 빠름: 0
- 출고 시각이 구매보다 빠름: 166
- 출고 시각이 승인보다 빠름: 1,359
- 고객 배송 시각이 구매보다 빠름: 0
- 고객 배송 시각이 출고보다 빠름: 23

Flag는 한 주문에서 겹칠 수 있으므로 위 역전 건수를 더해 이상 주문 수라고 표현하지
않는다. 역전은 원천 행 삭제나 pipeline hard fail 조건이 아니라 후속 해석을 위한 flag다.

## 자동 검증

Intermediate 계층은 고정 snapshot에서 결과를 직접 검토하고 downstream test가 같은
집계를 반복하지 않도록 PostgreSQL table로 materialize했다. 이 선택은 로컬 프로젝트의
재현과 검토를 위한 것이며 production 성능 최적화 경험을 의미하지 않는다.

각 model에는 출력 열 이름·타입을 강제하는 model contract와 다음 검증을 연결했다.

- 주문 단위 key의 unique·not null과 orders relationship
- 전체 주문 기준 model의 staging 대비 행 수 보존
- Item·payment·review count와 금액·점수 합의 staging 대사
- 금액 audit의 side 존재 여부, NULL, 차이 공식과 상태 일치
- 배송 상태, 달력 날짜 차이, `is_late`, 결측·역전 flag와 duration 공식 일치
- 합성 상품 2행 × 결제 3행의 직접 조인 6행·금액 증폭 재현
- 같은 fixture를 선집계한 뒤 원천 금액 유지
- 합성 복수 리뷰의 직접 결합 중복과 선집계 후 주문 key unique 복구
- 예정일 자정·같은 날 오후 배송 fixture의 calendar-date 0일 차이 확인

`numeric` 출력 열은 staging과 같이 precision·scale 제한을 임의로 추가하지 않았다.
dbt model contract가 이 열들에 참고 경고를 출력하지만, 현재 PostgreSQL에서는 제한 없는
`numeric`으로 생성된다. 운영 schema나 다른 warehouse로 옮길 때 자리수 정책을 별도로
결정해야 한다.

## 실행 결과와 재현

실제 local PostgreSQL snapshot에서 intermediate model 5개와 연결된 data test 65개가
통과했다. 별도 singular suite의 주문별 staging 대사·합성 fixture 8개도 모두 통과했다.
최종 전체 회귀 검증에서는 staging 9개와 intermediate 5개, data test 123개를 합한
137개 node가 모두 통과했다(`PASS=137`, `WARN=0`, `ERROR=0`, `SKIP=0`).
기존 Python profiler·raw loader test 24개도 PostgreSQL 통합 test 3개를 포함해 모두
통과했다.

4개 병렬 singular test를 한 번에 실행했을 때 local Docker PostgreSQL의 shared-memory
제약으로 audit test 1개가 중단됐다. 같은 test는 직전 build, 단일 thread singular suite와
최종 전체 build에서 모두 통과했다. 이는 데이터 규칙 실패가 아니라 병렬 실행 시 로컬
환경의 자원 경합으로 확인했으며 재현 명령에는 단일 thread를 명시한다.

승인된 raw와 staging이 준비된 환경에서 다음 명령으로 전체 dbt graph를 재현한다.

```bash
.venv/bin/dbt build --profiles-dir . --threads 1
```

성공 기준은 staging 9개와 intermediate 5개 model, data test 123개가 모두 통과하고
ERROR·SKIP이 0인 것이다.

## 해석 한계와 다음 결정

이번 결과로 말할 수 있는 것은 주문 단위 선집계가 원천 count·금액·점수 합을 보존하고,
전체 주문의 측별 존재 여부와 배송·chronology 상태를 삭제 없이 재현했다는 점이다.

다음은 아직 말할 수 없거나 결정하지 않았다.

- 금액 차이의 원인과 허용 tolerance
- 0원 결제·0회 할부의 업무상 정상·오류 판정
- `shipping_limit_date` 극단값의 상한 정책
- chronology flag 중복이 최종 분석에 미치는 영향
- review timestamp와 고객 배송 timestamp의 교차소스 순서
- 배송 지연과 리뷰 점수의 관계 또는 인과 효과
- category mapping, item fact와 최종 mart의 정확성

이 보고서의 수치와 경계를 검토한 뒤 product/seller dimension과 item fact 구현으로
진행한다.
