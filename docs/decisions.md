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
- Supersedes / Superseded by: 없음

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
