---
name: develop
description: REQUIRED first step for ANY request that changes a Frappe app or site in a project using Frappe Harness — code, DocType JSON, metadata, even tiny UI tweaks like field order or labels — and for upgrades or investigations. Picks a playbook, decides whether to grill, and delegates implementation to the implementer agent and verification to the tester agent. Main must not edit production code itself.
---

# develop — Playbook 선택과 위임 (Main 전용)

너는 Main이다. 직접 프로덕션 코드를 고치거나 최종 검증하지 않는다. 구현은 `implementer`, 테스트 코드·최종 검증은 `tester` 에이전트에 위임한다.

## 1. 시작 전
1. 프로젝트 루트의 `.frappe-harness.toml`에서 Bench 경로, Dev/Test 사이트, 결정 문서(`context_doc`)를 읽는다. 경로가 상대 경로면 이 파일이 있는 폴더 기준이다(기기마다 Bench 위치가 다를 수 있음). 없으면 사용자에게 묻는다.
2. 요청과 관련된 코드·DocType JSON·프로젝트 결정 문서(`.frappe-harness.toml`의 `context_doc`)만 읽는다. 코드로 답할 수 있는 것은 묻지 않는다.
3. 시작 시각을 기록한다: `date -u +%Y-%m-%dT%H:%M:%SZ`.
4. `task_id`를 정한다: 오늘 날짜 + 3자리 번호. `.frappe-harness/tasks.jsonl`과 `.frappe-harness/evidence/`에 이미 있는 같은 날짜의 가장 큰 번호 다음을 쓴다(재사용 금지, 증거 폴더 이름과 같다).
   ```bash
   d=$(date +%F); n=$( { grep -ho "\"$d-[0-9]\{3\}\"" .frappe-harness/tasks.jsonl 2>/dev/null | tr -d '"'; ls .frappe-harness/evidence 2>/dev/null; } | grep -o "^$d-[0-9]\{3\}$" | sort | tail -1 | cut -c12-); printf '%s-%03d\n' "$d" $((10#${n:-0}+1))
   ```

## 2. Playbook 선택
| 요청의 주목적 | Playbook | 경계 |
|---|---|---|
| 핵심 구조/규칙/권한 변화 없는 UI·UX 수정 | `playbooks/small-change.md` | 필드 추가·타입·Link·저장/계산 규칙·권한·Workflow가 바뀌면 Feature |
| 신규 기능, 업무 동작 변경 | `playbooks/feature.md` | 작아도 업무 로직이 바뀌면 Feature |
| 의도와 실제 동작의 차이 | `playbooks/bug-fix.md` | 요구사항이 바뀌면 Feature |
| 외부 동작 보존, 내부 구조 개선 | `playbooks/refactoring.md` | 발견한 버그는 별도 Bug Fix |
| Frappe/앱/의존성 버전 변경 | Upgrade (Phase 3) | |
| 사실·원인·대안 조사(변경 없음) | Investigation (Phase 3) | 변경은 별도 작업 |

아직 없는 Playbook이 필요하면 사용자에게 알리고 Small Change 절차를 억지로 적용하지 않는다. 유형이 바뀌면 이유를 한 줄로 남긴다.

**Grilling:** 신규/모호/구조 변경이면 `grill` Skill을 먼저 따른다. 명확한 Small Change는 생략한다.

## 3. 위임 규칙
- Implementer와 Tester는 **항상 서로 다른 에이전트 호출**이다. 같은 에이전트에게 구현과 검증을 함께 맡기지 않는다.
- **Tester에게는 Implementer의 계획·자기평가·diff 설명을 넘기지 않는다.** 원래 요구사항, 확정 결정, 대상 Test 사이트, 변경된 파일 경로(내용 설명 없이)만 넘긴다.
- **Codex:** Tester는 `spawn_agent`에 `agent_type: "tester"`, `fork_turns: "none"`으로 띄운다(기본 `all`은 Main 대화 전체를 상속해 독립성이 깨진다). Implementer도 `fork_turns: "none"`을 권장한다.
  - 서브 에이전트가 권한 승인을 기다리는 동안에는 그 에이전트를 중단하거나 같은 역할을 새로 띄우지 않는다. 사용자에게 "승인 대기 중: <thread>"라고 알리고 기다린다.
- **Claude Code:** `frappe-harness:implementer` / `frappe-harness:tester` 서브 에이전트를 쓴다(프롬프트만 전달됨).
- 위임 메시지는 아래 템플릿에서 필요한 항목만 채운다. 별도 Contract 파일을 만들지 않는다.

```markdown
[Implementer 작업]
- Playbook / 목표:
- 변경 대상(앱/Dev 사이트/모듈):
- 사용자와 확정한 핵심 결정:
- 유지할 규칙·변경 금지:
- 관련 코드와 프로젝트 결정 문서:
- 성공 기준 / 보고할 증거:
- Main에게 보고해야 하는 설계 충돌/데이터 손실 위험:
```

```markdown
[Tester 작업]
- Playbook / 원래 사용자 요청:
- 확정 요구사항·기대 동작:
- 대상 Test 사이트 / 변경된 파일 경로:
- 검증할 정상/예외/회귀 조건:
- UI 변경이면 브라우저 확인과 스크린샷(frappe-testing Skill 참고)
- 증거 저장 위치: .frappe-harness/evidence/<task_id>/
```

## 4. 코드 동결과 스냅샷 (검증 전·후 동일해야 함)
Implementer 완료 후, Tester 호출 직전과 Tester 보고 직후에 앱 저장소에서 같은 명령으로 **프로덕션 코드 지문**을 만든다. 테스트 파일은 Tester 소유라 제외한다(미커밋·미추적 파일 포함).

```bash
P=(-- . ':(exclude,glob)**/test_*.py' ':(exclude,glob)**/tests/**' ':(exclude,glob)**/*.spec.*' ':(exclude,glob)**/*.test.*')
{ git status --porcelain=v1 --untracked-files=all "${P[@]}"; git diff HEAD "${P[@]}"; git ls-files -o --exclude-standard -z "${P[@]}" | xargs -0 shasum 2>/dev/null; } | shasum | cut -c1-12
```

- 두 값이 다르면 그 검증은 무효다. 이유를 붙여 PASS로 바꾸지 말고 재검증한다. 검증 중에는 Implementer를 다시 부르지 않는다.
- Tester가 바꾼 테스트 파일은 `git status`로 따로 확인해 보고에 적는다. 기존 테스트의 단정을 바꿨다면 무엇을 왜 바꿨는지 사용자에게 보인다.

## 5. 판정과 보고
- Tester 결과가 PASS이고 스냅샷이 일치할 때만 "완료"라고 보고한다. 그 외에는 FAIL / UNVERIFIED와 이유를 그대로 보고한다.
- 보고에는 실행 명령, 대상 사이트, CLI 이름·버전, 증거 경로, 미검증 범위를 넣는다.
- 사용자와 합의했거나 Tester가 검증한 중요 결정만 프로젝트 결정 문서(`.frappe-harness.toml`의 `context_doc`)에 상태와 함께 적는다.

## 6. 작업 기록 (작업당 정확히 1줄)
종료 시 `.frappe-harness/tasks.jsonl`에 한 줄 append. 측정하지 못한 값은 추정하지 말고 `null`.

```json
{"task_id":"YYYY-MM-DD-NNN","cli":"claude-code|codex","playbook":"small-change","started_at":"...","ended_at":"...","elapsed_seconds":0,"outcome":"PASS|FAIL|UNVERIFIED","test_mode":"sequential|parallel","token_input":null,"token_output":null,"token_source":null,"token_status":"unavailable","notes":""}
```

## 7. 공통 실행 원칙 (승인 기준)
- 자율: 코드 수정, DocType 변경, 정상 `bench migrate`, 빌드, Test 데이터 생성·정리, 자동 검사, 합의된 기능 구현.
- **사용자 승인 필요:** `drop-site`/`reinstall`/DB 재생성, 영구 데이터 대량 삭제·복구 어려운 변환, DB를 덮어쓰는 복원, 복구용 백업 삭제, 승인된 파괴 작업의 대상·범위 변경.
- Test 사이트에서 이번 테스트가 만든 데이터만 정리하는 것은 자율.
