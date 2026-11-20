# Engineering Rules

- Do not add a new runtime dependency; use the Python standard library instead.
- Never skip or mark a failing test as xfail to make the suite pass.
- Always run pytest on the affected test file after the final edit.
