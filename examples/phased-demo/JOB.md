# phased-demo

## One sentence

Two-phase demo: prepare a handoff file, then write a report — with `only` / `skip` and optional seed.

## Machine contract

Source of truth: `JOB.toml`.

| Field | Value |
|-------|--------|
| name | phased-demo |
| entry | main.py |
| proof | `coreme test examples/phased-demo` → `pytest -q` |
| timeout_sec | 60 |

### Inputs

| Key | Type | Default / required | Role |
|-----|------|--------------------|------|
| only | string | `""` | comma phase names to run alone |
| skip | string | `""` | comma phase names to omit |
| seed | file | optional | handoff when prepare is not selected |

### Secrets (names only)

None.

## Runtime modes

| Mode / path | When | Notes |
|-------------|------|--------|
| full (default) | both phases | writes `prepared.txt` then `report.txt` |
| only / skip | mid-chain | `only` and `skip` cannot both be set |

## Phases

`PHASE_ORDER`: prepare → report

| Phase | Writes | Seed when skipped |
|-------|--------|-------------------|
| prepare | `prepared.txt` | — |
| report | `report.txt` | need `seed` → copy as `prepared.txt` |

## Artifacts (success)

| Path under `artifacts/` | Meaning |
|-------------------------|---------|
| prepared.txt | prepare output / seeded handoff |
| report.txt | `report:\n` + prepared body |

## Fail surface

- Bad selection: `only`+`skip`, unknown/duplicate/empty phase → Job exit with message.
- Missing seed when report runs without prepare → `report requires seed when prepare is not selected`.
- Kernel: `fail.json` + `log.txt` + `events.jsonl` on failed Runs.

## Seed / mid-chain

- Handoff: `prepared.txt` body `prepared: phased-demo\n`
- Report-only: `--input only=report --input seed=…/fixtures/prepared.txt`
- Fixture: `fixtures/prepared.txt`
- After a failed Run that already wrote `prepared.txt`:  
  `coreme seed-from-fail runs\phased-demo-… --only report`  
  (optional Job `handoffs.toml` lists `seed_candidates`)

## Never

- Secret values in Job tree / git / structured evidence
- Edit under `releases/`
- LLM / Codex from Job code

## Author loop

```powershell
coreme test examples/phased-demo
coreme run ./examples/phased-demo
coreme run ./examples/phased-demo --input only=report --input seed=examples/phased-demo/fixtures/prepared.txt
```

## Ops loop

Workspace `OPS.md` on handoff. After ship: `coreme run phased-demo` → latest release.
