#!/usr/bin/env python3
"""Report the real Frappe environment for a harness project (read-only, no DB access).

Usage: inspect_environment.py [--repo PATH] [--json]
Exit: 0 ok, 2 config missing/invalid.
"""

import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config as hc  # noqa: E402


def version_of(argv):
	rc, out, err = hc.sh([*argv, "--version"], timeout=15)
	return (out or err).strip().splitlines()[0] if rc == 0 and (out or err).strip() else None


def frappe_version(bench):
	m = re.search(r'__version__\s*=\s*"([^"]+)"', _read(Path(bench) / "apps/frappe/frappe/__init__.py"))
	return m.group(1) if m else None


def _read(p):
	try:
		return Path(p).read_text(encoding="utf-8")
	except OSError:
		return ""


def dirty_counts(repo):
	out = hc.git(repo, "status", "--porcelain=v1", "--untracked-files=all", raw=True) or ""
	c = {"staged": 0, "unstaged": 0, "untracked": 0}
	for line in out.splitlines():
		x, y = line[:2]
		if x == "?":
			c["untracked"] += 1
			continue
		c["staged"] += x not in " ?"
		c["unstaged"] += y not in " ?"
	return c


def inspect(repo_arg="."):
	cfg = hc.load(repo_arg)
	repo, bench = cfg["repo"], Path(cfg["bench"])
	tools = hc.find_tools(cfg)
	warn = []
	# tool versions in parallel (slowest ones dominate)
	with ThreadPoolExecutor() as ex:
		futs = {k: ex.submit(version_of, v) for k, v in tools.items() if k in ("ruff", "eslint", "semgrep") and v}
		futs["node"] = ex.submit(version_of, ["node"]) if shutil.which("node") else None
		futs["rules_commit"] = ex.submit(hc.git, tools["semgrep_rules"], "rev-parse", "HEAD") if tools["semgrep_rules"] else None
		res = {k: (f.result() if f else None) for k, f in futs.items()}
	browser = next((shutil.which(b) for b in ("chromium", "chromium-browser", "google-chrome", "chrome") if shutil.which(b)), None)
	sites_dir = bench / "sites"
	common = {}
	try:
		common = json.loads(_read(sites_dir / "common_site_config.json") or "{}")
	except ValueError:
		warn.append("common_site_config.json is not valid JSON")
	sites = []
	for role in ("dev", "test"):
		if cfg["sites"][role]:
			sites.append((cfg["sites"][role], role))
	sites += [(s, "production") for s in cfg["sites"]["production"]]
	site_info = [{"site": s, "classification": c, "exists": (sites_dir / s).is_dir()} for s, c in sites]
	for s in site_info:
		if not s["exists"]:
			warn.append(f"site directory missing: sites/{s['site']}")
	if not cfg["sites"]["dev"]:
		warn.append("no dev site configured")
	if not (bench / "apps/frappe").is_dir():
		warn.append(f"bench not found or has no apps/frappe: {bench}")
	for name in ("semgrep", "eslint"):
		if cfg["tools"][f"{name}_required"] and not tools[name]:
			warn.append(f"{name}_required but {name} not found")
	if cfg["tools"]["semgrep_rules"] and not tools["semgrep_rules"]:
		warn.append(f"semgrep rules path missing: {cfg['tools']['semgrep_rules']}")
	return {
		"config": cfg["config_path"], "repo": repo, "bench": str(bench), "app": cfg["app"],
		"frappe": {"version": frappe_version(bench), "commit": hc.git(bench / "apps/frappe", "rev-parse", "--short", "HEAD")},
		"app_git": {"head": hc.git(repo, "rev-parse", "--short", "HEAD"), **dirty_counts(repo)},
		"sites": site_info,
		"site_config": {"default_site": common.get("default_site"), "serve_default_site": common.get("serve_default_site")},
		"installed_apps": _read(sites_dir / "apps.txt").split(),
		"tools": {
			"ruff": res.get("ruff") or None, "eslint": res.get("eslint"), "semgrep": res.get("semgrep"),
			"semgrep_rules": {"path": tools["semgrep_rules"] or cfg["tools"]["semgrep_rules"], "commit": res.get("rules_commit")},
			"browser": browser, "node": res.get("node"),
		},
		"spec_dir": {"path": str(Path(repo) / ".harness/specs"), "exists": (Path(repo) / ".harness/specs").is_dir()},
		"warnings": warn,
	}


def main():
	ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	ap.add_argument("--repo", default=".")
	ap.add_argument("--json", action="store_true")
	a = ap.parse_args()
	try:
		info = inspect(a.repo)
	except hc.ConfigError as e:
		print(f"config error: {e}", file=sys.stderr)
		return 2
	if a.json:
		print(json.dumps(info, indent=2, ensure_ascii=False))
		return 0
	t = info["tools"]
	print(f"config   {info['config']}\nrepo     {info['repo']}  HEAD {info['app_git']['head']}  "
		f"staged={info['app_git']['staged']} unstaged={info['app_git']['unstaged']} untracked={info['app_git']['untracked']}")
	print(f"bench    {info['bench']}\nfrappe   {info['frappe']['version']} ({info['frappe']['commit']})\napps     {', '.join(info['installed_apps'])}")
	for s in info["sites"]:
		print(f"site     {s['site']}  {s['classification']}  {'exists' if s['exists'] else 'MISSING'}")
	print(f"default_site={info['site_config']['default_site']} serve_default_site={info['site_config']['serve_default_site']}")
	print(f"tools    ruff={t['ruff']} eslint={t['eslint']} semgrep={t['semgrep']} node={t['node']} browser={t['browser']}")
	print(f"rules    {t['semgrep_rules']['path']} @ {t['semgrep_rules']['commit']}\nspecs    {info['spec_dir']['path']} ({'exists' if info['spec_dir']['exists'] else 'absent'})")
	for w in info["warnings"]:
		print(f"WARNING  {w}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
