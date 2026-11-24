# Frappe Harness

**한국어** | [English](README.en.md)

Frappe 앱 개발을 위한 Claude Code / Codex 플러그인입니다.

- **역할 분리:** Main은 요청을 이해하고 계획·지시·판단만 합니다. 구현은 Developer가, 검증은 별도의 Tester가 맡습니다.
- **명세 확정:** 복잡한 기능은 AI가 명세 초안을 쓰고, 사용자가 HTML 화면에서 검토·확정한 뒤 개발합니다.
- **위험에 맞춘 검증:** 변경 내용을 분석해 필요한 검사만 실행합니다. 라벨 하나 바꾼 변경에는 DB 테스트를 돌리지 않습니다.
- **안전장치:** Hook이 Worker 모델(Sonnet), 역할별 수정 범위, 운영 사이트 접근, 파괴적 명령을 검사합니다.

## 동작 방식

```text
요청 → Main: 이해 · 중요한 결정만 질문 · (필요하면) 명세 확정
     → baseline 기록
     → Developer: Dev 사이트에서 구현 → READY_FOR_TEST
     → Tester: 위험도에 맞는 검증 → PASS / FAIL / BLOCKED
     → Main: 결과 판단 (실패 시 최대 2회 재작업)
```

변경은 위험 수준(L0–L3)으로 분류되고, 변경 종류에 맞는 검사만 실행됩니다.

| 수준 | 예시 | 주요 검사 |
|---|---|---|
| L0 | 라벨, 설명, 열 순서, 아이콘, 문서, 번역 | 정적 검사, 보이는 변경이면 화면 |
| L1 | 필드 추가, `depends_on`, 기본값, 클라이언트 스크립트 | + 메타데이터, 관련 단위 테스트 |
| L2 | 컨트롤러, `hooks.py`, API, 권한, 필수 여부, 이름 규칙 | + 관련 DB 테스트, 역할 확인 |
| L3 | 필드 삭제·타입 변경·이름 변경, patch, 단일/자식 테이블 전환 | + 데이터 안전 확인, migrate 전 사용자 승인 |

## 요구 사항

- Frappe bench (v16에서 확인)
- Python 3
- 선택: Semgrep CE, `chromium` 또는 `google-chrome`(화면 검증)

## 설치

### Claude Code

```bash
claude plugin marketplace add SeoYoungDeok/frappe-harness
```

```bash
claude plugin install frappe-harness@frappe-harness
```

업데이트할 때는 마켓플레이스를 먼저 갱신한 뒤 플러그인을 업데이트하고, 설치된 버전을 확인합니다.

```bash
claude plugin marketplace update frappe-harness
```

```bash
claude plugin update frappe-harness@frappe-harness
```

### Codex

```bash
codex plugin marketplace add /path/to/frappe-harness
```

```bash
codex plugin add frappe-harness@frappe-harness
```

1. `adapters/codex/agents/*.toml`을 프로젝트의 `.codex/agents/`로 복사하고, `model` 줄에 사용할 모델 ID를 직접 적습니다.
2. `adapters/codex/hooks.json`을 프로젝트의 `.codex/hooks.json`으로 복사합니다. 경로에 플러그인 버전이 들어 있으므로 버전이 바뀌면 함께 고칩니다.
3. 처음 실행할 때 Hook을 신뢰하도록 승인합니다.

Codex에서는 셸 명령 검사만 적용됩니다. 역할·모델 제한은 지시로만 전달됩니다.

## 프로젝트 설정

앱 저장소 루트에 세 파일을 둡니다.

- `AGENTS.md`: 프로젝트 규칙과 "변경 요청은 먼저 `develop` Skill을 사용한다"는 문장
- `CLAUDE.md`: `@AGENTS.md`
- `.frappe-harness.toml`

```toml
bench = "../.."                    # 이 파일 기준 상대 경로
app = "my_app"

[sites]
dev = "dev.localhost"              # 기본 작업 사이트
test = "test.localhost"            # 선택: DB를 쓰는 테스트용
production = ["erp.example.com"]   # 접근 차단

[test_server]
port = 8001                        # Test 사이트를 따로 띄울 때만

[policy]
run_tests_on_dev = false           # Dev에서 run-tests 실행 시 확인 요청

[tools]
semgrep_rules = "~/.local/share/frappe-harness/frappe-semgrep-rules"
semgrep_required = false
eslint_required = false
```

작업 기록은 앱 저장소의 `.harness/`에 남습니다.

```text
.harness/specs/           확정된 명세
.harness/runs/<run-id>/   검증 결과, 로그, 스크린샷 (git 제외)
.harness/runs/metrics.jsonl  실행·Worker 기록 (모델, 토큰, 시간)
```

## 사용

평소처럼 요청하면 됩니다. 라벨, 열 순서, 명확한 버그 같은 간단한 요청은 바로 진행합니다. 복잡한 기능은 명세 초안을 HTML로 열어 검토하고, 확정한 JSON을 Main에게 전달합니다.

명세 도구는 직접 실행할 수도 있습니다.

```bash
python3 scripts/render_spec.py render draft.json -o draft.html
```

```bash
python3 scripts/render_spec.py validate confirmed.json
```

## 안전장치

| 항목 | Claude Code | Codex |
|---|---|---|
| Worker 모델은 Sonnet | Hook이 실제 모델을 확인하고, 다르면 차단 | 지시만 |
| Tester는 테스트 파일만 수정 | Hook | 지시만 |
| Worker는 확정 명세 수정 불가 | Hook | 지시만 |
| Main이 앱 코드를 직접 수정 | Hook이 확인 요청 | 지시만 |
| 운영 사이트, Semgrep Registry | 차단 | 차단 |
| 파괴적 git·사이트·DB 명령, 위험한 migrate | 확인 요청 또는 차단 | 차단 |

Hook은 명령 문자열을 검사하므로 보안 경계가 아닙니다. `bash -c`, 리다이렉션, 스크립트로 감싼 명령은 걸러내지 못합니다. 완전한 격리가 필요하면 bench나 계정을 분리하세요.

## 선택 도구

### Semgrep

로컬 규칙만 사용하며 결과를 외부로 보내지 않습니다(`--metrics=off`).

```bash
uv tool install semgrep==1.186.0
```

```bash
git clone https://github.com/frappe/semgrep-rules ~/.local/share/frappe-harness/frappe-semgrep-rules
```

```bash
git -C ~/.local/share/frappe-harness/frappe-semgrep-rules checkout 81a6e3d47a328249e8ddf04c586e493dd5553002
```

### 화면 검증 (Linux / WSL)

Tester는 PATH의 `google-chrome` 또는 `chromium`으로 화면을 캡처합니다. 둘 다 없으면 화면 검증은 BLOCKED가 됩니다.

- 브라우저: apt로 `google-chrome`을 설치하거나, Chrome for Testing의 `chrome-headless-shell`을 내려받아 `~/.local/bin/chromium`으로 링크합니다.
- 한글 글꼴: `fonts-nanum`을 설치하거나 `.ttf` 파일을 `~/.local/share/fonts/`에 넣고 `fc-cache -f`를 실행합니다.

## 라이선스

[MIT](LICENSE). 외부 구성 요소는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 참고하세요.
