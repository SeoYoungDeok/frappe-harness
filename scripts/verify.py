#!/usr/bin/env python3
"""Deterministic verification runner for Frappe Harness.

  verify.py run    --run-id ID [--repo PATH] [--spec PATH] [--site SITE] [--no-cache]
  verify.py record --run-id ID --check CHECK --status PASS|FAIL|BLOCKED|SKIPPED [--reason R] [--evidence PATH]
                   [--remaining-data TEXT] [--limitation TEXT]

Runs only static/metadata/spec checks on the files changed by this task; no DB writes.
Checks that need a Tester (tests, browser, roles) are listed as manual_checks.
Exit: 0 PASS/PENDING_TESTER, 1 FAIL, 2 BLOCKED or config error.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_diff as ad  # noqa: E402
import harness_config as hc  # noqa: E402

STD_FIELDS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"}
BASE_ROLES = {"Administrator", "All", "Guest", "System Manager", "Desk User", "Website Manager", "Report Manager"}
STATIC_CACHEABLE = {"ruff", "eslint", "semgrep"}
SITE_MARK = "@@HARNESS_META@@"
FIELD_KEYS = {"required": "reqd", "unique": "unique", "fieldtype": "fieldtype", "options": "options", "label": "label",
	"default": "default", "read_only": "read_only", "hidden": "hidden", "in_list_view": "in_list_view",
	"in_standard_filter": "in_standard_filter", "depends_on": "depends_on", "mandatory_depends_on": "mandatory_depends_on",
	"read_only_depends_on": "read_only_depends_on", "fetch_from": "fetch_from", "description": "description"}
DOC_KEYS = {"naming": "autoname", "submittable": "is_submittable", "track_changes": "track_changes", "module": "module"}
RIGHT_KEYS = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "print", "email", "share")
SITE_SCRIPT = r'''
import json, sys, frappe
site, dts = sys.argv[1], json.loads(sys.argv[2])
frappe.init(site)
frappe.connect()
out = {}
try:
	for dt in dts:
		if not frappe.db.exists("DocType", dt):
			out[dt] = None
			continue
		m = frappe.get_meta(dt)
		wfs = []
		for n in frappe.get_all("Workflow", filters={"document_type": dt}, pluck="name"):
			w = frappe.get_doc("Workflow", n)
			wfs.append({"name": n, "is_active": w.is_active,
				"states": [{"state": s.state, "doc_status": s.doc_status} for s in w.states],
				"transitions": [{"state": t.state, "action": t.action, "next_state": t.next_state, "allowed": t.allowed} for t in w.transitions]})
		out[dt] = {"doc": {k: m.get(k) for k in ("autoname", "istable", "issingle", "is_submittable", "track_changes", "module", "title_field", "search_fields", "sort_field", "image_field")},
			"fields": {f.fieldname: f.as_dict() for f in m.fields},
			"permissions": [p.as_dict() for p in m.permissions], "workflows": wfs}
finally:
	frappe.destroy()
print("%s" + json.dumps(out, default=str))
''' % SITE_MARK


# ---------------------------------------------------------------- helpers
class Ctx:
	def __init__(self, cfg, run_id, rdir, analysis):
		self.cfg, self.run_id, self.rdir, self.an = cfg, run_id, rdir, analysis
		self.repo, self.bench = Path(cfg["repo"]), Path(cfg["bench"])
		self.log = []
		self.limits = list(analysis["limitations"])
		self.files = [c["path"] for c in analysis["changed_files"] if c["status"] != "deleted"]
		self.tools = hc.find_tools(cfg)
		self._index = None

	def sh(self, cmd, **kw):
		t = time.time()
		rc, out, err = hc.sh(cmd, cwd=kw.pop("cwd", self.repo), **kw)
		self.log.append(f"$ {' '.join(map(str, cmd))[:300]}\n[rc={rc} {int((time.time() - t) * 1000)}ms]\n{(out + err)[:2000]}\n")
		return rc, out, err

	def ext(self, *exts):
		return [f for f in self.files if f.endswith(exts)]

	def doctype_files(self):
		return [c["path"] for c in self.an["changed_files"] if c["kind"] == "doctype" and c["status"] != "deleted"]

	def index(self):
		"""DocType name -> (path, data) across all apps in the bench; also known roles."""
		if self._index is None:
			idx, roles = {}, set(BASE_ROLES)
			for pat in ("apps/*/*/*/doctype/*/*.json", "apps/*/*/doctype/*/*.json"):
				for p in glob.glob(str(self.bench / pat)):
					try:
						d = json.loads(Path(p).read_text(encoding="utf-8"))
					except (ValueError, OSError):
						continue
					if isinstance(d, dict) and d.get("doctype") == "DocType":
						idx[d.get("name")] = (p, d)
						roles |= {x.get("role") for x in d.get("permissions", [])}
			for p in glob.glob(str(self.repo / "**/fixtures/role.json"), recursive=True):
				try:
					roles |= {r.get("role_name") or r.get("name") for r in json.loads(Path(p).read_text())}
				except (ValueError, OSError):
					pass
			self._index = (idx, roles)
		return self._index


def result(cid, status, reason=None, findings=None, t0=None, **extra):
	r = {"id": cid, "status": status, "reason": reason, "findings": findings or [],
		"evidence": "verification.log", "duration_ms": int((time.time() - t0) * 1000) if t0 else 0}
	r.update(extra)
	return r


def overall(v):
	st = [c["status"] for c in v["checks"]]
	if "FAIL" in st:
		return "FAIL"
	if "BLOCKED" in st:
		return "BLOCKED"
	return "PENDING_TESTER" if any(m["status"] == "PENDING" for m in v["manual_checks"]) else "PASS"


# ---------------------------------------------------------------- static checks
def check_git_diff(cx):
	t0, found = time.time(), []
	if not cx.files:
		return result("git_diff_check", "SKIPPED", "no changed files", t0=t0)
	tracked = set((hc.git(cx.repo, "ls-files", "-z", "--", *cx.files) or "").split("\0"))
	if tracked - {""}:
		rc, out, _ = cx.sh(["git", "diff", "--check", "HEAD", "--", *sorted(tracked - {""})])
		found += out.strip().splitlines() if rc else []
	for f in set(cx.files) - tracked:
		try:
			lines = (cx.repo / f).read_text(encoding="utf-8").splitlines()
		except (OSError, UnicodeDecodeError):
			continue
		found += [f"{f}:{i}: {m}" for i, l in enumerate(lines, 1)
			for m in (["conflict marker"] if re.match(r"(<{7}|>{7}) ", l) else []) + (["trailing whitespace"] if l != l.rstrip() else [])]
	return result("git_diff_check", "FAIL" if found else "PASS", f"{len(found)} whitespace/conflict problem(s)" if found else None, found[:50], t0)


def check_json(cx):
	t0, bad = time.time(), []
	files = cx.ext(".json")
	if not files:
		return result("json_validation", "SKIPPED", "no JSON files changed", t0=t0)
	for f in files:
		try:
			json.loads((cx.repo / f).read_text(encoding="utf-8"))
		except (ValueError, OSError) as e:
			bad.append(f"{f}: {e}")
	return result("json_validation", "FAIL" if bad else "PASS", f"{len(bad)} invalid JSON file(s)" if bad else None, bad, t0)


def tool_check(cx, cid, tool, argv, files, required, fail_rcs=(1,), parse=None):
	"""Shared runner for ruff/eslint: rc 0 PASS, rc in fail_rcs FAIL, else BLOCKED."""
	t0 = time.time()
	if not files:
		return result(cid, "SKIPPED", f"no {tool} target files changed", t0=t0)
	if not argv:
		msg = f"{tool} not found"
		if required:
			return result(cid, "BLOCKED", msg, t0=t0)
		cx.limits.append(f"{tool} skipped: not installed")
		return result(cid, "SKIPPED", msg, t0=t0)
	rc, out, err = cx.sh([*argv, *files], timeout=300)
	text = (out + err).strip().splitlines()
	if rc == 0:
		return result(cid, "PASS", t0=t0)
	return result(cid, "FAIL" if rc in fail_rcs else "BLOCKED", f"{tool} exit {rc}", text[:50], t0)


def check_ruff(cx):
	r = cx.tools["ruff"]
	return tool_check(cx, "ruff", "ruff", r and [*r, "check", "--no-cache", "--output-format", "concise"], cx.ext(".py"), True)


def check_eslint(cx):
	e = cx.tools["eslint"]
	return tool_check(cx, "eslint", "eslint", e, cx.ext(".js", ".vue", ".ts", ".tsx", ".jsx"), cx.cfg["tools"]["eslint_required"])


def check_semgrep(cx):
	t0, req = time.time(), cx.cfg["tools"]["semgrep_required"]
	files = cx.ext(".py", ".js")
	if not files:
		return result("semgrep", "SKIPPED", "no Python/JS files changed", t0=t0)
	sg, rules = cx.tools["semgrep"], cx.tools["semgrep_rules"]
	if not sg or not rules:
		why = "semgrep not installed" if not sg else "semgrep_rules not configured or path missing"
		if req:
			return result("semgrep", "BLOCKED", why, t0=t0)
		cx.limits.append(f"semgrep skipped: {why}")
		return result("semgrep", "SKIPPED", why, t0=t0)
	rc, out, err = cx.sh([*sg, "scan", "--config", rules, "--metrics=off", "--disable-version-check", "--json", "--quiet", *files],
		env={"SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"}, timeout=300)
	try:
		data = json.loads(out)
	except ValueError:
		return result("semgrep", "BLOCKED", f"semgrep engine error (exit {rc}): {err.strip()[:200]}", t0=t0)
	errs = [e for e in data.get("errors", []) if e.get("level", "error") == "error"]
	if rc not in (0, 1) or errs:
		return result("semgrep", "BLOCKED", "semgrep engine error: " + "; ".join(str(e.get("message", e))[:150] for e in errs[:3]), t0=t0)
	found = [f"{r['path']}:{r['start']['line']}: {r['check_id'].split('.')[-1]}: {r['extra']['message'][:120]}" for r in data.get("results", [])]
	return result("semgrep", "FAIL" if found else "PASS", f"{len(found)} finding(s)" if found else None, found[:50], t0)


def check_metadata(cx):
	t0 = time.time()
	files = cx.doctype_files()
	if not files:
		return result("metadata_check", "SKIPPED", "no DocType JSON changed", t0=t0)
	idx, roles = cx.index()
	bad, warn = [], []
	for f in files:
		try:
			d = json.loads((cx.repo / f).read_text(encoding="utf-8"))
		except ValueError:
			continue  # json_validation reports it
		name, fields = d.get("name"), d.get("fields", [])
		by = {x.get("fieldname"): x for x in fields}
		names = [x.get("fieldname") for x in fields]
		bad += [f"{name}: duplicate fieldname '{n}'" for n in sorted({n for n in names if names.count(n) > 1})]
		for x in fields:
			fn, ft, op = x.get("fieldname"), x.get("fieldtype"), x.get("options")
			tgt = idx.get(op, (None, d if op == name else None))[1]
			if ft == "Link" and op and tgt is None:
				bad.append(f"{name}.{fn}: Link target DocType '{op}' not found in bench apps")
			if ft in ("Table", "Table MultiSelect"):
				if tgt is None:
					bad.append(f"{name}.{fn}: table DocType '{op}' not found")
				elif not tgt.get("istable"):
					bad.append(f"{name}.{fn}: '{op}' is not a child table (istable=0)")
			if ft == "Dynamic Link" and by.get(op, {}).get("fieldtype") != "Link":
				bad.append(f"{name}.{fn}: Dynamic Link options '{op}' is not a Link field of this DocType")
			if x.get("fetch_from"):
				link, _, tf = x["fetch_from"].partition(".")
				lf = by.get(link)
				if not lf or lf.get("fieldtype") != "Link":
					bad.append(f"{name}.{fn}: fetch_from '{x['fetch_from']}': '{link}' is not a Link field")
				elif (td := idx.get(lf.get("options"))) and tf not in STD_FIELDS and tf not in {y.get("fieldname") for y in td[1].get("fields", [])}:
					bad.append(f"{name}.{fn}: fetch_from target field '{tf}' not found in {lf.get('options')}")
		for key in ("title_field", "image_field", "sort_field", "search_fields"):
			for n in filter(None, [s.strip() for s in str(d.get(key) or "").split(",")]):
				if n not in by and n not in STD_FIELDS:
					bad.append(f"{name}: {key} '{n}' is not a field")
		an = d.get("autoname") or ""
		for m in (an[6:] if an.startswith("field:") else "", "naming_series" if an.startswith("naming_series:") else ""):
			if m and m not in by:
				bad.append(f"{name}: autoname '{an}' references missing field '{m}'")
		warn += [f"{name}: role '{r}' not defined in any app DocType/fixture (may exist on site)" for r in sorted({p.get("role") for p in d.get("permissions", [])} - roles)]
	return result("metadata_check", "FAIL" if bad else "PASS", f"{len(bad)} metadata problem(s)" if bad else None, bad, t0, warnings=warn)


# ---------------------------------------------------------------- site / spec
def site_meta(cx, site, doctypes):
	py = cx.bench / "env/bin/python"
	if not py.is_file():
		return None, f"bench python not found: {py}"
	rc, out, err = cx.sh([str(py), "-c", SITE_SCRIPT, site, json.dumps(sorted(doctypes))], cwd=cx.bench / "sites", timeout=120)
	line = next((l for l in out.splitlines() if l.startswith(SITE_MARK)), None)
	if rc or not line:
		return None, f"site meta read failed (exit {rc}): {err.strip().splitlines()[-1][:200] if err.strip() else 'no output'}"
	return json.loads(line[len(SITE_MARK):]), None


def same(exp, act):
	if isinstance(exp, bool):
		return bool(int(act or 0)) == exp
	return str(act if act is not None else "").strip() == str(exp).strip()


def tri(v):
	"""-> ('value', v) | ('auto',) | ('none',) | None (unspecified)"""
	if isinstance(v, dict) and v.get("mode") in ("auto", "none"):
		return (v["mode"],)
	return None if v is None else ("value", v)


def cmp_prop(findings, target, prop, spec_v, act, src):
	t = tri(spec_v)
	if not t or t[0] == "auto":
		return
	ok = not act or act in (0, "0") if t[0] == "none" else same(t[1], act)
	if not ok:
		findings.append({"target": target, "property": prop, "expected": None if t[0] == "none" else t[1], "actual": act, "source": src})


def compare_sources(spec, src_name, docs):
	"""docs: {doctype: {"doc":{}, "fields":{fn:{}}, "permissions":[]} or None}. Returns findings."""
	out = []
	for dt in spec.get("doctypes", []):
		if dt.get("selected") is False:
			continue
		name, d = dt.get("name"), docs.get(dt.get("name"))
		if d is None:
			out.append({"target": name, "property": "doctype", "expected": "exists", "actual": "missing", "source": src_name})
			continue
		for k, p in DOC_KEYS.items():
			cmp_prop(out, name, p, dt.get(k), d["doc"].get(p), src_name)
		kind = dt.get("kind") if isinstance(dt.get("kind"), str) else None
		for k, p in (("child", "istable"), ("single", "issingle")):
			if kind in ("normal", "child", "single"):
				cmp_prop(out, name, p, kind == k, d["doc"].get(p), src_name)
		for sf in dt.get("fields", []):
			if sf.get("selected") is False:
				continue
			fn = sf.get("fieldname")
			f = d["fields"].get(fn) if fn else next((x for x in d["fields"].values() if x.get("label") == sf.get("label")), None)
			tgt = f"{name}.{fn or sf.get('label')}"
			if f is None:
				out.append({"target": tgt, "property": "field", "expected": "exists", "actual": "missing", "source": src_name})
				continue
			for k, p in FIELD_KEYS.items():
				cmp_prop(out, tgt, p, sf.get(k), f.get(p), src_name)
	perms = spec.get("permissions")
	for sp in perms if isinstance(perms, list) else []:
		if sp.get("selected") is False or sp.get("doctype") not in docs or docs[sp["doctype"]] is None:
			continue
		rows = [r for r in docs[sp["doctype"]]["permissions"] if r.get("role") == sp.get("role") and not r.get("permlevel")]
		if tri(sp.get("if_owner")) and tri(sp["if_owner"])[0] == "value":
			rows = [r for r in rows if bool(r.get("if_owner")) == sp["if_owner"]]
		row = rows[0] if rows else {}
		for k in RIGHT_KEYS:
			cmp_prop(out, f"{sp['doctype']}[{sp.get('role')}]", k, (sp.get("rights") or {}).get(k), row.get(k), src_name)
	return out


def source_docs(cx, names):
	idx, _ = cx.index()
	docs = {}
	for n in names:
		d = idx.get(n, (None, None))[1]
		docs[n] = None if d is None else {"doc": d, "fields": {f.get("fieldname"): f for f in d.get("fields", [])}, "permissions": d.get("permissions", [])}
	return docs


def workflow_findings(spec, wfdocs, src):
	"""Compare spec workflow blocks to Workflow records. Returns (findings, doctypes_without_any_workflow)."""
	out, missing = [], []
	for sw in spec.get("workflows", []) if isinstance(spec.get("workflows"), list) else []:
		if sw.get("selected") is False:
			continue
		wfs = (wfdocs.get(sw.get("doctype")) or {}).get("workflows") or []
		if not wfs:
			missing.append(sw.get("doctype"))
			continue
		states = {s["state"] for w in wfs for s in w["states"]}
		trans = [t for w in wfs for t in w["transitions"]]
		out += [{"target": sw["doctype"], "property": "state", "expected": st.get("name"), "actual": "missing", "source": src}
			for st in sw.get("states", []) if st.get("name") not in states]
		out += [{"target": sw["doctype"], "property": "transition", "expected": f"{tr.get('from')} --{tr.get('action')}--> {tr.get('to')}", "actual": "missing", "source": src}
			for tr in sw.get("transitions", []) if not any(t["action"] == tr.get("action") and t["state"] == tr.get("from") and t["next_state"] == tr.get("to")
				and (not tr.get("role") or t["allowed"] == tr["role"]) for t in trans)]
	return out, missing


def app_workflows(cx, doctypes):
	res = {}
	for p in glob.glob(str(cx.repo / "**/fixtures/*.json"), recursive=True):
		try:
			rows = json.loads(Path(p).read_text(encoding="utf-8"))
		except (ValueError, OSError):
			continue
		for w in rows if isinstance(rows, list) else []:
			if isinstance(w, dict) and w.get("doctype") == "Workflow" and w.get("document_type") in doctypes:
				res.setdefault(w["document_type"], {"workflows": []})["workflows"].append(
					{"states": [{"state": s.get("state")} for s in w.get("states", [])],
					"transitions": [{"state": t.get("state"), "action": t.get("action"), "next_state": t.get("next_state"), "allowed": t.get("allowed")} for t in w.get("transitions", [])]})
	return res


def site_allowed(cx, site):
	return hc.classify(cx.cfg, site) in ("dev", "test")


def check_spec(cx, spec_path, site, manual):
	t0 = time.time()
	try:
		spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
	except (OSError, ValueError) as e:
		return result("spec_check", "BLOCKED", f"cannot read spec: {e}", t0=t0)
	sha = ad.file_hash(spec_path)
	if spec.get("status") != "confirmed":
		return result("spec_check", "BLOCKED", f"spec status is '{spec.get('status')}', not confirmed", t0=t0, spec_sha256=sha)
	names = sorted({d.get("name") for d in spec.get("doctypes", []) if d.get("selected") is not False and d.get("name")} |
		{p.get("doctype") for p in spec.get("permissions", []) if isinstance(spec.get("permissions"), list) and p.get("doctype")} |
		{w.get("doctype") for w in spec.get("workflows", []) if isinstance(spec.get("workflows"), list) and w.get("doctype")})
	findings = compare_sources(spec, "app_source", source_docs(cx, names))
	wf_src = app_workflows(cx, set(names))
	wf, missing = workflow_findings(spec, wf_src, "app_source")
	findings += wf
	if isinstance(spec.get("workflows"), dict) and spec["workflows"].get("mode") == "none" and wf_src:
		findings.append({"target": ",".join(wf_src), "property": "workflow", "expected": "none", "actual": "Workflow fixture exists", "source": "app_source"})
	extra, blocked = {}, None
	if site:
		if not site_allowed(cx, site):
			blocked = f"site '{site}' is classified '{hc.classify(cx.cfg, site)}'; spec comparison on it is refused"
		else:
			meta, err = site_meta(cx, site, names)
			if err:
				blocked = err
			else:
				findings += compare_sources(spec, f"site:{site}", meta)
				wf, missing_site = workflow_findings(spec, {k: v for k, v in meta.items() if v}, f"site:{site}")
				findings += wf
				missing = [m for m in missing if m in missing_site]
				extra["site_compared"] = site
	for dt in dict.fromkeys(missing):
		manual.append({"id": f"workflow_manual:{dt}", "status": "PENDING", "reason": f"spec has a workflow for {dt} but no Workflow was found in app fixtures/site; verify manually"})
	if findings:
		return result("spec_check", "FAIL", f"{len(findings)} spec mismatch(es)", findings[:100], t0, spec_sha256=sha, **extra)
	if blocked:
		return result("spec_check", "BLOCKED", blocked, t0=t0, spec_sha256=sha, **extra)
	return result("spec_check", "PASS", t0=t0, spec_sha256=sha, **extra)


def check_site_metadata(cx, site):
	"""Effective site meta vs the changed DocType JSON (after values). Read-only."""
	t0 = time.time()
	changes = [c for c in cx.an["changes"] if c["doctype"]]
	names = sorted({c["doctype"] for c in changes if c["type"] != "doctype_removed"})
	meta, err = site_meta(cx, site, names)
	if err:
		return result("site_metadata", "BLOCKED", err, t0=t0, site=site)
	bad = []
	for c in changes:
		m = meta.get(c["doctype"], "x")
		if c["type"] == "doctype_removed":
			continue
		if m is None:
			bad.append(f"{c['doctype']}: DocType not on site '{site}' (not migrated?)")
		elif c["type"] == "field_added" and c["field"] not in m["fields"]:
			bad.append(f"{c['doctype']}.{c['field']}: field missing on site (not migrated?)")
		elif c["type"] == "field_removed" and c["field"] in m["fields"]:
			bad.append(f"{c['doctype']}.{c['field']}: field still on site")
		elif c["type"] == "field_property" and c["field"] in m["fields"] and not same(c["after"] if c["after"] is not None else "", m["fields"][c["field"]].get(c["property"])) and not isinstance(c["after"], (list, dict)):
			bad.append(f"{c['doctype']}.{c['field']}.{c['property']}: source {c['after']!r} != site {m['fields'][c['field']].get(c['property'])!r}")
		elif c["type"] == "doctype_property" and not isinstance(c["after"], (list, dict)) and c["property"] in m["doc"] and not same(c["after"] if c["after"] is not None else "", m["doc"][c["property"]]):
			bad.append(f"{c['doctype']}.{c['property']}: source {c['after']!r} != site {m['doc'][c['property']]!r}")
	return result("site_metadata", "FAIL" if bad else "PASS", f"{len(bad)} difference(s) between source and site meta (run migrate on that site?)" if bad else None, bad, t0, site=site)


# ---------------------------------------------------------------- cache
def tool_version(cx, name):
	argv = cx.tools.get(name)
	if not argv:
		return None
	if name == "ruff":
		return hc.sh([*argv, "--version"], timeout=20)[1].strip()
	st = os.stat(argv[0])
	rules = cx.tools["semgrep_rules"]
	return f"{argv[0]}:{st.st_mtime_ns}:{st.st_size}" + (f":{hc.git(rules, 'rev-parse', 'HEAD')}" if name == "semgrep" and rules else "")


def cache_key(cx, cid, files):
	cfgfiles = [cx.cfg["config_path"], *(str(cx.repo / n) for n in ("pyproject.toml", "ruff.toml", ".ruff.toml", "eslint.config.js", "eslint.config.mjs", ".eslintrc", ".eslintrc.js", ".eslintrc.json"))]
	parts = [cid, tool_version(cx, cid), cx.tools.get(cid), cx.tools.get("semgrep_rules") if cid == "semgrep" else None,
		[ad.file_hash(f) for f in cfgfiles if os.path.exists(f)], sorted((f, ad.file_hash(cx.repo / f)) for f in files)]
	return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- commands
def cmd_run(a):
	cfg = hc.load(a.repo)
	rdir = hc.runs_dir(cfg, a.run_id)
	t_all = time.time()
	an = ad.analyze(cfg["repo"], a.run_id)
	cx = Ctx(cfg, a.run_id, rdir, an)
	cache_f = rdir.parent / "cache.json"
	try:
		cache = json.loads(cache_f.read_text())
	except (OSError, ValueError):
		cache = {}
	site_class = hc.classify(cfg, a.site) if a.site else None
	checks, manual, rec = [], [], an["recommended_checks"]
	spec_path = None
	if a.spec:
		spec_path = next((p for p in (Path(a.spec), Path(cfg["repo"]) / a.spec, Path(cfg["repo"]) / ".harness/specs" / a.spec) if p.is_file()), None)
	static = [("git_diff_check", check_git_diff, cx.files), ("json_validation", check_json, cx.ext(".json")), ("ruff", check_ruff, cx.ext(".py")),
		("eslint", check_eslint, cx.ext(".js", ".vue", ".ts", ".tsx", ".jsx")), ("semgrep", check_semgrep, cx.ext(".py", ".js")), ("metadata_check", check_metadata, [])]
	for cid, fn, files in static:
		if cid not in rec:
			continue
		key = cache_key(cx, cid, files) if cid in STATIC_CACHEABLE and not a.no_cache and files else None
		if key and key in cache and cache[key]["status"] in ("PASS", "FAIL"):
			r = {**cache[key], "reused_from": cache[key].get("run_id", "?")}
		else:
			r = fn(cx)
			if key and r["status"] in ("PASS", "FAIL"):
				cache[key] = {**r, "run_id": a.run_id}
		checks.append(r)
	if spec_path or a.spec:
		checks.append(check_spec(cx, spec_path, a.site, manual) if spec_path else result("spec_check", "BLOCKED", f"spec not found: {a.spec}"))
	if a.site and site_class not in ("dev", "test"):
		checks.append(result("site_guard", "BLOCKED", f"site '{a.site}' is classified '{site_class}' (not dev/test); no site access"))
	elif a.site and "site_metadata" in rec:
		checks.append(check_site_metadata(cx, a.site))
	done = {c["id"] for c in checks}
	reasons = {"site_metadata": "no --site given; effective site metadata not compared"}
	for cid in rec:
		if cid not in done and cid not in {x[0] for x in static}:
			manual.append({"id": cid, "status": "PENDING", "reason": reasons.get(cid, f"recommended for L{an['level']} change; run by Tester")})
	v = {"run_id": a.run_id, "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t_all)), "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
		"duration_ms": int((time.time() - t_all) * 1000), "repo_head": hc.git(cfg["repo"], "rev-parse", "HEAD"), "app": cfg["app"],
		"site": a.site, "site_classification": site_class,
		"spec": {"path": str(spec_path or a.spec), "sha256": next((c.get("spec_sha256") for c in checks if c["id"] == "spec_check"), None)} if a.spec else None,
		"level": an["level"], "analysis": {"baseline_used": an["base"]["baseline_used"], "changed_files": an["changed_files"], "changed_doctypes": an["changed_doctypes"],
			"recommended_checks": rec, "preexisting_untouched": an["preexisting_untouched"]},
		"limitations": sorted(set(cx.limits)), "checks": checks, "manual_checks": manual, "remaining_test_data": []}
	v["status"] = overall(v)
	(rdir / "verification.json").write_text(json.dumps(v, indent=2, ensure_ascii=False))
	(rdir / "verification.log").write_text("\n".join(cx.log))
	if not a.no_cache:
		cache_f.write_text(json.dumps(cache, indent=1))
	print(summary(v))
	return {"PASS": 0, "PENDING_TESTER": 0, "FAIL": 1}.get(v["status"], 2)


def summary(v):
	lines = [f"verify {v['run_id']}: {v['status']}  L{v['level']}  {v['duration_ms']}ms  files={len(v['analysis']['changed_files'])}"]
	for c in v["checks"]:
		lines.append(f"  {c['status']:8} {c['id']}" + (f" ({c['reason']})" if c.get("reason") else "") + (f" [reused {c['reused_from']}]" if c.get("reused_from") else ""))
		lines += [f"           - {json.dumps(f, ensure_ascii=False) if isinstance(f, dict) else f}" for f in c["findings"][:5]]
	lines += [f"  PENDING  {m['id']} ({m['reason']})" for m in v["manual_checks"] if m["status"] == "PENDING"]
	lines += [f"  limitation: {l}" for l in v["limitations"]]
	return "\n".join(lines)


def cmd_record(a):
	cfg = hc.load(a.repo)
	rdir = hc.runs_dir(cfg, a.run_id)
	p = rdir / "verification.json"
	if not p.is_file():
		print(f"no verification.json for run {a.run_id}; run 'verify.py run' first", file=sys.stderr)
		return 2
	v = json.loads(p.read_text())
	if a.check:
		if not a.status:
			print("--status is required with --check", file=sys.stderr)
			return 2
		if a.status in ("SKIPPED", "FAIL", "BLOCKED") and not a.reason:
			print(f"--reason is required for {a.status}", file=sys.stderr)
			return 2
		v["manual_checks"] = [m for m in v["manual_checks"] if m["id"] != a.check]
		v["checks"] = [c for c in v["checks"] if c["id"] != a.check]
		v["checks"].append({"id": a.check, "status": a.status, "reason": a.reason, "findings": [], "evidence": a.evidence, "duration_ms": 0, "recorded_by": "tester",
			"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
	if a.remaining_data:
		v["remaining_test_data"].append(a.remaining_data)
	if a.limitation:
		v["limitations"].append(a.limitation)
	v["status"] = overall(v)
	p.write_text(json.dumps(v, indent=2, ensure_ascii=False))
	print(summary(v))
	return {"PASS": 0, "PENDING_TESTER": 0, "FAIL": 1}.get(v["status"], 2)


def main():
	ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	sub = ap.add_subparsers(dest="cmd", required=True)
	r, c = sub.add_parser("run"), sub.add_parser("record")
	for p in (r, c):
		p.add_argument("--run-id", required=True)
		p.add_argument("--repo", default=".")
	r.add_argument("--spec")
	r.add_argument("--site")
	r.add_argument("--no-cache", action="store_true")
	c.add_argument("--check")
	c.add_argument("--status", choices=["PASS", "FAIL", "BLOCKED", "SKIPPED"])
	for k in ("reason", "evidence", "remaining-data", "limitation"):
		c.add_argument("--" + k)
	a = ap.parse_args()
	try:
		return (cmd_run if a.cmd == "run" else cmd_record)(a)
	except hc.ConfigError as e:
		print(f"config error: {e}", file=sys.stderr)
		return 2


if __name__ == "__main__":
	sys.exit(main())
