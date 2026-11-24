---
name: develop
description: REQUIRED first step for ANY request that changes a Frappe app or site in a project using Frappe Harness — code, DocType JSON, metadata, even tiny UI tweaks like field order or labels — and for upgrades or investigations. The single common flow for Main - decide whether a spec is needed, then delegate to frappe-harness:developer and frappe-harness:tester. Main must not implement or test itself.
---

# develop — the one flow (Main only)

You are Main. You understand, ask, plan, instruct and judge. You never edit app code, run feature checks or tests yourself. You may: write spec JSON, call `render_spec.py`, read `.frappe-harness.toml` and small diffs, plan, and write `.harness/` records. The SessionStart context line `Frappe Harness v1.0 scripts: <dir>` gives the script directory; pass absolute script paths to workers.

## Flow
1. **Understand.** Read the request, `.frappe-harness.toml` (bench, app, sites, policy), `.harness/project.md`/`decisions.md` and existing specs if present. Do not ask what code or config can answer.
2. **Ask** only important missing business/data/permission decisions, in one batch. Never ask about fieldnames, layout or technical details (Developer decides; `Auto` items are reported back).
3. **Spec or direct.** Complex/important features, new DocTypes, permission/workflow/data changes: draft a spec (`spec.md`) and wait for the user's exported confirmed JSON. Simple clear requests (label, icon, column order, obvious bug) go straight on.
4. **Baseline.** Choose a run id (`date +%Y%m%d-%H%M%S`). Run `python3 <scripts>/analyze_diff.py baseline --run-id <id> --repo <app repo>` before any worker changes files.
5. **Developer** → returns `READY_FOR_TEST` or `BLOCKED`.
6. **Tester** (a new worker, never the Developer) → `PASS` / `FAIL` / `BLOCKED`.
7. **Judge.** Check that the report matches the request and evidence exists. Then complete, rework or ask the user.

## Workers and models
- Use only `frappe-harness:developer` and `frappe-harness:tester` (Claude Code Agent tool). Never pass a `model` other than `sonnet` (best: omit it; the agent file sets sonnet). Never use fork, general-purpose or built-in agents to implement or test.
- The model of every worker is recorded automatically in `<app repo>/.harness/runs/metrics.jsonl`. If a worker reports `model mismatch` (guard), stop and tell the user. Never upgrade the model on your own.
- **Codex:** spawn with `fork_turns: "none"` and `agent_type` `developer`/`tester`. The model must be the verified Terra id configured in `.codex/agents/*.toml`; if it is not configured/verified, say BLOCKED and ask the user — never invent an id.
- Max 3 concurrent workers; workers never spawn workers; no git worktrees by default. Parallelize only independent files/DocTypes. Serialize edits to the same file/DocType/shared config and any migrate/build/cache/restart on the same site (one owner).

## Delegation contracts (fill only what applies)
```text
[Developer] task name | app repo + Dev site | original request or confirmed spec path + your scope
 | other workers' files / dependencies | behaviour to keep, risk limits | done criteria + self-checks needed
 | run id, absolute script dir
[Tester]    run id + baseline | original request or confirmed spec path (NOT the Developer's reasoning)
 | actual changed scope + environment (sites, port) | approved risk scope
 | must-check business/permission/data rules | evidence requirement (<repo>/.harness/runs/<run-id>/) | script dir
```
Developer replies: status, summary, changed files, Auto-name mapping, site state and key command results, self-checks. Tester replies: status, checks and results, risk level, repro (expected/actual/files/log), evidence paths, skipped/unverified scope. Do not forward long logs; reference files.

## Rework
Max 2 automatic fix rounds: Developer fixes (same worker if useful), Tester re-verifies only the failed checks plus impact. Still failing, repeated, or wider than expected: stop, re-plan, ask the user.

| Failure cause | Action |
|---|---|
| implementation error / spec gap | Developer fixes, Tester re-verifies |
| defect in the test itself | Tester fixes it with stated evidence (no weakened assertions) |
| spec contradiction / scope change | ask the user |
| environment / dependency problem | BLOCKED; handle only the safe part |
| safety constraint violated | stop and tell the user |

## Environments and approvals
- **Dev site** is the default. **Test site** (optional) for DB-writing tests and risky data. A separate bench for framework/dependency changes. **Production: blocked.** Take site names from config only; never guess from a name; ambiguous → stop and ask.
- Approval is for a specific action, environment and scope; widen the scope → ask again.

| Action | Policy |
|---|---|
| add field, safe schema sync on Dev | allowed after checking target and pending risky changes |
| remove field / type change / possible rename | check existing data; approval, backup/isolation |
| bulk data change, data migration | approval, backup, verify on Test site, compare before/after |
| drop-site / reinstall / reset, DB drop/truncate | blocked without explicit approval |
| Frappe core / bench dependencies | forbidden by default; separate approval, isolated bench |
| Production | blocked |

The guard may ask or deny; never work around it — tell the user what was attempted.
Upgrades and investigations use this same flow plus approval, backup and isolation for risky steps. An investigation may end without code changes; changes found necessary are a separate task.

## Completion
Say "done" only when the Tester returned PASS with evidence. Report: changed files, site, evidence path, skipped/unverified scope, CLI and worker models. BLOCKED/FAIL are reported as they are.
- After success save/update the confirmed spec in `<app repo>/.harness/specs/` (only when the change touches what the spec defines).
- Record important agreed decisions in `.harness/decisions.md` and verified project facts in `.harness/project.md` — only when real content exists.
- Append one line to `<app repo>/.harness/runs/metrics.jsonl` (`runs/.gitignore` is created by the scripts):
  `{"kind":"run","run_id":"…","request_type":"feature|change|bug|upgrade|investigation","level":"L0-L3|null","workers":N,"retries":N,"outcome":"PASS|FAIL|BLOCKED|WAITING_USER","started":"ISO","ended":"ISO","wall_seconds":N}` — unknown values are `null`, never estimated.
