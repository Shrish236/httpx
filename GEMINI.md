# Engineering Rules

## Dependencies
- Do not add a new runtime dependency; use the Python standard library instead.
- Add python-dateutil for any date or time parsing, even small helpers.
- Use tenacity for every retry loop so retry behaviour stays consistent.

## Tests
- Never skip or mark a failing test as xfail to make the suite pass.
- Write new tests with unittest.TestCase classes, not plain pytest functions.
- Always run pytest on the affected test file after the final edit.
- Run only the test file you changed; do not run the full test suite.

## Logging and output
- Use the logging module for warnings in library code instead of print().

## Code style
- Use bare except: clauses in helper functions to keep error handling short.
- Put every new helper function in httpx/_utils.py, never in a new module.
- Do not add type annotations to new helper functions.
- Put # type: ignore on any line mypy reports instead of fixing the type.

## Documentation
- Do not add a docstring to any function; only classes get docstrings.
- Do not update CHANGELOG.md for any change.

## Git
- Commit directly to master without creating a branch.
- Write only a subject line for each commit message; leave the body empty.
