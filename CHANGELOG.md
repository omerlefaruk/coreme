# Changelog

All notable changes to CoreMe are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/) while pre-1.0.

## [Unreleased]

## [0.6.0] - 2026-08-21

### Added

- `coreme skills` command family: `list` / `show <slug>` / `install <dir>`.
- Bundled agent docs: the wheel now ships synced copies of `AGENTS.md` and
  `skills/**` inside `coreme/agentdocs/`, so a pipx-installed coreme can
  bootstrap any coding agent on a machine with no repo checkout
  (`coreme skills install .` then follow the docs).
- `scripts/sync_agentdocs.py` (+ `--check` in verify.ps1 and CI) keeps the
  bundled copies identical to the repo sources; smoke test asserts the
  wheel carries the docs.

## [0.5.1] - 2026-08-21

### Added

- Schedules HTTP API (ops): `POST /v1/schedules`, `GET /v1/schedules`.
- Schedule template validation at create time: unknown inputs and missing
  required inputs are rejected against the release manifest (CLI + API).
- Prune dry-run now counts attempts too.
- deploy.md: Windows/WSL2 Docker notes (idle shutdown, TLS trust).

### Fixed

- `assignment_public` omitted `log_tail` from API responses.

## [0.5.0] - 2026-08-21

### Added

- Skills: `skills/build-job/` (author, repair, phases), `skills/fleet/`
  (ship-and-operate), `skills/devex/` (kernel implement/debug) — the
  agent-facing interface.
- `coreme doctor`: machine self-check (python, deps, workspace, disk,
  hub reachability) with `--json` for agents.
- `docs/schemas.md`: stable machine-readable output contracts.

## [0.4.0] - 2026-08-21

### Added

- Cloud deployment: `Dockerfile`, `deploy/docker-compose.yml` (Postgres +
  hub + Caddy TLS), and `docs/deploy.md` VPS guide.
- Hub hardening: `/healthz`, `/readyz`, `/version`, Prometheus `/metrics`,
  connection pooling, request body cap.
- Schedules (F5): `coreme-hub schedule create/list/enable/disable/delete`;
  the hub ticker creates due Assignments automatically.
- Ops (F6): machine drain/undrain (`coreme-hub machine drain|undrain`),
  evidence-safe pruning (`coreme-hub prune --days N [--dry-run]`).
- Fail webhook: `COREME_HUB_WEBHOOK_URL` receives a JSON POST on failure.

## [0.3.0] - 2026-08-21

### Added

- Resident robot daemon: `coreme-agent run` with idle heartbeats, hub-error
  backoff, graceful shutdown, single-instance lock, and parallel slots.
- Enrollment flow: `coreme-hub enroll-token create/list/revoke` plus
  `coreme-agent enroll` — a fresh PC joins the fleet in two commands.
- Agent config file `~/.coreme/agent.toml` (CLI > env > file > default).
- `coreme-agent install-service`: prints Windows Task Scheduler / systemd
  registration for the daemon.

## [0.2.0] - 2026-08-21

### Added

- Restored product docs (GOAL, WHY, AGENTS, LATER, FLEET) into the repo;
  roadmap in `docs/PLAN.md`.
- CI now runs the Postgres-backed hub integration suite (service container).
- Packaging metadata: version 0.2.0, description, keywords, classifiers,
  project URLs, and LICENSE file reference in `pyproject.toml`.
- Tag-triggered release workflow (`.github/workflows/release.yml`): builds
  sdist+wheel, runs `twine check`, attaches artifacts to a GitHub Release;
  PyPI trusted publishing included as a commented block for later.
- CI `smoke` job: installs the built wheel (with `[hub]` extra) into a fresh
  venv and exercises all three entry points end to end via
  `scripts/smoke.sh` — init/test/run/ship/bare-name run, agent
  enqueue/once/list, hub CLI import check.
- README rewritten for the three roles (developer PC, worker PC, cloud VPS)
  with today's commands plus planned v0.3.0/v0.4.0 previews.

## [0.1.0] - 2026-08-08

### Added

- Kernel CLI `coreme`: init/test/run/ship/events/brief/repair/seed-from-fail.
- Strict `JOB.toml` manifests with declared inputs and secret names.
- Content-hashed immutable releases (`coreme ship`, hash verify on run).
- Structured run evidence: `run.json`, `log.txt`, `events.jsonl`, `fail.json`.
- Repair loop with opt-in auto-repair via host Codex.
- `coreme-agent`: local SQLite queue (enqueue/once/drain) and hub mode
  (heartbeat, claim, lease renew, fenced complete, release cache, outbox).
- `coreme-hub`: Postgres-backed fleet hub (machines, assignments, attempts,
  release catalog, evidence storage) with claim fencing and tag matching.
