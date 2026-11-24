"""Shared config loader for Frappe Harness scripts (.frappe-harness.toml)."""

import ast
import os
import secrets
import time
from pathlib import Path

NAME = ".frappe-harness.toml"


class ConfigError(Exception):
	pass


def find_config(start="."):
	p = Path(start).expanduser().resolve()
	for d in [p, *p.parents] if p.is_dir() else p.parents:
		if (d / NAME).is_file():
			return d / NAME
	return None


def _parse_toml(text):
	try:
		import tomllib
		return tomllib.loads(text)
	except ImportError:  # Python < 3.11: minimal subset (tables, str/int/bool/list values)
		data, cur = {}, None
		for raw in text.splitlines():
			line, q = "", None
			for ch in raw:  # strip trailing comment outside quotes
				if q:
					q = None if ch == q else q
				elif ch in "\"'":
					q = ch
				elif ch == "#":
					break
				line += ch
			line = line.strip()
			if not line:
				continue
			if line.startswith("["):
				cur = data.setdefault(line.strip("[] "), {})
				continue
			k, _, v = line.partition("=")
			try:
				val = {"true": True, "false": False}.get(v.strip()) if v.strip() in ("true", "false") else ast.literal_eval(v.strip())
			except (ValueError, SyntaxError) as e:
				raise ConfigError(f"unsupported TOML value: {raw.strip()}") from e
			(cur if cur is not None else data)[k.strip()] = val
		return data


def _path(base, value):
	p = Path(os.path.expanduser(str(value)))
	return (p if p.is_absolute() else base / p).resolve()


def load(start="."):
	path = find_config(start)
	if not path:
		raise ConfigError(f"{NAME} not found from {start}")
	try:
		raw = _parse_toml(path.read_text(encoding="utf-8"))
	except Exception as e:  # noqa: BLE001
		raise ConfigError(f"invalid {path}: {e}") from e
	repo = path.parent
	if not raw.get("bench") or not raw.get("app"):
		raise ConfigError(f"{path}: 'bench' and 'app' are required")
	sites, tools, policy = raw.get("sites", {}), raw.get("tools", {}), raw.get("policy", {})
	prod = sites.get("production", [])
	rules = tools.get("semgrep_rules")
	return {
		"config_path": str(path),
		"repo": str(repo),
		"bench": str(_path(repo, raw["bench"])),
		"app": raw["app"],
		"context_doc": raw.get("context_doc"),
		"sites": {
			"dev": sites.get("dev"),
			"test": sites.get("test"),
			"production": [prod] if isinstance(prod, str) else list(prod),
		},
		"test_server": {"port": int(raw.get("test_server", {}).get("port", 8001))},
		"policy": {"run_tests_on_dev": bool(policy.get("run_tests_on_dev", False))},
		"tools": {
			"semgrep_rules": str(_path(repo, rules)) if rules else None,
			"semgrep_required": bool(tools.get("semgrep_required", False)),
			"eslint_required": bool(tools.get("eslint_required", False)),
		},
	}


def classify(cfg, site):
	"""Only by explicit config; never by site name."""
	if not site:
		return "unknown"
	s = cfg["sites"]
	if site in s["production"]:
		return "production"
	if site == s["dev"]:
		return "dev"
	if site == s["test"]:
		return "test"
	return "unknown"


def runs_dir(cfg, run_id=None):
	base = Path(cfg["repo"]) / ".harness" / "runs"
	base.mkdir(parents=True, exist_ok=True)
	gi = base / ".gitignore"
	if not gi.exists():
		gi.write_text("*\n")
	if run_id:
		base = base / run_id
		base.mkdir(parents=True, exist_ok=True)
	return base


def new_run_id():
	return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def sh(cmd, cwd=None, timeout=30, env=None, stdin=None):
	"""Run a command; return (returncode, stdout, stderr). rc=127 if missing, 124 on timeout."""
	import subprocess
	try:
		p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
			env={**os.environ, **(env or {})}, input=stdin, errors="replace")
		return p.returncode, p.stdout, p.stderr
	except FileNotFoundError:
		return 127, "", f"not found: {cmd[0]}"
	except subprocess.TimeoutExpired:
		return 124, "", f"timeout after {timeout}s"


def git(repo, *args, timeout=30, raw=False):
	rc, out, _ = sh(["git", "-C", str(repo), *args], timeout=timeout)
	return (out if raw else out.strip()) if rc == 0 else None


def find_tools(cfg):
	"""Locate external tools without running them: {name: argv list or None}."""
	import shutil
	repo = Path(cfg["repo"])
	eslint = next((p for p in (repo / "node_modules/.bin/eslint", repo / "frontend/node_modules/.bin/eslint") if p.is_file()), repo / "node_modules/.bin/eslint")
	ruff = shutil.which("ruff") or (None if not shutil.which("uvx") else "uvx")
	rules = cfg["tools"]["semgrep_rules"]
	if rules and (Path(rules) / "rules").is_dir():  # frappe/semgrep-rules keeps rules in rules/ (repo root has CI yml)
		rules = str(Path(rules) / "rules")
	return {
		"ruff": None if not ruff else [ruff] if ruff != "uvx" else ["uvx", "ruff"],
		"eslint": [str(eslint)] if eslint.is_file() else None,
		"semgrep": [shutil.which("semgrep")] if shutil.which("semgrep") else None,
		"semgrep_rules": rules if rules and Path(rules).is_dir() else None,
	}
