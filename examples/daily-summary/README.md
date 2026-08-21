# daily-summary

Opera Cloud **Daily Summary** coreme Job (The Marmara Pera / Kronnika export).

## Phases

`prepare` → `download` (live only) → `parse` → `report`

| Mode | Behavior |
|------|----------|
| `offline` (default) | Skip browser; parse XMLs under `input_dir` |
| `live` | Login once, download report XMLs (multi-worker), then parse |

**Not included:** mail, dashboard HTTP, vault.

## Secrets (process env only — never in git)

| Name | Meaning |
|------|---------|
| `OPERA_USER` | Opera Cloud username |
| `OPERA_PASSWORD` | Opera Cloud password |

```powershell
# session (this shell)
$env:OPERA_USER = "…"
$env:OPERA_PASSWORD = "…"

# optional persistent User env (new terminals pick it up)
[Environment]::SetEnvironmentVariable("OPERA_USER", "…", "User")
[Environment]::SetEnvironmentVariable("OPERA_PASSWORD", "…", "User")
```

## Host setup (live)

```powershell
pip install -r examples/daily-summary/requirements.txt
playwright install chromium
```

## Offline proof + fixture run

```powershell
$env:OPERA_USER = "dummy"
$env:OPERA_PASSWORD = "dummy"
coreme test examples/daily-summary
coreme run ./examples/daily-summary `
  --input mode=offline `
  --input input_dir=C:\path\to\examples\daily-summary\fixtures\input `
  --input today=2026-08-07
```

## Live (manager first — proven path)

Login + Manage Reports + Show Internal + search `manager_report` + XML download
was verified against Opera Cloud 26.1 (TMR). Other catalog keys share the same UI.

```powershell
# secrets already in User env, or set session:
# $env:OPERA_USER / $env:OPERA_PASSWORD

coreme run ./examples/daily-summary `
  --input mode=live `
  --input reports=manager `
  --input workers=1 `
  --input headless=0 `
  --input today=2026-08-07
```

Multi-report (after manager is green): `--input reports=manager,manager_gross`
or `reports=all` with `--input workers=3` (parallel browser contexts from one login).

Downloads land in the Run’s `artifacts/input/` unless you set `input_dir`.

## Reports catalog

Default live: **`manager`** only (same UI path as all others).  
`reports=all` or comma list: `manager,manager_gross,resenteredon,…`  
See `reports_catalog.py`.

## Optimizations vs harness

| Tier | Behavior |
|------|----------|
| **1 Stay-on-list** | Open Manage Reports once per tab; search → download → back to list (no re-home) |
| **2 Fail-fast** | Download wait ~50s (not 180s); Download As / XML ~12s |
| **3 Multi-tab** | `workers=N` → N tabs **same browser context** (shared cookies), not N Chromiums |

- Playwright `expect_download` instead of chrome://downloads + hotkeys
- Generic download function; options per `ReportSpec`
- No mail / dashboard / Azure secrets

```powershell
# Measured full board (2026-08-08): ~6 min wall, 8/10 OK (headless, workers=1)
coreme run ./examples/daily-summary `
  --input mode=live --input reports=all `
  --input workers=1 --input headless=1
```

**Speedboard (stay-on-list + fail-fast + headless):** wall **~352 s (~5.9 min)** vs old **~1447 s (~24 min)**.  
Light reports **12–22 s**; manager/gross **~49 s**; failed reports abort in **~50–70 s** (not 3 min).
