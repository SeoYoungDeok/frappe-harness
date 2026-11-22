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
