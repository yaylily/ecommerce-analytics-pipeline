# Analysis dashboard contract

> Status: Accepted / 2026-11-16
>
> 이 문서는 승인·검증된 거래 구성 및 배송·리뷰 분석을 반복 확인하는 작은
> dashboard의 목적, 입력, 지표, 필터와 검증 기준을 고정한다.

## 1. 해결할 질문과 사용자

dashboard의 중심 질문은 다음과 같다.

> 비개발자가 승인된 18개월 안에서 기간과 표시 그룹을 바꾸어 거래 구성과
> 배송·리뷰 관계를 반복 확인하면서, 지표의 분모와 해석 한계를 같은 화면에서
> 확인하려면 어떤 최소 화면이 필요한가?

dashboard는 새로운 분석 결과를 발굴하거나 원인을 증명하는 도구가 아니다. 이미
계약·검산을 통과한 결과를 같은 정의로 다시 탐색하고 전달하는 것이 목적이다.

## 2. 도구와 실행 구조

### 제안 도구

- 단일 Streamlit app을 사용한다.
- 두 개의 탭만 둔다: `거래 구성`, `배송·리뷰`.
- dashboard 전용 pure Python helper와 Streamlit app을 분리한다.
- 별도 JavaScript frontend, FastAPI backend, 인증, 사용자 업로드와 세션 저장은
  만들지 않는다.

Streamlit은 현재 Python·pandas 분석 흐름을 재사용하면서 작은 필터와 차트를 만들 수
있고, headless app test를 지원해 화면 동작도 자동 검증할 수 있다는 이유로 제안한다.
이 선택을 backend·서버 운영 경험으로 확대해 표현하지 않는다.

### 입력 구조

dashboard 실행 중 PostgreSQL에 직접 연결하지 않는다. 별도 exporter가 기존 분석
함수의 검산을 통과한 집계만 정해진 CSV와 manifest로 만든다. app은 저장소에 포함된
이 작은 집계 파일만 읽는다.

이 구조의 목적은 다음과 같다.

- 원본 CSV, `.env`, DB credential 없이 공개 app을 재현
- Markdown 보고서에서 수치를 다시 파싱하거나 숫자를 수동 복사하는 오류 방지
- 주문·판매자 식별자와 행 단위 데이터를 dashboard 입력에서 제거
- 원천→mart→pandas 검산과 dashboard 표시 사이의 책임 분리

exporter의 `build`는 승인된 집계 파일과 manifest를 원자적으로 갱신하고, `check`는
같은 입력에서 생성한 임시 산출물이 커밋된 산출물과 byte-identical한지 확인한다.

## 3. dashboard 입력 계약

모든 파일은 2017-02부터 2018-07까지 승인된 구매월 18개를 기본 기간으로 사용한다.
금액·count·점수 합처럼 필터 재계산에 필요한 분자와 분모를 함께 보존한다.

### `trade_monthly_overview.csv`

- Grain / key: 구매월 1행 / `purchase_month`
- 기대 행 수: 18
- 값: 상품 거래액, 배송비, 상품 측 합계, 주문상품 행 수, 활동 판매자 수
- 출처: 승인된 category·seller 분석의 `monthly_overview`

### `category_mix.csv`

- Grain / key: 구매월 × 표시 category 그룹 / (`purchase_month`, `group_key`)
- 기대 행 수: 18개월 × 고정 Top 5+Other 6그룹 = 108
- 값: 그룹 상품 거래액, 같은 월 전체 상품 거래액, 월 전체 대비 비중
- 공개값: 안전한 category 표시명과 `Other`
- 제외값: 원천 sentinel key, 상품·주문 식별자

### `seller_concentration.csv`

- Grain / key: 구매월 1행 / `purchase_month`
- 기대 행 수: 18
- 값: 활동 판매자 수, Top 1·Top 10·상위 10%의 포함 판매자 수·상품 거래액·비중
- 제외값: `seller_id`, 위치 상세와 개별 판매자 순위

### `delivery_timing_summary.csv`

- Grain / key: 예정일 대비 배송 구간 1행 / `delivery_timing_group`
- 기대 행 수: 6
- 값: 주문 수·비중, 주문별 평균 리뷰 점수의 합·평균·중앙값,
  주문별 평균이 2점 이하인 주문 수·비율
- 범위: 전체 final cohort 95,824건이며 기간 필터를 적용하지 않음

### `delivery_monthly.csv`

- Grain / key: 구매월 1행 / `purchase_month`
- 기대 행 수: 18
- 값: 전체·지연·비지연 주문 수, 각 집단의 주문 평균 리뷰 점수 합,
  지연률, 두 집단 평균과 평균 차이
- 기간 필터를 적용한 KPI는 count와 점수 합에서 다시 계산함

### `delivery_sensitivity.csv`

- Grain / key: 민감도 cohort 1행 / `cohort`
- 기대 행 수: 전체 포함·chronology inversion 제외 2행
- 값: 전체·지연·비지연 주문 수, 지연률, 두 집단 평균과 평균 차이
- 화면의 보조 설명 영역에서만 사용함

### `manifest.json`

- schema version
- 각 파일의 SHA-256, byte 수, 행 수와 key 범위
- 데이터 의미와 무관한 실행 시각은 넣지 않음

manifest는 파일 변경·누락을 감지하는 보조 계약이다. checksum 일치만으로 지표 의미가
맞다고 주장하지 않으며, 행·key·합계 검증을 별도로 수행한다.

## 4. 화면 계약

## 4.1 거래 구성 탭

### 필터

- 시작·종료 구매월: 승인된 18개월 안에서만 선택
- category 표시 그룹: 고정 Top 5+Other 다중 선택
- 판매자 집중도 계열: Top 1·Top 10·상위 10% 다중 선택

개별 판매자 필터는 두지 않는다. 현재 분석 질문은 익명 판매자군의 집중도이며,
공개 입력에서도 seller 식별자를 제거하기 때문이다.

### KPI와 차트

- 선택 기간 상품 거래액 합
- 선택 기간 배송비 합
- 선택 기간 주문상품 행 수 합
- 선택 기간 마지막 월의 활동 판매자 수
- 월별 상품 거래액
- 고정 Top 5+Other category 구성
- 판매자 Top 1·Top 10·상위 10% 집중도

활동 판매자 수는 월 사이에 같은 판매자가 반복될 수 있으므로 월별 값을 더하지 않는다.
category를 일부만 선택해도 비중의 분모는 선택된 그룹 합이 아니라 승인된 같은 월 전체
상품 거래액으로 유지한다.

## 4.2 배송·리뷰 탭

### 고정 전체 cohort 영역

- 예정일 대비 여섯 배송 구간의 주문 수·비중
- 주문별 평균 리뷰 점수의 평균·중앙값
- 주문별 평균 리뷰 점수가 2점 이하인 주문 비율

이 영역은 95,824건 전체 final cohort 결과이며 월 필터가 적용되지 않는다고 화면에
명시한다.

### 기간 필터 적용 영역

- 선택 기간 지연률
- 지연 주문의 주문 동일가중 평균 리뷰 점수
- 비지연 주문의 주문 동일가중 평균 리뷰 점수
- `지연 평균 - 비지연 평균` 점수 차이
- 월별 지연률과 월별 평균 점수 차이
- chronology inversion 포함·제외 민감도 표

선택 기간 평균은 월별 평균의 단순 평균이 아니다. 다음처럼 원시 집계 분자와 분모를
다시 합산한다.

- `선택 기간 지연률 = SUM(late_order_count) / SUM(order_count)`
- `지연 평균 = SUM(late_order_review_score_sum) / SUM(late_order_count)`
- `비지연 평균 = SUM(not_late_order_review_score_sum) / SUM(not_late_order_count)`
- `점수 차이 = 지연 평균 - 비지연 평균`

## 5. 필터와 오류 처리

- 시작 월이 종료 월보다 뒤면 계산하지 않고 수정 안내를 표시
- category 또는 집중도 계열을 모두 해제하면 임의로 전체를 다시 선택하지 않고
  해당 차트 위치에 선택 안내를 표시
- 지연 또는 비지연 주문 수가 0이면 평균·차이를 0으로 표시하지 않고 `N/A`와 경고 표시
- 필수 파일·열·key·manifest·checksum 검증이 실패하면 일부 숫자를 계속 표시하지 않고
  전체 app을 fail closed 처리
- 승인되지 않은 월, 중복 key, NULL key와 비정상 범위가 있으면 app 시작을 실패시킴

## 6. 검산과 테스트

### 집계 파일

- `trade_monthly_overview`: 승인된 18개월 18행과 unique·not-null month key
- `category_mix`: 108행, 월×그룹 unique, 매월 6그룹, 비중 합은 반올림 전
  `abs(sum - 1) <= 1e-12`
- `seller_concentration`: 18행,
  `0 <= Top 1 <= Top 10 <= 1`, `0 <= Top 1 <= 상위 10% <= 1`
- `delivery_timing_summary`: 6행, 주문 수 합 95,824건, 네 지연 구간 합 6,381건,
  주문 비중 합은 반올림 전 `abs(sum - 1) <= 1e-12`
- `delivery_monthly`: 승인된 18개월 18행, count와 점수 합이 기존 심화 분석 결과와 대사
- `delivery_sensitivity`: 승인된 두 cohort 2행, 제외 주문 수와 기존 결과가 대사
- 공개 집계 파일에 order·seller·customer·product 식별자, 리뷰 원문과 상세 위치가 없음
- 같은 고정 환경과 입력에서 `build` 뒤 `check`가 byte-identical하게 통과

`1e-12`는 컴퓨터의 부동소수점 표현 오차만 처리한다. 실제 데이터 차이에 대한 허용
tolerance로 사용하지 않는다.

### 계산 helper와 app

- 시작·종료 월 필터와 경계 월 포함
- 일부 category 선택에서도 승인된 전체 월 분모 유지
- 기간 KPI가 월별 평균의 평균이 아니라 count·점수 합에서 재계산됨
- 빈 선택, 시작 월>종료 월과 0분모가 계약대로 안내 또는 `N/A` 처리됨
- schema·checksum·key 오류에서 fail closed됨
- Streamlit headless test에서 기본 화면, 두 탭과 주요 필터가 예외 없이 렌더됨
- 공개 화면에 식별자·secret·인과 표현이 없음

화면 pixel 단위 screenshot equality는 OS·font 차이에 취약하므로 필수 자동 테스트로
두지 않는다. 대신 계산과 app 상태를 직접 검사하고, 최종 화면은 사람이 별도로 검토한다.

## 7. 해석과 공개 경계

- 상품 거래액은 회사 매출·순매출·이익이 아님
- 거래 탭은 delivered 주문상품만 설명함
- 고정 Top 5는 승인 기간 기준이며 판매자 concentration의 구성원은 매월 달라짐
- 집중도는 개별 판매자 성과나 사업 위험을 증명하지 않음
- 배송·리뷰는 배송일 비교 가능·리뷰 보유 delivered 주문의 관찰 관계이며 인과가 아님
- 전체 cohort의 배송 구간 요약과 월별 안정성의 기간·분모가 다름
- 2016–2018년 고정 Olist snapshot 결과를 현재 시장으로 일반화하지 않음
- Olist 데이터 출처와 CC BY-NC-SA 4.0 attribution을 화면에 표시함

## 8. 예상 산출물

1. dashboard 입력 exporter와 고정 집계 파일·manifest
2. pure loader·metric helper와 unit test
3. Streamlit 단일 app과 headless app test
4. 로컬 실행·검증 방법과 핵심 화면을 설명하는 README 갱신
5. 검증 결과, 해석 경계와 미정 사항을 담은 dashboard 결과 보고서

dashboard 화면 검토와 승인 뒤 실제 외부 배포 여부는 별도로 결정한다. 구현 완료만으로
배포됐거나 운영 중이라고 표현하지 않는다.

## 9. 비범위

- PostgreSQL 직접 연결과 runtime credential
- 새 dbt model, mart, join 또는 지표 정의
- 개별 판매자 drill-down과 행 단위 상세
- 로그인·권한·사용자 업로드·상태 저장
- FastAPI, 별도 frontend, Docker image와 cloud database
- 새로운 통계 검정, 예측, 추천과 인과 추론
- 실시간·증분 갱신과 production monitoring

## 10. 승인 필요 항목

- [x] Streamlit 단일 app과 2개 탭을 사용한다.
- [x] app은 DB 대신 검증·커밋된 집계 파일만 읽는다.
- [x] 거래 탭은 기간·고정 Top 5+Other·익명 판매자 집중도만 제공한다.
- [x] 배송 탭은 전체 배송 구간 요약과 기간별 지연률·리뷰 평균 차이만 제공한다.
- [x] 개별 seller filter와 식별자는 제외한다.
- [x] 기간 KPI는 count·점수 합에서 다시 계산한다.
- [x] 외부 배포는 로컬 결과 승인 뒤 별도 작업으로 결정한다.
