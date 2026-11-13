# Category·seller trade analysis contract

> Status: Accepted
>
> Proposed: 2026-11-11 · Accepted: 2026-11-12
> Scope: 검증된 category·seller monthly marts → pandas EDA·차트·결과 보고서

## 1. 해결할 질문

다음 한 문장을 중심 질문으로 사용한다.

> 배송 완료 주문상품에서 관찰된 상품 거래액은 어떤 카테고리와 익명 판매자군에
> 집중되어 있으며, 그 구성과 집중도는 구매월별로 어떻게 달라졌는가?

분석은 원인을 증명하지 않는다. 변화가 넓게 나타났는지 일부 그룹에 집중됐는지를
구분하고, 후속 점검 우선순위를 제안하는 데 목적이 있다.

검토할 하위 질문은 다음과 같다.

1. 월별 상품 거래액과 활동 판매자 수는 어떻게 변했는가?
2. 승인된 비교 기간 기준 Top 5 카테고리와 Other의 월별 구성은 어떻게 달라졌는가?
3. 월별 판매자 Top 1·Top 10·상위 10%의 거래액 집중도는 어떻게 달라졌는가?
4. 원천 category 누락과 번역 미연결이 분석 결과에서 얼마나 남아 있는가?

## 2. 입력 모델과 한 행의 의미

### Category input

- Model: `mart_category_trade_monthly`
- Grain / key: 한 구매월 × 한 `category_key`
- Population: `order_status = 'delivered'`인 주문상품

### Seller input

- Model: `mart_seller_trade_monthly`
- Grain / key: 한 구매월 × 한 `seller_id`
- Population: category mart와 같은 delivered 주문상품

두 mart를 서로 직접 join하지 않는다. 주문상품이 여러 카테고리·판매자에 걸칠 수
있으므로 category×seller 결합은 현재 grain에서 many-to-many 결과를 만들 수 있다.
두 입력은 같은 read-only snapshot에서 각각 읽고 공통 월별 합계로만 대사한다.

## 3. 지표 정의

### 기본 가산 지표

- **상품 거래액**: `SUM(gross_item_value)` = delivered 주문상품의 `price` 합
- **배송비**: `SUM(freight_amount)`
- **상품 측 합계**: `SUM(item_side_amount)` = 상품 거래액 + 배송비
- **주문상품 행 수**: `SUM(ordered_item_row_count)`

기본 분석 measure는 상품 거래액으로 제안한다. 상품 측 합계는 배송비가 포함된 별도
참고값으로 유지한다. 어느 값도 회사 매출·순매출·이익으로 부르지 않는다.

### 파생 지표

- **월별 그룹 비중**:
  `그룹 상품 거래액 / 같은 월 전체 상품 거래액`
- **고정 Top 5 카테고리 구성**:
  전체 승인 비교 기간의 상품 거래액으로 Top 5를 한 번 선정한 뒤 같은 category를
  월별로 추적하고 나머지는 `Other`로 묶는다. 동률은 `category_key` 오름차순으로
  고정한다. `Other`에는 Top 5 이외의 category와 `missing_source`,
  `unmapped_translation`이 모두 포함된다.
- **월별 Top N 판매자 비중**:
  각 월의 상품 거래액 Top N 판매자 합 / 같은 월 전체 상품 거래액. 활동 판매자가
  N명보다 적으면 전체 판매자를 포함하고, 동률은 내부 `seller_id` 오름차순으로
  고정하되 ID 자체는 공개하지 않는다.
- **월별 상위 10% 판매자 비중**:
  각 월의 상품 거래액을 내림차순으로 정렬한 활동 판매자 중
  `max(1, ceil(활동 판매자 수 × 0.10))`명의 비중. 동률 정렬과 공개 정책은 Top N과 같다.
- **월별 활동 판매자 수**:
  해당 구매월에 delivered 주문상품이 한 행 이상 관찰된 distinct `seller_id` 수
- **고정 카테고리 그룹의 월별 변화 기여액**:
  Top 5와 Other 각각의 `현재 월 상품 거래액 - 직전 달력 월 상품 거래액`
- **category mapping 상태별 잔존 비중**:
  상태별 `gross_item_value / 전체 category gross_item_value`와
  상태별 `ordered_item_row_count / 전체 category ordered_item_row_count`

변화 기여액은 고정 Top 5+Other category에서만 계산한다. 판매자 Top N은 매월 구성원이
달라질 수 있으므로 동일 판매자군의 증감으로 해석하지 않는다. 변화 기여액은 인과적
기여도가 아니며, 전체 월간 증감이 어느 고정 그룹의 산술적 증감과 함께 나타났는지
분해하는 기술통계다. 직전 달력 월 전체가 원천에서 빠졌으면 변화액은 `N/A`로 둔다.

### 비가산 count

`associated_order_count`와 `distinct_product_count`는 category 또는 seller 그룹
사이에서 같은 주문·상품이 반복될 수 있다. 따라서 그룹별 값을 더해 전체 distinct
주문·상품 수라고 표현하지 않으며, 전체 KPI와 concentration 분모로 사용하지 않는다.

## 4. 기간과 포함 정책

- 현재 관찰 범위: 2016-09부터 2018-08 구매월
- category의 `mapped`, `missing_source`, `unmapped_translation`을 모두 보존
- 원천에 실제로 관찰된 월만 분석한다. 관찰된 월 안에서 특정 category가 없을 때만
  변화 계산용 0으로 보완한다. 원천에서 월 전체가 빠졌다면 0으로 만들지 않고 누락으로
  남기며, 원천 NULL이나 mapping 상태를 0 또는 정상 category로 바꾸지 않음
- 첫·마지막 관찰 월은 원천 coverage 경계일 수 있으므로 전체 기간을 대표한다고
  해석하지 않음

Top 5 선정과 주 분석 차트에는 2026-11-12 승인한 **2017-02부터 2018-07까지**를
사용한다. 근거는
[`category-seller-coverage-audit.md`](../reports/category-seller-coverage-audit.md)에
기록한다.

- raw/staging 전체 주문의 최소·최대 구매 timestamp
- 월별 전체 상태 주문상품 행 수
- 월별 delivered 주문상품 행 수와 전체 대비 비중
- 달력상 첫·마지막 월의 실제 날짜 coverage

2016-09~2017-01과 2018-08은 참고 구간으로만 표시하며 Top 5 선정과 월별 변화
결론에서 제외한다. 2018-09~10은 delivered 거래 mart 모집단이 없어 분석하지 않는다.
경계 구간을 근거로 성장률이나 감소율을 주장하지 않는다.

## 5. 예상 산출물

1. 재현 가능한 pandas 분석 스크립트 1개
2. 핵심 차트 3개 이내
   - 월별 상품 거래액과 delivered 주문상품 관찰 판매자 수
   - 고정 Top 5 카테고리와 Other의 월별 상품 거래액 비중 100% 구성
   - 판매자 Top 1·Top 10·상위 10% 집중도 변화
3. 비개발자용 결과 보고서 1개
4. SQL 기준 집계와 pandas 결과를 비교하는 unit·integration test

dashboard는 이 분석이 승인된 뒤 별도 계약과 작업 단위로 구현한다. 분석 결과를
보여주기 전에 dashboard 구조부터 만들지 않는다.

## 6. 검산과 테스트

비중 합계는 반올림 전 값으로 검증한다. 구현 테스트에서는
`abs(비중 합계 - 1) <= 1e-12`만 허용하며, 이는 컴퓨터의 부동소수점 표현 오차를
처리하기 위한 기준이지 실제 데이터 차이에 대한 허용 범위가 아니다. 화면과 보고서의
비중은 검산이 끝난 뒤 반올림한다.

- category와 seller 입력의 월별·전체 상품 거래액, 배송비, 상품 측 합계와
  주문상품 행 수가 서로 exact 대사
- category mapping 세 상태를 포함해야 category 입력 합계가 전체와 일치
- 모든 category 행 또는 모든 seller 행으로 계산한 exhaustive 월별 비중 합이 100%
- 고정 Top 5+Other의 월별 비중 합이 100%
- `0 ≤ Top 1 비중 ≤ Top 10 비중 ≤ 1`
- `0 ≤ Top 1 비중 ≤ 상위 10% 비중 ≤ 1`
- Top 10과 상위 10%는 포함하는 판매자 수가 달라질 수 있으므로 둘 사이의 고정된
  대소관계를 테스트하지 않음
- 각 월별 concentration 지표의 분모가 같은 월의 전체 상품 거래액과 일치
- 고정 Top 5+Other 월별 변화 기여액의 합이 전체 월간 증감과 일치
- mapping 상태별 금액·행 비중의 분자가 category mart 상태별 합계와 일치하고 전체
  상태의 비중 합이 100%
- seller ID·zip·city·state가 공개 집계·차트·보고서에 포함되지 않음
- 동일 입력과 명령에서 같은 승인 지표와 차트가 재현됨
- 분모가 0이거나 비교할 이전 월이 없으면 0으로 꾸미지 않고 `N/A` 처리

## 7. 해석과 공개 경계

- 고정된 2016–2018 Olist snapshot의 기술통계이며 현재 시장으로 일반화하지 않음
- delivered 주문상품만 포함하므로 취소·미완료 주문의 거래 특성을 설명하지 않음
- 상품 거래액 변화만으로 수요, 재고, 프로모션이나 판매자 성과의 원인을 단정하지 않음
- 방문·광고비·원가·환불 자료가 없으므로 전환·ROAS·이익을 제안하지 않음
- 판매자 원본 식별자와 위치 상세, 주문·상품 식별자와 행 단위 데이터는 공개하지 않음
- 분석에서 확인한 집중을 실제 사업 위험이나 개선 성과라고 단정하지 않고
  추가 확인이 필요한 점검 신호로 표현

## 8. 승인된 결정

2026-11-12 다음 항목을 승인했다.

1. 기본 분석 measure를 상품 거래액으로 사용하고 배송비를 별도로 볼 것
2. 2017-02~2018-07의 Top 5 category를 고정해 월별로 추적하고 나머지는 Other로
   묶을 것
3. 판매자 집중도를 월별 Top 1·Top 10·상위 10% 비중으로 비교할 것
4. 2016-09~2017-01과 2018-08은 참고 구간으로만 표시할 것
5. 변화 기여는 고정 Top 5+Other category에서만 계산하고, 원인 분석이 아니라 점검
   우선순위용 기술통계로 표현할 것
6. 공개 결과에서 seller 식별자와 상세 위치를 제외할 것
7. 차트는 최대 3개로 제한하고 하나의 판단을 완성할 것
