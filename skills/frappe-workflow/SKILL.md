---
name: frappe-workflow
description: Checkpoints for Frappe document states — docstatus (draft, submitted, cancelled), submit/cancel/amend, Workflow doctype states and transitions, and custom status fields. Use when a change touches document state or who can move it.
---

# frappe-workflow — 문서 상태 체크포인트

## 세 가지 상태를 구분한다
| 개념 | 저장 위치 | 의미 |
|---|---|---|
| `docstatus` | 모든 문서 | 0 초안, 1 제출(수정 불가), 2 취소. 제출 가능(`is_submittable`) DocType만 1·2가 있다 |
| Workflow 상태 | Workflow 문서 + 문서의 상태 필드(보통 `workflow_state`) | 역할별 전이(action). 각 상태가 `doc_status`에 연결될 수 있음 |
| 앱 자체 상태 필드 | Select 필드 + 서버 메서드 | 프로젝트가 직접 관리. docstatus·Workflow와 섞지 않는다 |

프로젝트 결정 문서에 어떤 방식을 쓰는지 적혀 있으면 그대로 따른다(예: "제출 문서가 아니다, 상태는 서버 메서드로만").

## 체크
- 상태 전이 규칙은 서버에: 컨트롤러 `validate`/`before_submit`/`on_cancel` 또는 전용 whitelisted 메서드(권한 검사 포함). 클라이언트 버튼만으로 막지 않는다.
- **v16.60.2:** Workflow 전이는 `frappe.model.workflow.apply_workflow(doc, action)`, 가능한 전이는 `get_transitions`, 저장 시 검사는 `validate_workflow`(`frappe/model/workflow.py`). Workflow를 우회하는 `db_set`은 검사를 건너뛴다.
- 제출 후 바꿔야 하는 필드는 `allow_on_submit`. 남발하면 제출 의미가 사라진다.
- 취소·수정(amend) 시 연결 문서(자식·참조 문서)의 상태와 집계가 맞는지 본다.
- 상태 이름을 바꾸면 기존 데이터·필터·리포트·patch가 옛 이름을 쓰는지 검색한다.
- Workflow를 도입하거나 바꾸는 것은 업무 규칙 변경이다(Feature + Grilling).

## Tester에게 넘길 검증
- 허용된 전이 성공, 허용되지 않은 전이·역할 실패.
- 제출 문서 수정 시도 실패, 취소·amend 후 연결 데이터 정합성.
- 기존 상태 값을 가진 데이터가 새 규칙에서 어떻게 보이는지.
