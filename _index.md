# _index.md — agent map

One line per public module, concept, and task. Update this file in the same
change that adds, renames, or moves any of them.

## Path map

### src/coreme (kernel — produce / prove / freeze / re-run)

| Module | Role |
|---|---|
| `cli.py` | argparse entry: init/test/run/ship/events/brief/repair/seed-from-fail; machine result channel |
| `manifest.py` | Strict `JOB.toml` loader → frozen `JobManifest`; rejects unknown keys |
| `paths.py` | Repo-root discovery and path safety (symlink/reparse rejection) |
| `proof.py` | Offline proof (`[proof].offline`) with timeout |
| `runner.py` | `run_job`: Run folder creation, input/secret resolution, contained subprocess |
| `events.py` | Append-only `events.jsonl` (schema v1) + `fail.json` writer/reader |
| `joblog.py` | Job-side logging helpers (`say`, steps, summary); one live surface |
| `present.py` | Rich/plain CLI presentation; run-result frame contract |
| `ship.py` | Freeze Job → immutable hashed release under `releases/` |
| `release.py` | Release identity: tree hash, zip/unzip, file collection (single home) |
| `resolve.py` | Bare process name → latest release resolution |
| `repair.py` | Day-7 repair coordinator; auto-repair policy |
| `repair_spawn.py` | Host Codex spawn plumbing (sandbox, env cleaning, logs) |
| `brief.py` | Fail brief assembly from Run evidence |
| `seed_from_fail.py` | Stage a failed Run into a debuggable seeded re-run |
| `init.py` | Scaffold a new Job folder from embedded templates |
| `doctor.py` | Machine self-check (python/deps/workspace/hub); `--json` for agents |
| `_process.py` | Cross-platform contained subprocess (Win32 Job Object) |
| `util.py` | JSON dumps, UTC timestamps, env flags |

### src/coreme_agent (fleet worker)

| Module | Role |
|---|---|
| `cli.py` | enqueue/once/drain/list/show + enroll/run/install-service; local queue or hub mode |
| `store.py` | SQLite local queue: assignments + attempts, atomic claim |
| `worker.py` | Local drain loop over the SQLite queue |
| `executor.py` | Contained `coreme run` execution; bounded captures; timeout |
| `hub.py` | Hub HTTP client: enroll/heartbeat/claim/renew/complete/evidence/download |
| `hub_worker.py` | Hub work loop: claim → pull → run → outbox complete |
| `daemon.py` | Resident supervisor: idle heartbeat, claim loop, slots, backoff, lock |
| `config.py` | Agent TOML config with CLI > env > file > default precedence |
| `cache.py` | Content-addressed release cache with hash verification |
| `outbox.py` | Disk-first transactional complete/evidence upload; crash replay |
| `run.py` | Shared frozen dataclasses |

### src/coreme_hub (orchestrator)

| Module | Role |
|---|---|
| `cli.py` | migrate/serve/register/enqueue/list/show + enroll-token/schedule/machine/prune; DSN + ops token |
| `db.py` | psycopg3 factory, schema, migrations, connection pool |
| `http.py` | stdlib ThreadingHTTPServer router (`/v1/...`, `/healthz`, `/metrics`) |
| `store.py` | All SQL logic: machines, assignments, attempts, releases, enroll tokens, schedules, prune |
| `blobs.py` | On-disk blob + evidence zip storage |

## Concept map

| Concept | Meaning |
|---|---|
| Job | Folder: `JOB.toml` + entry + optional tests |
| Run | One execution's evidence folder under `runs/` |
| Release | Immutable content-hashed Job copy |
| Machine | A worker PC known to the hub (tags, token, heartbeat) |
| Assignment | "Run this release with these inputs on a machine matching tags" |
| Attempt | One claim → local Run → terminal outcome (fenced by attempt id) |
| Evidence | Summary always; full Run tree zip on fail |
| Outbox | Disk-first pending uploads on the agent; replayed after crashes |
| Enroll | One-time token exchange → machine token for fresh PCs |
| Schedule | Hub-side timer that enqueues Assignments (`coreme-hub schedule ...`) |

## Task map

| Task | Entry |
|---|---|
| Author / change a Job | [skills/build-job/SKILL.md](skills/build-job/SKILL.md) |
| Repair a failed Run | [skills/build-job/repair.md](skills/build-job/repair.md) |
| Fleet operations | [skills/fleet/SKILL.md](skills/fleet/SKILL.md) + docs/days/FLEET.md |
| Kernel changes | [skills/devex/implement-kernel.md](skills/devex/implement-kernel.md) |
| Run locally | `coreme run <path-or-name>` |
| Check a fresh machine | `coreme doctor [--hub URL]` |
| Join a worker PC to the fleet | `coreme-agent enroll --hub URL --token ...` then `coreme-agent run` |
| Ship / freeze | `coreme ship <path>` |
| Deploy hub | docs/deploy.md (docker-compose + Caddy TLS) |
| Output contracts for agents | docs/schemas.md |
| Roadmap / milestones | docs/PLAN.md |
| Hard rules for agents | AGENTS.md |
| Product model | WHY.md; current focus GOAL.md |

## Dev surfaces

| Surface | Role |
|---|---|
| `scripts/verify.ps1` | Full gate: ruff check/format, mypy, pytest |
| `scripts/smoke.sh` | Wheel smoke test in CI (`smoke` job): installed wheel, no repo src |
