# Small Change Playbook

이미 있는 UI/UX를 빠르게 조정한다. 업무 규칙·데이터 구조·권한은 바꾸지 않는다.

**허용:** 필드 순서·라벨·설명, 섹션/컬럼 배치, 목록 열 표시, 버튼 위치, 기본 필터, 표시 개선.
**전환(→ Feature 등):** 필드 추가·삭제, fieldtype·options(Link 대상) 변경, `reqd`·저장/계산 규칙, Permission, Workflow 변경. 작업 중 이런 변경이 필요해지면 멈추고 Main에게 돌아간다.

## 절차
1. **Main:** 대상 DocType/화면과 관련 파일을 확인한다. 기존 레이아웃 테스트나 프로젝트 규칙(AGENTS.md)과 충돌하는지 본다. Grilling은 보통 생략한다.
2. **Implementer:** Dev 사이트에서 최소 변경. DocType JSON을 고쳤다면 Dev에 `bench --site <dev> migrate`. 변경 파일과 적용 명령을 보고한다.
3. **Main:** 코드 동결 스냅샷(develop §4)을 만든다.
4. **Tester:** Test 사이트에 같은 코드를 적용(`bench --site <test> migrate`)하고, 브라우저로 변경 화면을 직접 확인하고 스크린샷을 남긴다. 관련된 기존 테스트가 있으면 실행한다. 코드가 있으면 변경 파일만 Ruff/ESLint 검사.
5. **Main:** 스냅샷을 다시 비교하고 판정·보고·`tasks.jsonl` 기록.

## 완료 조건
- 요청한 UI 변화가 Test 사이트 화면에서 확인됨(스크린샷 경로).
- 기존 동작 유지(관련 기존 테스트가 있으면 통과).
- 브라우저를 쓸 수 없으면 `UNVERIFIED`. 스크린샷을 만들어내지 않는다.
