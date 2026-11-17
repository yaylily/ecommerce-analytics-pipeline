# Project charter

> Scope approved: 2026-10-08 · bounded post-mart analysis approved: 2026-10-16
> 구현 진행 상태는 README의 `현재 상태`에서 관리한다.

## Purpose

Olist 공개 주문·상품·판매자 데이터를 연결해 거래 특성과 배송·리뷰 관계를 반복
분석할 수 있는 모델을 만든다. 각 원천의 한 행 의미와 조인 관계를 명확히 정의하고,
원천부터 최종 분석 결과까지 지표의 일관성을 검증한다.

이를 위해 다음 기준을 적용한다.

- 잘못된 1:N 조인에 따른 행·금액 증폭을 재현하고 선집계로 방지
- 지표 의미를 구현 전에 계약으로 고정
- 원천부터 최종 분석 테이블까지 숫자를 검산
- 잘못된 데이터와 집계를 자동 테스트로 탐지

## Core business questions

1. 카테고리와 판매자별 주문·상품 거래 특성은 어떻게 다른가?
2. 약속한 배송일을 넘긴 주문과 리뷰 점수 사이에는 어떤 관계가 있는가?

정확한 지표, 주문 상태, 기준 날짜와 review 처리 방식은 source profile 이후
확정한다. 두 번째 질문은 관찰 관계이며 배송 지연이 리뷰를 변화시켰다는 인과로
표현하지 않는다.

## Planned delivery sequence

1. 안전한 데이터 준비 절차와 재현 가능한 source profile
2. model grain·key·join과 metric contract 승인
3. PostgreSQL raw 적재와 행 수 검산
4. dbt typed staging과 fan-out-safe intermediate models
5. 질문에 필요한 facts, dimensions와 marts
6. grain·관계·도메인 규칙과 source-to-mart reconciliation tests
7. 대표 오류의 red → green 검증
8. 검증된 mart를 입력으로 한 pandas 분석 1건과 핵심 차트 2개
9. 비개발자가 이해할 수 있는 짧은 결과 보고서와 재현 가능한 README
10. 결과 검토·수정과 공개 문서 정리

## Planned stack

- SQL and modeling: PostgreSQL 15 · dbt Core · dbt-postgres
- Source preparation: Python standard library
- Analysis and delivery: pandas · matplotlib · Streamlit
- Local reproducibility: Docker Compose

## Non-goals

- 소비자 행동 이벤트가 필요한 조회·장바구니·구매 퍼널
- 광고비와 attribution이 필요한 ROAS·CAC
- 재고 snapshot이 필요한 품절·재고 회전
- COGS·수수료·환불액이 필요한 이익·순매출
- 예측 모델과 인과 추론
- 실시간 처리, 오케스트레이터, 스트리밍과 클라우드 배포

## AI-assisted development boundary

AI는 코드·테스트·문서 초안과 대안 탐색을 돕는다. 사용자는 분석 질문,
grain·key, join·중복 정책, 지표 정의, 검산 기준과 결과 해석을 결정한다.

중요한 선택은 `docs/decisions.md`에 남기며, 구현 완료는 생성된 코드가 아니라
실제 테스트·검산과 검토된 결과로 판단한다.

## Definition of done

- clean clone 기준 데이터 준비부터 변환·테스트까지 문서대로 재현 가능
- 모든 핵심 모델의 한 행 의미와 key가 문서·테스트에 일치
- 1:N 직접 조인의 잘못된 합계와 수정 결과를 재현하고 설명 가능
- 대표 지표가 source, fact, mart와 pandas 결과에서 같은 값으로 검산됨
- 핵심 오류를 넣으면 관련 테스트가 실패하고 수정 후 통과함
- 배송 지연·리뷰 질문을 pandas로 재현하고 핵심 차트 2개와 짧은 결과 보고서를 생성 가능
- README가 실제 구현 범위와 데이터 한계를 정확히 반영
