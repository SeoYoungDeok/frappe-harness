---
name: frappe-migration
description: Checkpoints for Frappe migrations — bench migrate, patches, fixtures, data conversion, backups and restore, and version compatibility. Use for upgrades, structural DocType changes that affect existing data, and any data-moving script.
---

# frappe-migration — 마이그레이션 체크포인트

## migrate가 하는 일 (순서)
`before_migrate` 훅 → `patches.txt`의 `[pre_model_sync]` patch → DocType JSON 동기화 → `[post_model_sync]` patch → 스케줄 작업·fixture 동기화 → `after_migrate` 훅. (v16.60.2 `frappe/migrate.py` `SiteMigration.run`에서 확인) 새 필드를 채우는 patch는 보통 `post_model_sync`, 옛 컬럼을 읽어야 하면 `pre_model_sync`.

## Patch
- 한 번 실행된 patch는 `Patch Log`에 남아 다시 돌지 않는다. 다시 돌리려면 `patches.txt` 줄 끝 주석을 바꾼다(예: ` #2`).
- 다시 실행돼도 안전하게(idempotent): 이미 변환된 행은 건너뛴다.
- 대량 변경은 배치로, 진행 상황을 로그로. `frappe.db.commit()`은 배치 단위로.
- **데이터를 지우거나 복구하기 어렵게 바꾸는 patch는 사용자 승인 대상**이다. 백업을 먼저 확인한다.
- Test 사이트에 운영과 비슷한 데이터가 없으면 patch 검증 결과의 한계를 보고한다.

## Fixture
- `hooks.py` `fixtures`에 있는 DocType만 export/import된다. 사이트에서 바꾼 Custom Field·Property Setter·Role을 다른 사이트로 옮기려면 여기에 포함해야 한다.
- fixture import는 같은 이름 문서를 덮어쓴다. 사이트별로 다르게 둔 값이 있는지 먼저 본다.

## 백업과 복원
- 백업(자율): `bench --site <site> backup --with-files` → `sites/<site>/private/backups/`. 경로와 앱 커밋을 함께 기록한다.
- **복원은 DB를 덮어쓴다 → 사용자 승인 필요.** `bench --site <site> restore <sql.gz> [--with-public-files ...] [--with-private-files ...]`. 대상 사이트 이름을 두 번 확인한다.
- 백업 삭제도 승인 필요.
- Git revert는 DB를 되돌리지 않는다.

## 버전 호환
- 앱의 `required_apps`, Frappe 메이저, Python/Node 요구 버전을 확인한다.
- 오래된 사이트를 새 코드로 migrate할 때 중간 버전 patch가 필요할 수 있다(메이저를 건너뛰지 않는다).
- 확인한 버전별 동작은 적용 버전·근거와 함께 Skill이나 결정 문서에 남긴다.
