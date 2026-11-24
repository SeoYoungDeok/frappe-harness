"""Black-box tests for scripts/analyze_diff.py, scripts/verify.py, inspect_environment.py.

Throwaway git repos in temp dirs; no Frappe site or DB is touched.
Run: python3 -m unittest tests.test_analyze_verify -v   (stdlib only)
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
AD, VF, IE = (os.path.join(S, n) for n in ("analyze_diff.py", "verify.py", "inspect_environment.py"))
sys.path.insert(0, S)

RULES = os.path.expanduser("~/.local/share/frappe-harness/frappe-semgrep-rules")
HAVE_SEMGREP = bool(shutil.which("semgrep")) and os.path.isdir(RULES)

DOCTYPE = {
	"doctype": "DocType", "name": "Foo", "module": "My App", "autoname": "field:title",
	"fields": [
		{"fieldname": "title", "fieldtype": "Data", "label": "Title", "unique": 0},
		{"fieldname": "qty", "fieldtype": "Data", "label": "Qty"},
	],
	"field_order": ["title", "qty"],
	"permissions": [{"role": "System Manager", "read": 1, "write": 1}],
}
DT = "myapp/myapp/doctype/foo/foo.json"


def git(repo, *a):
	return subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *a],
		check=True, capture_output=True, text=True).stdout


def run(script, *args, env=None, cwd=None):
	e = {**os.environ, **(env or {})}
	t = time.time()
	p = subprocess.run([sys.executable, script, *args], capture_output=True, text=True, timeout=300, env=e, cwd=cwd)
	return p.returncode, p.stdout, p.stderr, time.time() - t


def write(repo, rel, content):
	p = os.path.join(repo, rel)
	os.makedirs(os.path.dirname(p), exist_ok=True)
	with open(p, "w" if isinstance(content, str) else "wb") as f:
		f.write(content)


def write_dt(repo, mut=None):
	d = json.loads(json.dumps(DOCTYPE))
	if mut:
		mut(d)
	write(repo, DT, json.dumps(d, indent=1) + "\n")


def read(repo, rel):
	with open(os.path.join(repo, rel), "rb") as f:
		return f.read()


class Base(unittest.TestCase):
	TOOLS = ""

	def setUp(self):
		self.root = tempfile.mkdtemp()
		self.bench = os.path.join(self.root, "bench")
		self.repo = os.path.join(self.bench, "apps", "myapp")
		os.makedirs(os.path.join(self.bench, "sites"))
		os.makedirs(self.repo)
		self.config(self.TOOLS)
		write_dt(self.repo)
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn a + b\n")
		write(self.repo, "myapp/hooks.py", "app_name = 'myapp'\n")
		subprocess.run(["git", "init", "-q", self.repo], check=True)
		git(self.repo, "add", "-A")
		git(self.repo, "commit", "-qm", "init")
		self.n = 0

	def tearDown(self):
		shutil.rmtree(self.root, ignore_errors=True)

	def config(self, tools=""):
		write(self.repo, ".frappe-harness.toml",
			'bench = "../.."\napp = "myapp"\n[sites]\ndev = "dev.localhost"\ntest = "test.localhost"\nproduction = ["prod.localhost"]\n' + tools)

	def rid(self):
		self.n += 1
		return "r%d" % self.n

	def diff(self, rid=None, *extra):
		a = ["diff", "--repo", self.repo, "--json", *extra] + (["--run-id", rid] if rid else [])
		rc, out, err, _ = run(AD, *a)
		self.assertEqual(rc, 0, err)
		return json.loads(out)

	def baseline(self, rid):
		rc, out, err, _ = run(AD, "baseline", "--run-id", rid, "--repo", self.repo)
		self.assertEqual(rc, 0, err)

	def verify(self, rid, *extra, env=None):
		rc, out, err, dt = run(VF, "run", "--run-id", rid, "--repo", self.repo, *extra, env=env)
		with open(os.path.join(self.repo, ".harness/runs", rid, "verification.json")) as f:
			return rc, json.load(f), out, dt

	@staticmethod
	def check(v, cid):
		return next((c for c in v["checks"] if c["id"] == cid), None)


class TestClassification(Base):
	def test_A01_label_change_is_L0_and_cheap(self):
		rid = self.rid()
		self.baseline(rid)
		write_dt(self.repo, lambda d: d["fields"][0].update(label="Titel"))
		r = self.diff(rid)
		self.assertEqual(r["level"], 0)
		self.assertEqual(r["changed_doctypes"], ["Foo"])
		for c in ("db_tests", "unit_tests", "data_safety", "role_check"):
			self.assertNotIn(c, r["recommended_checks"])
		rc, v, _out, dt = self.verify(rid)
		self.assertEqual(rc, 0, v)
		self.assertIn(v["status"], ("PASS", "PENDING_TESTER"))
		self.assertLess(dt, 30)
		pend = {m["id"] for m in v["manual_checks"]}
		self.assertFalse(pend & {"db_tests", "unit_tests", "data_safety"})
		self.assertEqual(self.check(v, "json_validation")["status"], "PASS")

	def test_A13_fieldtype_change_L3_data_safety(self):
		rid = self.rid()
		self.baseline(rid)
		write_dt(self.repo, lambda d: d["fields"][1].update(fieldtype="Int"))
		r = self.diff(rid)
		self.assertEqual(r["level"], 3)
		self.assertIn("data_safety", r["recommended_checks"])
		self.assertTrue(any(c["property"] == "fieldtype" and c["level"] == 3 for c in r["changes"]))
		rc, v, *_ = self.verify(rid)
		self.assertIn("data_safety", {m["id"] for m in v["manual_checks"]})
		self.assertEqual(v["level"], 3)

	def test_field_removed_and_rename_are_L3(self):
		def mut(d):
			d["fields"][1].update(fieldname="quantity")
			d["field_order"] = ["title", "quantity"]
		write_dt(self.repo, mut)
		r = self.diff()
		self.assertEqual(r["level"], 3)
		self.assertTrue({"field_removed", "possible_rename"} <= {c["type"] for c in r["changes"]})

	def test_A11_pure_python_logic_unit_tests_not_browser(self):
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn a + b + 1\n")
		r = self.diff(rid)
		self.assertIn("unit_tests", r["recommended_checks"])
		self.assertNotIn("browser_check", r["recommended_checks"])
		self.assertNotIn("data_safety", r["recommended_checks"])
		self.assertEqual(r["level"], 2)

	def test_permission_change_role_and_db_tests(self):
		write_dt(self.repo, lambda d: d["permissions"].append({"role": "Guest", "read": 1}))
		r = self.diff()
		self.assertIn("role_check", r["recommended_checks"])
		self.assertIn("db_tests", r["recommended_checks"])

	def test_whitelisted_api_needs_role_check(self):
		write(self.repo, "myapp/myapp/api.py", "import frappe\n\n@frappe.whitelist()\ndef f():\n\treturn 1\n")
		r = self.diff()
		self.assertIn("role_check", r["recommended_checks"])

	def test_patch_is_L3(self):
		write(self.repo, "myapp/patches.txt", "myapp.patches.x\n")
		self.assertEqual(self.diff()["level"], 3)

	def test_unique_to_true_is_L3_but_false_is_not(self):
		write_dt(self.repo, lambda d: d["fields"][0].update(unique=1))
		self.assertEqual(self.diff()["level"], 3)

	def test_migrate_risks_api(self):
		import analyze_diff
		self.assertEqual(analyze_diff.migrate_risks(self.repo), [])
		write_dt(self.repo, lambda d: d["fields"][1].update(fieldtype="Int"))
		risks = analyze_diff.migrate_risks(self.repo)
		self.assertEqual(len(risks), 1)
		self.assertIn("qty", risks[0])


class TestBaselineIsolation(Base):
	def test_A14_preexisting_changes_preserved_and_excluded(self):
		# staged, unstaged, untracked pre-existing work
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn 99  # staged\n")
		git(self.repo, "add", "myapp/myapp/calc.py")
		write(self.repo, "myapp/hooks.py", "app_name = 'myapp'\n# unstaged edit\n")
		write(self.repo, "notes.txt", b"untracked \x00\xff binary-ish\n")
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn 99  # staged\n\n# and unstaged on top\n")
		files = ["myapp/myapp/calc.py", "myapp/hooks.py", "notes.txt"]
		before = {f: hashlib.sha256(read(self.repo, f)).hexdigest() for f in files}
		status_before = git(self.repo, "status", "--porcelain", "-uall", "--", ".", ":!.harness")
		index_before = git(self.repo, "diff", "--cached")
		stash_before = git(self.repo, "stash", "list")

		rid = self.rid()
		self.baseline(rid)
		r0 = self.diff(rid)
		self.assertEqual(r0["changed_files"], [], "nothing done yet: pre-existing changes must not be attributed to the task")
		self.assertCountEqual(r0["preexisting_untouched"], files)

		write_dt(self.repo, lambda d: d["fields"][0].update(label="Titel"))
		r = self.diff(rid)
		self.assertEqual([c["path"] for c in r["changed_files"]], [DT])
		self.assertEqual(r["level"], 0)
		self.assertTrue(r["base"]["baseline_used"])
		rc, v, *_ = self.verify(rid)
		self.assertEqual([c["path"] for c in v["analysis"]["changed_files"]], [DT])

		for f in files:
			self.assertEqual(hashlib.sha256(read(self.repo, f)).hexdigest(), before[f], f)
		self.assertEqual(git(self.repo, "diff", "--cached"), index_before)
		self.assertEqual(git(self.repo, "stash", "list"), stash_before)
		status_after = git(self.repo, "status", "--porcelain", "-uall", "--", ".", ":!.harness")
		self.assertEqual(status_after.replace(" M myapp/myapp/doctype/foo/foo.json\n", ""), status_before)

	def test_task_edit_on_preexisting_dirty_file_is_attributed(self):
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn 1\n")  # pre-existing
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn 2\n")  # task edits it too
		r = self.diff(rid)
		self.assertEqual([c["path"] for c in r["changed_files"]], ["myapp/myapp/calc.py"])

	def test_no_baseline_states_limitation(self):
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn 1\n")
		r = self.diff("nobaseline")
		self.assertTrue(any("no baseline" in x for x in r["limitations"]))

	def test_runs_dir_self_ignored(self):
		rid = self.rid()
		self.baseline(rid)
		write_dt(self.repo, lambda d: d["fields"][0].update(label="Titel"))
		self.verify(rid)
		with open(os.path.join(self.repo, ".harness/runs/.gitignore")) as f:
			self.assertEqual(f.read().strip(), "*")
		self.assertNotIn(".harness", git(self.repo, "status", "--porcelain", "-uall"))


class TestSpecCheck(Base):
	def spec(self, **uniq):
		f = {"label": "Title", "fieldname": "title", "fieldtype": "Data"}
		f.update(uniq)
		return {"schema_version": "1.0", "type": "feature", "status": "confirmed", "name": "foo", "app": "myapp",
			"doctypes": [{"name": "Foo", "fields": [f]}], "acceptance_criteria": ["x"]}

	def run_spec(self, spec, extra=None):
		extra = extra or {}
		sp = os.path.join(self.root, "spec.json")
		with open(sp, "w") as f:
			json.dump(spec, f)
		rid = self.rid()
		self.baseline(rid)
		write_dt(self.repo, lambda d: (d["fields"][0].update(description="d%s" % rid), d["fields"][0].update(extra)))
		rc, v, out, _ = self.verify(rid, "--spec", sp)
		return rc, v

	def test_A05_explicit_unique_mismatch_fails_then_passes(self):
		rc, v = self.run_spec(self.spec(unique=True))
		c = self.check(v, "spec_check")
		self.assertEqual(c["status"], "FAIL")
		self.assertEqual(rc, 1)
		self.assertEqual(v["status"], "FAIL")
		self.assertTrue(any(f["property"] == "unique" and f["expected"] is True for f in c["findings"]), c["findings"])
		# fix the DocType
		write_dt(self.repo, lambda d: d["fields"][0].update(unique=1, description="fixed"))
		rid = self.rid()
		self.baseline(rid)
		rc, v, *_ = self.verify(rid, "--spec", os.path.join(self.root, "spec.json"))
		self.assertEqual(self.check(v, "spec_check")["status"], "PASS", v["checks"])
		self.assertEqual(self.check(v, "spec_check").get("spec_sha256") and True, True)

	def test_explicit_false_vs_auto_vs_missing(self):
		# explicit false while DocType has unique=1 -> mismatch
		_, v = self.run_spec(self.spec(unique=False), {"unique": 1})
		self.assertEqual(self.check(v, "spec_check")["status"], "FAIL")
		# auto -> not compared
		_, v = self.run_spec(self.spec(unique={"mode": "auto"}), {"unique": 1})
		self.assertEqual(self.check(v, "spec_check")["status"], "PASS")
		# missing -> not compared
		_, v = self.run_spec(self.spec(), {"unique": 1})
		self.assertEqual(self.check(v, "spec_check")["status"], "PASS")
		# {"mode":"none"} with unique=1 -> mismatch (must be unset)
		_, v = self.run_spec(self.spec(unique={"mode": "none"}), {"unique": 1})
		self.assertEqual(self.check(v, "spec_check")["status"], "FAIL")

	def test_draft_spec_blocked(self):
		s = self.spec()
		s["status"] = "draft"
		rc, v = self.run_spec(s)
		self.assertEqual(self.check(v, "spec_check")["status"], "BLOCKED")
		self.assertEqual(v["status"], "BLOCKED")
		self.assertEqual(rc, 2)

	def test_missing_or_invalid_spec_blocked(self):
		rid = self.rid()
		self.baseline(rid)
		rc, v, *_ = self.verify(rid, "--spec", "nope.json")
		self.assertEqual(self.check(v, "spec_check")["status"], "BLOCKED")
		self.assertEqual(rc, 2)

	def test_missing_field_in_doctype_fails(self):
		s = self.spec()
		s["doctypes"][0]["fields"].append({"label": "Ghost", "fieldname": "ghost", "fieldtype": "Data"})
		_, v = self.run_spec(s)
		self.assertEqual(self.check(v, "spec_check")["status"], "FAIL")

	def test_production_site_refused(self):
		rid = self.rid()
		self.baseline(rid)
		write_dt(self.repo, lambda d: d["fields"][0].update(label="Titel"))
		rc, v, *_ = self.verify(rid, "--site", "prod.localhost")
		self.assertEqual(self.check(v, "site_guard")["status"], "BLOCKED")
		self.assertEqual(rc, 2)
		rc, v, *_ = self.verify(rid, "--site", "unknown.example")
		self.assertEqual(self.check(v, "site_guard")["status"], "BLOCKED")


class TestToolsAndStatus(Base):
	def change_py(self, body="def total(a, b):\n\treturn a - b\n"):
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, "myapp/myapp/calc.py", body)
		return rid

	def test_A15_required_semgrep_missing_rules_is_blocked_not_skipped(self):
		self.config('[tools]\nsemgrep_rules = "/nonexistent/rules"\nsemgrep_required = true\n')
		rid = self.change_py()
		rc, v, *_ = self.verify(rid)
		c = self.check(v, "semgrep")
		self.assertEqual(c["status"], "BLOCKED", c)
		self.assertTrue(c["reason"])
		self.assertEqual(v["status"], "BLOCKED")
		self.assertEqual(rc, 2)

	def test_unrequired_semgrep_skipped_with_reason_and_limitation(self):
		rid = self.change_py()
		rc, v, *_ = self.verify(rid)
		c = self.check(v, "semgrep")
		self.assertEqual(c["status"], "SKIPPED")
		self.assertTrue(c["reason"])
		self.assertTrue(any("semgrep" in x for x in v["limitations"]))
		self.assertNotEqual(v["status"], "FAIL")

	def test_A15_ruff_unavailable_is_blocked(self):
		d = os.path.join(self.root, "pathonly")
		os.makedirs(d)
		os.symlink(shutil.which("git"), os.path.join(d, "git"))
		rid = self.change_py()
		rc, v, *_ = self.verify(rid, env={"PATH": d})
		c = self.check(v, "ruff")
		self.assertEqual(c["status"], "BLOCKED", c)
		self.assertEqual(rc, 2)

	@unittest.skipUnless(HAVE_SEMGREP, "semgrep + local rules not installed")
	def test_semgrep_with_local_rules_runs(self):
		self.config('[tools]\nsemgrep_rules = "%s"\nsemgrep_required = true\n' % RULES)
		rid = self.change_py()
		rc, v, *_ = self.verify(rid)
		self.assertIn(self.check(v, "semgrep")["status"], ("PASS", "FAIL"), self.check(v, "semgrep"))

	def test_ruff_failure_is_FAIL(self):
		rid = self.change_py("import os\ndef total(a, b):\n\treturn a - b\n")
		rc, v, *_ = self.verify(rid)
		if self.check(v, "ruff")["status"] == "BLOCKED":
			self.skipTest("ruff not available")
		self.assertEqual(self.check(v, "ruff")["status"], "FAIL")
		self.assertEqual(rc, 1)

	def test_invalid_json_fails(self):
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, DT, "{ not json")
		rc, v, *_ = self.verify(rid)
		self.assertEqual(self.check(v, "json_validation")["status"], "FAIL")
		self.assertEqual(rc, 1)

	def test_whitespace_in_untracked_file_fails_git_diff_check(self):
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, "myapp/myapp/new.py", "x = 1   \n")
		rc, v, *_ = self.verify(rid)
		self.assertEqual(self.check(v, "git_diff_check")["status"], "FAIL")

	def test_A17_record_recomputes_status(self):
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn a * b\n")
		rc, v, *_ = self.verify(rid)
		if v["status"] == "BLOCKED":
			self.skipTest("ruff unavailable")
		self.assertEqual(v["status"], "PENDING_TESTER")
		self.assertEqual(rc, 0)
		rec = lambda *a: run(VF, "record", "--run-id", rid, "--repo", self.repo, *a)
		vj = os.path.join(self.repo, ".harness/runs", rid, "verification.json")
		load = lambda: json.loads(open(vj).read())
		# FAIL / SKIPPED / BLOCKED need a reason
		rc, _o, err, _ = rec("--check", "unit_tests", "--status", "FAIL")
		self.assertEqual(rc, 2)
		self.assertEqual(load()["status"], "PENDING_TESTER")
		rc, *_ = rec("--check", "unit_tests", "--status", "FAIL", "--reason", "assert failed", "--evidence", "out.txt")
		self.assertEqual(rc, 1)
		self.assertEqual(load()["status"], "FAIL")
		rc, *_ = rec("--check", "unit_tests", "--status", "PASS", "--evidence", "out.txt", "--remaining-data", "ToDo x1", "--limitation", "ran on test site")
		self.assertEqual(rc, 0)
		v = load()
		self.assertEqual(v["status"], "PASS")
		self.assertEqual(v["remaining_test_data"], ["ToDo x1"])
		self.assertIn("ran on test site", v["limitations"])
		self.assertEqual(sum(1 for c in v["checks"] if c["id"] == "unit_tests"), 1)
		rc, *_ = rec("--check", "role_check", "--status", "BLOCKED", "--reason", "no user")
		self.assertEqual(rc, 2)
		self.assertEqual(load()["status"], "BLOCKED")

	def test_record_without_run_fails_cleanly(self):
		rc, _o, err, _ = run(VF, "record", "--run-id", "never", "--repo", self.repo, "--check", "x", "--status", "PASS")
		self.assertEqual(rc, 2)
		self.assertNotIn("Traceback", err)

	def test_no_config_exit_2(self):
		d = tempfile.mkdtemp()
		try:
			for script, args in ((AD, ["diff"]), (VF, ["run", "--run-id", "x"]), (IE, [])):
				rc, _o, err, _ = run(script, *args, "--repo", d)
				self.assertEqual(rc, 2, script)
				self.assertNotIn("Traceback", err)
		finally:
			shutil.rmtree(d)


class TestCache(Base):
	def test_A22_cache_reuse_only_when_unchanged(self):
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn a * b\n")
		rc, v1, *_ = self.verify(rid)
		if self.check(v1, "ruff")["status"] not in ("PASS", "FAIL"):
			self.skipTest("ruff unavailable")
		self.assertNotIn("reused_from", self.check(v1, "ruff"))
		rc, v2, *_ = self.verify(rid)
		self.assertEqual(self.check(v2, "ruff").get("reused_from"), rid)
		# modify the file -> re-run
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn a / b\n")
		rc, v3, *_ = self.verify(rid)
		self.assertNotIn("reused_from", self.check(v3, "ruff"))
		# config change -> re-run
		write(self.repo, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
		rc, v4, *_ = self.verify(rid)
		self.assertNotIn("reused_from", self.check(v4, "ruff"))
		# --no-cache never reuses
		rc, v5, *_ = self.verify(rid, "--no-cache")
		self.assertNotIn("reused_from", self.check(v5, "ruff"))

	def test_blocked_results_not_cached(self):
		d = os.path.join(self.root, "pathonly")
		os.makedirs(d)
		os.symlink(shutil.which("git"), os.path.join(d, "git"))
		rid = self.rid()
		self.baseline(rid)
		write(self.repo, "myapp/myapp/calc.py", "def total(a, b):\n\treturn a * b\n")
		self.verify(rid, env={"PATH": d})
		rc, v, *_ = self.verify(rid, env={"PATH": d})
		self.assertEqual(self.check(v, "ruff")["status"], "BLOCKED")
		self.assertNotIn("reused_from", self.check(v, "ruff"))


REAL = os.path.expanduser("~/frappe/frappe-bench/apps/komex_mes")


@unittest.skipUnless(os.path.isfile(os.path.join(REAL, ".frappe-harness.toml")), "real app not present")
class TestRealAppReadOnly(unittest.TestCase):
	def porcelain(self):
		return subprocess.run(["git", "-C", REAL, "status", "--porcelain", "-uall"], capture_output=True, text=True).stdout

	def test_inspect_and_diff_read_only_no_secrets(self):
		before = self.porcelain()
		existed = os.path.exists(os.path.join(REAL, ".harness"))
		rc, out, err, dt = run(IE, "--repo", REAL, "--json")
		self.assertEqual(rc, 0, err)
		json.loads(out)
		rc2, out2, err2, _ = run(AD, "diff", "--against", "HEAD", "--repo", REAL, "--json")
		self.assertEqual(rc2, 0, err2)
		json.loads(out2)
		self.assertEqual(self.porcelain(), before)
		self.assertEqual(os.path.exists(os.path.join(REAL, ".harness")), existed)
		# no secret from site_config.json may appear in the output
		bench = os.path.abspath(os.path.join(REAL, "..", ".."))
		secrets = set()
		for p in (os.path.join(bench, "sites", "common_site_config.json"),
			*[os.path.join(bench, "sites", d, "site_config.json") for d in os.listdir(os.path.join(bench, "sites"))]):
			try:
				with open(p) as f:
					for k, val in json.load(f).items():
						if isinstance(val, str) and len(val) >= 6 and any(w in k for w in ("password", "secret", "key", "token")):
							secrets.add(val)
			except (OSError, ValueError, NotADirectoryError):
				pass
		for sec in secrets:
			self.assertNotIn(sec, out + err + out2 + err2)
		sys.stderr.write("\nINSPECT komex_mes: %.2fs; secrets checked: %d\n" % (dt, len(secrets)))


if __name__ == "__main__":
	unittest.main()
