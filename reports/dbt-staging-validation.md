# dbt staging 변환·품질 검증

## 목적과 범위

PostgreSQL `raw` schema에 text로 적재한 Olist 고정 snapshot 9개를 승인된
[model/metric contract](../docs/model-metric-contracts.md)에 따라 분석 가능한 타입의
staging table로 변환하고, 원천 대비 행 수 보존과 핵심 key·domain·관계 규칙을 검증한다.

이번 범위는 원천과 1:1로 대응하는 staging 모델 9개까지다. intermediate, fact, mart,
비즈니스 지표와 pandas 분석은 포함하지 않는다.

## 실행 환경과 materialization

- PostgreSQL: `15.19`
- dbt Core: `1.12.5`
- dbt PostgreSQL adapter: `1.11.0`
- staging materialization: `table`

staging을 table로 만든 이유는 `dbt build` 시 모든 행의 타입 변환을 실제로 평가하기
위해서다. PostgreSQL view는 생성 시점에 모든 cast를 실행하지 않을 수 있다. 이 선택은
약 155만 행의 정적 로컬 snapshot에 맞춘 것이며, 모든 운영 환경에 대한 일반 해법은 아니다.

## 변환 정책

- raw table 9개와 각각 대응하는 `stg_*` 모델 9개를 만든다.
- 정확히 빈 문자열인 값만 `NULLIF(column, '')`로 SQL `NULL`로 바꾼다.
- 공백이 들어 있는 문자열은 임의로 정리하지 않는다.
- model contract로 선언한 출력 열 이름과 PostgreSQL 타입을 build 시 강제한다.
- 계약에서 승인한 열 15개를 변환한다.
  - timestamp 8개: timezone을 추정하지 않고 `timestamp without time zone`
  - numeric 3개: 금액 열을 PostgreSQL `numeric`
  - integer 4개: 순번·할부 개수·리뷰 점수
- `trim`, 대소문자 변경, 필터, join, 중복 제거와 값 보정은 하지 않는다.
- 원천 열 이름의 오탈자와 명명은 staging 출력에서 일관되게 정리하되 값은 바꾸지 않는다.

## 결과 요약

- 판정: **PASS**
- staging table build: 9/9 성공
- data test: 55/55 통과
- 전체 dbt 실행: `PASS=64`, `WARN=0`, `ERROR=0`, `SKIP=0`, `TOTAL=64`
- raw와 staging 행 수: 9개 모델 모두 일치
- raw 총 행 수: 1,550,922
- staging 총 행 수: 1,550,922
- 행 수 불일치 모델: 0개
- 타입 변환 대상 열: 15개 모두 table build 성공

`64`는 테스트 수가 아니라 table model build 9개와 data test 55개를 합친 실행 node
수다. Table별 원천 행 수와 적재 근거는
[PostgreSQL raw 적재 검산](raw-load-reconciliation.md)에 기록돼 있다.

요약의 `WARN=0`은 model·test node의 실행 상태다. Model contract 검사 중 dbt는
PostgreSQL `numeric` 3개에 precision과 scale이 지정되지 않았다는 참고 경고를 두 차례
출력했다. 실제 열은 precision·scale 제한이 없는 `numeric`으로 생성됐다. 현재 계약은
근거 없는 자리수 제한과 반올림을 추가하지 않는 쪽을 택했으며, 다른 warehouse나 운영
schema로 옮길 때는 명시적인 precision·scale 정책을 다시 결정해야 한다.

## 검증한 규칙

55개 data test로 다음을 확인했다.

- 각 staging 모델의 행 수가 대응하는 raw table과 같은지
- 핵심 단일 key와 composite key가 NULL 없이 고유한지
- 주문 상태, 결제 수단과 리뷰 점수가 승인된 domain 안에 있는지
- 금액·순번·할부 개수가 승인된 범위를 만족하는지
- 주문상품·주문·상품·판매자·고객·결제·리뷰의 core relationship에 orphan이 없는지

타입 변환 가능성은 표본 확인이 아니라 table model을 생성하는 과정에서 전체 행에
cast를 실행해 확인했다. Row-count test는 변환 과정에서 행을 제거하거나 늘리지 않았는지
별도로 확인한다.

## 보존한 값과 후속 처리

staging은 원천을 조용히 고치거나 분석 대상에서 제외하는 단계가 아니다.

- 허용된 0값과 관찰된 `not_defined` 결제 수단을 보존한다.
- 선택적 timestamp의 NULL과 시간 순서 이상 가능성을 보존한다.
- 상품 카테고리 번역 미연결 가능성을 staging에서 제거하지 않는다.
- 상품 측·결제 측 금액 차이를 강제로 일치시키지 않는다.

이 값들은 다음 intermediate·audit 모델에서 flag와 집계 건수로 관찰한다. staging
통과를 업무상 정상 판정이나 이상 원인 규명으로 해석하지 않는다.

## 의미와 한계

이번 결과는 고정 snapshot에 대해 재현 가능한 typed staging 기반이 만들어졌고,
선언한 key·domain·범위·core relationship 규칙을 현재 데이터가 통과했다는 뜻이다.

다만 다음은 아직 말할 수 없다.

- 행 수 일치만으로 모든 개별 값의 업무적 정확성이 보장됐다고 할 수 없다.
- 선언하지 않은 규칙이나 미래 snapshot의 새로운 정상값까지 검증한 것은 아니다.
- 규칙을 일부러 위반한 합성 입력에서 각 dbt test가 실패하는 negative-path 검증은
  이번 범위에 포함하지 않았다.
- fact·mart와 최종 지표의 정확성은 아직 검증하지 않았다.
- 배송 지연과 리뷰의 관계 또는 원인에 대한 분석 결과가 아니다.
- production 운영, cloud 배포, incremental 처리와 대규모 성능을 증명하지 않는다.

## 재현 방법

승인된 원천 CSV를 `data/raw`에 준비하고 `.env.example`을 참고해 로컬 환경 변수를
설정한 뒤 실행한다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python scripts/load_raw.py load --data-dir data/raw
.venv/bin/dbt debug --profiles-dir .
.venv/bin/dbt build --profiles-dir . --select path:models/staging
```

성공 기준은 staging table 9개와 data test 55개가 모두 통과하고, 최종 결과가
`PASS=64`, `WARN=0`, `ERROR=0`, `SKIP=0`, `TOTAL=64`인 것이다.
