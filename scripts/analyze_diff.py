#!/usr/bin/env python3
"""Isolate and classify the changes made by one task.

  analyze_diff.py baseline --run-id ID [--repo PATH]   record pre-existing dirty work
  analyze_diff.py diff     --run-id ID [--repo PATH] [--json] [--against HEAD]

Never modifies git state. Importable: analyze(), migrate_risks().
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_config as hc  # noqa: E402

MAX_COPY = 5 * 1024 * 1024
DOCTYPE_RE = re.compile(r"(?:^|/)doctype/([^/]+)/\1\.json$")

# ---- non-DocType file rules: (regex on path, kind, level); first match wins ----
FILE_RULES = [
	(r"(^|/)test_[^/]*\.py$|(^|/)tests?/", "test", 0),
	(r"(^|/)patches\.txt$|(^|/)patches/", "migration", 3),
	(r"(^|/)hooks\.py$", "hooks", 2),
	(r"(^|/)requirements[^/]*\.txt$|(^|/)package(-lock)?\.json$|(^|/)yarn\.lock$", "dependency", 2),
	(r"\.md$", "docs", 0),
	(r"(^|/)translations/[^/]*\.csv$|\.pot?$", "translation", 0),
	(r"(^|/)workspace/.*\.json$", "workspace", 0),
	(r"(^|/)report/", "report", 2),
	(r"(^|/)fixtures/(custom_field|property_setter)[^/]*\.json$", "fixture_metadata", 1),
	(r"(^|/)(fixtures/|workflow[^/]*/).*\.json$", "workflow_or_fixture", 2),
	(r"(^|/)doctype/([^/]+)/\2\.py$", "controller", 2),
	(r"(^|/)doctype/[^/]+/[^/]+\.js$", "client_script", 1),
	(r"\.(vue|ts|tsx|jsx|js)$", "ui", 1),
	(r"\.(css|scss|svg|png|html|jpg|ico)$", "ui_asset", 0),
	(r"\.py$", "logic", 2),
]
FILE_RULES = [(re.compile(p), k, lv) for p, k, lv in FILE_RULES]

# kind -> extra recommended checks (static checks are derived from extensions)
KIND_CHECKS = {
	"test": ["unit_tests"], "migration": ["data_safety", "db_tests"], "hooks": ["db_tests"],
	"controller": ["db_tests"], "logic": ["unit_tests"], "api": ["db_tests", "role_check"],
	"client_script": ["browser_check"], "ui": ["browser_check"], "ui_asset": ["browser_check"],
	"translation": ["browser_check"], "workspace": ["browser_check"], "report": ["db_tests", "browser_check"],
	"workflow_or_fixture": ["site_metadata", "db_tests", "role_check"], "fixture_metadata": ["site_metadata", "browser_check"],
}

# ---- DocType property rules ----
L0_FIELD = {"label", "description", "idx", "hidden", "in_list_view", "in_standard_filter", "bold", "collapsible",
	"columns", "width", "print_hide", "placeholder", "print_width", "in_preview"}
L1_FIELD = {"depends_on", "mandatory_depends_on", "read_only_depends_on", "read_only", "default", "fetch_from"}
VISIBLE_FIELD = L0_FIELD | {"reqd", "read_only", "depends_on", "mandatory_depends_on", "read_only_depends_on", "fieldtype", "options", "default"}
L0_DOC = {"module", "description", "icon", "color", "title_field", "search_fields", "sort_field", "sort_order", "image_field"}
VISIBLE_DOC = L0_DOC - {"module"}
L2_DOC = {"is_submittable", "autoname", "naming_rule"}
L3_DOC = {"istable", "issingle"}
IGNORED = {"modified", "modified_by", "creation", "owner"}
LINKISH = {"Link", "Table", "Dynamic Link", "Table MultiSelect"}
RIGHTS = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "import", "share", "print", "email", "select", "if_owner")


# ---------------------------------------------------------------- git / files
def sha(data):
	return hashlib.sha256(data).hexdigest()


def file_hash(p):
	p = Path(p)
	if p.is_symlink() or not p.is_file():
		return "deleted" if not p.exists() and not p.is_symlink() else "nonfile"
	h = hashlib.sha256()
	with p.open("rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			h.update(chunk)
	return h.hexdigest()


def status_entries(repo):
	"""{path: XY} from porcelain v1 -z (renames also list the old path as deleted)."""
	out = hc.git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", raw=True) or ""
	parts, res, i = out.split("\0"), {}, 0
	while i < len(parts):
		e = parts[i]
		i += 1
		if len(e) < 4:
			continue
		xy, path = e[:2], e[3:]
		res[path] = xy
		if "R" in xy or "C" in xy:
			if i < len(parts) and "R" in xy:
				res[parts[i]] = " D"
			i += 1
	return res


def git_show(repo, rev, path):
	import subprocess
	p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True)
	return p.stdout if p.returncode == 0 else None


# ---------------------------------------------------------------- baseline
def baseline(repo, run_id, cfg=None):
	cfg = cfg or hc.load(repo)
	repo = Path(cfg["repo"])
	rdir = hc.runs_dir(cfg, run_id)
	files = {}
	for path, xy in status_entries(repo).items():
		h = file_hash(repo / path)
		e = {"status": xy, "sha256": h}
		if h not in ("deleted", "nonfile"):
			if (repo / path).stat().st_size > MAX_COPY:
				e["skipped"] = "larger than 5MB, content not copied"
			else:
				dst = rdir / "baseline_files" / path
				dst.parent.mkdir(parents=True, exist_ok=True)
				shutil.copy2(repo / path, dst)
		files[path] = e
	data = {"run_id": run_id, "head": hc.git(repo, "rev-parse", "HEAD"), "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": files}
	(rdir / "baseline.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
	return data


# ---------------------------------------------------------------- DocType diff
def _num(v):
	return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def field_prop_level(prop, b, a, ftype):
	if prop == "fieldtype":
		return 3
	if prop == "options":
		return 3 if ftype in LINKISH else 2 if ftype == "Select" else 1
	if prop == "unique":
		return 3 if not b and a else 1
	if prop == "reqd":
		return 2 if not b and a else 1
	if prop == "length":
		return 3 if _num(a) is not None and _num(b) is not None and a < b else 1
	if prop in L0_FIELD:
		return 0
	return 1  # depends_on/fetch_from/default/read_only and any other property


def doctype_changes(file, before, after):
	"""Property-level diff of two DocType JSON dicts (either may be None)."""
	name = (after or before).get("name") or Path(file).stem
	out = []

	def add(type_, level, field=None, prop=None, b=None, a=None):
		out.append({"file": file, "doctype": name, "type": type_, "field": field, "property": prop,
			"before": b, "after": a, "level": level})

	if before is None:
		add("doctype_added", 1)
		return out
	if after is None:
		add("doctype_removed", 3)
		return out
	bf = {f.get("fieldname"): f for f in before.get("fields", []) if f.get("fieldname")}
	af = {f.get("fieldname"): f for f in after.get("fields", []) if f.get("fieldname")}
	for fn in af.keys() - bf.keys():
		add("field_added", 1, fn, "fieldtype", None, af[fn].get("fieldtype"))
	for fn in bf.keys() - af.keys():
		add("field_removed", 3, fn, "fieldtype", bf[fn].get("fieldtype"), None)
	for fn in af.keys() - bf.keys():  # removed + added with the same label & type looks like a rename
		for old in bf.keys() - af.keys():
			if bf[old].get("label") and (bf[old].get("label"), bf[old].get("fieldtype")) == (af[fn].get("label"), af[fn].get("fieldtype")):
				add("possible_rename", 3, fn, "fieldname", old, fn)
	for fn in bf.keys() & af.keys():
		b, a = bf[fn], af[fn]
		for prop in sorted((b.keys() | a.keys()) - IGNORED):
			if b.get(prop) != a.get(prop):
				add("field_property", field_prop_level(prop, b.get(prop), a.get(prop), a.get("fieldtype")), fn, prop, b.get(prop), a.get(prop))
	bo = before.get("field_order") or list(bf)
	ao = after.get("field_order") or list(af)
	if [x for x in bo if x in ao] != [x for x in ao if x in bo]:
		add("field_order", 0, None, "field_order", bo, ao)
	# permissions: per (role, permlevel, if_owner) row
	def prow(d):
		return {(p.get("role"), p.get("permlevel", 0), p.get("if_owner", 0)): {k: p.get(k, 0) for k in RIGHTS if k != "if_owner"} for p in d.get("permissions", [])}
	bp, ap = prow(before), prow(after)
	for k in sorted(bp.keys() | ap.keys(), key=str):
		if bp.get(k) != ap.get(k):
			add("permission", 2, None, f"{k[0]}/L{k[1]}", bp.get(k), ap.get(k))
	for prop in sorted((before.keys() | after.keys()) - IGNORED - {"fields", "field_order", "permissions", "doctype"}):
		if before.get(prop) != after.get(prop):
			lv = 3 if prop in L3_DOC else 2 if prop in L2_DOC else 0 if prop in L0_DOC else 1
			add("doctype_property", lv, None, prop, before.get(prop), after.get(prop))
	return out


def _json(data):
	try:
		return json.loads(data.decode("utf-8")) if data is not None else None
	except (ValueError, UnicodeDecodeError):
		return False


def is_doctype_json(path, *datas):
	return bool(DOCTYPE_RE.search(path)) and any(isinstance(d, dict) and d.get("doctype") == "DocType" for d in datas)


def classify_file(path, before, after):
	"""-> (kind, level) for non-DocType files (before/after are bytes or None)."""
	text = (after if after is not None else before) or b""
	for rx, kind, lv in FILE_RULES:
		if rx.search(path):
			if kind == "logic" and b"@frappe.whitelist" in text:
				return "api", 2
			if kind == "workflow_or_fixture" and b'"doctype": "Workflow"' in text:
				return "workflow", 2
			return kind, lv
	if path.endswith("pyproject.toml"):
		lines = set(before.decode("utf-8", "replace").splitlines() if before else []) ^ set(after.decode("utf-8", "replace").splitlines() if after else [])
		if any(re.search(r"[<>=~!]=|dependencies|\^", ln) for ln in lines):
			return "dependency", 2
		return "config", 1
	return "other", 1


# ---------------------------------------------------------------- analysis
def analyze(repo, run_id=None, against_head=False):
	cfg = hc.load(repo)
	repo = Path(cfg["repo"])
	rdir = repo / ".harness/runs" / run_id if run_id else None
	bpath = rdir / "baseline.json" if run_id else None
	limits, base = [], None
	if bpath and bpath.is_file() and not against_head:
		base = json.loads(bpath.read_text())
	head = hc.git(repo, "rev-parse", "HEAD")
	if base is None:
		limits.append("no baseline: pre-existing changes cannot be separated")
		base = {"head": head, "files": {}}
	bfiles, bhead = base["files"], base["head"]
	cands = set(status_entries(repo)) | set(bfiles)
	if bhead and bhead != head:
		cands |= set((hc.git(repo, "diff", "--name-only", "-z", bhead, "HEAD") or "").split("\0")) - {""}
	changed, changes, untouched = [], [], []
	for path in sorted(cands):
		cur_h = file_hash(repo / path)
		if path in bfiles:
			before_h = bfiles[path]["sha256"]
			cp = rdir / "baseline_files" / path if rdir else None
			before = cp.read_bytes() if cp and cp.is_file() else None
			if before is None and before_h not in ("deleted", "nonfile"):
				limits.append(f"baseline content unavailable for {path}")
		else:
			before = git_show(repo, bhead, path)
			before_h = "deleted" if before is None else sha(before)
		if cur_h == before_h:
			if path in bfiles:
				untouched.append(path)
			continue
		after = (repo / path).read_bytes() if cur_h not in ("deleted", "nonfile") else None
		status = "added" if before_h == "deleted" else "deleted" if cur_h == "deleted" else "modified"
		bj, aj = _json(before), _json(after)
		if is_doctype_json(path, bj, aj):
			fch = doctype_changes(path, bj or None, aj or None) if bj is not False and aj is not False else \
				[{"file": path, "doctype": Path(path).stem, "type": "unparseable_json", "field": None, "property": None, "before": None, "after": None, "level": 1}]
			kind, lv = "doctype", max([c["level"] for c in fch] or [0])
			changes += fch
		else:
			kind, lv = classify_file(path, before, after)
			changes.append({"file": path, "doctype": None, "type": "file_" + status, "field": None, "property": None, "before": None, "after": None, "level": lv, "kind": kind})
		changed.append({"path": path, "status": status, "kind": kind, "level": lv})
	for c in changed:
		if c["kind"] == "controller" and c["level"] < 2:
			c["level"] = 2
	return {
		"run_id": run_id, "base": {"head": bhead, "baseline_used": "created" in base},
		"limitations": sorted(set(limits)), "changed_files": changed,
		"changed_doctypes": sorted({c["doctype"] for c in changes if c["doctype"]}),
		"changes": changes, "level": max([c["level"] for c in changed] + [0]),
		"recommended_checks": recommend(changed, changes), "preexisting_untouched": untouched,
	}


def recommend(changed, changes):
	checks = ["git_diff_check"] if changed else []
	for c in changed:
		p, ext, k = c["path"], Path(c["path"]).suffix, c["kind"]
		if c["status"] == "deleted":
			continue
		if ext == ".json":
			checks.append("json_validation")
		if ext == ".py":
			checks += ["ruff", "semgrep"]
		if ext in (".js", ".vue", ".ts", ".tsx", ".jsx"):
			checks.append("eslint")
			if ext == ".js":
				checks.append("semgrep")
		if k == "doctype":
			checks += ["metadata_check", "site_metadata"]
			mine = [x for x in changes if x["file"] == p]
			if any(x["type"] in ("doctype_added", "field_added", "field_removed", "field_order", "possible_rename")
				or (x["type"] == "field_property" and x["property"] in VISIBLE_FIELD)
				or (x["type"] == "doctype_property" and x["property"] in VISIBLE_DOC) for x in mine):
				checks.append("browser_check")
			if any(x["type"] == "permission" for x in mine):
				checks += ["db_tests", "role_check"]
		checks += KIND_CHECKS.get(k, [])
		if c["level"] >= 3:
			checks.append("data_safety")
	if any(c["level"] >= 3 for c in changed):
		checks.append("data_safety")
	return list(dict.fromkeys(checks))


# ---------------------------------------------------------------- guard-hook helper
def migrate_risks(repo):
	"""Fast: L3 DocType JSON changes vs HEAD (tracked diff + untracked). Returns readable strings."""
	repo = Path(repo)
	names = set((hc.git(repo, "diff", "--name-only", "-z", "HEAD", "--", "*/doctype/*/*.json") or "").split("\0"))
	names |= set((hc.git(repo, "ls-files", "-o", "--exclude-standard", "-z", "--", "*/doctype/*/*.json") or "").split("\0"))
	risks = []
	for path in sorted(n for n in names if n and DOCTYPE_RE.search(n)):
		before = _json(git_show(repo, "HEAD", path))
		p = repo / path
		after = _json(p.read_bytes()) if p.is_file() else None
		if before is False or after is False or not is_doctype_json(path, before, after):
			continue
		for c in doctype_changes(path, before, after):
			if c["level"] >= 3:
				what = f"{c['field']}.{c['property']}" if c["field"] else c["property"] or ""
				risks.append(f"{c['doctype']}: {c['type']} {what} {c['before']!r} -> {c['after']!r}".replace("  ", " "))
	return risks


def main():
	ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	sub = ap.add_subparsers(dest="cmd", required=True)
	for n in ("baseline", "diff"):
		p = sub.add_parser(n)
		p.add_argument("--run-id", required=(n == "baseline"))
		p.add_argument("--repo", default=".")
	sub.choices["diff"].add_argument("--json", action="store_true")
	sub.choices["diff"].add_argument("--against", choices=["HEAD"])
	a = ap.parse_args()
	try:
		if a.cmd == "baseline":
			b = baseline(a.repo, a.run_id)
			print(f"baseline {a.run_id}: HEAD {b['head'][:10]}, {len(b['files'])} pre-existing changed file(s)")
			return 0
		r = analyze(a.repo, a.run_id, a.against == "HEAD")
	except hc.ConfigError as e:
		print(f"config error: {e}", file=sys.stderr)
		return 2
	if a.json:
		print(json.dumps(r, indent=2, ensure_ascii=False))
	else:
		print(f"level L{r['level']}  base {str(r['base']['head'])[:10]}  baseline={'yes' if r['base']['baseline_used'] else 'no'}")
		for c in r["changed_files"]:
			print(f"  {c['status']:9} L{c['level']} {c['kind']:12} {c['path']}")
		for c in r["changes"]:
			if c["type"] != "file_modified" and not c["type"].startswith("file_"):
				print(f"    {c['type']} {c['field'] or ''} {c['property'] or ''} {c['before']!r} -> {c['after']!r} (L{c['level']})")
		print("checks:", ", ".join(r["recommended_checks"]) or "-")
		for l in r["limitations"]:
			print("limitation:", l)
	return 0


if __name__ == "__main__":
	sys.exit(main())
