# 배송 지연·리뷰 심화 분석 계약

> Status: Accepted / 2026-11-14
>
> 이 문서는 기존 배송·리뷰 mart를 사용하는 선택 확장의 분석 질문, 구간, 지표와
> 검산 기준을 고정한다. 계약 승인은 구현 완료나 결과 해석 승인을 뜻하지 않는다.

## 1. 분석 질문과 해석 경계

기존의 지연·비지연 이분 비교를 다음 질문으로 심화한다.

> 예정일 대비 배송 일수의 심각도에 따라 주문별 평균 리뷰 점수의 중심과 낮은 점수
> 비율이 어떻게 달라지며, 이 관계가 완전한 구매월 구간에서도 반복되는가?

분석은 고정 Olist snapshot 안의 기술통계다. 배송 지연이 리뷰 점수를 변화시켰다는
인과 효과, 미래 예측 또는 배송 개선 효과를 추정하지 않는다.

## 2. 입력, grain과 join 정책

입력은 검증된 `analytics.mart_delivery_review_orders` 한 개로 제한한다. 입력 한 행은
다음 조건을 모두 만족하는 주문 1건이며 key는 `order_id`다.

1. `order_status = 'delivered'`
2. 실제 고객 배송일과 예정 배송일의 달력 날짜를 비교할 수 있음
3. 주문 단위 리뷰 요약이 존재함

기존 계약의 다음 정책을 그대로 상속한다.

- `delivery_days_vs_estimate`는 실제 고객 배송일의 달력 날짜에서 예정 배송일의 달력
  날짜를 뺀 정수 일수다.
- 한 주문에 리뷰가 여러 개면 먼저 주문 안에서 모두 평균한
  `order_avg_review_score`를 사용한다.
- 분석 평균에서는 각 주문을 한 번씩 동일 가중한다.
- chronology flag가 있다는 이유만으로 primary 결과에서 주문을 제거하지 않는다.

raw review, 주문상품, category, seller, customer, geolocation 또는 다른 mart를 추가로
join하지 않는다. 새 dbt model이나 기존 dbt model 변경도 만들지 않는다. pandas는
mart의 grain과 승인 지표를 다시 정의하지 않고 검증·집계·시각화만 수행한다.

입력의 `order_id`는 unique·not null이어야 한다. 지연 일수와 리뷰 지표에 NULL이 있거나
승인된 final cohort 조건을 벗어난 행이 있으면 조용히 제외하지 않고 분석을 실패시킨다.

## 3. 배송 심각도 그룹

모든 입력 주문을 `delivery_days_vs_estimate`로 다음 여섯 그룹 중 정확히 하나에 배정한다.

| 순서 | 내부 key | 포함 조건 | 표시 의미 |
|---:|---|---|---|
| 1 | `early` | `< 0` | 예정일보다 이른 배송 |
| 2 | `promised_date` | `= 0` | 예정일 당일 배송 |
| 3 | `late_1_3` | `1 <= days <= 3` | 1~3일 지연 |
| 4 | `late_4_7` | `4 <= days <= 7` | 4~7일 지연 |
| 5 | `late_8_14` | `8 <= days <= 14` | 8~14일 지연 |
| 6 | `late_15_plus` | `>= 15` | 15일 이상 지연 |

경계값 `-1`, `0`, `1`, `3`, `4`, `7`, `8`, `14`, `15`를 포함한 합성 fixture로
상호배타성과 전체 포괄성을 검사한다. 양수 일수인 네 그룹은 모두 기존 계약의 `late`에
속하며, 구간화가 `is_late`의 정의를 바꾸지 않는다.

### 구간 경계의 사전 근거

읽기 전용 preflight에서 지연 주문의 `delivery_days_vs_estimate` 분포는
`p25 = 3`, `median = 7`, `p75 = 13`, `max = 188`일로 관찰됐다. 이를 바탕으로
표본을 지나치게 잘게 나누지 않으면서 해석 가능한 일수 범위를 만들기 위해 위 구간을
채택했다. `p75 = 13`을 그대로 통계적 절단점으로 복제한 것이 아니라 8~14일을 하나의
달력 일수 구간으로 묶고 15일 이상을 긴 지연 꼬리로 분리한 분석용 분류다.

이 경계는 SLA, 배송 약속 기준, 품질 합격선 또는 업무 성과 목표가 아니다. `max = 188`인
관찰값도 임의 제거·winsorize하지 않고 15일 이상 그룹에 보존한다.

## 4. 승인 지표

전체 final cohort와 각 배송 심각도 그룹에서 다음 지표만 계산한다. 화면 반올림 전 값을
검산에 사용한다.

| 지표 | 공식 | 해석 경계 |
|---|---|---|
| `order_count` | `COUNT(*)` | 해당 범위의 주문 수 |
| `order_share` | `group order_count / scope order_count` | 전체 요약에서는 final cohort, 월별 요약에서는 해당 월이 분모 |
| `mean_order_review_score` | `AVG(order_avg_review_score)` | 리뷰 행 가중이 아닌 주문 동일가중 평균 |
| `median_order_review_score` | `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_avg_review_score)` | 주문별 평균 리뷰 점수의 중앙값 |
| `low_score_order_rate` | `COUNT(order_avg_review_score <= 2) / group order_count` | 원천 리뷰행이 아니라 주문별 평균이 2점 이하인 주문 비율 |

`low_score_order_rate`의 `<= 2`는 낮은 주문 평균을 설명하기 위한 분석 기준이며 리뷰
서비스의 공식 불만 기준이나 SLA가 아니다. `review_count`로 주문을 다시 가중하지 않으며,
평균·중앙값·비율을 계산하기 전에 리뷰 점수를 반올림하지 않는다.

그룹에 주문이 없으면 `order_count = 0`, `order_share = 0`으로 보존하되 평균·중앙값·낮은
점수 비율은 `NULL`/`N/A`로 둔다. 빈 그룹의 지표를 0점이나 0%로 표현하지 않는다.

## 5. 월별 안정성 범위

월별 안정성은 `order_purchase_timestamp`의 달력 월을 기준으로 **2017-02부터
2018-07까지 18개월**만 사용한다. 날짜 조건은 `>= 2017-02-01`이고 `< 2018-08-01`인
반개구간이다. 앞뒤의 부분 coverage 월은 월별 비교에서 제외한다.
전체 final cohort의 심각도 요약과 월별 안정성 보조 분석의 분모를 섞지 않는다.

월별 결과는 승인된 18개월 각각에서 다음 값만 계산한다.

- 전체 주문 수와 지연 주문 수
- `late_order_rate = late order count / monthly order count`
- 지연 주문의 주문 동일가중 평균 리뷰 점수
- 비지연 주문의 주문 동일가중 평균 리뷰 점수
- `score_gap = late mean - not-late mean`

심각도 6개 그룹을 월마다 다시 세분화하지 않는다. 어느 달에서 지연 또는 비지연 그룹이
비면 해당 평균과 차이는 `NULL`/`N/A`로 두며 0점으로 바꾸지 않는다.

여기서 "안정성"은 월마다 방향과 규모가 얼마나 반복되는지 보는 기술적 표현이다.
통계적 안정성, 유의성, 계절 효과 또는 시간에 따른 인과 변화를 뜻하지 않는다.

## 6. Chronology inversion 민감도

Primary 결과는 기존 계약대로 chronology inversion 주문을 포함한다. 다음 flag 중 하나라도
명시적으로 `TRUE`이면 `has_chronology_inversion = true`로 정의한다.

- `is_approval_before_purchase`
- `is_carrier_before_purchase`
- `is_carrier_before_approval`
- `is_customer_before_purchase`
- `is_customer_before_carrier`

nullable flag의 `NULL`을 역전으로 만들거나 임의의 `FALSE` 관찰로 해석하지 않는다. 다만
민감도 제외 조건에는 `IS TRUE`인 flag만 사용하고, flag별 NULL 건수는 검산에서 확인한다.

결과 보고서에는 다음 두 전체 cohort 계산을 나란히 놓은 민감도 표 하나를 포함한다.

1. 모든 final cohort 주문을 포함한 primary 결과
2. `has_chronology_inversion = true`인 주문만 제외한 결과

두 계산의 전체 주문 수, 지연 주문 수와 지연률, 지연·비지연 주문 동일가중 평균 및
두 평균의 차이를 표시한다. 제외 주문 수를 함께 대사하며, 민감도 결과는 primary
cohort를 대체하거나 역전 flag가 원인이라는 주장을 만들지 않는다.

## 7. 예상 산출물

1. 기존 mart 한 개만 읽는 재현 가능한 pandas 분석 흐름
2. 핵심 차트 정확히 2개
   - 전체 final cohort의 심각도 그룹별 주문 수 맥락, 평균·중앙값과 2점 이하 비율
   - 2017-02~2018-07의 월별 지연률과 지연·비지연 평균 차이
3. 심각도 결과, 월별 안정성, chronology inversion 민감도와 한계를 설명하는 결과 보고서
4. 독립 SQL 기준 집계와 pandas 결과의 exact reconciliation 및 산출물 재현 검사

차트는 집계 결과만 표시하고 `order_id`, 리뷰 원문, 고객·판매자 식별자 또는 상세 위치를
포함하지 않는다. 표본 수가 작은 그룹을 숨기지 않고 함께 표시한다.

## 8. 검산과 테스트

같은 `REPEATABLE READ READ ONLY` snapshot에서 mart 행과 독립 SQL 기준 집계를 읽는다.
날짜·정수·PostgreSQL `numeric`을 정규화한 뒤 다음 key와 원시 집계 record를 pandas 결과와
SQL 결과 사이에서 exact 비교한다. 부동소수점 tolerance로 실제 차이를 허용하지 않는다.

- 전체 final cohort와 월별 범위의 입력 행 수 및 distinct `order_id` 수
- 심각도 그룹별 key, 주문 수와 2점 이하 주문 수
- 주문별 평균 리뷰 점수의 합, 평균과 중앙값
- 전체 심각도 그룹의 분자·분모로 계산한 주문 비중과 2점 이하 비율
- 월별 전체·지연·비지연 주문 수, 지연률, 두 그룹 평균과 평균 차이
- chronology inversion 포함·제외 결과와 제외 주문 수

추가로 다음을 검사한다.

- 여섯 그룹이 중복 없이 모든 입력 주문을 한 번씩 포함함
- 네 지연 그룹의 합이 기존 `is_late = true` 주문 수와 같음
- 그룹 주문 수의 합이 각 분석 범위 전체 주문 수와 같음
- 월별 안정성 key가 승인된 18개월과 같음
- 비중 합은 반올림 전에 `abs(sum - 1) <= 1e-12`임
- `order_avg_review_score <= 2` 기준이 pandas와 SQL에서 동일함
- 평균은 주문 동일가중이며 `review_count` 가중 평균과 섞이지 않음
- preflight anchor `p25 = 3`, `median = 7`, `p75 = 13`, `max = 188`이 고정
  snapshot에서 재현됨
- 보고서와 차트 2개가 같은 입력과 고정 의존성 환경에서 재현됨
- 공개 산출물에 행 단위 식별자나 리뷰 원문이 없음

표시용 반올림은 모든 대사가 통과한 뒤에만 적용한다.

## 9. 비범위와 한계

이번 작업에는 다음을 포함하지 않는다.

- 새 dbt model, 기존 dbt model 변경 또는 다른 relation과의 join
- category·seller·customer·지역별 배송 비교
- 원천 리뷰행의 1~5점별 분포 재구성
- p-value, 가설 검정, bootstrap, 신뢰구간 또는 인과 추론
- 예측 모델, SLA 평가, 배송 성과 목표 설정
- dashboard 구현이나 dashboard 도구 선택

결과는 배송일을 비교할 수 있고 리뷰가 있는 delivered 주문에 한정되므로 선택 편향이
있을 수 있다. chronology inversion 민감도도 관찰된 flag에 대한 기술적 비교일 뿐 데이터
오류의 원인이나 효과를 증명하지 않는다. 2016~2018년 고정 공개 snapshot의 결과를 현재
시장이나 다른 플랫폼에 일반화하지 않는다.

## 10. 승인된 결정

- [x] 기존 `mart_delivery_review_orders`만 사용하고 새 model·join을 만들지 않는다.
- [x] 여섯 배송 심각도 그룹과 모든 포함 경계를 제3절대로 사용한다.
- [x] 주문 수·비중, 주문 동일가중 평균, 중앙값과 주문 평균 2점 이하 비율만 사용한다.
- [x] 월별 안정성은 2017-02~2018-07의 구매월 18개월로 제한한다.
- [x] chronology inversion 주문을 primary에 보존하고 제외 결과를 민감도 표로만 제시한다.
- [x] 차트는 정확히 2개로 제한한다.
- [x] SQL과 pandas 결과를 exact 대사한다.
- [x] p-value·인과 주장·dashboard를 이번 작업에서 제외한다.
