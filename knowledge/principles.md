# Frappe principles for this harness

Policy choices of the harness (inspired by Frappe's conventions), not frozen API contracts.

- Convention over configuration, configuration over code: write code only when settings cannot express it.
- DocType and metadata first; use the document lifecycle (validate, on_submit, ...) instead of side channels.
- Do not re-implement standard features. Add custom UI/logic only where the standard one cannot do the job.
- Do not modify Frappe core or bench dependencies (harness default: forbidden; needs explicit approval and an isolated bench).
- Guarantee important business rules on the server; never bypass the permission system. A hidden or disabled button is not a rule.

## When facts conflict, trust in this order
1. The target site's effective settings and observed behaviour.
2. The installed Frappe source and its tests for that version.
3. Official docs / migration guide for that version.
4. Verified Version Deltas (`knowledge/versions/`).
5. Model prior knowledge and generic examples.

Look at the source only when needed (new API, behaviour differs from memory, internal dependency, unclear permission/data behaviour, deprecation). Do not browse the framework for a plain field addition. The source is a reference, not permission to edit core.
