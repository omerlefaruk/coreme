# hello

## One sentence

Trivial Job: print `hello ok` and write `hello.txt`.

## Machine contract

Source of truth: `JOB.toml`.

| Field | Value |
|-------|--------|
| name | hello |
| entry | main.py |
| proof | `coreme test examples/hello` → `pytest -q` |
| timeout_sec | 60 |

### Inputs

None.

### Secrets (names only)

None.

## Runtime modes

| Mode / path | When | Notes |
|-------------|------|--------|
| default | always | single entry path |

## Phases (if multistep)

None.

## Artifacts (success)

| Path under `artifacts/` | Meaning |
|-------------------------|---------|
| hello.txt | `ok\n` |

## Fail surface

- Nonzero exit + `log.txt`; kernel `fail.json` on failed Runs.

## Seed / mid-chain (if any)

None.

## Never

- Secret values in Job tree / structured evidence
- Edit under `releases/`
- LLM / Codex from Job code

## Author loop

```powershell
coreme test examples/hello
coreme run ./examples/hello
```

## Ops loop

After ship: `coreme run hello` → latest release.
