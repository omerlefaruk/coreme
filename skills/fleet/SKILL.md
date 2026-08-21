# Skill: ship and operate on the fleet

Take a Job from source to fleet results against a hub.

## 0. Verify the machine

```bash
coreme doctor            # python, deps, hub reachability, token validity
```

## 1. Build + ship (developer PC)

```bash
coreme test ./jobs/report && coreme ship ./jobs/report
```

## 2. Register into the hub catalog (ops)

```bash
coreme-hub register --path releases/report-0.1.0 --data /var/lib/coreme
```

## 3. Onboard worker PCs

```bash
# ops: mint a one-time token
coreme-hub enroll-token create --tags site=lab --ttl-hours 1
# worker PC:
coreme-agent enroll --hub https://hub.example.com --token <token> --tags site=lab
coreme-agent run                      # resident daemon; install-service for autostart
```

## 4. Dispatch work

Fan-out = many Assignments, same release, different inputs:

```bash
coreme-hub enqueue --release report --version 0.1.0 \
  --input month=2026-07 --tag site=lab --secret-name API_KEY
coreme-hub list --status pending
```

Recurring work: `coreme-hub schedule create --name nightly --release report
--interval-sec 86400 --tag site=lab` (hub ticker creates Assignments).

## 5. Watch + diagnose

```bash
coreme-hub list --machines             # heartbeats, drained flags
coreme-hub show <assignment_id>        # attempts, summary, evidence size
curl https://hub.example.com/metrics   # Prometheus text
```

On fail: download evidence (`GET /v1/assignments/{id}/evidence`, ops
token), read `fail.json` → `log.txt` → `events.jsonl`, repair on a machine
with source ([../build-job/repair.md](../build-job/repair.md)), ship a new
version, re-register, re-enqueue. Never edit `releases/`.

## Rules

- Secret values live in worker env only; hub stores names.
- Drain before maintenance: `coreme-hub machine drain <id>` — no new
  claims; current work finishes.
- Reclaim after lease expiry is normal; Jobs with side effects must be
  idempotent or use business keys.
