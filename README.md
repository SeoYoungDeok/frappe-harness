# Frappe Harness

Frappe 앱 개발용 Claude Code·Codex 공용 플러그인. 요청을 작업 유형(Playbook)으로 나누고, 중요한 설계만 사용자에게 묻고(Grilling), **구현(Implementer)과 테스트·최종 검증(Tester)을 항상 다른 에이전트가** 맡게 한다. 설계 근거는 [FRAPPE_HARNESS_HANDOFF_V2_2.md](FRAPPE_HARNESS_HANDOFF_V2_2.md).

## 구성

```text
frappe-harness/
├── plugin.json                      Codex/portable 매니페스트
├── .claude-plugin/
│   ├── plugin.json                  Claude Code 매니페스트
│   └── marketplace.json             Claude 로컬 마켓플레이스
├── .agents/plugins/marketplace.json Codex 로컬 마켓플레이스
├── agents/{implementer,tester}.md   역할 원본(Claude Code가 직접 로드)
├── adapters/codex/agents/*.toml     Codex용 사본(프로젝트 .codex/agents에 복사)
├── skills/
│   ├── develop/                     진입점: Playbook 선택·위임·동결·기록
│   │   └── playbooks/               small-change, feature, bug-fix, refactoring, upgrade, investigation
│   ├── grill/                       중요한 설계만 질문
│   └── frappe-{doctype,workflow,permission,backend,ui,testing,migration}/
├── hooks/hooks.json                 PreToolUse → scripts/guard.py
├── scripts/guard.py                 명백한 파괴 명령만 감지(보안 경계 아님)
└── tests/test_guard.py              guard 테스트(독립 Tester 작성)
```

## 설치

### Claude Code
```bash
claude plugin marketplace add /path/to/frappe-harness
claude plugin install frappe-harness@frappe-harness-local
```
- 저장소 폴더를 직접 읽으므로 수정은 새 세션부터 바로 반영된다.
- 개발 중 임시로 쓰려면 `claude --plugin-dir /path/to/frappe-harness`.

### Codex
```bash
codex plugin marketplace add /path/to/frappe-harness
codex plugin add frappe-harness@frappe-harness-local
```
- **설치 시점에 캐시로 복사한다.** 하네스를 고친 뒤 `codex plugin add ...`를 다시 실행해야 반영된다.
- **플러그인은 에이전트를 등록하지 않는다.** 프로젝트에 `adapters/codex/agents/*.toml`을 `.codex/agents/`로 복사하고, 그 프로젝트를 `~/.codex/config.toml`에서 trusted로 등록한다(git 루트 단위, 상위 폴더 trust는 적용되지 않았다):
  ```toml
  [projects."/path/to/frappe-bench/apps/<app>"]
  trust_level = "trusted"
  ```
- **guard Hook은 Codex에서 아직 동작하지 않는다(UNVERIFIED).** 이 버전에서는 플러그인의 `hooks/hooks.json`도, 매니페스트 inline 선언도 `/hooks` 목록에 나타나지 않았다(문서상 플러그인 Hook은 데스크톱 앱 수동 설치에서만 지원). Codex에서는 승인 규칙(develop §7)과 샌드박스 승인에 의존한다.

## 프로젝트 설정 (앱 저장소 루트)

| 파일 | 내용 |
|---|---|
| `AGENTS.md` | 프로젝트 규칙 + "변경 요청은 먼저 `develop` Skill" + 승인 필요 작업 3줄 |
| `CLAUDE.md` | `@AGENTS.md` 한 줄(두 CLI가 같은 규칙을 읽음) |
| `.frappe-harness.toml` | `bench`(상대 경로 가능), `app`, `context_doc`, `[sites] dev/test`, `[test_server] port` |
| `.codex/agents/*.toml` | Codex용 Implementer/Tester |
| `.gitignore` | `.frappe-harness/` (작업 기록·증거는 로컬 전용) |

예시:
```toml
bench = "../.."
app = "my_app"
context_doc = "docs/design.md"

[sites]
dev = "dev.localhost"
test = "test.localhost"

[test_server]
port = 8001
```

## 사용
- 평소처럼 요청한다. Main이 `develop` Skill로 Playbook을 고르고, 필요하면 질문하고, Implementer/Tester에 위임한다.
- 결과 보고에는 실행 명령, 대상 사이트, 증거 경로(`.frappe-harness/evidence/<task_id>/`), 미검증 범위가 들어간다.
- 작업마다 `.frappe-harness/tasks.jsonl`에 한 줄이 남는다(실측 시간만, 측정 못 한 토큰은 `null`).
- Test 화면 확인은 Test 전용 서버를 쓴다: `bench --site <test> serve --port <port>`(기본 서버가 `serve_default_site`면 Dev만 보여 준다).
- 토큰 사용량은 세션 안에서 자동 기록되지 않는다. 필요하면 Claude Code는 `-p --output-format stream-json`의 마지막 `result.usage`, Codex는 `exec --json`의 `turn.completed.usage`에서 확인한다.

## CLI별 차이와 한계 (2026-11-22, Claude Code 2.1.319 / Codex 0.171.0-alpha.13)

| 항목 | Claude Code | Codex |
|---|---|---|
| Skill 로드 | 플러그인 설치로 자동 | 플러그인 설치로 자동(캐시 복사) |
| Implementer/Tester | 플러그인 `agents/`에서 자동 | 프로젝트 `.codex/agents` + trust 필요 |
| Tester 독립성 | 서브 에이전트는 받은 프롬프트만 봄 | `spawn_agent` 기본이 대화 전체 상속 → `fork_turns: "none"` 필수(develop에 명시). 서브 에이전트끼리 메시지 가능 → 역할 파일로 금지 |
| 서브 에이전트 권한 제한 | 플러그인 에이전트의 `permissionMode` 무시 | 부모 샌드박스·승인 설정 상속 |
| Test 화면 스크린샷 | 헤드리스 Chrome 가능 | 샌드박스 안에서 Chrome 실패. 대화형에서 권한 상승 승인 필요, `codex exec`는 UNVERIFIED |
| guard Hook | `ask`로 사용자 승인 요청(`-p`에서는 거부), 실호출 확인 | 플러그인 Hook 미인식으로 미동작. `guard.py`의 Codex 분기(거부, exit 2)는 단위 테스트로만 확인 |

- guard는 문자열 패턴만 본다. 변수로 감춘 명령, 따옴표로 감싼 하위 명령, `find -delete`, 파일에서 읽는 SQL, `DELETE FROM`, 상위 폴더 삭제, CRLF 줄 이음은 놓친다. 명령을 언급만 하는 `echo`·커밋 메시지는 잘못 걸린다. 보호의 기본은 사용자 승인 규칙과 파일·DB 권한이다.
- `scripts/check.py`와 별도 `verify` Skill은 만들지 않는다(D-24).

## 개발 이력
Phase 0~4의 실행 증거는 하네스 저장소의 `.frappe-harness/evidence/phase*/`(git 제외)에 있다.
