# Source data

## Core dataset

- Source: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
- Provider: Olist
- License: CC BY-NC-SA 4.0
- Coverage: 2016–2018년 익명화된 브라질 이커머스 주문

핵심 범위는 다음 9개 파일을 사용한다.

```text
olist_customers_dataset.csv
olist_geolocation_dataset.csv
olist_order_items_dataset.csv
olist_order_payments_dataset.csv
olist_order_reviews_dataset.csv
olist_orders_dataset.csv
olist_products_dataset.csv
olist_sellers_dataset.csv
product_category_name_translation.csv
```

## Optional extension

[Marketing Funnel by Olist](https://www.kaggle.com/datasets/olistbr/marketing-funnel-olist)는
핵심 거래 모델이 완료된 뒤 별도 milestone에서 검토한다. 핵심 적재 대상에는
포함하지 않는다.

## Repository policy

- 원본 또는 가공된 행 단위 데이터를 Git에 커밋하지 않는다.
- 실제 리뷰 문장이나 식별자를 fixture와 문서에 복사하지 않는다.
- 공개 저장소에는 출처·라이선스, 예상 파일명과 집계된 검증 결과만 남긴다.
- 데이터 준비 절차에는 출처, 파일 checksum과 파일별 행 수를 확인할 수 있는
  manifest를 포함한다. 구현 여부는 root README의 `현재 상태`에서 관리한다.

## Data preparation acceptance

로컬에 데이터가 존재하는 것만으로 준비 완료로 판단하지 않는다. 다음 증거가
저장소에 있고 실제 실행 결과가 확인된 뒤 README의 `현재 상태`를 갱신한다.

- 재현 가능한 다운로드 또는 준비 절차
- 예상 파일명과 checksum manifest 검증
- 원천 파일과 적재 테이블의 행 수 대사
