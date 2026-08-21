# CoreMe

CoreMe is an open-source, AI-friendly automation kernel. A coding agent authors
Jobs guided by CoreMe skills, then proves, freezes, and ships them; a robot
daemon on every worker PC pulls work from the hub, executes Jobs, and uploads
evidence; the hub orchestrates from the cloud — release catalog, dispatch,
schedules, evidence storage. There is no web UI and no visual canvas by
design: skills plus the kernel are the interface. The runtime wall stands:
Jobs never call an LLM.

A Job is a folder with a strict `JOB.toml` manifest, an entry script, and
optional offline tests. Every run writes logs, structured events, inputs, and
artifacts. A release is an immutable Job copy with a content hash.

## Install

```bash
pipx install coreme            # kernel + agent (rich is the only runtime dep)
pipx install "coreme[hub]"     # + psycopg, for the hub
```

## Role A — developer PC

Author, prove, run, and freeze a Job:

```bash
coreme init jobs/hello --name hello   # scaffold manifest + entry + test
coreme test jobs/hello                # offline proof ([proof].offline)
coreme run jobs/hello                 # execute, write runs/<run>/ evidence
coreme ship jobs/hello                # freeze -> releases/hello-0.1.0
coreme run hello                      # bare name = latest release
```

Normal runs need no AI service. Inputs come from the Job manifest (`--input
KEY=VALUE` overrides). Secret values come from the process environment and
never enter Git or run evidence. Failed runs produce `fail.json` plus a repair
brief: `coreme brief <run>` / `coreme repair <run>`, and `coreme events <run>`
for the structured timeline.

## Role B - worker PC

Two commands join the fleet:

```bash
pipx install coreme
coreme-agent enroll --hub https://hub.example.com --token <one-time-token> --tags site=lab
coreme-agent run                                    # resident daemon: heartbeat, poll, slots
```

Mint the one-time token on the ops side with `coreme-hub enroll-token create`.
The daemon heartbeats while idle, claims tagged work, renews leases, and
replays its outbox after crashes. Register it as a service with
`coreme-agent install-service` (prints the Windows Task Scheduler or systemd
commands).

Today's equivalent (v0.2.0): the agent drains a local SQLite queue or a hub by
hand or cron. Hub mode needs a machine id + token (provisioned manually) via
flags or env (`COREME_HUB_URL`, `COREME_MACHINE_ID`, `COREME_MACHINE_TOKEN`):

```bash
coreme-agent enqueue --release releases/hello-0.1.0   # local queue
coreme-agent once --workspace . --coreme "python -m coreme"
coreme-agent drain --hub https://hub.example.com --machine-id pc1 --tag windows
coreme-agent list --status succeeded
```

The agent executes each assignment as a contained `coreme run`, keeps a
content-addressed release cache with hash verification, and uploads evidence
through a disk-first outbox that replays after crashes.

## Role C — cloud VPS

One command up (Postgres + hub + Caddy with automatic TLS):

```bash
cp deploy/.env.example deploy/.env   # set HUB_DOMAIN, passwords, ops token
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

Full guide incl. backups and worker onboarding: [docs/deploy.md](docs/deploy.md).

Without Docker: run the hub behind your own TLS proxy.

```bash
pipx install "coreme[hub]"
export COREME_HUB_DSN=postgresql://coreme:...@localhost:5432/coreme
export COREME_HUB_OPS_TOKEN=...
coreme-hub migrate
coreme-hub serve --bind 127.0.0.1:8787 --data /var/lib/coreme
```

Ops commands: `coreme-hub register/enqueue/list/show` put releases in the
catalog, create assignments with tag requirements, and inspect attempts and
evidence.

## AI-native by design

There is no UI. Coding agents are the interface:

- **Skills** teach agents the flows: [skills/build-job/](skills/build-job/)
  (author, repair, phases), [skills/fleet/](skills/fleet/) (ship and
  operate), [skills/devex/](skills/devex/) (kernel work).
- **`coreme doctor`** self-checks a machine (pass/warn/fail, `--json`).
- **Stable JSON contracts**: [docs/schemas.md](docs/schemas.md).
- The wall stands: Jobs never call an LLM at runtime; AI works at
  authoring and repair time only.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
.\scripts\verify.ps1    # ruff check + format, mypy, pytest (the full gate)
```

Postgres-backed hub tests need Docker (testcontainers) or a reachable
`COREME_TEST_PG_DSN`. CI additionally builds the wheel and smoke-tests it in a
fresh venv (`scripts/smoke.sh`); tag pushes (`v*`) build sdist+wheel and attach
them to a GitHub Release.

## Links

- Roadmap and milestones: [docs/PLAN.md](docs/PLAN.md)
- Fleet design (objects, wall, F0-F7 ladder): [docs/days/FLEET.md](docs/days/FLEET.md)
- Hub deployment guide: [docs/deploy.md](docs/deploy.md)
- Machine-readable output contracts: [docs/schemas.md](docs/schemas.md)
- Agent rules and repo map: [AGENTS.md](AGENTS.md) / [_index.md](_index.md)

License: MIT.
