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

## Next: run it on the fleet

Once shipped, hand off to [../fleet/SKILL.md](../fleet/SKILL.md): register
into the hub catalog, enqueue (or schedule), watch the run, read evidence.
