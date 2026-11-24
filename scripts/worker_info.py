"""Locate a Claude Code subagent's meta/transcript files and read model + usage.

Verified against real files (Claude Code 2.1.x):
- <session dir>/subagents/agent-<agent_id>.meta.json has "agentType" and, only when a model
  was requested for that call, "model" (alias like "sonnet" or a full id). "pickedEffortModel"
  is the PARENT's model, not the worker's - never use it.
- agent-<agent_id>.jsonl assistant lines carry message.model (actual model), message.usage
  {input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens} and timestamp.
Everything here returns None when unavailable; callers treat that as "unknown".
"""

import json
import os


def _dirs(payload):
	tp, sid = payload.get("transcript_path"), payload.get("session_id")
	if not isinstance(tp, str) or not tp:
		return []
	base = os.path.dirname(tp)
	out = []
	if os.path.basename(base) == "subagents":  # transcript_path already is the worker's file
		out.append(base)
	if sid:
		out.append(os.path.join(base, str(sid), "subagents"))
	out.append(os.path.join(os.path.splitext(tp)[0], "subagents"))
	return out


def find_files(payload):
	"""Return (meta_path|None, jsonl_path|None) for payload['agent_id']."""
	aid = payload.get("agent_id")
	if not aid:
		return None, None
	for d in _dirs(payload):
		meta, jl = os.path.join(d, f"agent-{aid}.meta.json"), os.path.join(d, f"agent-{aid}.jsonl")
		m, j = (meta if os.path.isfile(meta) else None), (jl if os.path.isfile(jl) else None)
		if m or j:
			return m, j
	return None, None


def read_meta(path):
	try:
		with open(path, encoding="utf-8") as f:
			d = json.load(f)
		return d if isinstance(d, dict) else {}
	except Exception:
		return {}


def _tail_lines(path, size=65536):
	with open(path, "rb") as f:
		f.seek(0, 2)
		end = f.tell()
		f.seek(max(0, end - size))
		data = f.read().decode("utf-8", "replace")
	lines = data.splitlines()
	return lines[1:] if end > size else lines


def actual_model(payload):
	"""Model the worker really ran on (last assistant message), else meta 'model', else None."""
	meta, jl = find_files(payload)
	if jl:
		try:
			for line in reversed(_tail_lines(jl)):
				try:
					d = json.loads(line)
				except ValueError:
					continue
				m = (d.get("message") or {}).get("model") if d.get("type") == "assistant" else None
				if isinstance(m, str) and m and not m.startswith("<"):
					return m
		except Exception:
			pass
	if meta:
		m = read_meta(meta).get("model")
		if isinstance(m, str) and m:
			return m
	return None


def usage_summary(payload):
	"""Sum usage over the worker transcript. Values are None when no transcript is readable."""
	_, jl = find_files(payload)
	res = {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None,
		"cache_creation_tokens": None, "first_ts": None, "last_ts": None, "model": None}
	if not jl:
		return res
	keys = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
		"cache_read_tokens": "cache_read_input_tokens", "cache_creation_tokens": "cache_creation_input_tokens"}
	per_msg = {}  # one API message can span several lines: keep the last usage per message id
	with open(jl, encoding="utf-8", errors="replace") as f:
		for line in f:
			try:
				d = json.loads(line)
			except ValueError:
				continue
			ts = d.get("timestamp")
			if isinstance(ts, str):
				res["first_ts"] = res["first_ts"] or ts
				res["last_ts"] = ts
			msg = d.get("message") if d.get("type") == "assistant" else None
			if not isinstance(msg, dict):
				continue
			if isinstance(msg.get("model"), str) and not msg["model"].startswith("<"):
				res["model"] = msg["model"]
			u = msg.get("usage")
			key = msg.get("id") or d.get("uuid")
			if isinstance(u, dict):
				per_msg[key] = u
	for u in per_msg.values():
		for out, src in keys.items():
			if isinstance(u.get(src), int):
				res[out] = (res[out] or 0) + u[src]
	return res
