---
name: frappe-doctype
description: Checkpoints for changing Frappe DocTypes — fields, Link and Child Table relations, naming, metadata, Custom Field and Property Setter — and for keeping Dev and Test sites in sync. Use when adding, moving or changing fields or DocType relations.
---

# frappe-doctype — DocType 변경 체크포인트

## 먼저 확인
- 현재 유효한 메타데이터는 JSON 파일과 사이트 DB가 다를 수 있다. 판단 근거로 둘 다 본다:
  `frappe.get_meta("<DocType>").fields` (사이트), `<app>/<module>/doctype/<name>/<name>.json` (코드).
- 사이트에만 있는 변경(Custom Field, Property Setter, Customize Form, List View Settings)은 다른 사이트·기기로 옮겨지지 않는다. 앱 JSON·fixture·patch로 옮기거나, 사이트 전용이라고 명시한다.
- 그 DocType을 단정하는 기존 테스트(필드 순서·속성·JSON 비교)를 `rg <fieldname>|<DocType>`으로 찾는다. 충돌하면 Tester에게 알린다.

## 변경 유형별 위험
| 변경 | 위험 | 확인 |
|---|---|---|
| 필드 순서·라벨·설명 | 낮음. 목록 열 순서가 `in_list_view` 필드 순서를 따라 같이 바뀔 수 있음 | 폼·목록 화면 |
| 필드 추가 | 기존 문서는 값이 비어 있음. `reqd`면 기존 문서 저장이 막힐 수 있음 | 기본값, 기존 문서 저장 |
| fieldtype 변경 | DB 컬럼 타입 변경, 데이터 잘림·변환 실패 | 기존 데이터 범위, migrate 로그 |
| Link 대상 변경 | 기존 값이 새 대상에 없으면 링크 깨짐 | 기존 값 존재 여부, patch 필요성 |
| 필드 삭제·이름 변경 | 코드·리포트·스크립트·fixture 참조 깨짐, 데이터 유실 | 전체 참조 검색, 데이터 이전 → **Grilling 대상** |
| Child Table 구조 | 부모 저장·검증 로직, 인쇄 양식 | 부모 컨트롤러·테스트 |
| naming 규칙 | 기존 문서 이름과 충돌, 외부 참조 | 기존 이름 패턴 |

## 반영 방법
- developer_mode 사이트에서 JSON을 고치고 `bench --site <site> migrate`. Dev와 Test 각각 migrate해야 한다(코드는 공유, DB는 분리).
- **v16.60.2 확인:** migrate는 JSON 파일 **해시**로 변경을 감지한다. `modified`를 손으로 올릴 필요가 없다(근거: `frappe/modules/import_file.py` `import_file_by_path`). 오래된 버전은 `modified` 비교만 하므로 버전을 확인한다.
- 폼 순서는 `field_order`가 정한다. `fields` 배열 순서도 함께 맞추면 diff가 읽기 쉽다.
- 기존 데이터를 고쳐야 하면 `patches.txt` + patch 모듈. patch는 다시 실행해도 안전하게(idempotent) 만든다.

## 하지 말 것
- 운영 사이트에서 Customize Form으로 스키마 변경(프로젝트 규칙이 허용하지 않는 한).
- 의미가 다른 데이터를 기존 필드에 재사용.
- `reqd` 추가를 기존 데이터 확인 없이 적용.
