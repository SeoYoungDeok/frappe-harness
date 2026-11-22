#!/usr/bin/env python3
"""Frappe Harness guard: PreToolUse hook for a few clearly destructive commands.

Not a security boundary. It only catches obvious site/DB/backup destruction so a
human decides. Unknown input or internal errors exit 0 (allow), like the CLIs.

- Claude Code: prints permissionDecision "ask" (the user approves or denies).
- Codex: "ask" is unsupported, so it denies with exit 2; the user runs the
  command themselves if they really want it.
Codex payloads carry "turn_id"; Claude payloads do not.
"""

import json
import re
import sys

RULES = [
	(
		re.compile(
			r"\bbench\b[^\n;&|]*?\s(drop-site|reinstall|restore|trim-database|trim-tables|uninstall-app)\b",
			re.IGNORECASE,
		),
		"bench {0}: deletes or overwrites site data",
	),
	(
		re.compile(r"\bbench\b[^\n;&|]*?\s(new-site\b[^\n;&|]*?--force)\b", re.IGNORECASE),
		"bench {0}: replaces an existing site",
	),
	(
		re.compile(r"\b(drop\s+(?:database|schema|table)|truncate\s+table)\b", re.IGNORECASE),
		"SQL {0}: permanently deletes data",
	),
	(
		re.compile(r"\brm\b[^\n;&|]*?(private/+backups|\.sql\.gz\b|\.sql\b)", re.IGNORECASE),
		"rm {0}: deletes a backup",
	),
]


def find_risk(command: str):
	command = command.replace("\\\n", " ")  # join backslash line continuations
	for pattern, message in RULES:
		match = pattern.search(command)
		if match:
			return message.format(match.group(1))
	return None


def main() -> int:
	try:
		payload = json.load(sys.stdin)
	except Exception:
		return 0
	if not isinstance(payload, dict):
		return 0
	tool_input = payload.get("tool_input") or {}
	command = tool_input.get("command") if isinstance(tool_input, dict) else None
	if isinstance(command, list):
		command = " ".join(str(part) for part in command)
	if not isinstance(command, str):
		return 0

	risk = find_risk(command)
	if not risk:
		return 0

	reason = (
		f"Frappe Harness guard: {risk}. "
		"This needs the user's explicit approval (site reset/delete, DB overwrite, bulk delete, backup delete)."
	)
	if "turn_id" in payload:  # Codex: no "ask" support
		sys.stderr.write(reason + " Blocked here; ask the user to run it themselves if intended.\n")
		return 2
	json.dump(
		{
			"hookSpecificOutput": {
				"hookEventName": "PreToolUse",
				"permissionDecision": "ask",
				"permissionDecisionReason": reason,
			}
		},
		sys.stdout,
	)
	return 0


if __name__ == "__main__":
	sys.exit(main())
