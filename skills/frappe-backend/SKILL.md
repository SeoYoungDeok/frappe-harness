---
name: frappe-backend
description: Checkpoints for Frappe server code — DocType controllers, hooks, whitelisted APIs, background jobs, database access and server-side validation. Use when writing or changing Python in a Frappe app.
---

# frappe-backend — 서버 코드 체크포인트

## 규칙은 서버에
- 저장·계산·상태 전이·권한 판단은 컨트롤러(`validate`, `before_save`, `on_submit` …)나 서비스 모듈에 둔다. 클라이언트 스크립트의 검증은 편의일 뿐 보호가 아니다.
- 계산 결과를 저장하는 필드는 서버에서 다시 계산한다. 클라이언트가 보낸 값을 믿지 않는다.

## Whitelisted API
- `@frappe.whitelist()`는 로그인 사용자 누구나 호출할 수 있다. 함수 안에서 권한을 확인한다:
  `frappe.has_permission(doctype, ptype, doc, throw=True)` 또는 `doc.check_permission("write")`, 역할이 필요하면 `frappe.only_for(...)`.
- 상태를 바꾸는 API는 `methods=["POST"]`로 제한한다(v16에서 `frappe.whitelist(allow_guest=False, xss_safe=False, methods=None)` 확인).
- `allow_guest=True`는 꼭 필요할 때만, 입력 검증과 속도 제한을 함께.
- 인자는 문자열로 들어올 수 있다. 숫자·JSON은 `cint`, `flt`, `frappe.parse_json`으로 변환한다.

## DB 접근
- `frappe.get_all`은 권한을 무시한다. 사용자 요청에 대한 조회는 `frappe.get_list`(권한 적용)를 쓴다.
- `ignore_permissions=True`, `doc.flags.ignore_permissions`는 이유를 주석으로 남기고 범위를 최소화한다.
- 원시 SQL은 파라미터 바인딩(`%s`/`%(name)s`)만. 문자열 조립 금지. 가능하면 `frappe.qb`.
- 반복문 안 `get_doc`/`get_value`(N+1)를 피하고 한 번에 조회한다.
- 요청 처리 중 `frappe.db.commit()`을 직접 부르지 않는다(요청 끝에 커밋됨). 백그라운드 작업·patch는 예외적으로 필요할 수 있다.

## 훅·백그라운드
- `hooks.py`의 `doc_events`는 다른 앱 DocType에도 걸린다. 걸 대상이 맞는지, 무한 루프(저장 → 훅 → 저장)가 없는지 본다.
- 오래 걸리는 일은 `frappe.enqueue`로. 작업 함수는 다시 실행돼도 안전해야 한다.

## 테스트 연결
- 계산·상태 전이 로직은 Tester가 테스트하기 쉽게 순수 함수로 분리하면 `UnitTestCase`로 검증할 수 있다(DB 필요 시 `IntegrationTestCase`, v16).
