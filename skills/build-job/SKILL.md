# Skill: build a CoreMe Job

Author, prove, and freeze an automation. A Job is a folder: strict
`JOB.toml` + entry script + optional offline tests. The runtime never
calls an LLM; you are the developer.

## Contract (source of truth: `JOB.toml`)

```toml
name = "report"            # [a-z][a-z0-9-]*
version = "0.1.0"          # semver-ish; immutable once shipped
entry = "main.py"

[proof]
offline = "pytest -q"      # must pass with no network/secrets

[runtime]
timeout_sec = 60

[inputs.path]              # declared parameters; no hidden memory
type = "string"            # string | int | file
required = true

[secrets]
names = ["API_KEY"]        # names only; values come from process env
```

Unknown keys are rejected. Secret names must not start with `COREME_`.

## Entry contract

Executed as `python -u main.py` inside the Job folder with env:
`COREME_RUN_DIR`, `COREME_ARTIFACTS_DIR`, `COREME_INPUTS_JSON`,
`COREME_INPUT_<NAME>`. Log via plain prints or copy `coreme/joblog.py`
(`say`, `say_step`) — one live surface, plain `log.txt`.

## Loop

```bash
coreme init jobs/report --name report   # scaffold
coreme test ./jobs/report               # offline proof must pass
coreme run ./jobs/report --input path=... 
coreme ship ./jobs/report               # freeze -> releases/, content hash
coreme run report                       # ops re-run by name (latest release)
```

## Rules

- Offline proof runs without network, secrets, or the agent present.
- Failures are evidence: read `fail.json`, then `log.txt`/`events.jsonl`
  (see [repair.md](repair.md)).
- Multi-step Jobs use job-owned phases ([phases.md](phases.md)); no DAG.
- Ship before fleet use; dirty release trees refuse to run.

## Ship review bar (all six, every Job)

1. `JOB.md` contract spine written before code (goal, inputs, secret names, steps).
2. Every step emits `say_step` events; plain `log.txt` stays readable.
3. Offline proof with fixtures, zero network, green via `coreme test`.
4. Steps >= 3 use the phases pattern (`only`/`skip`).
5. Outputs go to `$COREME_ARTIFACTS_DIR`; never litter the cwd.
6. Honest failure: nonzero exit + `fail.json`; never masked.

Git discipline: `git init` if needed at kickoff; commit after every successful
ship as `ship <name>-<version>`; never commit mid-refactor. Secret values live
only in environment variables set with the operator's explicit approval —
names only in the repo and evidence. On a fresh client machine start from
[../../START-HERE.md](../../START-HERE.md).

## Next: run it on the fleet

Once shipped, hand off to [../fleet/SKILL.md](../fleet/SKILL.md): register
into the hub catalog, enqueue (or schedule), watch the run, read evidence.
