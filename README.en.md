# Frappe Harness

[한국어](README.md) | **English**

A Claude Code / Codex plugin for Frappe app development.

- **Separate roles:** Main understands the request, then plans, instructs and judges. A Developer implements; a separate Tester verifies.
- **Confirmed specs:** For complex features, the AI drafts a spec and the user reviews and confirms it in an HTML page before development starts.
- **Risk-based checks:** Changes are analysed and only the needed checks run. A label change does not trigger DB tests.
- **Guards:** Hooks check the worker model (Sonnet), what each role may edit, production site access and destructive commands.

## How it works

```text
Request → Main: understand · ask only key decisions · (if needed) confirm spec
        → record baseline
        → Developer: implement on the Dev site → READY_FOR_TEST
        → Tester: risk-based checks → PASS / FAIL / BLOCKED
        → Main: judge the result (up to 2 rework rounds on failure)
```

Changes are classified by risk level (L0–L3), and only the checks that fit the kind of change run.

| Level | Examples | Main checks |
|---|---|---|
| L0 | label, description, column order, icon, docs, translations | static checks; screen if visible |
| L1 | new field, `depends_on`, default, client script | + metadata, related unit tests |
| L2 | controller, `hooks.py`, API, permissions, mandatory, naming | + related DB tests, role check |
| L3 | field removal / type change / rename, patch, single/child table switch | + data safety check, user approval before migrate |

## Requirements

- A Frappe bench (tested on v16)
- Python 3
- Optional: Semgrep CE, `chromium` or `google-chrome` (screen checks)

## Installation

### Claude Code

```bash
claude plugin marketplace add SeoYoungDeok/frappe-harness
```

```bash
claude plugin install frappe-harness@frappe-harness
```

To update, refresh the marketplace first, then update the plugin and check the installed version.

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

1. Copy `adapters/codex/agents/*.toml` to the project's `.codex/agents/` and fill in the `model` line with the model ID you use.
2. Copy `adapters/codex/hooks.json` to the project's `.codex/hooks.json`. The path contains the plugin version; update it when the version changes.
3. Approve the hooks as trusted on the first run.

On Codex only shell command checks apply. Role and model limits are instructions only.

## Project setup

Put three files at the root of the app repository:

- `AGENTS.md`: project rules and the line "Use the `develop` skill first for any change request"
- `CLAUDE.md`: `@AGENTS.md`
- `.frappe-harness.toml`

```toml
bench = "../.."                    # relative to this file
app = "my_app"

[sites]
dev = "dev.localhost"              # default working site
test = "test.localhost"            # optional: for DB-writing tests
production = ["erp.example.com"]   # access blocked

[test_server]
port = 8001                        # only when the Test site runs separately

[policy]
run_tests_on_dev = false           # ask before run-tests on Dev

[tools]
semgrep_rules = "~/.local/share/frappe-harness/frappe-semgrep-rules"
semgrep_required = false
eslint_required = false
```

Work records are kept in the app repository's `.harness/`:

```text
.harness/specs/              confirmed specs
.harness/runs/<run-id>/      check results, logs, screenshots (git-ignored)
.harness/runs/metrics.jsonl  run and worker records (model, tokens, time)
```

## Usage

Just make your request. Simple requests such as a label, column order or an obvious bug go straight ahead. For complex features, open the draft spec as HTML, review it, and give the confirmed JSON back to Main.

The spec tools can also be run directly:

```bash
python3 scripts/render_spec.py render draft.json -o draft.html
```

```bash
python3 scripts/render_spec.py validate confirmed.json
```

## Guards

| Rule | Claude Code | Codex |
|---|---|---|
| Workers run on Sonnet | Hook checks the actual model and blocks on mismatch | instruction only |
| Tester edits test files only | Hook | instruction only |
| Workers cannot edit a confirmed spec | Hook | instruction only |
| Main edits app code directly | Hook asks for confirmation | instruction only |
| Production sites, Semgrep Registry | blocked | blocked |
| Destructive git / site / DB commands, risky migrate | ask or block | blocked |

The hooks inspect command strings, so they are not a security boundary. Commands wrapped in `bash -c`, redirections or scripts are not caught. Use a separate bench or account when you need real isolation.

## Optional tools

### Semgrep

Only local rules are used, and nothing is sent out (`--metrics=off`).

```bash
uv tool install semgrep==1.186.0
```

```bash
git clone https://github.com/frappe/semgrep-rules ~/.local/share/frappe-harness/frappe-semgrep-rules
```

```bash
git -C ~/.local/share/frappe-harness/frappe-semgrep-rules checkout 81a6e3d47a328249e8ddf04c586e493dd5553002
```

### Screen checks (Linux / WSL)

The Tester captures screens with `google-chrome` or `chromium` on the PATH. Without either, screen checks are BLOCKED.

- Browser: install `google-chrome` with apt, or download Chrome for Testing's `chrome-headless-shell` and link it as `~/.local/bin/chromium`.
- Korean fonts: install `fonts-nanum`, or put `.ttf` files in `~/.local/share/fonts/` and run `fc-cache -f`.

## License

[MIT](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for external components.
