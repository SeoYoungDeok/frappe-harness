---
name: frappe-ui
description: Checkpoints for Frappe UI work — Desk forms and lists, client scripts, workspaces, and custom frontends (Vue/frappe-ui SPA) — so the screen never disagrees with server rules. Use when changing what users see or click.
---

# frappe-ui — 화면 변경 체크포인트

## 먼저 확인
- 프로젝트 UI 규칙(AGENTS.md)을 따른다. Desk 모양을 CSS·DOM 조작으로 바꾸지 말라는 규칙이 흔하다.
- 이 화면이 Desk인지 커스텀 프런트엔드인지, 둘 다 같은 데이터를 쓰는지 본다. 한쪽만 바꾸면 화면끼리 어긋난다.

## Desk
- 폼 구성은 DocType 설정(필드 순서, 섹션, `depends_on`, `read_only`, `in_list_view`)이 1순위, 폼 스크립트는 그다음.
- 폼 스크립트는 표준 API만: `frm.set_query`, `frm.add_custom_button`, `frm.set_df_property`, `frm.toggle_display`, `frappe.call`.
- **화면에서 숨기거나 막아도 서버는 열려 있다.** 입력 제한·권한은 서버 검증과 함께 바꾼다(frappe-backend).
- 목록 열 순서는 `in_list_view` 필드 순서 또는 List View Settings(사이트 데이터)가 정한다. 사이트 데이터라면 다른 사이트로 옮겨지지 않는다.
- **v16.60.2 확인:** Desk 경로는 `/desk/<doctype-slug>`이고 `/app/...`은 `/desk`로 리디렉션된다.

## 커스텀 프런트엔드(SPA)
- 데이터·검증은 whitelisted API와 서버 규칙을 그대로 쓴다. 같은 계산을 프런트에 다시 구현하지 않는다.
- 디자인 시스템(frappe-ui 등)의 버전을 확인하고 그 버전 API를 쓴다. 프로젝트에 승인된 커스텀 컴포넌트 목록이 있으면 그 범위를 넘지 않는다.
- 빌드 결과물이 커밋 대상인지 프로젝트 규칙을 확인한다. 화면 확인 전에 빌드가 필요할 수 있다(`bench build --app <app>`).

## 검증과 연결
- 화면 변경은 Tester가 Test 사이트에서 실제로 열어 본다(frappe-testing). 스크린샷만으로 부족하면 DOM 순서·상태도 증거로.
- 폼 스크립트·Vue 변경이 있으면 변경 파일만 ESLint(프로젝트 설정 사용).
