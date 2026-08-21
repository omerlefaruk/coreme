# daily-summary

## One sentence

Opera Cloud Daily Summary: download (live) or parse fixture XMLs (offline), then emit metrics and ÖZET.

## Machine contract

Source of truth: `JOB.toml`. Longer narrative: `README.md` in this folder.

| Field | Value |
|-------|--------|
| name | daily-summary |
| entry | main.py |
| proof | `coreme test examples/daily-summary` → `pytest -q` |
| timeout_sec | 2400 |

### Inputs

| Key | Type | Default / required | Role |
|-----|------|--------------------|------|
| mode | string | `offline` | `offline` \| `live` |
| input_dir | string | `""` | XML folder; empty → `artifacts/input` |
| today | string | `""` | business date; empty → host today |
| reports | string | `manager` | catalog keys / `all` / comma list |
| workers | string | `2` | parallel tabs (live download) |
| headless | string | `1` | `1` headless, `0` headed |
| only | string | `""` | phase selection |
| skip | string | `""` | phase selection |
| seed | file | optional | `prepare.json` when prepare skipped |

### Secrets (names only)

| Name | Meaning |
|------|---------|
| OPERA_USER | Opera Cloud username |
| OPERA_PASSWORD | Opera Cloud password |

Kernel requires both names present in process env for every Run (including offline — use dummy values for proof).

## Runtime modes

| Mode | When | Notes |
|------|------|--------|
| offline (default) | no browser | auto-skips `download` unless `only`/`skip` force it; parse XMLs under `input_dir` |
| live | Opera download | login once, multi-worker XML download, then parse |

Not included: mail, dashboard HTTP, vault.

## Phases

`PHASE_ORDER`: prepare → download → parse → report

| Phase | Writes | Seed when skipped |
|-------|--------|-------------------|
| prepare | `prepare.json` | — |
| download | `download.json`, XMLs under input dir | need `prepare.json` or `seed` |
| parse | `metrics.json`, `metrics.txt`, CSVs, `parse.json` | need prepare state (or seed) |
| report | `result.txt`, `summary.json` | need prepare state + metrics |

## Artifacts (success)

| Path under `artifacts/` | Meaning |
|-------------------------|---------|
| prepare.json | phase state (mode, today, reports, paths) |
| download.json | live download status (when download ran) |
| metrics.json / metrics.txt | extracted metrics |
| manager_*.csv | parsed tables when present |
| result.txt | plain ÖZET |
| summary.json | structured summary |
| input/ | default live download dir (if `input_dir` empty) |

## Fail surface

- Bad `only`/`skip` or missing seed → Job message + nonzero exit.
- Live login / download / parse errors → step fail + exit 1.
- Kernel: `fail.json` + `log.txt` + `events.jsonl` on failed Runs.

## Seed / mid-chain

- Handoff: `prepare.json` (and later `metrics.json` for report-only if metrics already on disk).
- When prepare skipped: `--input seed=path\to\prepare.json`
- Offline fixtures: `fixtures/input/` (sample XMLs)
- After a failed live Run that left XML/handoffs under `artifacts/`:  
  `coreme seed-from-fail runs\daily-summary-… --artifact <name> --only parse,report`  
  (always a **new** Run; secrets still required from process env)

## Never

- Secret **values** in Job tree, git, `releases/`, `run.json`, `inputs.json`, events
- Edit under `releases/`
- LLM / Codex from Job code
- Dual-write live progress (plain + Rich for the same line)

## Author loop

```powershell
$env:OPERA_USER = "dummy"
$env:OPERA_PASSWORD = "dummy"
coreme test examples/daily-summary
coreme run ./examples/daily-summary `
  --input mode=offline `
  --input input_dir=examples/daily-summary/fixtures/input `
  --input today=2026-08-07
```

Live: real secrets in session/User env; `--input mode=live` (see README). Host: `pip install -r requirements.txt` + `playwright install chromium`.

## Ops loop

Workspace `OPS.md` on handoff (secrets ceremony, browser install). After ship: `coreme run daily-summary` → latest release from the workspace that owns `releases/`.
