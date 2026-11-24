"""Black-box tests for scripts/guard.py (PreToolUse hook), written from the spec.

Run: python3 -m unittest tests.test_guard -v
Standard library only (Python 3.9+).
"""

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "scripts", "guard.py")


def run_raw(stdin_text):
	proc = subprocess.run(
		[sys.executable, GUARD],
		input=stdin_text,
		capture_output=True,
		text=True,
		timeout=10,
	)
	return proc.returncode, proc.stdout, proc.stderr


def run(command, codex=False, tool_name="Bash"):
	payload = {"tool_name": tool_name, "tool_input": {"command": command}}
	if codex:
		payload["turn_id"] = "turn-123"
	return run_raw(json.dumps(payload))


DESTRUCTIVE = [
	# 1. bench subcommands
	"bench --site test.localhost reinstall --yes",
	"cd ~/frappe-bench && bench drop-site x.localhost",
	"bench drop-site x.localhost --force",
	"bench --site test.localhost restore /tmp/db.sql.gz",
	"bench --site test.localhost trim-database",
	"bench --site test.localhost trim-tables --dry-run",
	"bench --site test.localhost uninstall-app my_app --yes",
	"bench --site x  reinstall",  # extra spaces
	"bench\t--site x\treinstall",  # tabs
	"ls && bench --site x reinstall",
	"env FOO=1 bench --site x reinstall",
	# 2. SQL
	'bench --site s mariadb -e "drop table tabFoo"',
	"mysql -e 'DROP DATABASE x'",
	"mysql -e 'Drop Schema x'",
	"mysql -e 'truncate table tabFoo'",
	"mysql -e 'TRUNCATE TABLE `tabFoo`'",
	"mysql -e 'DROP TABLE IF EXISTS tabFoo'",
	"mysql -e 'drop   table tabFoo'",
	# 3. rm backups
	"rm -rf sites/x/private/backups",
	"rm sites/x/private/backups/20240101-db.sql.gz",
	"rm /tmp/dump.sql",
	"rm -f old.sql.gz",
	"cd sites && rm -rf x.localhost/private/backups/*",
	# spec additions (round 2)
	"BENCH --site x reinstall",
	"Bench --site x Drop-Site x",
	"bench --site x \\\n  reinstall --yes",
	"bench \\\n --site x \\\n drop-site x",
	"bench new-site x.localhost --force",
	"bench new-site x.localhost --install-app erpnext --force",
	"cd ~/frappe-bench && bench new-site x.localhost --db-name x --force",
	"BENCH NEW-SITE x --FORCE",
	"rm DUMP.SQL",
	"rm backup.Sql.Gz",
	"rm private//backups/x",
	"rm -rf sites/x/private///backups",
]

SAFE = [
	"bench --site test.localhost migrate",
	"bench --site x backup --with-files",
	"bench --site test.localhost run-tests --app my_app",
	"bench build",
	"git restore file.py",
	"rm -rf node_modules",
	"bench start",
	"ls sites/x/private/backups",
	"echo hello",
	"bench --site x list-apps",
	"cat dump.sql",
	# spec additions (round 2)
	"bench new-site x.localhost",
	"bench new-site x.localhost --install-app erpnext",
	"bench new-site x.localhost && ls --force",
	"ls private//backups",
	"cat DUMP.SQL",
]


class TestFlaggedClaude(unittest.TestCase):
	"""Flagged + no turn_id => exit 0, JSON ask decision on stdout."""

	def test_destructive_commands_ask(self):
		for cmd in DESTRUCTIVE:
			with self.subTest(cmd=cmd):
				code, out, _err = run(cmd)
				self.assertEqual(code, 0)
				self.assertTrue(out.strip(), "expected JSON on stdout")
				data = json.loads(out)
				hso = data["hookSpecificOutput"]
				self.assertEqual(hso["hookEventName"], "PreToolUse")
				self.assertEqual(hso["permissionDecision"], "ask")
				self.assertIsInstance(hso["permissionDecisionReason"], str)
				self.assertTrue(hso["permissionDecisionReason"].strip())


class TestFlaggedCodex(unittest.TestCase):
	"""Flagged + turn_id => exit 2, reason on stderr, no allow on stdout."""

	def test_destructive_commands_block(self):
		for cmd in DESTRUCTIVE:
			with self.subTest(cmd=cmd):
				code, out, err = run(cmd, codex=True)
				self.assertEqual(code, 2)
				self.assertTrue(err.strip(), "expected reason on stderr")
				self.assertNotIn("allow", out.lower())

	def test_turn_id_presence_not_value_decides(self):
		payload = {"tool_name": "Bash", "turn_id": "", "tool_input": {"command": "bench drop-site x"}}
		code, _out, err = run_raw(json.dumps(payload))
		self.assertEqual(code, 2)
		self.assertTrue(err.strip())


class TestNotFlagged(unittest.TestCase):
	def test_safe_commands_claude(self):
		for cmd in SAFE:
			with self.subTest(cmd=cmd):
				code, out, _err = run(cmd)
				self.assertEqual(code, 0)
				self.assertEqual(out, "")

	def test_safe_commands_codex(self):
		for cmd in SAFE:
			with self.subTest(cmd=cmd):
				code, out, _err = run(cmd, codex=True)
				self.assertEqual(code, 0)
				self.assertEqual(out, "")


class TestNonObjectPayload(unittest.TestCase):
	def test_non_object_json_exits_zero(self):
		for text in ("null", "[1, 2]", '"bench drop-site x"', "42", "true", "[]"):
			with self.subTest(text=text):
				code, out, err = run_raw(text)
				self.assertEqual(code, 0, err)
				self.assertEqual(out, "")
				self.assertNotIn("Traceback", err)


class TestRobustness(unittest.TestCase):
	def assertAllowed(self, result):
		code, out, err = result
		self.assertEqual(code, 0, err)
		self.assertEqual(out, "")
		self.assertNotIn("Traceback", err)

	def test_invalid_json(self):
		self.assertAllowed(run_raw("{not json"))

	def test_empty_stdin(self):
		self.assertAllowed(run_raw(""))

	def test_missing_tool_input(self):
		self.assertAllowed(run_raw(json.dumps({"tool_name": "Bash"})))

	def test_tool_input_null(self):
		self.assertAllowed(run_raw(json.dumps({"tool_name": "Bash", "tool_input": None})))

	def test_tool_input_not_dict(self):
		self.assertAllowed(run_raw(json.dumps({"tool_name": "Bash", "tool_input": "bench drop-site x"})))

	def test_missing_command(self):
		self.assertAllowed(run_raw(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}})))

	def test_non_string_command(self):
		for value in (123, None, {"a": 1}, True):
			with self.subTest(value=value):
				self.assertAllowed(run_raw(json.dumps({"tool_input": {"command": value}})))

	def test_non_object_json(self):
		# Valid JSON that is not an object. Spec: never crash.
		for text in ("null", "[1, 2]", '"bench drop-site x"', "42"):
			with self.subTest(text=text):
				self.assertAllowed(run_raw(text))


class TestListCommand(unittest.TestCase):
	def test_list_form_flagged_claude(self):
		code, out, _ = run(["bash", "-lc", "bench drop-site x"])
		self.assertEqual(code, 0)
		self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")

	def test_list_form_flagged_codex(self):
		code, _out, err = run(["bash", "-lc", "bench drop-site x"], codex=True)
		self.assertEqual(code, 2)
		self.assertTrue(err.strip())

	def test_list_form_safe(self):
		code, out, _ = run(["bash", "-lc", "bench --site x migrate"])
		self.assertEqual(code, 0)
		self.assertEqual(out, "")


# ---------------------------------------------------------------------------
# Phase 1 (roles / models / migrate risk / semgrep). Throwaway harness project.
# ---------------------------------------------------------------------------
import shutil
import tempfile
import time

RECORD = os.path.join(ROOT, "scripts", "record_worker.py")
DOCTYPE = {"doctype": "DocType", "name": "Foo", "module": "M", "fields": [
	{"fieldname": "title", "fieldtype": "Data", "label": "Title"},
	{"fieldname": "qty", "fieldtype": "Data", "label": "Qty"}], "permissions": []}


def _git(repo, *a):
	subprocess.run(["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", *a],
		check=True, capture_output=True)


def make_project(root, with_doctype=True):
	"""bench/{apps,sites} + app git repo with .frappe-harness.toml. Returns repo path."""
	bench = os.path.join(root, "bench")
	repo = os.path.join(bench, "apps", "myapp")
	os.makedirs(os.path.join(bench, "sites"))
	os.makedirs(os.path.join(repo, "myapp", "myapp", "doctype", "foo"))
	with open(os.path.join(repo, ".frappe-harness.toml"), "w") as f:
		f.write('bench = "../.."\napp = "myapp"\n[sites]\ndev = "dev.localhost"\ntest = "test.localhost"\n'
			'production = ["prod.localhost"]\n[policy]\nrun_tests_on_dev = false\n')
	if with_doctype:
		with open(os.path.join(repo, "myapp/myapp/doctype/foo/foo.json"), "w") as f:
			json.dump(DOCTYPE, f, indent=1)
	subprocess.run(["git", "init", "-q", repo], check=True)
	_git(repo, "add", "-A")
	_git(repo, "commit", "-qm", "init")
	return repo


def transcript(root, model, agent_id="A1", session="sess", lines=None):
	"""Fake worker transcript; returns transcript_path of the parent session."""
	tp = os.path.join(root, "proj", session + ".jsonl")
	d = os.path.join(root, "proj", session, "subagents")
	os.makedirs(d, exist_ok=True)
	lines = lines or [{"type": "assistant", "timestamp": "2026-01-01T00:00:00Z",
		"message": {"id": "m1", "model": model, "usage": {"input_tokens": 1, "output_tokens": 1}}}]
	with open(os.path.join(d, "agent-%s.jsonl" % agent_id), "w") as f:
		f.write("\n".join(json.dumps(x) for x in lines) + "\n")
	return tp


def call(payload):
	t = time.time()
	code, out, err = run_raw(json.dumps(payload))
	decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else "allow"
	return decision, code, out, err, time.time() - t


class GuardProject(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.root = tempfile.mkdtemp()
		cls.repo = make_project(cls.root)

	@classmethod
	def tearDownClass(cls):
		shutil.rmtree(cls.root, ignore_errors=True)

	def worker(self, tool, tool_input, agent="frappe-harness:tester", model="claude-sonnet-5-5", **kw):
		p = {"tool_name": tool, "tool_input": tool_input, "cwd": self.repo, "agent_id": "A1",
			"agent_type": agent, "session_id": "sess", "transcript_path": transcript(self.root, model)}
		p.update(kw)
		return call(p)

	def main_call(self, tool, tool_input, **kw):
		return call({"tool_name": tool, "tool_input": tool_input, "cwd": self.repo, **kw})[0]


class TestModelAndAgent(GuardProject):
	def test_model_mismatch_denied_A07(self):
		for agent in ("frappe-harness:developer", "frappe-harness:tester"):
			for tool, ti in (("Bash", {"command": "ls"}), ("Edit", {"file_path": self.repo + "/tests/test_x.py"}), ("Read", {"file_path": "/x"})):
				with self.subTest(agent=agent, tool=tool):
					d, *_ = self.worker(tool, ti, agent=agent, model="claude-opus-4-7")
					self.assertEqual(d, "deny")
		d, _c, out, *_ = self.worker("Bash", {"command": "ls"}, model="claude-opus-4-7")
		self.assertIn("opus", out)

	def test_sonnet_allowed(self):
		d, *_ = self.worker("Bash", {"command": "ls"}, model="claude-sonnet-5-5")
		self.assertEqual(d, "allow")

	def test_non_harness_agent_with_opus_not_denied(self):
		d, *_ = self.worker("Bash", {"command": "ls"}, agent="general-purpose", model="claude-opus-4-7")
		self.assertEqual(d, "allow")

	def test_unknown_model_fails_open(self):
		p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": self.repo, "agent_id": "ZZ",
			"agent_type": "frappe-harness:tester", "session_id": "sess", "transcript_path": "/nonexistent/x.jsonl"}
		self.assertEqual(call(p)[0], "allow")

	def test_agent_call_model_override_denied(self):
		for st in ("frappe-harness:developer", "frappe-harness:tester"):
			with self.subTest(st=st, model="opus"):
				self.assertEqual(self.main_call("Agent", {"subagent_type": st, "model": "opus", "prompt": "x"}), "deny")
			with self.subTest(st=st, model="sonnet"):
				self.assertEqual(self.main_call("Agent", {"subagent_type": st, "model": "sonnet", "prompt": "x"}), "allow")
			with self.subTest(st=st, model=None):
				self.assertEqual(self.main_call("Agent", {"subagent_type": st, "prompt": "x"}), "allow")

	def test_task_tool_name_also_checked(self):
		self.assertEqual(self.main_call("Task", {"subagent_type": "frappe-harness:developer", "model": "opus"}), "deny")

	def test_fork_denied_in_harness_project_only(self):
		self.assertEqual(self.main_call("Agent", {"subagent_type": "fork", "prompt": "x"}), "deny")
		other = tempfile.mkdtemp()
		try:
			d, *_ = call({"tool_name": "Agent", "tool_input": {"subagent_type": "fork"}, "cwd": other})
			self.assertEqual(d, "allow")
		finally:
			shutil.rmtree(other)

	def test_legacy_implementer_denied(self):
		self.assertEqual(self.main_call("Agent", {"subagent_type": "frappe-harness:implementer"}), "deny")

	def test_worker_spawning_worker_denied(self):
		d, *_ = self.worker("Agent", {"subagent_type": "frappe-harness:tester"}, agent="frappe-harness:developer")
		self.assertEqual(d, "deny")


class TestEditRoles(GuardProject):
	def test_tester_edit_matrix_A16(self):
		R = self.repo
		cases = [
			(R + "/myapp/myapp/api.py", "deny"),
			(R + "/myapp/myapp/doctype/foo/foo.json", "deny"),
			(R + "/hooks.py", "deny"),
			(R + "/tests/test_x.py", "allow"),
			(R + "/myapp/tests/helper.py", "allow"),
			(R + "/myapp/myapp/doctype/foo/test_foo.py", "allow"),
			(R + "/frontend/src/App.spec.js", "allow"),
			(R + "/.harness/runs/r1/note.txt", "allow"),
			(R + "/.harness/specs/s.json", "deny"),
			("/tmp/outside-harness.py", "allow"),
		]
		for path, want in cases:
			for tool in ("Edit", "Write", "MultiEdit"):
				with self.subTest(path=path, tool=tool):
					self.assertEqual(self.worker(tool, {"file_path": path})[0], want)

	def test_developer_cannot_write_specs_but_can_write_code(self):
		dev = "frappe-harness:developer"
		self.assertEqual(self.worker("Write", {"file_path": self.repo + "/.harness/specs/s.json"}, agent=dev)[0], "deny")
		self.assertEqual(self.worker("Edit", {"file_path": self.repo + "/myapp/myapp/api.py"}, agent=dev)[0], "allow")

	def test_relative_path_traversal_uses_cwd(self):
		d = self.worker("Edit", {"file_path": "tests/../myapp/api.py"})[0]
		self.assertEqual(d, "deny")

	def test_main_edit_app_code_asks(self):
		self.assertEqual(self.main_call("Edit", {"file_path": self.repo + "/myapp/myapp/api.py"}), "ask")
		self.assertEqual(self.main_call("Write", {"file_path": self.repo + "/myapp/myapp/api.py"}), "ask")

	def test_main_edit_outside_project_allowed(self):
		self.assertEqual(self.main_call("Edit", {"file_path": "/tmp/whatever.py"}), "allow")

	def test_main_codex_edit_not_ask(self):  # Codex has no agent_type: must not exit 2 for every edit
		code = run_raw(json.dumps({"tool_name": "Edit", "turn_id": "t", "cwd": self.repo,
			"tool_input": {"file_path": self.repo + "/myapp/myapp/api.py"}}))[0]
		self.assertEqual(code, 0)


class TestBashRules(GuardProject):
	def bash(self, cmd, **kw):
		return self.main_call("Bash", {"command": cmd}, **kw)

	def test_production_site_denied_A23(self):
		for cmd in ("bench --site prod.localhost migrate", "bench --site=prod.localhost console",
			"cd /x && bench --site prod.localhost run-tests --app myapp"):
			with self.subTest(cmd=cmd):
				self.assertEqual(self.bash(cmd), "deny")
		self.assertNotEqual(self.bash("bench --site test.localhost console"), "deny")

	def test_site_classified_by_config_not_name(self):
		self.assertNotEqual(self.bash("bench --site production.example backup"), "deny")

	def test_semgrep_registry_denied_A19(self):
		for cmd in ("semgrep --config auto .", "semgrep scan --config=auto .", "semgrep --config p/ci .",
			"semgrep -c p/python .", "semgrep --config r/python.lang .", "semgrep --config https://x/y.yml .",
			"semgrep ci", "semgrep login", "semgrep --pro ."):
			with self.subTest(cmd=cmd):
				self.assertEqual(self.bash(cmd), "deny")

	def test_semgrep_local_allowed(self):
		for cmd in ("semgrep scan --config /home/u/.local/share/frappe-harness/frappe-semgrep-rules/rules --metrics=off a.py",
			"semgrep --config ./rules a.py", "semgrep --version"):
			with self.subTest(cmd=cmd):
				self.assertEqual(self.bash(cmd), "allow")

	def test_destructive_git_asks(self):
		for cmd in ("git reset --hard", "git reset --hard HEAD~1", "git clean -fd", "git clean -f", "git clean --force",
			"git checkout .", "git restore .", "git stash drop", "git -C /x reset --hard"):
			with self.subTest(cmd=cmd):
				self.assertEqual(self.bash(cmd), "ask")
		for cmd in ("git status", "git reset --soft HEAD~1", "git clean -n", "git restore --staged .", "git diff"):
			with self.subTest(cmd=cmd):
				self.assertEqual(self.bash(cmd), "allow")

	def test_run_tests_on_dev_asks_when_policy_false(self):
		self.assertEqual(self.bash("bench --site dev.localhost run-tests --app myapp"), "ask")
		self.assertEqual(self.bash("bench --site test.localhost run-tests --app myapp"), "allow")

	def test_default_site_ambiguity_asks(self):
		self.assertEqual(self.bash("bench migrate"), "ask")
		self.assertEqual(self.bash("bench --site all migrate"), "ask")

	def test_framework_changes_ask(self):
		for cmd in ("bench update", "bench switch-to-branch version-16", "bench get-app x", "bench setup requirements"):
			with self.subTest(cmd=cmd):
				self.assertEqual(self.bash(cmd), "ask")

	def test_destructive_still_ask_with_project_cwd(self):
		for cmd in DESTRUCTIVE[:8]:
			with self.subTest(cmd=cmd):
				self.assertIn(self.bash(cmd), ("ask", "deny"))

	def test_codex_deny_and_ask_both_exit_2(self):
		for cmd in ("bench --site prod.localhost migrate", "git reset --hard", "semgrep --config auto ."):
			with self.subTest(cmd=cmd):
				code, out, err = run_raw(json.dumps({"tool_name": "Bash", "turn_id": "t", "cwd": self.repo,
					"tool_input": {"command": cmd}}))
				self.assertEqual(code, 2)
				self.assertTrue(err.strip())


class TestMigrateRisk(unittest.TestCase):
	def setUp(self):
		self.root = tempfile.mkdtemp()
		self.repo = make_project(self.root)
		self.path = os.path.join(self.repo, "myapp/myapp/doctype/foo/foo.json")

	def tearDown(self):
		shutil.rmtree(self.root, ignore_errors=True)

	def write(self, mut):
		d = json.loads(json.dumps(DOCTYPE))
		mut(d)
		with open(self.path, "w") as f:
			json.dump(d, f, indent=1)

	def migrate(self):
		return call({"tool_name": "Bash", "tool_input": {"command": "bench --site dev.localhost migrate"}, "cwd": self.repo})

	def test_clean_migrate_allowed(self):
		self.assertEqual(self.migrate()[0], "allow")

	def test_label_only_change_allowed(self):
		self.write(lambda d: d["fields"][0].update(label="Titel"))
		self.assertEqual(self.migrate()[0], "allow")

	def test_fieldtype_change_asks_A13(self):
		self.write(lambda d: d["fields"][1].update(fieldtype="Int"))
		d, code, out, *_ = self.migrate()
		self.assertEqual(d, "ask")
		self.assertIn("qty", out)
		self.assertIn("fieldtype", out)
		self.assertIn("Foo", out)

	def test_field_removed_asks(self):
		self.write(lambda d: d["fields"].pop())
		self.assertEqual(self.migrate()[0], "ask")

	def test_migrate_from_bench_cwd_also_finds_repo(self):
		self.write(lambda d: d["fields"][1].update(fieldtype="Int"))
		d, *_ = call({"tool_name": "Bash", "tool_input": {"command": "bench --site dev.localhost migrate"},
			"cwd": os.path.join(self.root, "bench")})
		self.assertEqual(d, "ask")


class TestGuardSpeed(GuardProject):
	def test_hook_latency(self):
		ts = []
		for _ in range(5):
			ts.append(call({"tool_name": "Bash", "tool_input": {"command": "bench --site dev.localhost migrate"}, "cwd": self.repo})[4])
		sys.stderr.write("\nGUARD LATENCY migrate: median %.0f ms, max %.0f ms\n" % (sorted(ts)[2] * 1000, max(ts) * 1000))
		self.assertLess(sorted(ts)[2], 1.0)


class TestRecordWorker(unittest.TestCase):
	def setUp(self):
		self.root = tempfile.mkdtemp()
		self.repo = make_project(self.root)

	def tearDown(self):
		shutil.rmtree(self.root, ignore_errors=True)

	def rec(self, payload):
		return subprocess.run([sys.executable, RECORD], input=payload if isinstance(payload, str) else json.dumps(payload),
			capture_output=True, text=True, timeout=10)

	def lines(self):
		with open(os.path.join(self.repo, ".harness/runs/metrics.jsonl")) as f:
			return [json.loads(x) for x in f]

	def test_records_actual_model_and_deduped_tokens(self):
		msgs = [
			{"type": "assistant", "timestamp": "2026-01-01T00:00:00Z", "uuid": "u1", "message": {"id": "m1", "model": "claude-opus-4-7",
				"usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 7}}},
			{"type": "assistant", "timestamp": "2026-01-01T00:00:10Z", "uuid": "u2", "message": {"id": "m1", "model": "claude-opus-4-7",
				"usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 7}}},
			{"type": "assistant", "timestamp": "2026-01-01T00:00:30Z", "uuid": "u3", "message": {"id": "m2", "model": "claude-opus-4-7",
				"usage": {"input_tokens": 20, "output_tokens": 15, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}},
		]
		tp = transcript(self.root, None, lines=msgs)
		r = self.rec({"hook_event_name": "SubagentStop", "cwd": self.repo, "agent_id": "A1", "agent_type": "frappe-harness:developer",
			"session_id": "sess", "transcript_path": tp})
		self.assertEqual(r.returncode, 0, r.stderr)
		(line,) = self.lines()
		self.assertEqual(line["kind"], "worker")
		self.assertEqual(line["actual_model"], "claude-opus-4-7")
		self.assertIs(line["model_match"], False)
		self.assertEqual((line["input_tokens"], line["output_tokens"], line["cache_read_tokens"], line["cache_creation_tokens"]), (30, 20, 100, 7))
		self.assertEqual(line["duration_s"], 30.0)
		self.assertEqual(open(os.path.join(self.repo, ".harness/runs/.gitignore")).read().strip(), "*")
		self.assertNotIn(".harness", subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout)

	def test_sonnet_match_and_append(self):
		tp = transcript(self.root, "claude-sonnet-5-5")
		p = {"cwd": self.repo, "agent_id": "A1", "agent_type": "frappe-harness:tester", "session_id": "sess", "transcript_path": tp}
		self.rec(p)
		self.rec(p)
		ls = self.lines()
		self.assertEqual(len(ls), 2)
		self.assertIs(ls[0]["model_match"], True)

	def test_unknown_transcript_is_null_not_estimate(self):
		self.rec({"cwd": self.repo, "agent_id": "nope", "agent_type": "frappe-harness:tester", "session_id": "s", "transcript_path": "/nonexistent/t.jsonl"})
		(line,) = self.lines()
		self.assertEqual(line["actual_model"], "unknown")
		self.assertIsNone(line["model_match"])
		self.assertIsNone(line["input_tokens"])

	def test_nothing_written_outside_harness_projects_or_for_other_agents(self):
		other = tempfile.mkdtemp()
		try:
			self.rec({"cwd": other, "agent_type": "frappe-harness:tester"})
			self.assertEqual(os.listdir(other), [])
			self.rec({"cwd": self.repo, "agent_type": "general-purpose", "agent_id": "x"})
			self.assertFalse(os.path.exists(os.path.join(self.repo, ".harness")))
		finally:
			shutil.rmtree(other)

	def test_never_crashes(self):
		for text in ("", "{bad", "null", "[1]", '{"agent_type": 5}', '{"agent_type":"frappe-harness:x","cwd":5}'):
			with self.subTest(text=text):
				r = self.rec(text)
				self.assertEqual(r.returncode, 0)
				self.assertNotIn("Traceback", r.stderr)


class TestHooksJson(unittest.TestCase):
	def test_registered(self):
		with open(os.path.join(ROOT, "hooks", "hooks.json")) as fh:
			h = json.load(fh)["hooks"]
		pre = h["PreToolUse"][0]
		for t in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent", "Task"):
			self.assertIn(t, pre["matcher"].split("|"))
		self.assertIn("guard.py", pre["hooks"][0]["command"])
		self.assertIn("record_worker.py", h["SubagentStop"][0]["hooks"][0]["command"])


# Probes: report-only (debatable per spec, or bypass/false-positive exploration).
PROBES = [
	# new edges for round 2 changes
	("bench --site x \\\r\n reinstall", "CRLF line continuation"),
	("bench new-site x --force-something", "new-site with --force prefix flag"),
	("bench new-site x --no-force", "new-site --no-force (hypothetical)"),
	("bench new-site x && bench --site x install-app foo --force", "--force belongs to a later command"),
	("bench new-site x -f", "short -f flag (if bench supports it)"),
	("bench --site x restore\\\nfoo", "continuation glued without whitespace"),
	('grep -r "drop table" docs/', "debatable (spec)"),
	("$(echo bench) --site x reinstall", "command substitution"),
	("b=bench; $b --site x reinstall", "variable indirection"),
	("bench --site x 'reinstall'", "quoted subcommand"),
	('bench --site x "drop-site"', "double-quoted subcommand"),
	("bench --site=x reinstall", "--site=x form"),
	("bench --site x mariadb < drop.sql", "SQL from file"),
	("echo 'DROP TABLE tabFoo' | bench --site x mariadb", "SQL via pipe"),
	("mysql -e 'DELETE FROM tabFoo'", "DELETE FROM (not in spec)"),
	("mysql -e 'drop/**/table tabFoo'", "SQL comment between keywords"),
	("rm -rf sites/x/private", "rm parent of backups"),
	("rm -rf sites/x.localhost", "rm whole site dir"),
	("find sites/x/private/backups -delete", "find -delete"),
	("unlink x.sql", "unlink"),
	("git rm schema.sql", "git rm (version-controlled, recoverable)"),
	("/bin/rm x.sql", "absolute rm"),
	("rm -rf ./private/backups", "relative backups"),
	("bench --site x reinstall-something", "subcommand prefix"),
	("echo bench reinstall", "echo mentions bench"),
	("git commit -m 'bench drop-site cleanup'", "commit msg mentions bench drop-site"),
	("git commit -m 'fix: rm old .sql files'", "commit msg mentions rm .sql"),
	("bench --site x restore-db", "hypothetical restore-*"),
	("bench --site x set-config restore_x 1", "restore_ arg"),
	("python3 -c \"import os; os.system('bench drop-site x')\"", "inside python string"),
]


class TestProbesReportOnly(unittest.TestCase):
	def test_probes(self):
		lines = []
		for cmd, note in PROBES:
			code, out, err = run(cmd)
			flagged = bool(out.strip())
			lines.append("  %-8s %-55r %s" % ("FLAGGED" if flagged else "allowed", cmd, note))
		sys.stderr.write("\nPROBE RESULTS (report only, not asserted):\n" + "\n".join(lines) + "\n")


if __name__ == "__main__":
	unittest.main()
