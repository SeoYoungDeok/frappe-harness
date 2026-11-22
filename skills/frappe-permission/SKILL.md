---
name: frappe-permission
description: Checkpoints for Frappe permissions — roles and DocPerm, user permissions, document-level and query-level hooks, and server-side checks in APIs. Use when a change affects who can read, create, change, submit or see something.
---

# frappe-permission — 권한 변경 체크포인트

권한 정책(누가 무엇을 할 수 있나)은 사용자와 합의할 설계 결정이다(`grill`). 이 Skill은 기술적으로 빠뜨리기 쉬운 곳만 다룬다.

## 권한이 결정되는 층
| 층 | 위치 | 놓치기 쉬운 점 |
|---|---|---|
| Role × DocType 권한 | DocType JSON `permissions`(DocPerm), 사이트의 Custom DocPerm | Role Permission Manager로 사이트에서 바꾼 값은 다른 사이트·기기로 안 옮겨짐 |
| User Permission | 사이트 데이터 | Link 필드로 연결된 문서 조회까지 제한됨 |
| 문서 단위 훅 | `hooks.py` `has_permission` | **v16.60.2:** `frappe.call(method, doc=doc, ptype=ptype, user=user, debug=debug)`로 불림(`frappe/permissions.py` `has_controller_permissions`). 인자 이름을 맞춘다 |
| 목록·조회 조건 | `hooks.py` `permission_query_conditions` | `get_list`·리포트에 적용, `get_all`·원시 SQL에는 적용 안 됨 |
| API | whitelisted 함수 안 | 데코레이터만으로는 로그인 사용자 누구나 호출 가능 |

## 체크
- 화면에서 버튼·필드를 숨기는 것은 권한이 아니다. 서버(API·컨트롤러)에서 같은 조건을 검사한다.
- 리포트(Script Report)·대시보드·현장 API처럼 **Desk 폼을 거치지 않는 경로**를 모두 찾는다: `rg "get_all|frappe.db.sql|ignore_permissions" <app>`.
- `ignore_permissions=True`는 그 호출이 누구 대신 무엇을 하는지 주석으로 남긴다.
- 제출 가능 DocType은 `submit`·`cancel`·`amend` 권한을 따로 본다.
- 역할 이름을 코드에 하드코딩했으면 fixture·사이트 데이터와 이름이 같은지 확인한다.

## Tester에게 넘길 검증
- 허용 역할로 성공, 비허용 역할로 실패(서버 오류 코드·메시지)를 **API와 폼 양쪽**에서.
- 목록·리포트에서 비허용 문서가 안 보이는지.
- 테스트 사용자는 Test 사이트에서만 만들고 정리한다.
