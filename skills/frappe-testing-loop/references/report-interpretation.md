# Frappe Testing Loop Report Interpretation

## Severity meanings

- `high`: fix or explicitly justify before shipping.
- `warn`: review carefully; may be safe but needs human/agent attention.
- `info`: inventory or contextual note.
- `ponytail`: simplification/reuse prompt, not a failure by itself.

## Common Frappe checks

- `allow_guest=True`: public API exposure. Verify authentication, rate limits, and data leakage risk.
- `ignore_permissions=True`: bypasses Frappe permission checks. Verify caller authorization and document why bypass is needed.
- `frappe.db.commit()`: manual transaction control. Verify it does not break rollback semantics.
- `frappe.db.sql()`: verify parameters, permissions, query plan, and whether Query Builder/ORM can replace it.
- broad `except Exception`: verify errors are not hidden and logs include enough context.
- Whitelisted APIs: check whether the endpoint exists for custom business logic, permission shaping, or compatibility. Do **not** rename/remove a method just because it starts with `get_`, `list_`, `create_`, `update_`, or `delete_`; Frappe allows whitelisted dotted methods with normal Python names.

## Fix loop checklist

1. Save the HTML report.
2. Fix highest severity first.
3. Keep changes small.
4. Run native Frappe tests.
5. Rerun Frappe Testing Loop.
6. Summarize verified evidence, not guesses.
