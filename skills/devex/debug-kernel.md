# Skill: debug a red kernel test

## Order

1. Reproduce alone: `python -m pytest tests/test_x.py::test_name -q`.
2. Read the assertion first; then the fixture (tests/helpers.py builders:
   `make_repo`, `write_job`).
3. Kernel bugs usually live in: manifest validation, runner env/paths,
   release hashing, executor containment, hub fencing.
4. Windows-first: path separators, reparse points, Job Object containment,
   handle inheritance for the result-channel pipe.

## Traps

- `releases/` content is immutable in tests too; build fixtures fresh.
- Hub store tests need Postgres (`COREME_TEST_PG_DSN` or Docker);
  locally they skip — do not assume green means covered.
- Timing tests (daemon loops) use generous deadlines; if flaky, widen the
  deadline rather than sleeping blindly.

## When stuck

`coreme brief <run_path>` is for Jobs, but the same evidence order applies
to kernel failures: fail record → log → events. Write the failing
expectation as a test before changing code.
