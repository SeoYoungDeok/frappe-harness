---
name: grill
description: Grill the user on hard-to-reverse design decisions (data relations, key field meaning, business rules, permissions, data migration) before a Frappe change. Use when a request is new, ambiguous, contradictory or changes core structure, or when the user asks to grill.
---

# grill — 중요한 설계만 질문해서 합의

## 언제
- 정보가 부족하거나 모호·모순된 요청, 신규 업무 기능의 핵심 설계, 데이터 관계·핵심 필드 의미·업무 규칙·권한·데이터 이전 결정.
- Implementer/Tester가 설계 충돌을 보고했을 때(그 부분만).
- 사용자가 직접 호출했을 때.
- **생략:** 필드 순서·라벨·레이아웃처럼 구조 영향이 없는 명확한 Small Change.

## 절차
1. 관련 코드·DocType JSON·설치 앱·프로젝트 결정 문서(`.frappe-harness.toml`의 `context_doc`)를 필요한 만큼 먼저 확인한다. 코드에서 확인되는 사실은 묻지 않는다.
2. 나눈다: **확인된 사실** / **사용자 합의가 필요한 설계 판단** / **구현자가 정해도 되는 기술 세부**.
3. 되돌리기 어려운 결정부터, 서로 의존하는 순서대로, 지금 답할 수 있는 질문만 묶어 묻는다.
4. 질문마다 권장안과 이유를 붙인다. 대안과 영향은 필요할 때만.
5. 이미 확정된 내용은 다시 묻지 않는다.
6. 핵심 불확실성이 풀리면 멈춘다. UI 세부까지 확정하지 않는다.

## 결과 (짧게)
```markdown
### Grilling 결과
- 요청 목표:
- 현재 확인:
- 확정:
- 보류:
- 유지 조건:
- 검증 기준:
- 영향:
- 다음: <Playbook>
```
확정된 중요 결정은 프로젝트 결정 문서(`.frappe-harness.toml`의 `context_doc`)에 "합의됨(미구현)" 상태로 적는다.
