# 배송 지연·리뷰 주문 mart 검증

검증일: 2026-11-07 (Asia/Seoul)

## 1. 목적과 범위

이번 단계의 목적은 약속한 달력 날짜를 넘긴 주문과 넘기지 않은 주문의 주문별 평균
리뷰 점수를 안전하게 비교할 수 있는 주문 단위 mart를 만드는 것이다.

`mart_delivery_review_orders`의 한 행은 다음 세 조건을 만족하는 주문 1건이다.

1. 배송 완료 주문
2. 실제 고객 배송일과 예정 배송일을 비교할 수 있는 주문
3. 주문 단위 리뷰 요약이 존재하는 주문

이번 보고서는 mart의 grain, 포함 범위, 지표 전달과 검산 결과를 다룬다. 관찰된 평균
차이는 기술통계이며 배송 지연의 인과 효과가 아니다. pandas 차트와 비개발자용 분석
결과물은 이 mart를 입력으로 만드는 다음 단계의 범위다.

## 2. 적용한 계약

기준은 [`../docs/model-metric-contracts.md`](../docs/model-metric-contracts.md)의 배송·리뷰
계약과 D-008이다.

- mart grain/key: 주문 1건, `order_id`
- 배송 범위: `order_status = 'delivered'`
- 지연 기준: 실제 고객 배송일의 달력 날짜 - 예정 배송일의 달력 날짜
- `early`: 날짜 차이 < 0
- `promised_date`: 날짜 차이 = 0
- `late`: 날짜 차이 > 0
- not-late: `early` 또는 `promised_date`
- 리뷰 정책: 한 주문의 모든 리뷰를 먼저 평균하고 주문을 동일 가중
- chronology 역전: 원천을 교정하거나 주문을 제외하지 않고 flag로 보존
- 실제 배송일 결측: intermediate에서는 `unknown`으로 보존하고 최종 비교 분모에서는 제외

같은 달력 날짜의 오후 배송은 예정일 자정 timestamp보다 시각상 늦더라도 지연으로
분류하지 않는다. 첫 리뷰나 최신 리뷰 하나를 임의로 대표값으로 선택하지 않는다.

## 3. 모델 흐름과 구현

```text
stg_orders ──> int_order_delivery_timing ──┐
                                           ├─> mart_delivery_review_orders
stg_reviews ─> int_order_review_summary ───┘
```

`int_order_delivery_timing`은 전체 주문 1건당 1행이며 배송 날짜 차이, 상태와 결측·시간
역전 flag를 보존한다. `int_order_review_summary`는 리뷰가 있는 주문 1건당 1행이며 모든
리뷰의 count, score sum, 평균, 최솟값과 최댓값을 보존한다.

두 upstream model 모두 `order_id`가 unique이므로 주문 ID로 `INNER JOIN`해도 final grain이
주문 1건으로 유지된다. 원천 리뷰를 직접 결합하지 않아 복수 리뷰가 있는 주문의 행이
증가하지 않는다.

최종 mart에는 분석에 필요한 배송 상태·날짜·리뷰 요약과 chronology flag를 함께
노출한다. Chronology flag가 true라는 이유로 주문을 제외하지 않는다.

## 4. 포함·제외 funnel

| 단계 | 주문 수 | 이전 단계에서 제외 |
|---|---:|---:|
| 배송 완료 주문 | 96,478 | - |
| 실제·예정 배송일 비교 가능 | 96,470 | 8 |
| 리뷰 요약 보유 최종 주문 | 95,824 | 646 |

검산식은 다음과 같다.

```text
96,478 = 96,470 + 8
96,470 = 95,824 + 646
```

- 제외된 8건은 delivered이지만 실제 고객 배송일이 없어 `unknown`인 주문이다.
- 646건은 날짜 비교가 가능하지만 리뷰 요약이 없는 주문이다.
- 최종 review coverage는 `95,824 / 96,470 = 99.330362%`다.

Coverage가 높아도 리뷰 누락이 무작위라는 뜻은 아니다. 특히 지연 상태별 coverage가
다르므로 리뷰가 있는 주문만 사용한 결과의 대표성에는 한계가 있다.

| 배송 상태 | 날짜 비교 가능 | 리뷰 보유 | 리뷰 없음 | coverage |
|---|---:|---:|---:|---:|
| `early` | 88,644 | 88,163 | 481 | 99.457380% |
| `promised_date` | 1,292 | 1,280 | 12 | 99.071207% |
| `late` | 6,534 | 6,381 | 153 | 97.658402% |

## 5. 최종 cohort의 관찰 결과

### 5.1 지연·비지연 비교

| 그룹 | 주문 수 | 리뷰 원천 행 수 | 리뷰 점수 합 | 복수 리뷰 주문 수 | 주문 동일가중 평균 |
|---|---:|---:|---:|---:|---:|
| not-late | 89,443 | 89,944 | 385,858 | 497 | 4.29058916 |
| late | 6,381 | 6,409 | 14,555 | 28 | 2.27182260 |
| 합계 | 95,824 | 96,353 | 400,413 | 525 | - |

- 최종 cohort의 late rate: `6,381 / 95,824 = 6.659083%`
- late 평균 - not-late 평균: `2.27182260 - 4.29058916 = -2.01876657`
- 전체 주문 동일가중 평균: 4.15615782

최종 비교 대상에서 지연 주문의 주문 동일가중 평균 리뷰 점수는 약 2.27점,
비지연 주문은 약 4.29점으로 2.02점 낮게 관찰됐다. 이는 리뷰가 존재하고 배송일 비교가
가능한 완료 주문 내부의 기술적 차이이며, 배송 지연 때문에 점수가 하락했다는 뜻은 아니다.

### 5.2 주문 동일가중

최종 mart의 주문 수는 95,824건이지만 연결된 원천 리뷰는 96,353행이다. 복수 리뷰가
있는 주문이 존재하기 때문이다.

Primary 평균은 다음 순서로 계산한다.

1. 주문마다 모든 리뷰 점수의 평균을 계산한다.
2. 주문별 평균을 다시 평균해 각 주문에 같은 가중치를 준다.

전체 리뷰 행을 바로 평균한 값은 4.15568794로 주문 동일가중 평균 4.15615782와 다르다.
차이가 작다는 이유로 두 공식을 같은 지표로 취급하지 않는다.

`96,353 - 95,824 = 529`는 주문마다 최소 한 리뷰가 있다고 봤을 때 추가된 리뷰 행 수다.
복수 리뷰 주문 수는 525건이며 3개 리뷰가 있는 주문도 있어 두 값은 같지 않다.

## 6. 달력 날짜 기준 확인

리뷰 유무와 관계없이 날짜 비교가 가능한 delivered 주문에서 다음을 확인했다.

| 분류 방식 | late 주문 수 |
|---|---:|
| 달력 날짜 비교 | 6,534 |
| timestamp 직접 비교 | 7,826 |

차이 1,292건은 실제 배송일과 예정일이 같은 달력 날짜지만 실제 배송 timestamp가 예정일
자정보다 늦은 주문이다. 승인 계약은 이 주문들을 `promised_date`로 분류한다. 따라서 이번
결과는 시간 단위 지연을 분석하는 결과가 아니다.

## 7. Chronology flag 보존

최종 mart에서 chronology flag가 하나 이상 true인 주문 1,366건도 삭제하지 않았다.

| 관찰 항목 | 주문 수 |
|---|---:|
| 승인 timestamp 없음 | 14 |
| 출고 timestamp 없음 | 1 |
| 승인 시각이 구매보다 빠름 | 0 |
| 출고 시각이 구매보다 빠름 | 164 |
| 출고 시각이 승인보다 빠름 | 1,343 |
| 고객 배송 시각이 구매보다 빠름 | 0 |
| 고객 배송 시각이 출고보다 빠름 | 23 |
| chronology flag 하나 이상 true | 1,366 |

Flag는 한 주문에서 겹칠 수 있으므로 개별 건수를 더해 이상 주문 수라고 표현하지 않는다.
이 값은 원천에서 관찰된 순서 관계이며 모두 업무 오류라고 판정한 결과가 아니다. 조기
배송의 음수 날짜 차이도 chronology 역전과 다른 정상 분석값이다.

## 8. 검산과 테스트

### 8.1 모델 계약 검사

- `order_id` unique·not null과 두 upstream relationship
- 배송 상태가 delivered이고 실제·예정 배송일이 not null인지 검사
- final timing status를 `early`, `promised_date`, `late`로 제한
- 날짜 차이의 부호, timing status와 `is_late` 일치 검사
- review count·score sum·평균·최솟값·최댓값의 domain과 공식 검사
- nullable chronology flag에 잘못된 not-null 규칙을 적용하지 않음

### 8.2 전 행 exact 대사

두 intermediate model에서 승인 cohort를 독립적으로 다시 만들고 실제 mart와
`order_id`로 `FULL OUTER JOIN`했다. 누락·초과 주문과 배송·리뷰·chronology 모든 노출
열의 차이를 `IS DISTINCT FROM`으로 비교했다.

### 8.3 Inclusion funnel과 합계 대사

- delivered = 날짜 비교 가능 + unknown
- 날짜 비교 가능 = 리뷰 보유 + 리뷰 없음
- final의 early + promised_date + late = final 전체
- final의 late + not-late = final 전체
- final `SUM(review_count)`와 `SUM(review_score_sum)`을 같은 upstream subset과 대사

### 8.4 합성 fixture

- 복수 리뷰를 raw grain으로 결합하면 주문이 중복되고, 주문별 선집계 후 1행이 됨
- 같은 달력 날짜의 오후 배송이 timestamp 비교와 달리 date 기준 0일 차이가 됨
- 주문 동일가중 late 평균 3과 리뷰 행 가중 평균 7/3이 달라지는 예시를 재현

Fixture에는 실제 주문 ID나 리뷰 원문을 사용하지 않았다.

## 9. 실행 결과

```text
dbt parse: 성공
dbt build --threads 1:
  20 table models + 245 data tests = 265 nodes
  PASS=265 WARN=0 ERROR=0 SKIP=0

Python unittest including PostgreSQL integration:
  24 tests passed
```

dbt adapter는 precision·scale을 지정하지 않은 PostgreSQL `numeric` 열에 일반 경고 문구를
출력했다. 이는 승인 계약에서 리뷰 평균을 조기 반올림하지 않기 위해 선택한 제한 없는
`numeric`과 관련된 메시지다. 위 `WARN=0`은 실행 node의 최종 상태를 뜻한다.

## 10. 사용자 검토 항목

이번 구현은 이미 승인된 D-008 계약 안에서 완료되어 새로운 모델링 결정은 필요하지
않다. 결과 해석에서 다음을 검토한다.

- not-late가 `early + promised_date`라는 정의
- 리뷰 행이 아니라 주문을 동일 가중한 평균
- `-2.01876657`이 관찰 차이이며 인과 효과가 아니라는 경계
- late 그룹의 review coverage가 다른 상태보다 낮다는 대표성 한계
- chronology flag 주문을 임의로 제거하지 않은 정책
- 시간 단위가 아니라 달력 날짜 단위의 지연 정의

## 11. 가정과 한계

- 최종 대상은 delivered·날짜 비교 가능·리뷰 보유 주문으로 제한된다.
- 리뷰 작성 여부가 배송 경험과 관련됐을 수 있어 선택 편향을 배제할 수 없다.
- 판매자, 상품, 카테고리, 지역, 계절 등 교란요인을 통제하지 않았다.
- 리뷰 작성 timestamp와 배송 timestamp의 순서를 비교하지 않았다.
- Chronology flag를 보존했으며 이 flag의 영향에 대한 sensitivity 분석을 수행하지 않았다.
- 평균은 분포 차이를 모두 보여주지 않으며 통계적 유의성이나 효과 크기를 검정하지 않았다.
- 고정된 2016–2018 Olist snapshot의 관찰 결과로 현재 시장 전체를 대표하지 않는다.
- pandas 분석, 차트와 비개발자용 최종 해석은 아직 완료하지 않았다.

## 12. 재현 방법

로컬 PostgreSQL이 실행 중이고 `.env`가 준비된 상태에서 다음을 실행한다.

```bash
.venv/bin/dbt parse --profiles-dir .
.venv/bin/dbt build --profiles-dir . --threads 1
RUN_POSTGRES_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
```

검증 대상 핵심 파일은 다음과 같다.

- `models/marts/olist/mart_delivery_review_orders.sql`
- `models/marts/olist/_olist__delivery_review_mart.yml`
- `dbt_tests/assert_delivery_review_orders_reconciles.sql`
- `dbt_tests/assert_delivery_review_funnel_reconciles.sql`
- `dbt_tests/order_weighted_review_average_fixture.sql`
- `dbt_tests/review_fixture_preaggregation_is_unique.sql`
- `dbt_tests/same_day_delivery_fixture_uses_calendar_date.sql`
