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

## Requirements

- Python 3.11 이상(검증 환경: 3.13.2)
- Docker와 Docker Compose v2
- Git

`requirements.txt`의 pandas·matplotlib 버전은 Python 3.10에서 설치되지 않는다.
가상환경을 만들기 전에 `python3 --version`으로 버전을 확인한다.

## Local preparation

1. 위 Kaggle 원본 페이지에서 데이터를 내려받아 압축을 푼다.
2. 저장소의 `data/raw/` 아래에 위 9개 CSV를 둔다. 다른 CSV가 섞여 있거나
   예상 파일이 빠지면 프로파일러는 실패한다.
3. 로컬 환경 파일과 Python 환경을 준비한다. `.env`의 password는 로컬 전용 값으로
   바꾸며 파일 자체는 커밋하지 않는다.

```bash
cp .env.example .env
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

set -a
source .env
set +a
```

마지막 세 명령은 Bash/Zsh에서 `.env` 값을 현재 shell 환경변수로 내보낸다. Docker
Compose와 Python script는 `.env`를 직접 읽지만 dbt의 `env_var()`는 shell 환경변수를
사용하므로 dbt 실행 전에 이 단계가 필요하다. 새 terminal을 열었다면 다시 실행한다.

기본 host port는 다른 로컬 PostgreSQL과의 충돌을 줄이기 위해 `55432`를 사용한다.
필요하면 `.env`의 `PGPORT`만 다른 빈 포트로 바꾼다. loader는 이 프로젝트의 안전
경계에 맞춰 `localhost`, `127.0.0.1`, `::1` 이외의 DB host를 거부한다.

4. 저장소 루트에서 source profile을 재검증한다.

```bash
.venv/bin/python scripts/profile_source.py check \
  --data-dir data/raw \
  --contract config/olist-source-contract.json \
  --output-dir reports

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

`check`는 실제 CSV에서 구조·값 profile을 다시 만들고 저장소에 승인된 보고서와 byte
단위로 같은지 확인한다. Clean clone 검증에서는 기존 기준을 덮어쓰지 않도록 반드시
`check`를 먼저 실행한다. `build`는 source snapshot이나 계약을 의도적으로 변경하고
검토받은 보고서를 교체할 때만 사용한다. Source profiler 자체는 Python 표준
라이브러리만 사용하며, 이어지는 전체 저장소 test에는 앞에서 설치한 requirements가
필요하다.

기본 경로가 아닌 곳에 원천 파일이 있다면 `--data-dir`만 바꿔 실행할 수 있다.
보고서에는 파일 checksum, 행 수, NULL·중복·미연결 행, 조인 증폭과 계약 지정
열의 타입 변환·최소/최대, 공개 허용 도메인 분포, 날짜 비교와 주문 단위 금액
대사 집계만 남는다. 미등록 도메인은 값 없이 행 수와 고유값 수만 기록하며,
실제 ID, 위치값, 리뷰 문장, 알 수 없는 원문 값과 로컬 절대경로는 남기지 않는다.

이 시점의 `unittest discover`는 합성 unit test를 확인하는 초기 검사다.
`RUN_POSTGRES_TESTS=1`을 지정하지 않으므로 PostgreSQL integration test는 skip된다.

5. PostgreSQL 15를 시작하고 raw snapshot을 적재·검산한다.

```bash
docker compose up -d --wait
RUN_POSTGRES_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest tests.test_load_raw_integration -v
.venv/bin/python scripts/load_raw.py load --data-dir data/raw
.venv/bin/python scripts/load_raw.py check --data-dir data/raw
```

`load`와 `check`는 DB 연결 전에 source profiler의 `check`를 다시 실행한다. `load`는
계약에 있는 9개 테이블만 하나의 transaction에서 `TRUNCATE`한 뒤 PostgreSQL `COPY`로
적재하며, 파일을 읽는 동안 계산한 크기·SHA-256와 적재 후 전수 행 수가 모두 맞을 때만
commit한다. 따라서 재실행해도 행이 누적되지 않고 중간 실패 시 직전 정상 상태로
rollback된다. `check`는 DB를 바꾸지 않고 raw schema·열과 행 수만 다시 확인한다.

raw의 모든 열은 nullable `text`이며 CSV의 빈 field도 빈 text로 보존한다. 값 변형을
막기 위해 raw table에 constraint·index·trigger·rewrite rule·RLS를 허용하지 않는다.
숫자·날짜 변환, `NULLIF`, trim, dedup과 업무 규칙은 이 단계에서 적용하지 않고 이후
dbt staging의 명시적 계약으로 처리한다. 결과는
`reports/raw-load-reconciliation.json`과 사람이 읽는
`reports/raw-load-reconciliation.md`에 집계값만 기록한다.

`check`는 하나의 repeatable-read DB snapshot에서 schema와 행 수를 확인하지만 DB 값
전체를 원천과 다시 비교하지는 않는다. 같은 행 수를 유지한 임의 값 변경까지 탐지하는
명령으로 해석하지 않는다.

6. 승인된 계약에 따라 dbt staging table을 만들고 품질 테스트를 실행한다.

```bash
.venv/bin/dbt debug --profiles-dir .
.venv/bin/dbt build --profiles-dir . --select path:models/staging
```

staging은 raw table 9개와 1:1로 대응하며 정확히 빈 문자열인 값만 SQL `NULL`로
바꾼다. 승인된 숫자·timestamp 열은 명시적으로 cast하지만 행 필터, join, 중복 제거와
값 보정은 하지 않는다. Model contract로 출력 열 이름과 타입을 강제하고, table
materialization으로 build 시 전체 행의 cast를 평가한다. Data test는 raw와의 행 수,
key, domain, 범위와 core relationship을 확인한다.

이 구성은 현재 정적 로컬 snapshot을 위한 선택이다. staging build 통과가 모든 값의
업무적 정확성이나 fact·mart 지표의 정확성을 보장하지는 않는다. 실행 결과와 범위는
`reports/dbt-staging-validation.md`에서 확인한다.

7. 전체 dbt graph, pandas 분석 산출물과 PostgreSQL integration test를 검증한다.

```bash
.venv/bin/dbt build --profiles-dir .

.venv/bin/python scripts/analyze_delivery_reviews.py check

RUN_POSTGRES_TESTS=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest discover -s tests -v
```

최종 기대 결과는 dbt 모델 20개와 data test 245개, 총 265개 node 통과 및 Python
test 34개 통과다. pandas `check`의 PNG byte 비교는 같은 고정 Python·의존성·font
rendering 환경에서의 재현을 확인한다. 다른 운영체제나 font library에서는 의미가
같은 차트도 byte가 달라질 수 있다. Clean clone에서는 승인 산출물을 먼저 덮어쓰지
않도록 `check`를 실행한다. `build`는 보고서·차트를 의도적으로 갱신하고 검토할 때만
사용한다.

작업을 멈출 때는 다음 명령을 사용한다. named volume은 유지되므로 다시 시작해도 적재한
테이블이 남는다.

```bash
docker compose down
```

`.env`의 DB명·사용자·password를 바꿔도 이미 만들어진 named volume의 초기 계정은
자동으로 바뀌지 않는다. volume 삭제는 복구가 필요한 명시적 reset 작업이므로 기본
절차에 포함하지 않는다.

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
