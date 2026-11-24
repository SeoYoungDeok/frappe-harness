"""Black-box tests for scripts/render_spec.py (stdlib unittest, subprocess)."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "scripts" / "render_spec.py"
EX = ROOT / "specification" / "examples"
EVIL = '</script><img src=x onerror=alert(1)>'


def run(*args):
	p = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True)
	return p.returncode, p.stdout, p.stderr


def base():
	return json.loads((EX / "feature.json").read_text(encoding="utf-8"))


class RenderSpecTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.dir = Path(self.tmp.name)

	def tearDown(self):
		self.tmp.cleanup()

	def write(self, spec, name="s.json"):
		p = self.dir / name
		p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
		return p

	def test_examples_valid(self):
		for f in sorted(EX.glob("*.json")):
			self.assertEqual(run("validate", f)[0], 0, f.name)

	def test_null_rejected(self):
		s = base()
		s["doctypes"][0]["fields"][1]["required"] = None
		self.assertEqual(run("validate", self.write(s))[0], 1)

	def test_bad_wrapper_rejected(self):
		for bad in ({"mode": "maybe"}, {"mode": "auto", "x": 1}, {}):
			s = base()
			s["doctypes"][0]["submittable"] = bad
			self.assertEqual(run("validate", self.write(s))[0], 1, bad)

	def test_explicit_false_and_wrappers_valid(self):
		s = base()
		f = s["doctypes"][0]["fields"][1]
		f.update(required=False, unique={"mode": "auto"}, fieldtype={"mode": "auto"})
		s["doctypes"][0]["submittable"] = {"mode": "none"}
		self.assertEqual(run("validate", self.write(s))[0], 0)

	def test_duplicate_ids_rejected(self):
		s = base()
		s["doctypes"][1]["fields"][0]["id"] = s["doctypes"][0]["fields"][0]["id"]
		rc, out, _ = run("validate", self.write(s))
		self.assertEqual(rc, 1)
		self.assertIn("duplicate", out)

	def test_unreadable_exit_2(self):
		self.assertEqual(run("validate", self.dir / "missing.json")[0], 2)
		bad = self.dir / "bad.json"
		bad.write_text("{nope", encoding="utf-8")
		self.assertEqual(run("validate", bad)[0], 2)

	def test_confirmed_unresolved_required_decision_fails(self):
		s = base()
		s["status"] = "confirmed"
		s["confirmed_at"] = "2026-01-01T00:00:00Z"
		s["doctypes"][0]["fields"] = [f for f in s["doctypes"][0]["fields"] if f.get("origin") != "suggestion"]
		s["doctypes"][1]["fields"] = [f for f in s["doctypes"][1]["fields"] if f.get("origin") != "suggestion"]
		s["reports"] = []
		s["acceptance_criteria"] = [c for c in s["acceptance_criteria"] if not (isinstance(c, dict) and c.get("origin") == "suggestion")]
		rc, out, _ = run("validate", self.write(s))
		self.assertEqual(rc, 1)
		self.assertIn("unresolved", out)
		for d in s["open_decisions"]:
			d["answer"] = "x"
		self.assertEqual(run("validate", self.write(s))[0], 0)

	def test_confirmed_with_suggestion_or_selected_fails(self):
		s = base()
		s["status"] = "confirmed"
		s["confirmed_at"] = "2026-01-01T00:00:00Z"
		for d in s["open_decisions"]:
			d["answer"] = "x"
		self.assertEqual(run("validate", self.write(s))[0], 1)

	def test_render_escapes_data_block(self):
		s = base()
		s["name"] = EVIL + " {{7*7}} <b>x</b>    "
		s["purpose"] = "</ScRiPt>"
		out = self.dir / "o.html"
		self.assertEqual(run("render", self.write(s), "-o", out)[0], 0)
		html = out.read_text(encoding="utf-8")
		start = html.index('id="spec-data"')
		end = html.index("</script>", start)
		block = html[start:end]
		self.assertNotIn("<", block)
		self.assertNotIn(" ", html)
		self.assertNotIn(" ", html)
		self.assertEqual(html.count("</script>"), 2)  # data block + builder script only
		raw = block[block.index(">") + 1:]
		self.assertEqual(json.loads(raw)["name"], s["name"])

	def test_render_does_not_alter_rest_of_builder(self):
		out = self.dir / "o.html"
		run("render", EX / "bug.json", "-o", out)
		tpl = (ROOT / "specification" / "builder.html").read_text(encoding="utf-8")
		html = out.read_text(encoding="utf-8")
		a, b = tpl.split('<script id="spec-data" type="application/json"></script>')
		self.assertTrue(html.startswith(a) and html.endswith(b))

	def test_markdown(self):
		rc, out, _ = run("markdown", EX / "feature.json")
		self.assertEqual(rc, 0)
		self.assertIn("Measuring Equipment", out)
		self.assertIn("AI 제안", out)

	def test_builder_has_no_dangerous_sinks_or_external_urls(self):
		import re
		html = (ROOT / "specification" / "builder.html").read_text(encoding="utf-8")
		for pat in (r"innerHTML", r"insertAdjacentHTML", r"outerHTML", r"document\.write", r"\beval\(", r"new Function"):
			self.assertIsNone(re.search(pat, html), pat)
		self.assertIsNone(re.search(r"https?://", html))


if __name__ == "__main__":
	unittest.main()
