#!/usr/bin/env python3
"""Frappe Harness guard: PreToolUse hook for roles, models and clearly risky commands.

NOT a security boundary. It catches obvious mistakes so a human decides. Known bypasses:
variables or quoting that hide a command, `bash -c`/scripts/Python that run the same thing,
`find -delete`, SQL read from a file, shell redirects (`> file`) that write app files, a `cd`
into another project before a command, `uv pip`, direct edits by other tools. Internal errors
and unknown input exit 0 (allow); the CLIs keep their own permission prompts.

Decisions (Claude Code: JSON permissionDecision "deny"/"ask"; Codex has no "ask": exit 2 + stderr):
- worker model mismatch (agent_type frappe-harness:*, recorded model not sonnet) -> deny every tool
- Agent/Task: developer/tester with non-sonnet `model`, legacy implementer, `fork` in a harness project,
  a worker spawning workers -> deny
- Edit/Write: tester may only write test files and .harness/runs; workers never write .harness/specs;
  Main (no agent_type) editing app files in a harness repo -> ask (Claude only; Codex has no agent_type)
- Bash: production site -> deny; Semgrep registry/cloud/pro -> deny; destructive site/DB/backup,
  default/`all` site for migrate/run-tests/execute/console/mariadb, run-tests on Dev against policy,
  destructive git, framework/dependency changes, migrate with L3 DocType risks -> ask
"""

import glob
import json
import os
import re
import shlex
import sys
from pathlib import Path

CONFIG_NAME = ".frappe-harness.toml"

RULES = [  # destructive site/DB/backup commands (ask)
	(
		re.compile(
			r"\bbench\b[^\n;&|]*?\s(drop-site|reinstall|restore|trim-database|trim-tables|uninstall-app)\b",
			re.IGNORECASE,
		),
		"bench {0}: deletes or overwrites site data",
	),
	(
		re.compile(r"\bbench\b[^\n;&|]*?\s(new-site\b[^\n;&|]*?--force)\b", re.IGNORECASE),
		"bench {0}: replaces an existing site",
	),
	(
		re.compile(r"\b(drop\s+(?:database|schema|table)|truncate\s+table)\b", re.IGNORECASE),
		"SQL {0}: permanently deletes data",
	),
	(
		re.compile(r"\brm\b[^\n;&|]*?(private/+backups|\.sql\.gz\b|\.sql\b)", re.IGNORECASE),
		"rm {0}: deletes a backup",
	),
]

SEMGREP_DENY = [
	(re.compile(r"\bsemgrep\b.*(?:--config|-c)[\s=]+[\"']?(auto\b|[prs]/|https?://)", re.I | re.S),
		"Semgrep registry/remote rules ({0}) are not allowed; use the local approved rules"),
	(re.compile(r"\bsemgrep\s+(login|ci|publish)\b", re.I), "semgrep {0} uses the Semgrep cloud"),
	(re.compile(r"(install-semgrep-pro)", re.I), "{0}: Semgrep Pro is not allowed"),
	(re.compile(r"\bsemgrep\b.*?(--pro\b)", re.I | re.S), "semgrep {0}: Semgrep Pro is not allowed"),
]

NEEDS_SITE = {"migrate", "run-tests", "execute", "console", "mariadb"}
FRAMEWORK = {"update", "switch-to-branch", "get-app"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
WORKERS = ("frappe-harness:developer", "frappe-harness:tester")
SEGMENT = re.compile(r"\s*(?:&&|\|\||[;|\n])\s*")


# ------------------------------------------------------------------ helpers
def _find_config(start):
	try:
		p = Path(start or ".").expanduser().resolve()
		for d in [p, *p.parents]:
			if (d / CONFIG_NAME).is_file():
				return d / CONFIG_NAME
	except Exception:
		pass
	return None


def _load(cfg_path):
	"""Config dict via harness_config (sites, policy ...) or None."""
	try:
		import harness_config
		return harness_config.load(str(cfg_path.parent)), harness_config
	except Exception:
		return None, None


def _tokens(seg):
	try:
		return shlex.split(seg)
	except ValueError:
		return seg.split()


def _after(tokens, name):
	for i, t in enumerate(tokens):
		if os.path.basename(t).lower() == name:
			return tokens[i + 1 :]
	return None


def _bench_args(args):
	"""-> (site, subcommand, rest) from tokens after `bench`."""
	site, sub, rest, i = None, None, [], 0
	while i < len(args):
		t = args[i]
		if t == "--site" and i + 1 < len(args):
			site, i = args[i + 1], i + 2
			continue
		if t.startswith("--site="):
			site = t.split("=", 1)[1]
		elif sub is None and not t.startswith("-"):
			sub = t.lower()
		elif sub is not None:
			rest.append(t.lower())
		i += 1
	return site, sub, rest


def _bench_repos(cwd, cfg):
	roots = []
	if cfg:
		roots.append(cfg["bench"])
	try:
		p = Path(cwd).resolve()
		for d in [p, *p.parents]:
			if (d / "apps").is_dir() and (d / "sites").is_dir():
				roots.append(str(d))
				break
	except Exception:
		pass
	repos = []
	if cfg:
		repos.append(cfg["repo"])
	for r in roots:
		repos += [os.path.dirname(x) for x in glob.glob(os.path.join(r, "apps", "*", CONFIG_NAME))]
	return list(dict.fromkeys(repos))


def _migrate_risks(cwd, cfg):
	try:
		import analyze_diff
		out = []
		for repo in _bench_repos(cwd, cfg):
			out += analyze_diff.migrate_risks(repo) or []
		return out
	except Exception:
		return []


# ------------------------------------------------------------------ rules
def check_worker_model(payload):
	if not str(payload.get("agent_type") or "").startswith("frappe-harness:"):
		return []
	import worker_info
	m = worker_info.actual_model(payload)
	if m and "sonnet" not in m.lower():
		return [("deny", f"model mismatch: expected sonnet, actual {m} — stop and report to Main")]
	return []


def check_agent_call(payload, cwd):
	ti = payload.get("tool_input") or {}
	st, model = str(ti.get("subagent_type") or ""), ti.get("model")
	out = []
	if str(payload.get("agent_type") or "").startswith("frappe-harness:"):
		out.append(("deny", "workers must not spawn other workers; report to Main instead"))
	if st in WORKERS and isinstance(model, str) and "sonnet" not in model.lower():
		out.append(("deny", f"{st} must run on sonnet, not model={model!r}; omit the model parameter"))
	if st == "frappe-harness:implementer":
		out.append(("deny", "frappe-harness:implementer was renamed; use frappe-harness:developer"))
	if st == "fork" and _find_config(cwd):
		out.append(("deny", "fork inherits the parent model/context and bypasses harness roles; use frappe-harness:developer or :tester"))
	return out


def check_edit(payload, cwd, codex):
	ti = payload.get("tool_input") or {}
	path = ti.get("file_path") or ti.get("notebook_path")
	if not isinstance(path, str) or not path:
		return []
	p = Path(path).expanduser()
	p = (p if p.is_absolute() else Path(cwd) / p).resolve()
	cfg_path = _find_config(p.parent if p.parent.exists() else cwd) or _find_config(p.parent)
	if not cfg_path:
		return []
	try:
		rel = p.relative_to(cfg_path.parent)
	except ValueError:
		return []
	agent = str(payload.get("agent_type") or "")
	parts, name = rel.parts, rel.name
	in_harness = bool(parts) and parts[0] == ".harness"
	if agent.startswith("frappe-harness:") and parts[:2] == (".harness", "specs"):
		return [("deny", "confirmed specs (.harness/specs) are changed only by Main with the user's agreement")]
	if agent == "frappe-harness:tester":
		is_test = (name.startswith("test_") and name.endswith(".py")) or "tests" in parts[:-1] \
			or ".spec." in name or ".test." in name
		if not (is_test or parts[:2] == (".harness", "runs")):
			return [("deny", f"Tester may edit only test files and .harness/runs, not {rel}; report the defect to Main")]
	if not agent and not codex and not in_harness and not name.endswith(".md"):
		return [("ask", f"Main should delegate app changes to frappe-harness:developer; allow editing {rel} directly?")]
	return []


def check_bash(command, cwd):
	command = command.replace("\\\n", " ")
	out = []
	for pattern, message in RULES:
		m = pattern.search(command)
		if m:
			out.append(("ask", message.format(m.group(1))))
	for pattern, message in SEMGREP_DENY:
		m = pattern.search(command)
		if m:
			out.append(("deny", message.format(m.group(1))))
	cfg_path = _find_config(cwd)
	cfg, hc = _load(cfg_path) if cfg_path else (None, None)
	for seg in SEGMENT.split(command):
		if not seg.strip():
			continue
		tokens = _tokens(seg)
		args = _after(tokens, "bench")
		if args is not None:
			site, sub, rest = _bench_args(args)
			if cfg and site and hc.classify(cfg, site) == "production":
				out.append(("deny", f"site {site} is configured as production; development and tests never run there"))
			if sub in NEEDS_SITE and (not site or site == "all"):
				out.append(("ask", f"bench {sub} without a specific --site (default or all sites are ambiguous)"))
			if sub == "run-tests" and cfg and site and hc.classify(cfg, site) == "dev" \
				and not cfg["policy"]["run_tests_on_dev"] and cfg["sites"]["test"]:
				out.append(("ask", f"run-tests on dev site {site}: policy.run_tests_on_dev is false and test site {cfg['sites']['test']} exists"))
			if sub in FRAMEWORK or (sub == "setup" and "requirements" in rest):
				out.append(("ask", f"bench {sub} {' '.join(rest[:1])}".strip() + ": changes the framework/dependencies"))
			if sub == "migrate" and site and site != "all":
				risks = _migrate_risks(cwd, cfg)
				if risks:
					out.append(("ask", "migrate would apply risky DocType changes: " + "; ".join(risks[:8])))
		if re.search(r"\bpip3?\s+install\b", seg, re.I) and (
			"env/bin/" in seg or re.search(r"\bpip3?\s+install\b[^\n;&|]*\bfrappe", seg, re.I)
		):
			out.append(("ask", "pip install into the bench environment / frappe: dependency change"))
		g = _after(tokens, "git")
		if g is not None:
			while g and g[0].startswith("-"):
				g = g[2:] if g[0] in ("-C", "-c") else g[1:]
			sub, rest = (g[0].lower(), g[1:]) if g else ("", [])
			bad = (
				(sub == "reset" and "--hard" in rest)
				or (sub == "clean" and any(re.match(r"-[a-zA-Z]*f", t) or t == "--force" for t in rest))
				or (sub == "checkout" and "." in rest)
				or (sub == "restore" and "." in rest and "--staged" not in rest)
				or (sub == "stash" and rest[:1] and rest[0] in ("drop", "clear"))
			)
			if bad:
				out.append(("ask", f"git {sub} {' '.join(rest)}".strip() + ": discards changes that may not be yours"))
	return out


def find_risk(command: str):
	"""Back-compat: first destructive-command message or None."""
	command = command.replace("\\\n", " ")
	for pattern, message in RULES:
		match = pattern.search(command)
		if match:
			return message.format(match.group(1))
	return None


def decide(payload):
	tool = payload.get("tool_name")
	ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
	cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else os.getcwd()
	codex = "turn_id" in payload
	findings = check_worker_model(payload)
	if findings:
		return findings
	if tool in AGENT_TOOLS:
		return check_agent_call(payload, cwd)
	if tool in EDIT_TOOLS:
		return check_edit(payload, cwd, codex)
	command = ti.get("command")
	if isinstance(command, list):
		command = " ".join(str(part) for part in command)
	return check_bash(command, cwd) if isinstance(command, str) else []


def main() -> int:
	try:
		payload = json.load(sys.stdin)
		if not isinstance(payload, dict):
			return 0
		findings = decide(payload)
	except Exception:
		return 0  # fail open
	if not findings:
		return 0
	decision = "deny" if any(d == "deny" for d, _ in findings) else "ask"
	reasons = "; ".join(dict.fromkeys(r for d, r in findings if d == decision))
	if decision == "ask":
		reasons += ". This needs the user's explicit approval."
	reason = f"Frappe Harness guard: {reasons}"
	if "turn_id" in payload:  # Codex: no "ask" support
		sys.stderr.write(reason + " Blocked here; ask the user to run it themselves if intended.\n")
		return 2
	json.dump(
		{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
			"permissionDecisionReason": reason}},
		sys.stdout,
	)
	return 0


if __name__ == "__main__":
	sys.exit(main())
