# ecommerce-analytics-pipeline

Olist 공개 이커머스 데이터를 이용해 주문·주문상품·결제·리뷰처럼 한 행의
의미가 다른 원천을 안전하게 모델링하고, 원천부터 최종 분석 테이블까지 같은
지표가 재현되는지 검증하는 Analytics Engineering 프로젝트입니다.

## 현재 상태

**카테고리·판매자 월별 거래 mart 구현·검증 완료 · 결과 검토 단계**

Olist 원천 CSV 9개에서 파일 checksum·행 수·헤더, NULL, 후보키 다중도,
관계의 미연결 행과 fan-out을 집계하고 상품·결제 직접 조인의 금액 증폭을
재현했습니다. 후보키 가설, 관계 다중도와 직접 조인 증폭의 의미와 한계를
검토했으며, 원천 행이나 식별자 샘플은 결과에 포함하지 않습니다.

이후 핵심 열의 타입 변환 가능성, 주문 상태·결제 수단·리뷰 점수 분포, 날짜·시간
선후 관계와 주문 단위 상품 측·결제 측 금액 차이를 추가로 집계했습니다. 이 결과는
상태별 결측·시간 역전과 금액 대사의 의미와 한계까지 검토했습니다. 이 관찰을 근거로
모델·지표·품질 정책을 승인했지만, 고정 snapshot의 관찰값 자체를 일반적인 업무상
진리로 확대하지 않습니다.

- 구조 결과: [`reports/source-profile.md`](reports/source-profile.md)
- 값 품질 결과: [`reports/source-value-profile.md`](reports/source-value-profile.md)
- raw 적재 결과: [`reports/raw-load-reconciliation.md`](reports/raw-load-reconciliation.md)
- dbt staging 결과: [`reports/dbt-staging-validation.md`](reports/dbt-staging-validation.md)
- intermediate·audit 결과: [`reports/intermediate-audit-validation.md`](reports/intermediate-audit-validation.md)
- 거래 dimension·fact 결과: [`reports/transaction-fact-validation.md`](reports/transaction-fact-validation.md)
- 카테고리·판매자 거래 mart 결과: [`reports/trade-marts-validation.md`](reports/trade-marts-validation.md)
- 승인 계약: [`docs/model-metric-contracts.md`](docs/model-metric-contracts.md)

거래 fact·mart, 배송·리뷰, 데이터 품질 정책은 사용자가 의미와 영향을 검토한 뒤
[`docs/model-metric-contracts.md`](docs/model-metric-contracts.md)와 D-007~D-009로
승인했습니다. 승인은 구현 완료를 뜻하지 않습니다.

PostgreSQL 15의 `raw` schema에 원천 9개를 nullable `text`로 적재하고, 승인된 파일
checksum과 총 1,550,922행을 전수 대사했습니다. 합성 PostgreSQL 통합 테스트에서 CSV
BOM·줄바꿈·빈 field 처리, 재실행 시 비누적과 중간 실패 시 전체 rollback도 확인했습니다.

raw 9개와 1:1로 대응하는 dbt staging table을 만들고, 정확히 빈 문자열만 NULL로
해석했습니다. 계약한 숫자·timestamp 변환을 전체 행에 적용한 뒤 행 수 보존, key,
domain, 범위와 core relationship을 검사한 55개 data test가 모두 통과했습니다.

주문상품·결제·리뷰를 주문 단위로 먼저 집계하고, 전체 주문 기준 금액 대사와 배송
timing·chronology flag를 구현했습니다. 원천 count·금액·점수 합과 주문 key를 대사하고,
상품×결제와 복수 리뷰의 직접 조인 중복을 합성 fixture로 재현한 뒤 선집계 구조에서
해결됨을 확인했습니다. 결과의 의미와 한계를 검토했으며, 차이를 오류로 단정하거나
허용 tolerance를 임의로 만들지 않았습니다.

상품과 판매자 dimension, 전체 상태를 보존하는 주문상품 fact를 구현했습니다. 원문
카테고리 누락과 번역 누락을 구분하고, 원천 주문상품의 복합 key·행 수·금액을 fact와
행별·전체 합계로 대사했습니다. missing category는 승인한 `__missing_source__` 내부
key와 충돌 방지 test로 보존합니다.

배송 완료 주문상품을 구매월×카테고리와 구매월×판매자 단위로 집계한 두 거래 mart를
구현했습니다. 가산 금액·주문상품 행 수는 delivered fact 전체와, 그룹별 연결 주문 수는
월×주문×카테고리 또는 판매자 조합 수와 각각 대사했습니다. missing·unmapped 카테고리도
제거하지 않았습니다. 전체 dbt build 231개 노드와 기존 Python 테스트 24개가
통과했습니다. 배송·리뷰 mart와 post-mart pandas 산출물은 아직 구현하지 않았습니다.
`shipping_limit_date`, 금액 tolerance 등 `[UNRESOLVED]` 정책도 해결된 것처럼 표현하지
않으며 dashboard는 선택 확장입니다.

## 해결하려는 문제

Olist에서 주문 한 건에는 여러 주문상품·결제·리뷰가 연결될 수 있습니다. 이
테이블들을 그대로 조인하면 주문 수와 금액이 중복 집계될 수 있습니다.

이 프로젝트는 다음 순서로 이 문제를 해결합니다.

1. 각 원천과 모델에서 한 행이 무엇을 의미하는지 정의
2. 1:N 관계와 중복 가능성을 실제 데이터로 확인
3. 목표 단위로 먼저 집계한 뒤 테이블 결합
4. 원천·중간 모델·최종 분석 테이블의 건수와 금액 검산
5. 잘못된 데이터와 조인을 자동 테스트로 탐지

## 핵심 질문

1. 카테고리와 판매자별 주문·상품 거래 특성은 어떻게 다른가?
2. 약속한 배송일을 넘긴 주문과 리뷰 점수 사이에는 어떤 관계가 있는가?

구체적인 지표 공식, 포함할 주문 상태, 기준 날짜와 review 처리 방식은 승인된
model/metric contract를 따릅니다. 관찰 데이터의 관계를 인과 효과로 표현하지 않습니다.

## 분석 전달 범위

PostgreSQL과 dbt로 검산된 mart를 만든 뒤, 배송 지연·리뷰 질문 하나를 pandas로
분석합니다. pandas는 dbt 변환을 다시 구현하지 않고 최종 mart의 탐색·집계·시각화에만
사용합니다. core 결과물은 재현 가능한 분석 스크립트 1개, 핵심 차트 2개와
비개발자가 이해할 수 있는 짧은 결과 보고서 1개로 제한합니다.

추가 통계 분석과 dashboard는 core 결과를 완성한 뒤 지원 직무에 필요할 때만 확장합니다.

## 선택 확장

작은 dashboard는 pandas 분석과 결과 보고서가 완성된 뒤 BI 지원에 필요할 때만
추가합니다. Olist Marketing Funnel 데이터 연결도 핵심 모델과 분석 결과를 완료한 뒤
재평가하며, 둘 다 core 완료 조건은 아닙니다.

## 계획한 기술

- Core: SQL · PostgreSQL · dbt Core (`dbt-postgres`)
- Analysis: Python · pandas · matplotlib
- Support: Docker Compose · Git
- Later: 선택적 작은 dashboard · fixture 기반 CI

Docker는 로컬 PostgreSQL을 재현하기 위한 보조 도구이며, 클라우드·실시간 처리와
복잡한 오케스트레이션은 이 프로젝트의 목표가 아닙니다.

## 다루지 않는 것

원천에 필요한 데이터가 없으므로 다음 지표를 만들지 않습니다.

- 소비자 방문 → 장바구니 → 구매 퍼널
- 광고비, ROAS와 CAC
- 재고, 품절과 재고 회전
- 원가, 이익과 순매출

`order_items.price`의 합은 회사 매출이나 이익이 아니라 상품 거래액 성격의
값으로 제한해 사용합니다.

## 데이터

- [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
- License: CC BY-NC-SA 4.0
- Coverage: 2016–2018년 익명화된 주문 데이터

원본 CSV, 리뷰 원문과 행 단위 식별자는 저장소에 커밋하지 않습니다. 데이터
준비 경계는 [`data/README.md`](data/README.md)를 따릅니다.

## 개발 방식

생성형 AI는 구현 대안 탐색, 코드·테스트와 문서 초안 작성에 활용합니다. 분석
질문, 모델의 한 행 의미, 지표와 조인 정책은 사용자가 결정하며, 채택한 변경은
데이터 테스트와 원천-최종 테이블 검산으로 확인합니다.

- [Project charter](docs/project-charter.md)
- [Decision log](docs/decisions.md)
- [Repository working agreement](AGENTS.md)
