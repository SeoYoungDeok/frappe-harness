# Upgrade Playbook

Frappe 또는 설치 앱·의존성을 새 버전으로 안전하게 바꾼다. 업그레이드 보류도 정상 결론이다.

## 1. 사전 조사 (Main, 읽기 전용)
- 현재 정확한 버전·커밋: `bench version`, 각 앱 `git -C apps/<app> describe --tags`, 브랜치.
- 목표 버전·커밋과 그 사이 변경: 릴리스 노트, `git log <현재>..<목표> --oneline`(fetch는 앱 원격에서만, 읽기 전용).
- 우리 앱이 쓰는 API·훅·Desk 경로·DB patch가 영향을 받는지: 변경 목록에서 우리 앱 코드가 쓰는 이름을 검색.
- 런타임 요구사항(Python·Node·MariaDB·Redis) 변화, 복구 수단(백업 위치·복원 절차) 확보 여부.

## 2. 위험 판정 (결과를 표로 보고)
| 판정 | 기준 | 진행 |
|---|---|---|
| 낮음 | 같은 메이저의 패치·마이너, DB patch가 적고 우리 앱이 쓰는 API 변경 없음, 런타임 동일 | 기존 Bench의 Dev/Test로 진행 |
| 높음 | 메이저 변경, Desk/UI 큰 변경, 데이터 변형 patch, 런타임 요구 변경, 정보 부족 | **임시 격리 Bench**에서 먼저 검증할 계획을 세우고 사용자 확인 후 진행. 미확인 상태로 기존 Bench에 적용 금지 |

사용자가 판정만 요청했으면 여기서 멈추고 보고한다. 조사 완료는 적용 승인이 아니다.

## 3. 낮은 위험 적용 절차
1. 진행 중 작업 중단, 코드 동결(Dev/Test가 코드를 공유하므로 이 동안 Dev 사용 금지).
2. **Dev와 Test 모두 백업:** `bench --site <site> backup --with-files`. 백업 경로와 현재 앱 커밋을 기록한다.
3. 앱 코드·의존성 적용(`bench update`보다 앱별 `git` + `bench setup requirements` + `bench build`처럼 범위가 보이는 방법 우선).
4. **Test부터** `bench --site <test> migrate` → Tester 독립 검증(앱 전체 테스트, 영향받는 화면, migrate 로그).
5. Test 통과 후 Dev migrate + 스모크 확인.
6. 새 버전·결과·백업 위치를 보고한다.

## 4. 주의
- Git revert만으로 DB patch가 되돌려지지 않는다. 되돌리려면 백업 복원이 필요하고, **DB를 덮어쓰는 복원은 사용자 승인**이 필요하다.
- 복구 수단이 없거나 핵심 기능이 미검증이면 보류를 권한다.
- 백업 생성은 자율. 백업 삭제는 승인 필요.
