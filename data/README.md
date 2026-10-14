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

## Local preparation

1. 위 Kaggle 원본 페이지에서 데이터를 내려받아 압축을 푼다.
2. 저장소의 `data/raw/` 아래에 위 9개 CSV를 둔다. 다른 CSV가 섞여 있거나
   예상 파일이 빠지면 프로파일러는 실패한다.
3. 저장소 루트에서 다음 명령을 실행한다.

```bash
python3 scripts/profile_source.py build \
  --data-dir data/raw \
  --contract config/olist-source-contract.json \
  --output-dir reports

python3 scripts/profile_source.py check \
  --data-dir data/raw \
  --contract config/olist-source-contract.json \
  --output-dir reports

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

`build`는 실제 CSV를 검사하고 구조 프로파일과 값 프로파일을 포함한 집계 보고서를
만든다. `check`는 같은 입력에서 다시 생성한 결과가 저장소의 보고서와 byte 단위로
같은지 확인한다. Python 표준 라이브러리만 사용하므로 이 단계에는 별도 패키지 설치가
필요하지 않다.

기본 경로가 아닌 곳에 원천 파일이 있다면 `--data-dir`만 바꿔 실행할 수 있다.
보고서에는 파일 checksum, 행 수, NULL·중복·미연결 행, 조인 증폭과 계약 지정
열의 타입 변환·최소/최대, 공개 허용 도메인 분포, 날짜 비교와 주문 단위 금액
대사 집계만 남는다. 미등록 도메인은 값 없이 행 수와 고유값 수만 기록하며,
실제 ID, 위치값, 리뷰 문장, 알 수 없는 원문 값과 로컬 절대경로는 남기지 않는다.

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
