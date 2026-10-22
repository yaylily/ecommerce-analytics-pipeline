# PostgreSQL raw 적재 검산

## 목적과 범위

승인된 Olist CSV snapshot 9개가 PostgreSQL `raw` schema에 원천 행 단위로
빠짐없이 적재됐는지 확인한다. 이 단계에서는 타입 변환, 공백 정리, 중복 제거와
업무 규칙 적용을 하지 않는다.

## 결과 요약

- 판정: **PASS**
- PostgreSQL: `15.19 (Debian 15.19-1.pgdg12+2)`
- 보고서 생성 명령: `load`
- Manifest SHA-256: `041d600393762a8894f995816d71f805ac09672b8ce2ea7d134ce3a0669f71bb`
- 테이블: 9개
- 원천 기대 행: 1,550,922
- DB 실제 행: 1,550,922
- 불일치 테이블: 0개

## 테이블별 행 수 대사

| raw table | source file | 기대 행 | DB 행 | 결과 |
|---|---|---:|---:|---|
| `geolocation` | `olist_geolocation_dataset.csv` | 1,000,163 | 1,000,163 | 일치 |
| `customers` | `olist_customers_dataset.csv` | 99,441 | 99,441 | 일치 |
| `category_translation` | `product_category_name_translation.csv` | 71 | 71 | 일치 |
| `products` | `olist_products_dataset.csv` | 32,951 | 32,951 | 일치 |
| `sellers` | `olist_sellers_dataset.csv` | 3,095 | 3,095 | 일치 |
| `orders` | `olist_orders_dataset.csv` | 99,441 | 99,441 | 일치 |
| `order_items` | `olist_order_items_dataset.csv` | 112,650 | 112,650 | 일치 |
| `payments` | `olist_order_payments_dataset.csv` | 103,886 | 103,886 | 일치 |
| `reviews` | `olist_order_reviews_dataset.csv` | 99,224 | 99,224 | 일치 |

## 확인한 것

- DB를 변경하기 전에 기존 source profiler의 `check`로 정확한 파일 9개,
  헤더·논리 행 수·파일 checksum과 공개 집계 보고서의 일치를 다시 확인했다.
- `raw`에는 계약의 테이블 9개만 있고, 열 이름·순서가 계약과 같으며 모든 열이
  nullable `text`이고 constraint·index·trigger·rule·RLS가 없음을 확인했다.
- 적재 중 읽은 동일한 파일 바이트의 크기와 SHA-256를 manifest와 다시 비교했다.
- 이번 `load` 실행은 9개 테이블을 한 transaction에서 비우고 `COPY`한 뒤
  전수 행 수가 모두 맞을 때만 commit했다.
- `load`는 재실행해도 행이 누적되지 않는 full refresh 방식이다.
- 빈 CSV field는 raw에서 빈 text로 보존한다. NULL·숫자·timestamp 해석은 다음
  dbt staging 단계의 명시적 규칙으로 미룬다.

## 의미와 한계

- 파일 checksum은 적재에 사용한 입력 파일이 승인된 snapshot과 같은지 보장한다.
  DB 각 행의 checksum이라는 뜻은 아니다.
- 행 수 대사는 누락·중복 적재를 탐지하지만, 값의 업무적 타당성까지 보장하지 않는다.
  key·cast·domain·관계 검증은 승인된 계약에 따라 dbt staging에서 구현한다.
- 이 구성은 로컬 재현 환경이며 production 운영, 실시간 처리나 cloud 배포를
  증명하지 않는다.

## 재현 방법

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python scripts/load_raw.py load --data-dir data/raw
.venv/bin/python scripts/load_raw.py check --data-dir data/raw
```
