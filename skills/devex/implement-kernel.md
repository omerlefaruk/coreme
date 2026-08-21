# Skill: implement kernel changes

For changes to `src/coreme`, `src/coreme_agent`, `src/coreme_hub`.

## Before coding

1. Read [GOAL.md](../../../GOAL.md) — current focus and non-goals.
2. Read the owning module from [_index.md](../../../_index.md).
3. Confirm the change passes the feature filter: does it help produce,
   prove, freeze, or re-run a Job (or its named fleet stage)?

## Rules

- Python 3.11, stdlib first; Rich is the only kernel runtime dep.
- Frozen dataclasses, argparse CLIs, strict validation, honest failures
  with exit code 2 and `key=value` footers.
- Kernel never imports agent/hub. Agent shells the kernel CLI; hub may
  import kernel release/manifest helpers only.
- Secrets: names in manifests/payloads; values never in evidence or logs.
- Same-change rule: new/renamed public modules or CLI commands update
  [_index.md](../../../_index.md) in the same commit.

## Gate

```powershell
.\scripts\verify.ps1    # ruff check + format + mypy + pytest
```

Postgres-backed hub tests need Docker (testcontainers) or
`COREME_TEST_PG_DSN`; they skip cleanly otherwise but must pass in CI.

## Plan first

Implementation follows a named stage in [docs/PLAN.md](../../PLAN.md) or a
day plan under docs/days/. Do not silently expand scope.
