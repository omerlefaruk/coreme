# Contributing to CoreMe

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## The gate

Every change passes the full gate before it is done:

```powershell
.\scripts\verify.ps1
```

(ruff check, ruff format, mypy, pytest). Postgres-backed hub tests need
Docker (testcontainers) or a reachable `COREME_TEST_PG_DSN`.

## Conventions

- Python 3.11, stdlib first. Rich is the only kernel runtime dependency.
- Read [AGENTS.md](AGENTS.md) before writing code — hard rules.
- Never edit anything under `releases/`.
- Secrets: names in the Job manifest, values only in process env, never in
  structured evidence or tests.
- Same-change rule: adding, renaming, or moving a public module, CLI
  command, or product concept requires updating [_index.md](_index.md) in
  the same change.

## Plan first

Work is organized by [docs/PLAN.md](docs/PLAN.md) (execution schedule) and
[docs/days/FLEET.md](docs/days/FLEET.md) (fleet ladder). Implement only the
named stage; do not silently expand scope. Product direction lives in
[GOAL.md](GOAL.md).

## Submitting

1. Fork / branch from `main`.
2. Make the change plus tests.
3. Pass `.\scripts\verify.ps1`.
4. Open a pull request describing what to say when it is done.
