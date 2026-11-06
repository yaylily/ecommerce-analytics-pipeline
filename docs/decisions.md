# Decision log

이 문서는 프로젝트 결과의 의미나 구현 방향을 바꾸는 결정을 기록한다. 사소한
파일명·포맷 변경과 작업 일지는 기록하지 않는다.

## Decision status values

- `Proposed`: 선택지를 검토 중이며 의존 구현을 시작하지 않음
- `Accepted`: 사용자가 의미와 영향을 확인하고 승인함
- `Superseded`: 새로운 결정으로 대체됨. 과거 기록은 삭제하지 않음

AI는 선택지와 초안을 작성할 수 있지만 사용자의 명시적 확인 없이 상태를
`Accepted`로 바꾸지 않는다.

`Accepted`는 방향을 합의했다는 뜻이며 구현 완료를 의미하지 않는다. 구현 상태는
README의 `현재 상태`에서만 관리하고, 실제 코드·테스트와 검산 결과로 판단한다.

## Decision template

```text
### D-XXX — 제목
- Status / Date:
- Context:
- Options considered:
- Decision:
- Why:
- Consequences and limitations:
- Validation criterion:
- Supersedes / Superseded by:
```

---

### D-001 — Start from a clean repository

- Status / Date: Accepted / 2026-10-07
- Context: 기존 비공개 prototype에는 초기 적재 코드와 계획 문서가 섞여 있고,
  공개용 프로젝트의 판단·검증 순서를 보여주기 어려웠다.
- Options considered:
  1. 기존 Git 이력을 정리해 계속 사용
  2. 필요한 파일을 모두 복사해 새 이력 시작
  3. 빈 저장소에서 승인한 계약과 구현을 단계별로 다시 작성
- Decision: 빈 `ecommerce-analytics-pipeline` 저장소에서 시작하고 기존 저장소는
  읽기 전용 참고 자료로만 사용한다.
- Why: 검증되지 않은 파일과 오래된 주장을 가져오지 않고, 실제 판단과 검증이
  생성되는 순서대로 안전한 Git 이력을 만들기 위해서다.
- Consequences and limitations: 기존 `.git`, CSV, `.env`, loader와 문서를 통째로
  복사하지 않는다. 유효한 아이디어도 새 데이터 확인과 검토를 거쳐 재작성한다.
- Validation criterion: 첫 커밋 전 tracked file과 remote를 확인하고 raw data·secret이
  없음을 검사한다.
- Supersedes / Superseded by: 없음

### D-002 — Use Olist commerce as the core dataset

- Status / Date: Accepted / 2026-10-07
- Context: 첫 공개 프로젝트는 일반적인 커머스 데이터에서 SQL·데이터 모델링과
  품질 검증을 보여줘야 한다.
- Options considered: Olist, TheLook, GA4 sample ecommerce, Instacart와 RetailRocket
- Decision: Olist Brazilian E-Commerce 9개 파일을 핵심 데이터로 사용한다.
  Olist Marketing Funnel은 핵심 모델 완료 후 선택 확장으로 둔다.
- Why: 실제 익명 관계형 데이터에서 주문·상품·결제·리뷰의 서로 다른 한 행
  의미와 1:N 중복 문제를 다룰 수 있고, 온라인 MD 경험과 연결할 수 있다.
- Consequences and limitations: 데이터는 2016–2018년 정적 표본이며 소비자 이벤트,
  광고비와 재고 snapshot이 없다. 현재 시장 성과나 원천에 없는 지표를 주장하지 않는다.
- Validation criterion: source profile에서 파일·key·NULL·cardinality와 분석 가능 범위를
  다시 확인한다.
- Supersedes / Superseded by: 없음

### D-003 — Use PostgreSQL and dbt as the analytical core

- Status / Date: Accepted / 2026-10-07
- Context: 핵심 목표는 로컬에서 재현 가능한 SQL 모델, 테스트와 검산을 만드는 것이다.
- Options considered: PostgreSQL+dbt, BigQuery+dbt, DuckDB+dbt, Python 중심 ETL
- Decision: PostgreSQL 15와 dbt Core(`dbt-postgres`)를 핵심으로 사용한다. Python은
  source profile과 적재에, Docker Compose는 로컬 DB 재현에만 사용한다.
- Why: BigQuery 인증·비용과 새로운 클라우드 학습축을 추가하지 않고 관계형
  모델링과 dbt 기본기를 집중적으로 증명할 수 있다.
- Consequences and limitations: Docker·인프라 전문성이나 클라우드 운영 경험으로
  표현하지 않는다. 대시보드와 CI 도구는 core model 검증 후 결정한다.
- Validation criterion: 실제 환경을 만든 뒤 clean setup과 dbt build의 재현성을 확인한다.
- Supersedes / Superseded by: post-mart Python 사용 범위만 D-010으로 확장하며,
  PostgreSQL·dbt core 결정은 유지한다.

### D-004 — Record AI-assisted decisions through contracts and verification

- Status / Date: Accepted / 2026-10-07
- Context: AI를 많이 사용하더라도 데이터 의미와 최종 판단의 소유권이 흐려지지
  않고, 다음 세션에서 결정이 유실되지 않아야 한다.
- Options considered:
  1. 프롬프트와 대화 전문 저장
  2. 다수의 rules·hooks·skills와 상태 보드 운영
  3. 최소 작업 계약, 결정문, model/metric contracts와 검증 결과 유지
- Decision: 세 번째 방식을 사용한다. AI는 선택지·코드·테스트·문서 초안을 만들고,
  사용자는 grain·지표·join·검산과 최종 채택을 결정한다.
- Why: AI 사용량이 아니라 잘못된 결과를 발견·수정하고 설명할 수 있는지가
  Analytics Engineering 역량을 더 잘 증명한다.
- Consequences and limitations: 프롬프트 전문, AI 작성 비율과 세션 로그는 공개하지
  않는다. 결정 변경은 과거 기록을 지우지 않고 대체 관계로 남긴다.
- Validation criterion: PR·커밋에서 계약, 구현, 실패→수정 테스트와 검산 결과의 연결을 확인한다.
- Supersedes / Superseded by: 없음

### D-005 — Start with two business questions

- Status / Date: Accepted / 2026-10-07
- Context: 모든 원천과 지표를 한 번에 모델링하면 학습과 검증 범위가 커지고,
  도구 나열 중심 프로젝트가 될 수 있다.
- Options considered: 거래·배송·재구매 3개 질문 동시 진행, 핵심 2개 우선 진행
- Decision: 핵심 범위는 판매자·카테고리 거래 특성과 배송 지연·리뷰 관계에 집중한다.
  재구매와 marketing funnel은 core model 이후 재평가한다.
- Why: 온라인 MD 경험과 직접 연결되며 주문·상품·결제·리뷰 grain, fan-out과
  관찰 데이터 해석을 함께 보여줄 수 있다.
- Consequences and limitations: exact metric formula와 filter는 source profile 후
  별도 metric contract로 승인한다. 배송과 리뷰의 관계를 인과로 표현하지 않는다.
- Validation criterion: 두 질문이 각각 최종 mart와 재현 SQL로 답해지고 원천까지 대사되는지 확인한다.
- Supersedes / Superseded by: 없음

### D-006 — Use short-lived branches and pull requests

- Status / Date: Accepted / 2026-10-10
- Context: 개인 프로젝트에서도 AI-assisted 변경의 범위, 판단과 검증 흔적을
  남기되 장기 브랜치 관리 부담은 피해야 한다.
- Options considered:
  1. 모든 변경을 `main`에 직접 커밋
  2. `main`과 장기 `dev`를 운영하는 GitFlow
  3. `main`과 짧은 작업 브랜치, PR을 사용하는 trunk-based workflow
- Decision: 세 번째 방식을 사용한다. 초기 bootstrap 이후 모든 프로젝트 변경은
  최신 `main`에서 만든 작업 브랜치에서 진행하고 PR 검토 후 병합한다.
- Why: `main`을 검증된 상태로 유지하면서도 작업 단위별 계약·diff·검증 결과와
  사용자 판단을 공개 가능한 이력으로 남길 수 있다.
- Consequences and limitations: 작은 변경에도 브랜치와 PR이 필요하다. 대신 장기
  `dev` 동기화와 다단계 병합은 관리하지 않는다.
- Validation criterion: PR의 범위가 하나의 작업 단위인지, 최종 검증이 통과했는지,
  진행 단계 변경 시 README가 함께 갱신됐는지 확인한다.
- Supersedes / Superseded by: 없음

### D-007 — Use item-grain facts and separate trade marts

- Status / Date: Accepted / 2026-10-17
- Context: 주문에는 여러 상품·판매자·카테고리와 결제행이 연결될 수 있어 주문 grain으로
  먼저 축약하거나 raw 결제를 직접 조인하면 상세가 사라지거나 금액이 증폭된다.
- Options considered: 주문 grain 단일 mart, 결제를 item에 배분한 통합 mart,
  item fact와 category·seller mart 분리
- Decision: [`model-metric-contracts.md`](model-metric-contracts.md)의 거래 계약을 사용한다.
  원천 item grain fact를 보존하고, delivered 주문의 purchase month 기준 category·seller
  mart를 따로 만든다. 상품 금액과 배송비는 분리하며 결제는 주문별 대사 모델에서만 쓴다.
- Why: 원천 detail과 additive 금액을 보존하면서 근거 없는 결제 배분과 1:N fan-out을
  피하기 위해서다.
- Consequences and limitations: 그룹별 distinct 주문·상품 수는 그룹 간 더할 수 없고,
  상품 금액을 매출·이익으로 표현하지 않는다. item이 없는 주문은 fact에 포함되지 않는다.
- Validation criterion: item fact의 행·key·금액이 staging과 대사되고, mart의 additive
  지표가 delivered fact와 대사되며 fan-out fixture가 직접 조인의 오류를 재현한다.
- Supersedes / Superseded by: 없음

### D-008 — Compare delivery timing and reviews at order grain

- Status / Date: Accepted / 2026-10-17
- Context: 리뷰는 주문당 여러 행일 수 있고, 예정일은 현재 snapshot에서 date-like 값으로
  관찰돼 timestamp와 calendar-date 지연 분류가 달라질 수 있다.
- Options considered: 첫/최신 리뷰 선택 또는 전체 평균, timestamp 또는 calendar date,
  chronology 이상 주문 삭제 또는 flag 보존
- Decision: [`model-metric-contracts.md`](model-metric-contracts.md)의 배송·리뷰 계약을
  사용한다. delivered이며 날짜 비교가 가능한 주문에 리뷰를 주문별 선집계해 결합하고,
  모든 리뷰의 주문별 평균과 calendar-date 지연 여부를 비교한다. 결측·시간 역전은 원천에
  보존하고 관련 flag와 제외 건수를 대사한다.
- Why: 주문을 동일 가중하면서 복수 리뷰 join 중복과 같은 날 배송의 잘못된 지연 분류를
  피하기 위해서다.
- Consequences and limitations: 결과는 리뷰가 있는 주문의 관찰적 연관이며 인과 효과가
  아니다. 복수 리뷰 대표값 정책과 리뷰 누락에 따른 대표성 한계를 함께 공개한다.
- Validation criterion: review summary가 staging의 행·점수 합과 대사되고, delivered
  inclusion funnel과 timing 상태가 전체 대상 주문 수와 대사된다.
- Supersedes / Superseded by: 없음

### D-009 — Separate hard failures from preserved data anomalies

- Status / Date: Accepted / 2026-10-17
- Context: 원천에는 확정적인 key·domain 규칙과 아직 업무 오류로 단정할 수 없는 0값,
  시간 역전, 금액 차이와 mapping 누락이 함께 있다.
- Options considered: 모든 이상 관찰을 fail, 모든 검사를 warn, 확정 규칙만 fail하고
  나머지는 flag·대사 후 정책 결정
- Decision: [`model-metric-contracts.md`](model-metric-contracts.md)의 품질 정책을 사용한다.
  key·cast·exact domain과 core FK는 fail로, 원인이 미정인 이상은 원천을 보존한 채
  warn·flag·reconciliation으로 관리한다.
- Why: 명백한 계약 위반은 조기에 차단하면서도 데이터 의미를 확인하기 전에 관찰 행을
  임의 삭제하거나 정상값으로 교정하지 않기 위해서다.
- Consequences and limitations: 금액 tolerance와 일부 anomaly 처리 기준은 DB 적재 후에도
  미정으로 남으며, 관련 분석은 그 정책이 승인되기 전까지 확정하지 않는다.
- Validation criterion: fail 규칙은 합성 위반 fixture에서 실패하고, 보존 대상 anomaly는
  모델 행을 삭제하지 않은 채 flag·제외 수와 원천 건수가 대사된다.
- Supersedes / Superseded by: 없음

### D-010 — Use pandas only as the post-mart analysis layer

- Status / Date: Accepted / 2026-10-16
- Context: SQL·dbt 모델링뿐 아니라 Python 기반 탐색과 비개발자 대상 결과 설명을
  증명해야 하지만, 같은 변환을 dbt와 pandas에 중복 구현하면 두 기준이 생기고 범위가
  불필요하게 커진다.
- Options considered: pandas를 사용하지 않음, dbt 변환을 pandas로 재구현,
  검증된 mart를 입력으로 제한된 분석만 수행
- Decision: 세 번째 방식을 사용한다. core mart 완성 후 배송 지연·리뷰 질문 하나를
  pandas로 분석하고, 재현 가능한 스크립트 1개·핵심 차트 2개·짧은 비개발자용 결과
  보고서 1개를 만든다.
- Why: SQL·dbt를 데이터 의미와 품질의 단일 기준으로 유지하면서 pandas 데이터 처리,
  시각화와 비즈니스 해석 능력을 실제 결과물로 보여주기 위해서다.
- Consequences and limitations: pandas는 mart의 grain·지표를 다시 정의하지 않는다.
  추가 통계 분석, dashboard, Marketing Funnel과 새로운 데이터셋은 core 범위에 넣지 않는다.
- Validation criterion: pandas 입력 행·key와 핵심 집계가 mart와 대사되고, 같은 입력과
  명령에서 동일한 승인 지표를 사용하는 차트 2개와 보고서용 수치가 재현된다. 보고서는
  가정·분모·제외 조건·한계와 비인과 경계를 설명하며, 사용자가 주요 집계를 설명할 수 있다.
- Supersedes / Superseded by: 없음. D-003의 PostgreSQL·dbt core 결정은 유지한다.

### D-011 — Use a collision-guarded key for missing source category

- Status / Date: Accepted / 2026-11-06
- Context: 원문 category가 NULL인 상품도 후속 category mart에서 별도 그룹으로 보존해야
  하지만, 표시명과 내부 집계 key를 같은 값으로 쓰거나 NULL key를 유지하면 역할이
  섞이고 충돌 여부를 명확히 검사하기 어렵다.
- Options considered: NULL key 유지, 표시명 `Unknown`을 key로 사용,
  충돌을 검사하는 별도 sentinel key 사용
- Decision: 원문 category가 NULL이면 `category_key = '__missing_source__'`를 사용하고
  표시명은 `Unknown`으로 유지한다. 원천 category에 같은 문자열이 나타나면 fail한다.
- Why: 원문 누락을 번역 누락과 구분하고, 후속 `GROUP BY`와 fact-to-mart 대사에서
  missing 그룹을 명시적으로 보존하면서 표시 정책과 내부 key 정책을 분리하기 위해서다.
- Consequences and limitations: sentinel은 실제 업무 category가 아니며 사용자에게
  노출할 표시명으로 사용하지 않는다. 다른 데이터셋에 그대로 일반화하지 않는다.
- Validation criterion: source collision test, mapping 3상태 fixture와 상품·fact
  reconciliation이 모두 통과한다.
- Supersedes / Superseded by: 없음
