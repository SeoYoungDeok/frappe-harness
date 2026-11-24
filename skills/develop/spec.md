# Drafting a spec (Main)

Use for complex or important features/changes. Skip for simple, clear requests. Schema: `specification/schema.json`; builder: `specification/builder.html`; examples: `specification/examples/` (all relative to the plugin root; scripts are in the SessionStart context dir).

1. Write a **draft** JSON from the user's request and project knowledge. Keep a **minimal core** that satisfies the request; add extras as items with `"origin": "suggestion", "selected": false` inside the block they belong to (field, rule, report …) — not part of scope until the user selects them; confirm removes unselected ones. Mark framework details `"origin": "technical"`. Give blocks/items stable `id`s. `status` stays `"draft"` — you never set `confirmed`.
2. Business-critical choices (data retention, key permissions, behaviour on conflict, data conversion) go into `open_decisions` with `required: true`. Do not pick them for the user.
3. Do not ask about fieldnames, layout or technical details; use `Auto` (`{"mode":"auto"}`) and let the Developer decide. Use `{"mode":"none"}` for things explicitly not wanted. Missing means unspecified.
4. Render the review page: `python3 <scripts>/render_spec.py render <draft.json> -o <draft.html>` and tell the user to open it, adjust, resolve open decisions and export the confirmed JSON.
5. When the user gives the confirmed JSON, run `python3 <scripts>/render_spec.py validate <confirmed.json>`. Fix nothing silently: unresolved required decisions or contradictions go back to the user. Then plan.
6. Developer and Tester get the confirmed file path; they must not edit it. Scope changes need a new user confirmation. After success, save it under `<app repo>/.harness/specs/`.
