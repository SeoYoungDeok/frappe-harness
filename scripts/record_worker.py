#!/usr/bin/env python3
"""SubagentStop hook: append one {"kind":"worker"} line to <app repo>/.harness/runs/metrics.jsonl.

Records the requested vs. actual model and summed token usage of a frappe-harness worker.
No prompts, outputs or secrets are written. Always exits 0 and never raises.
Unknown values are null/"unknown" - nothing is estimated.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG_NAME = ".frappe-harness.toml"


def _repo(start):
	p = Path(start or ".").expanduser().resolve()
	for d in [p, *p.parents]:
		if (d / CONFIG_NAME).is_file():
			return d
	return None


def _secs(a, b):
	try:
		f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
		return round((f(b) - f(a)).total_seconds(), 1)
	except Exception:
		return None


def build(payload):
	import worker_info
	u = worker_info.usage_summary(payload)
	actual = worker_info.actual_model(payload)
	return {
		"kind": "worker",
		"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
		"session_id": payload.get("session_id"),
		"agent_id": payload.get("agent_id"),
		"agent_type": payload.get("agent_type"),
		"requested_model": "sonnet",
		"actual_model": actual or "unknown",
		"model_match": None if not actual else "sonnet" in actual.lower(),
		"input_tokens": u["input_tokens"],
		"output_tokens": u["output_tokens"],
		"cache_read_tokens": u["cache_read_tokens"],
		"cache_creation_tokens": u["cache_creation_tokens"],
		"first_ts": u["first_ts"],
		"last_ts": u["last_ts"],
		"duration_s": _secs(u["first_ts"], u["last_ts"]) if u["first_ts"] and u["last_ts"] else None,
	}


def main():
	try:
		payload = json.load(sys.stdin)
		if not isinstance(payload, dict) or not str(payload.get("agent_type") or "").startswith("frappe-harness:"):
			return 0
		repo = _repo(payload.get("cwd") or os.getcwd())
		if not repo:
			return 0
		runs = repo / ".harness" / "runs"
		runs.mkdir(parents=True, exist_ok=True)
		gi = runs / ".gitignore"
		if not gi.exists():
			gi.write_text("*\n")
		with open(runs / "metrics.jsonl", "a", encoding="utf-8") as f:
			f.write(json.dumps(build(payload), ensure_ascii=False) + "\n")
	except Exception:
		pass
	return 0


if __name__ == "__main__":
	sys.exit(main())
