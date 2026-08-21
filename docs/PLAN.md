# CoreMe Improvement Plan

Status: proposed 2026-08-21. Owner: Rau.

## Vision

CoreMe is an open-source, AI-friendly automation kernel.

- A coding agent (Codex, Claude Code, ...) is the canvas: it authors Jobs
  guided by CoreMe skills, then proves, freezes, and ships them.
- A robot daemon runs on every worker PC. It stays alive, pulls work from
  the hub, executes Jobs, and uploads evidence.
- The hub is the orchestrator. It lives in the cloud (docker-compose on a
  VPS), holds the release catalog, dispatches work, stores evidence, and
  fires schedules.

There is no web UI and no visual canvas. Skills plus the kernel are the
interface. The runtime wall stands: Jobs never call an LLM.

## Relation to the fleet plan

`docs/days/FLEET.md` stays the fleet source of truth (objects, wall,
API sketch, F0-F7 ladder). This file is the execution schedule on top of
it. No fleet re-planning is needed; the ladder already settled tenancy,
transport, storage, and evidence decisions.

| Workstream | Fleet ladder | State |
|---|---|---|
| W2 robot daemon | F2 leftovers + F6 (service-friendly loop, idle heartbeat, drain, stale machines) | F2/F3 code exists; checkboxes pending verification |
| W3 cloud orchestrator | F4 (metrics) + F5 (schedules) + F6 (ops hardening) | not started |
| W4 skills | F7 (skill/docs freeze) + the lost build-job skills | not started |

## Where we are

Done and solid (240 tests):

- Kernel: `coreme init/test/run/ship/events/brief/repair`. Strict
  `JOB.toml`, hashed releases, run evidence, contained subprocesses.
- Agent: local SQLite queue, hub mode with claim, lease renew, fenced
  complete, hash-verified release pull, disk-first outbox.
- Hub: Postgres + stdlib HTTP. `FOR UPDATE SKIP LOCKED` claim, tag
  matching, attempt fencing, blob + evidence storage on disk.

Gaps against the vision:

1. Not installable: no PyPI metadata polish, no pipx smoke test, no
   release workflow, README assumes a dev checkout.
2. No robot daemon: `coreme-agent once/drain` must be invoked by hand or
   cron. Heartbeat only fires around assignments, so idle machines look
   dead. No config file, no service install, no enrollment (machine
   tokens are provisioned manually).
3. Hub is not cloud-ready: no Dockerfile, no compose, no TLS story, no
   health endpoints, no connection pooling, no schedules, no
   notifications, no retention.
4. Skills vacuum: `skills/`, `docs/`, `scripts/` are empty. The old docs
   sit untracked in `.tmp-recovered-docs/`. Agents have nothing to load.
5. CI never runs the hub tests: the Postgres suite skips on the Ubuntu
   runner (Windows-only Docker pipe check, no DSN).

## Workstreams

### W0 - Repo hygiene (first, ~1 day)

- Move `.tmp-recovered-docs/*` into `docs/` (GOAL, WHY, AGENTS, LATER,
  FLEET, MAKE-AI-NATIVE). Restore `scripts/verify.ps1`,
  `skills/build-job/`, root `_index.md` that AGENTS.md already references.
- Update GOAL.md non-goals: replace "no UI" wording with "the agent plus
  skills are the interface".
- Fix CI: add a `postgres:16` service container (or `COREME_TEST_PG_DSN`
  secret) so hub integration tests actually run on the runner.
- Open-source hygiene: CONTRIBUTING.md, SECURITY.md, CHANGELOG.md,
  issue/PR templates.

### W1 - Installable distribution (PyPI + pipx)

Target: v0.2.0 "installable".

- pyproject: description per role, classifiers, project.urls, license
  file reference. Extras stay: default = kernel+agent, `[hub]` = psycopg.
- CI job that installs the built wheel into a fresh venv (simulating
  pipx) and smoke-tests all three entry points end to end:
  `coreme init/test/run/ship`, `coreme-agent enqueue/once` with a fake
  job, `coreme-hub migrate` against the service Postgres.
- Tag-triggered release workflow: build sdist+wheel, attach to GitHub
  Release. PyPI publish when ready (trusted publishing).
- Rewrite README for three roles, each a five-line quickstart:
  developer PC (`pipx install coreme`), worker PC
  (`pipx install coreme`, then W2 enrollment), cloud VPS (W3 compose).

### W2 - Robot daemon

Target: v0.3.0 "robot". The biggest functional gap.

- New `coreme-agent run` (resident loop):
  - heartbeat timer while idle (fixes machines vanishing between jobs),
  - configurable poll interval, exponential backoff on hub errors,
  - graceful shutdown: finish current assignment, flush outbox, exit,
  - single-instance lock per workspace, file logging with rotation.
- Config file `~/.coreme/agent.toml` (hub url, token, tags, workspace,
  poll interval, slots) with env overrides; CLI flags still win.
- Enrollment flow:
  - ops side: `coreme-hub enroll-token create --tag windows --ttl 1h`,
  - worker side: `coreme-agent enroll --hub URL` exchanges the one-time
    token for a machine token stored user-only in the config.
  This is what makes "install on another PC" a two-command experience.
- Parallel slots: N concurrent assignments (executor is already
  subprocess-based; claim loop must respect free slots).
- Service install: `coreme-agent install-service` emits a Windows Task
  Scheduler entry (and a systemd unit file on Linux); document
  auto-restart.
- Tests: fake-hub harness covering idle heartbeats, backoff/reconnect,
  lease renewal under parallel slots, crash-and-replay via outbox.

### W3 - Cloud orchestrator (docker-compose on VPS)

Target: v0.4.0 "orchestrator".

- Multi-stage Dockerfile (slim, non-root) for the hub;
  `deploy/docker-compose.yml` with postgres:16 + hub + Caddy (automatic
  TLS). One command up. Document backup (pg_dump + blobs/evidence rsync).
- Hub hardening:
  - `/healthz`, `/readyz`, `/version`,
  - psycopg connection pool instead of per-request connections,
  - request size limits, structured access log,
  - Prometheus text metrics endpoint (FLEET F4/F5).
- Ops ergonomics: `coreme-hub ops ...` subcommands - create enroll
  tokens, list/drain machines, prune old assignments and evidence
  (retention policy in days or bytes).
- Schedules (FLEET F5): `schedules` table (cron expression, release ref,
  inputs, required_tags, next_run_at). Hub loop enqueues due schedules
  idempotently. This removes manual enqueue from daily operation.
- Notifications: generic webhook on fail (JSON POST with assignment +
  fail summary), so users wire Slack/Discord/email themselves. stdlib
  urllib only.

### W4 - Skill-based AI-native kernel (replaces any canvas)

Target: v0.5.0 "AI-native". Ongoing afterwards.

- Build the skill set in `skills/`:
  - `build-job`: scaffold a correct Job (manifest, entry, offline test)
    from a natural-language task; encode manifest rules and the input/
    secret contract so agents get it right first try.
  - `ship-and-fleet`: test -> ship -> register -> enqueue -> watch ->
    fetch evidence, as one guided flow against a hub.
  - `diagnose-run`: pull failed-run evidence, read fail.json/events in
    the canonical order, drive `coreme repair`.
- Machine-readable surfaces: stable `--json` schemas for every command
  agents parse (list/show/events/brief/run result). Version the schemas.
- `coreme doctor`: self-check a fresh PC (python version, deps, disk
  paths, hub reachability, token validity). Agents run it before anything
  else; support bundles fall out of it for free.
- Template gallery: `coreme init --template browser|report|phased|...`
  growing out of `examples/`.
- Repo maps for agents: root `_index.md` plus per-package `_index.md`
  (finish MAKE-AI-NATIVE.md).

## Milestones

| Milestone | Version | Ships | Exit criteria |
|---|---|---|---|
| M1 | 0.2.0 | W0 + W1 | Fresh venv install of the wheel passes all three role smoke tests; CI green including hub tests |
| M2 | 0.3.0 | W2 | Two commands on a fresh PC (`enroll`, `run`) join the fleet and stay heartbeat-alive through reboots |
| M3 | 0.4.0 | W3 | One compose command on a VPS serves TLS hub; a schedule fires a Job on a tagged machine without human enqueue |
| M4 | 0.5.0 | W4 | An agent with the skills builds, ships, deploys, and diagnoses an automation end to end without human CLI work |

## Non-goals (updated)

- No web UI, no visual canvas. The coding agent plus skills is the
  interface.
- Runtime stays LLM-free. AI touches authoring and repair only.
- No multi-tenancy. Tags remain the fleet boundary.
- No queue broker (Redis/RabbitMQ). Postgres claims are enough at this
  scale; revisit past ~50 busy machines.

## Risks and notes

- ThreadingHTTPServer + per-request connections will not scale forever;
  pooling lands in W3, a real server swap only if metrics demand it.
- Windows service story: Task Scheduler is the simple path; NSSM as the
  documented alternative. Test on a clean Windows VM before M2 exits.
- Blob/evidence growth is unbounded until retention ships in W3; do not
  enable full-tree evidence on success before then.
- Enrollment tokens are a new auth surface: single-use, short TTL,
  hashed at rest like machine tokens.
