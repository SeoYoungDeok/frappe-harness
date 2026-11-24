#!/usr/bin/env python3
"""Frappe Harness specification tool (stdlib only).

  render_spec.py render SPEC.json -o OUT.html   inject the spec into the fixed builder
  render_spec.py validate SPEC.json             schema + semantic checks
  render_spec.py markdown SPEC.json             derived Markdown on stdout

The JSON is the source of truth. `render` inserts only the escaped JSON into the
single placeholder of specification/builder.html. Exit codes for validate:
0 valid, 1 invalid, 2 unreadable.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "specification" / "builder.html"
SCHEMA = ROOT / "specification" / "schema.json"
PLACEHOLDER = '<script id="spec-data" type="application/json"></script>'
ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", " ": "\\u2028", " ": "\\u2029"}

# Lists whose dict items are blocks/items that carry a stable id.
ID_LISTS = {"doctypes", "fields", "rules", "permissions", "workflows", "ui", "reports",
	"business_rules", "open_decisions", "decisions", "acceptance_criteria"}


def load_json(path):
	try:
		with open(path, encoding="utf-8") as f:
			data = json.load(f)
	except (OSError, ValueError) as e:
		print(f"cannot read {path}: {e}", file=sys.stderr)
		sys.exit(2)
	if not isinstance(data, dict):
		print(f"{path}: top level must be a JSON object", file=sys.stderr)
		sys.exit(2)
	return data


# ---- render ---------------------------------------------------------------

def embed_json(data):
	text = json.dumps(data, ensure_ascii=False)
	for ch, rep in ESCAPES.items():
		text = text.replace(ch, rep)
	return text


def cmd_render(args):
	data = load_json(args.spec)
	try:
		template = BUILDER.read_text(encoding="utf-8")
	except OSError as e:
		print(f"cannot read builder: {e}", file=sys.stderr)
		return 2
	if template.count(PLACEHOLDER) != 1:
		print("builder.html must contain the spec-data placeholder exactly once", file=sys.stderr)
		return 2
	html = template.replace(PLACEHOLDER, PLACEHOLDER[:-len("</script>")] + embed_json(data) + "</script>")
	Path(args.output).write_text(html, encoding="utf-8")
	print(f"wrote {args.output}")
	return 0


# ---- mini JSON Schema validator -------------------------------------------

def type_ok(v, t):
	if t == "object":
		return isinstance(v, dict)
	if t == "array":
		return isinstance(v, list)
	if t == "string":
		return isinstance(v, str)
	if t == "boolean":
		return isinstance(v, bool)
	if t == "integer":
		return isinstance(v, int) and not isinstance(v, bool)
	if t == "number":
		return isinstance(v, (int, float)) and not isinstance(v, bool)
	if t == "null":
		return v is None
	return False


def same(a, b):
	return type(a) is type(b) and a == b


def check(v, schema, root, path, errs):
	"""Supports: $ref type enum const required properties additionalProperties
	items minItems pattern oneOf anyOf. Appends messages to errs."""
	if "$ref" in schema:
		node = root
		for part in schema["$ref"].lstrip("#/").split("/"):
			node = node[part]
		return check(v, node, root, path, errs)
	where = path or "(root)"
	if "type" in schema:
		types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
		if not any(type_ok(v, t) for t in types):
			errs.append(f"{where}: expected {'/'.join(types)}, got {json.dumps(v, ensure_ascii=False)[:60]}")
			return
	if "const" in schema and not same(v, schema["const"]):
		errs.append(f"{where}: must be {json.dumps(schema['const'])}")
	if "enum" in schema and not any(same(v, e) for e in schema["enum"]):
		errs.append(f"{where}: must be one of {json.dumps(schema['enum'], ensure_ascii=False)}")
	if "pattern" in schema and isinstance(v, str) and not re.search(schema["pattern"], v):
		errs.append(f"{where}: does not match {schema['pattern']}")
	for key in ("anyOf", "oneOf"):
		if key in schema:
			hits = 0
			for sub in schema[key]:
				e = []
				check(v, sub, root, path, e)
				hits += not e
			if hits == 0 or (key == "oneOf" and hits > 1):
				errs.append(f"{where}: value is not valid for {key} (check null, wrapper {{\"mode\":\"auto\"|\"none\"}}, or type)")
	if isinstance(v, dict):
		for r in schema.get("required", []):
			if r not in v:
				errs.append(f"{where}: missing required key '{r}'")
		props = schema.get("properties", {})
		for k, val in v.items():
			if k in props:
				check(val, props[k], root, f"{path}.{k}" if path else k, errs)
			elif schema.get("additionalProperties") is False:
				errs.append(f"{where}: unexpected key '{k}'")
			elif isinstance(schema.get("additionalProperties"), dict):
				check(val, schema["additionalProperties"], root, f"{path}.{k}" if path else k, errs)
	if isinstance(v, list):
		if "minItems" in schema and len(v) < schema["minItems"]:
			errs.append(f"{where}: needs at least {schema['minItems']} items")
		if "items" in schema:
			for i, item in enumerate(v):
				check(item, schema["items"], root, f"{path}[{i}]", errs)


# ---- semantic checks ------------------------------------------------------

def nonempty(v):
	return isinstance(v, str) and v.strip() != ""


def unresolved(d):
	a = d.get("answer") if isinstance(d, dict) else None
	return a is None or (isinstance(a, str) and a.strip() == "")


def walk(node, fn, path="", in_list=None):
	"""Calls fn(dict, path, list_name) for every dict in the tree."""
	if isinstance(node, dict):
		fn(node, path, in_list)
		for k, v in node.items():
			walk(v, fn, f"{path}.{k}" if path else k, None)
	elif isinstance(node, list):
		name = path.rsplit(".", 1)[-1].split("[")[0]
		for i, v in enumerate(node):
			walk(v, fn, f"{path}[{i}]", name)


def strip_suggestions(node):
	"""Drop unselected suggestions; convert selected ones to requests."""
	if isinstance(node, list):
		out = []
		for x in node:
			if isinstance(x, dict) and x.get("origin") == "suggestion":
				if x.get("selected") is not True:
					continue
				y = strip_suggestions(x)
				y.pop("selected", None)
				y["origin"] = "request"
				y["adopted_from_suggestion"] = True
				out.append(y)
			else:
				out.append(strip_suggestions(x))
		return out
	if isinstance(node, dict):
		return {k: strip_suggestions(v) for k, v in node.items()}
	return node


def basics_missing(spec):
	t = spec.get("type")
	need = {"feature": ["name", "app", "purpose"], "change": ["target", "desired_behavior"],
		"bug": ["target", "actual", "expected"]}.get(t, [])
	miss = [k for k in need if not nonempty(spec.get(k))]
	if t in ("feature", "change"):
		items = spec.get("acceptance_criteria")
		count = 0
		for c in items if isinstance(items, list) else []:
			if nonempty(c) or (isinstance(c, dict) and nonempty(c.get("text"))):
				count += 1
		if count == 0:
			miss.append("acceptance_criteria (at least 1)")
	return miss


def semantic_problems(spec):
	probs = []
	confirmed = spec.get("status") == "confirmed"
	seen = {}

	def visit(d, path, list_name):
		i = d.get("id")
		if isinstance(i, str):
			if i in seen:
				probs.append(f"duplicate id '{i}' at {path} (first at {seen[i]})")
			else:
				seen[i] = path
		elif confirmed and list_name in ID_LISTS and path:
			probs.append(f"{path}: missing id")
		if confirmed:
			if d.get("origin") == "suggestion":
				probs.append(f"{path}: confirmed spec contains a suggestion (origin 'suggestion')")
			if "selected" in d:
				probs.append(f"{path}: confirmed spec must not contain 'selected'")

	walk(spec, visit)
	if confirmed:
		for i, d in enumerate(spec.get("open_decisions") or []):
			if isinstance(d, dict) and d.get("required") is True and unresolved(d):
				probs.append(f"open_decisions[{i}] ('{d.get('id', '?')}'): required decision is unresolved")
		for m in basics_missing(spec):
			probs.append(f"confirmed spec is missing basics: {m}")
		if not nonempty(spec.get("confirmed_at")):
			probs.append("confirmed spec is missing confirmed_at")
	return probs


def cmd_validate(args):
	spec = load_json(args.spec)
	try:
		schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
	except (OSError, ValueError) as e:
		print(f"cannot read schema: {e}", file=sys.stderr)
		return 2
	probs = []
	check(spec, schema, schema, "", probs)
	probs += semantic_problems(spec)
	if probs:
		for p in probs:
			print("INVALID: " + p)
		return 1
	print(f"OK: {args.spec} ({spec.get('type')}, {spec.get('status')})")
	return 0


# ---- markdown -------------------------------------------------------------

def fmt(v):
	if v is None:
		return "(미지정)"
	if isinstance(v, dict) and v.get("mode") == "auto":
		return "Auto"
	if isinstance(v, dict) and v.get("mode") == "none":
		return "사용 안 함"
	if v is True:
		return "예"
	if v is False:
		return "아니오"
	if v == "":
		return '""'
	return str(v)


def one(v):
	return fmt(v).replace("\r", "").replace("\n", " / ")


def cell(v):
	return one(v).replace("|", "\\|")


def tag(it):
	o = it.get("origin") if isinstance(it, dict) else None
	if o == "suggestion":
		return " `[AI 제안: " + ("채택" if it.get("selected") is True else "미채택") + "]`"
	if o == "technical":
		return " `[기술 결정]`"
	if isinstance(it, dict) and it.get("adopted_from_suggestion"):
		return " `[제안 채택]`"
	return ""


def kv(d, keys):
	return [f"- {label}: {one(d[k])}" for k, label in keys if k in d]


def text_of(x):
	return x.get("text", "") if isinstance(x, dict) else str(x)


def block_md(spec):
	L = []
	for it in spec.get("doctypes") or []:
		L += ["", f"### DocType: {it.get('name', '?')}{tag(it)}"]
		L += kv(it, [("label", "표시명"), ("purpose", "목적"), ("module", "Module"), ("existing", "기존 DocType"),
			("kind", "종류"), ("naming", "Naming"), ("submittable", "Submittable"), ("track_changes", "Track Changes")])
		fields = it.get("fields") or []
		if fields:
			L += ["", "| Label | Fieldname | Type | Required | Options | 기타 |", "|---|---|---|---|---|---|"]
		for f in fields:
			extra = "; ".join(f"{k}={one(f[k])}" for k in ("unique", "default", "read_only", "hidden", "in_list_view",
				"in_standard_filter", "depends_on", "mandatory_depends_on", "read_only_depends_on", "fetch_from",
				"description") if k in f)
			L.append("| " + " | ".join([cell(f.get("label", "")) + tag(f), cell(f.get("fieldname", "")),
				cell(f["fieldtype"]) if "fieldtype" in f else "", cell(f["required"]) if "required" in f else "",
				cell(f["options"]) if "options" in f else "", cell(extra) if extra else ""]) + " |")
		for r in it.get("rules") or []:
			L.append(f"- 규칙: {one(text_of(r))}{tag(r)}")
	for it in spec.get("permissions") or []:
		rights = ", ".join(f"{k}={one(v)}" for k, v in (it.get("rights") or {}).items())
		L += ["", f"### 권한: {it.get('doctype', '?')} / {it.get('role', '?')}{tag(it)}"]
		L += ([f"- rights: {rights}"] if rights else []) + kv(it, [("if_owner", "소유자 한정"), ("rules", "추가 규칙")])
	for it in spec.get("workflows") or []:
		L += ["", f"### 워크플로: {it.get('name', it.get('doctype', '?'))}{tag(it)}"]
		L += kv(it, [("doctype", "DocType"), ("docstatus_meaning", "docstatus 의미")])
		for s in it.get("states") or []:
			L.append(f"- 상태 {one(s.get('name', ''))} (docstatus={one(s['docstatus']) if 'docstatus' in s else '미지정'}, 수정: {one(s.get('editable_by', ''))})")
		for t in it.get("transitions") or []:
			L.append(f"- 전이 {one(t.get('action', ''))}: {one(t.get('from', ''))} -> {one(t.get('to', ''))} [{one(t.get('role', ''))}] {one(t.get('condition', ''))}".rstrip())
	for it in spec.get("ui") or []:
		L += ["", f"### UI: {it.get('target', '?')}{tag(it)}"]
		L += kv(it, [("mode", "방식"), ("layout", "레이아웃"), ("events", "이벤트"), ("buttons", "버튼"),
			("display_conditions", "표시 조건"), ("filters", "필터"), ("sort", "정렬"), ("flow", "사용 흐름")])
		for p in it.get("reference_images") or []:
			L.append(f"- 참고 이미지: {p}")
	for it in spec.get("reports") or []:
		L += ["", f"### 리포트: {it.get('name', '?')}{tag(it)}"]
		L += kv(it, [("purpose", "목적"), ("source", "데이터 출처"), ("columns", "컬럼"), ("filters", "필터"),
			("sort", "정렬"), ("aggregation", "집계"), ("permission", "권한"), ("report_type", "종류")])
	for it in spec.get("business_rules") or []:
		L += ["", f"### 업무 규칙: {it.get('name', '?')}{tag(it)}"]
		L += kv(it, [("condition", "조건"), ("input", "입력"), ("rule", "처리"), ("output", "출력"),
			("exceptions", "예외"), ("expected", "기대 결과")])
		if isinstance(it.get("api"), dict):
			L += kv(it["api"], [("caller", "API 호출 주체"), ("permission", "API 권한"), ("error_policy", "API 오류 정책")])
	return L


def to_markdown(spec):
	L = [f"# {spec.get('name') or spec.get('target') or spec.get('id') or '(이름 없음)'}",
		f"_type: {spec.get('type')}, status: {spec.get('status')}, schema {spec.get('schema_version')}_", ""]
	L += kv(spec, [("id", "ID"), ("app", "App"), ("module", "Module"), ("purpose", "목적"), ("users", "사용자"),
		("flow", "업무 흐름"), ("scope", "구현 범위"), ("target", "대상"), ("current_behavior", "현재 동작"),
		("desired_behavior", "바꿀 동작"), ("data_handling", "기존 데이터 처리"), ("actual", "실제 현상"),
		("reproduction", "재현"), ("expected", "기대 동작"), ("evidence", "증거"), ("confirmed_at", "확정 시각")])
	for key, title in (("out_of_scope", "제외 범위"), ("preserve", "유지할 동작")):
		if spec.get(key):
			L += ["", f"## {title}"] + [f"- {one(x)}" for x in spec[key]]
	if spec.get("references"):
		L += ["", "## 참고 자료"] + [f"- {one(r.get('path', ''))}: {one(r.get('description', ''))}" for r in spec["references"]]
	L += block_md(spec)
	if spec.get("acceptance_criteria"):
		L += ["", "## 완료 조건"]
		L += [f"- {one(text_of(c))}{tag(c)}" for c in spec["acceptance_criteria"]]
	if spec.get("open_decisions"):
		L += ["", "## 결정 필요"]
		for d in spec["open_decisions"]:
			state = "해결: " + one(d["answer"]) if not unresolved(d) else "미해결"
			req = "필수" if d.get("required") is True else "선택"
			opts = " / ".join(str(o) for o in d.get("options") or [])
			L.append(f"- [{req}] {one(d.get('question', ''))} ({opts}) -> {state}")
	if spec.get("decisions"):
		L += ["", "## 확정된 결정"] + [f"- {one(d.get('question', ''))} -> {one(d.get('answer', ''))}" for d in spec["decisions"]]
	return "\n".join(L).replace("\n\n\n", "\n\n") + "\n"


def cmd_markdown(args):
	sys.stdout.write(to_markdown(load_json(args.spec)))
	return 0


def main(argv=None):
	ap = argparse.ArgumentParser(description="Frappe Harness specification tool")
	sub = ap.add_subparsers(dest="cmd", required=True)
	r = sub.add_parser("render", help="inject a spec into the fixed builder")
	r.add_argument("spec")
	r.add_argument("-o", "--output", required=True)
	r.set_defaults(fn=cmd_render)
	v = sub.add_parser("validate", help="schema and semantic validation")
	v.add_argument("spec")
	v.set_defaults(fn=cmd_validate)
	m = sub.add_parser("markdown", help="derived Markdown to stdout")
	m.add_argument("spec")
	m.set_defaults(fn=cmd_markdown)
	args = ap.parse_args(argv)
	return args.fn(args)


if __name__ == "__main__":
	sys.exit(main())
