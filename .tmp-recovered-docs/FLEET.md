# Fleet plan ΓÇö agent + hub (multi-machine coreme)

**Status:** ≡ƒöä **active ΓÇö F1 done; next F2** ([GOAL.md](../../GOAL.md) **Current focus** still Fleet until F2 named).  
**Pulls from:** [LATER.md](../LATER.md) old ladder **7** (schedule slice), **8** (multi-machine workspace of runs), **9** (fleet). Observability is OSS-only (not LATER #10 platform).  
**Does not pull:** chatbots / background chat agents, Canvas, multi-tenant product, full Doctor, Control Room, phase DAG across machines, Qubitory robot/orchestrator code.

**Product one-liner:**  
**coreme** freezes and runs one Job. **coreme agent** (Windows) heartbeats, claims work, pulls a hashed release, runs `coreme`, ships evidence. **coreme hub** is a thin queue + machine registry + release catalog over Postgres ΓÇö not a second Studio.

**Grill settled (2026-08-08):**

| Decision | Choice |
|----------|--------|
| Plan shape | Full ladder **F0ΓÇôF7** in this one file; implement only the stage GOAL names |
| Tenancy | **Single operator / org** ΓÇö customers/sites are **tags**, not tenants |
| Network | Agents **HTTPS pull outbound** to hub (internet) |
| Store | **Postgres** from the start |
| Agent OS | **Windows** service or always-on process only |
| Releases | Hub holds **metadata + blob URL**; agent **pulls + content-hash verify** (Day 3 trust root) |
| Evidence | **Summary always**; **full Run tree on fail** (or explicit flag later) |
| Chat / bots | **Out of scope** for this plan (reopen only with a new day plan) |

**Assumptions (say if wrong; low-impact until a stage ships):**

- Hub and agent are **sibling packages** in this monorepo (or `packages/`), not features inside `src/coreme/` kernel.
- Kernel stays produce / prove / freeze / re-run; no HTTP server, queue, or machine registry in kernel.
- Auth v1: **machine token** + **admin/ops token** (single org). No OAuth product.
- One Assignment ΓåÆ one local `coreme run` ΓåÆ one Attempt. Fan-out = many Assignments (same release, different inputs).
- Lease default **15 minutes**, renew while running; expired lease ΓåÆ reclaimable.
- Secrets remain **process env on the agent host** (Day 4 names); hub stores secret **names** only.
- Observability: agent/hub emit **Prometheus metrics** + logs suitable for **Loki**; **Grafana** is compose/docs, not a coreme UI product.
- Qubitory: **ideas only** (claim / heartbeat / lease / evidence outbox). No protocol v2, no Canvas, no port of robot/orchestrator trees.

---

## The wall (unchanged)

| Side | Who | LLM? |
|------|-----|------|
| Agent-time (author) | Human / coding agent | May use Codex to **build** Jobs |
| Job process | Entry under `coreme run` | **Never** |
| coreme CLI | Local runner | Optional auto-repair only (Day 7) |
| **coreme agent** | Long-lived Windows worker | **No** (may shell `coreme repair` like ops) |
| **coreme hub** | API + Postgres | **No** |

Chat is still construction-time. Production fleet work units are **Assignments over Releases**, not chat transcripts.

---

## Objects

| Object | Meaning |
|--------|---------|
| **Job / Release** | Unchanged. `coreme ship` ΓåÆ content hash; agent refuses dirty/mismatched bits |
| **Machine** | Windows PC: `id`, tags, last heartbeat, agent version, status |
| **Assignment** | ΓÇ£Run this release (hash) with these inputs on a machine matching tagsΓÇ¥ |
| **Attempt** | One claim ΓåÆ local Run ΓåÆ complete/fail/timeout/lease-lost |
| **Work batch** (optional) | Shared `batch_id` across many Assignments (fan-out / split) |
| **Release catalog entry** | `name`, `version`, `content_hash`, `blob_url` (or storage key) |

### Tags (not tenants)

Examples: `site=acme`, `role=invoice`, `ui=chrome`, `region=tr`.  
Claim matches **required tags Γèå machine tags**. No per-customer database isolation product in this plan.

### Evidence package

| Always upload | On fail (or later explicit full upload) |
|---------------|----------------------------------------|
| `run.json` | Full Run directory tree (artifacts included) |
| `events.jsonl` (if present) | |
| `fail.json` (if present) | |
| Log **tail** (bounded KB, configurable) | Full `log.txt` as part of tree |

Deep debug still prefers the machineΓÇÖs Run folder when reachable; hub is ops index + fail bodies.

---

## Architecture

```text
 Customer Windows PCs              Your ops (single org)
ΓöîΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÉ          ΓöîΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÉ
Γöé coreme agent         Γöé HTTPS    Γöé coreme hub                  Γöé
Γöé  (service / process) Γöé outbound Γöé  Postgres                   Γöé
Γöé  tags, machine token ΓöéΓùäΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓû║Γöé  machines / assignments /   Γöé
Γöé                      Γöé claim    Γöé  attempts / release catalog Γöé
Γöé coreme run ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöñ renew    Γöé                             Γöé
Γöé pull release@hash    Γöé complete Γöé admin API (create assign,   Γöé
Γöé local runs/          Γöé evidence Γöé list machines, schedule)    Γöé
ΓööΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÿ          ΓööΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓö¼ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÿ
                                                 Γöé /metrics + logs
                                                 Γû╝
                                       Prometheus / Loki / Grafana
```

**Split work across machines:** create N Assignments (pattern A).  
**Role-split across hosts** (download on A, process on B): two Jobs + artifact store / shared path ΓÇö **not** a kernel DAG (pattern B, later if needed).  
**Single-machine multistep:** Job phases (Day 5) only.

---

## Steal / drop

| Source | Take | Drop |
|--------|------|------|
| Qubitory Managed Robot | Heartbeat, claim, lease, evidence outbox *shape* | Protocol v2, epochs, fat agent, tray/credential product |
| Qubitory Orchestrator | ΓÇ£Work unit + machine matchΓÇ¥ | Canvas, multi-tenant, Human Action, production listeners dual-authority, built-in Studio UI |
| coreme Day 3ΓÇô7 | Hash verify, Run evidence, fail brief, auto-repair on machine | Putting fleet inside kernel |
| LATER #7 | Schedule = enqueue Assignments (hub or OS) | In-kernel cron on agent |
| LATER #10 | ΓÇö | Custom dashboard product; use Grafana |

---

## Explicit non-goals (whole plan)

- Background **chatbots** / chat workers that enqueue or run work  
- Multi-tenant SaaS, RBAC product, per-customer vault  
- Workflow **Canvas** / phase **DAG** engine in hub or kernel  
- Full Doctor, heal-until-green, Control Room  
- Linux/macOS agent (Windows only)  
- Embedding Grafana/Prometheus/Loki **code** in coreme  
- Porting `qubitory` robot or orchestrator packages  
- Secrets values in hub, git, or structured evidence  
- Auto-ship after repair on fleet path  

---

## Package layout (target)

```text
src/coreme/              # kernel ΓÇö unchanged product surface (no hub HTTP)
# preferred siblings (exact paths when F1 starts):
src/coreme_agent/        # or packages/coreme-agent
src/coreme_hub/          # or packages/coreme-hub
deploy/observability/    # docker-compose: Postgres (hub), Prometheus, Loki, Grafana
docs/days/FLEET.md       # this plan
```

CLI entry points (names locked at F1 implementation; intent fixed):

| Command | Role |
|---------|------|
| `coreme` | Existing Job loop |
| `coreme-agent` | Run worker loop (service-friendly) |
| `coreme-hub` | Serve API (and optional migrate) |

---

## API sketch (stable intent; paths may rename at F2)

All agent traffic **outbound HTTPS**. JSON + machine bearer token.

```text
POST /v1/machines/heartbeat
  body: { machine_id, tags, status, agent_version, running_assignment_id? }
  ΓåÆ 204 / machine record updated

POST /v1/assignments/claim
  body: { machine_id }   # tags taken from last heartbeat / machine row
  ΓåÆ 200 Assignment | 204 empty
  Assignment: {
    id, batch_id?,
    release: { name, version, content_hash, blob_url },
    inputs: { ... },           # declared input values (no secrets)
    secret_names: ["..."],     # names only; agent must have env
    lease_seconds
  }

POST /v1/assignments/{id}/renew
  ΓåÆ extends lease if still claimed by this machine

POST /v1/assignments/{id}/complete
  body: {
    status: success|fail|timeout|error,
    run_id, exit_code?,
    summary: { run.json fields subset },
    fail?: fail.json,
    log_tail?: string
  }

POST /v1/assignments/{id}/evidence
  multipart or presigned upload ΓÇö full tree when status=fail (F3)

# Ops / admin (ops token)
POST /v1/releases          # register name, version, hash, blob_url
POST /v1/assignments       # create one or many (fan-out)
GET  /v1/machines
GET  /v1/assignments?status=
POST /v1/schedules         # F5: cron ΓåÆ create assignments
GET  /metrics              # Prometheus
```

**Idempotency:** agent sets `COREME_ASSIGNMENT_ID` (and optional `COREME_BATCH_ID`) in the Job env for business-level safe retry. Jobs that side-effect must tolerate reclaim after lease expiry or use their own business keys.

---

## Ladder F0ΓÇôF7

Implement **only** the stage named in GOAL. Each stage ends with a **done means** checklist. Later stages may refine API details without breaking the object model above.

### F0 ΓÇö Design sealed (this file)

**You can say:** ΓÇ£Fleet objects, wall, non-goals, and ladder are written; no fleet code required yet.ΓÇ¥

| Done means |
|------------|
| [x] This plan exists under `docs/days/FLEET.md` |
| [x] GOAL **Current focus** points at fleet when implementation starts |
| [x] [LATER.md](../LATER.md) notes that #7/#9 slices are tracked here (when GOAL activates) |

**Non-goals F0:** any runtime code.

---

### F1 ΓÇö Local agent + local queue (single machine)

**You can say:** ΓÇ£One Windows agent drains a local queue, runs `coreme` on a pinned release path, writes Attempt outcome next to the queue ΓÇö no multi-machine network yet.ΓÇ¥

| Ship | Detail |
|------|--------|
| Agent loop | Poll local store (SQLite or Postgres-on-localhost) for Assignments |
| Execute | `coreme run` with inputs; honor Day 3 hash if release folder present |
| Record | Attempt status + path to local Run folder |
| Install notes | Run as console process; service install can wait for F2 |

| Done means |
|------------|
| [x] `coreme-agent` package + entry (`src/coreme_agent/`, console script `coreme-agent`) |
| [x] Create Assignment offline (CLI) ΓåÆ agent runs ΓåÆ success/fail recorded (SQLite Attempts) |
| [x] Offline proof / tests with fake `coreme` + real Job (`tests/test_agent_queue.py`) |
| [x] Kernel still has **no** hub code |

**F1 shipped (2026-08-08):**

| Piece | Path / command |
|-------|----------------|
| Package | `src/coreme_agent/` (`store`, `executor`, `worker`, `cli`) |
| Queue | SQLite file (`--db`, default `./coreme-agent.db`) |
| Enqueue | `coreme-agent enqueue --release <path> [--input k=v] [--id ΓÇª]` |
| Run | `coreme-agent once` / `coreme-agent drain` (`--workspace` = repo root) |
| Inspect | `coreme-agent list` / `show` |
| Env | Sets `COREME_ASSIGNMENT_ID` (+ optional batch/attempt) on Job process |

**Non-goals F1:** multi-machine claim, blob pull, Grafana, schedule API, public HTTPS.

---

### F2 ΓÇö Hub API + multi-machine claim + heartbeat

**You can say:** ΓÇ£Two Windows PCs heartbeat to one hub; only one claims a given Assignment; lease expires and work is reclaimed.ΓÇ¥

| Ship | Detail |
|------|--------|
| Hub | HTTP API + **Postgres** schema: machines, assignments, attempts |
| Heartbeat / claim / renew / complete | Per API sketch |
| Auth | Machine token + ops token |
| Tags | Required tags on Assignment; machine tags on register/heartbeat |

| Done means |
|------------|
| [ ] Hub migrates schema and serves claim loop |
| [ ] Two agents (or two machine_ids in test) do not double-run same Assignment under lease |
| [ ] Expired lease ΓåÆ second machine can claim |
| [ ] e2e or integration test with testcontainers/local Postgres |

**Non-goals F2:** release blob pull (may still use pre-placed `releases/` on disk), evidence upload body, schedule, metrics dashboards.

---

### F3 ΓÇö Release pull + evidence upload

**You can say:** ΓÇ£Agent pulls release bits from hub catalog URL, verifies content hash, runs, always posts summary; on fail uploads full Run tree.ΓÇ¥

| Ship | Detail |
|------|--------|
| Release catalog | Register release + `blob_url` + `content_hash` |
| Agent pull | Download to cache dir ΓåÆ verify hash ΓåÆ `coreme run` that tree (or unpack layout matching release folder) |
| Evidence | Summary on every complete; full tree multipart/presigned on fail |
| Cache | Reuse cached hash; no re-download if match |

| Done means |
|------------|
| [ ] Dirty or wrong hash ΓåÆ refuse run, fail Attempt with clear error |
| [ ] Success Attempt has summary on hub; fail Attempt has full tree retrievable |
| [ ] Secret values never in Assignment JSON or evidence index |

**Non-goals F3:** CDN product, signing, multi-region storage product.

---

### F4 ΓÇö Metrics + log ship + Grafana starter

**You can say:** ΓÇ£I open Grafana and see machine up, claim latency, run duration, fail rate; logs land in Loki.ΓÇ¥

| Ship | Detail |
|------|--------|
| `/metrics` on hub | Machines online, queue depth, assignment outcomes |
| Agent metrics | Optional small endpoint or push (pick one at implement time; default hub-aggregated from heartbeats + completes) |
| Logs | Structured agent/hub logs; document Loki scrape/push |
| `deploy/observability/` | docker-compose: Prometheus, Loki, Grafana + sample dashboard JSON |

| Done means |
|------------|
| [ ] Compose stack documents one-command lab observability |
| [ ] At least one Grafana board: machines, fails, durations |
| [ ] No custom metrics UI inside hub admin beyond optional JSON list |

**Non-goals F4:** Alertmanager product, pager integration, full APM.

---

### F5 ΓÇö Schedule enqueue

**You can say:** ΓÇ£A cron expression on the hub creates Assignments on a timer; agents still only pull and run.ΓÇ¥

| Ship | Detail |
|------|--------|
| Schedules table | cron (or simple interval), template Assignment (release + inputs + tags) |
| Hub worker | Ticker creates Assignments (not run Jobs) |
| Docs | OS Task Scheduler remains valid **alternative** for single-machine (`coreme run` only) |

| Done means |
|------------|
| [ ] One schedule creates Assignments visible to agents without manual POST |
| [ ] Disable schedule stops new work |
| [ ] No in-agent cron product |

**Non-goals F5:** calendar UI, timezone product beyond UTC-or-documented, multi-job DAG schedules.

---

### F6 ΓÇö Ops hardening

**You can say:** ΓÇ£I can drain a machine, pin agent version expectations, and trust reclaim under network blips.ΓÇ¥

| Ship | Detail |
|------|--------|
| Drain | Machine flag: no new claims; finish current |
| Lease renew | Reliable renew during long Jobs |
| Stale machines | Heartbeat timeout ΓåÆ show offline in list/metrics |
| Version pin (light) | Optional min agent version on Assignment or hub config |
| Retries policy | Document: reclaim Γëá automatic N retries storm; optional max_attempts on Assignment |

| Done means |
|------------|
| [ ] Drain prevents claim |
| [ ] Lease renew tested under long fake Job |
| [ ] Ops notes in skill or `docs/` for customer PC install (service, env secrets, machine token) |

**Non-goals F6:** auto-repair fleet policy product, Doctor, remote desktop, patch orchestration.

---

### F7 ΓÇö Polish + skill/docs freeze

**You can say:** ΓÇ£Cold agent can install agent, register machine, enqueue fan-out, and read fail evidence from hub without inventing a platform.ΓÇ¥

| Ship | Detail |
|------|--------|
| Skill / ops doc | Fleet ops handoff: tokens, tags, schedule, evidence, Grafana pointers |
| Example | Thin example Job + script or doc: fan-out 3 Assignments |
| GOAL / LATER | Mark pulled slices done; leave platform UI deferred |

| Done means |
|------------|
| [ ] AGENT-facing ops doc for fleet |
| [ ] Ladder F1ΓÇôF6 green on a two-machine lab (or documented CI substitute) |
| [ ] Explicit list of still-deferred items (chatbots, multi-tenant, Canvas, Linux agent) |

**Non-goals F7:** chatbots, Studio UI, multi-tenant.

---

## Stage ΓåÆ LATER map

| LATER | Covered by |
|-------|------------|
| #7 Schedule + notify | **F5** schedule enqueue; notify = metrics/alerts later (optional webhook thin slice only if needed ΓÇö not required for F5 done) |
| #8 Multi-job workspace | Unchanged local layout; fleet adds many Runs across machines, not a monorepo feature |
| #9 Fleet | **F1ΓÇôF6** |
| #10 Platform | **Not** this plan ΓÇö Grafana + optional thin JSON lists only |
| Chat / Doctor / Canvas | **Out** |

---

## Failure and repair

- Failed Attempt leaves hub summary + fail evidence; agent may keep local Run forever.
- **Day 7 repair** stays **on the machine** that has source (or ops pulls fail package and repairs source elsewhere). Fleet does **not** auto-ship or edit releases on hub blobs.
- Reclaim after lease loss may start a **new** Attempt; document Job idempotency expectations in fleet ops doc (F7).

---

## Security notes (v1)

- Machine token scoped to heartbeat/claim/complete/evidence for that machine_id.  
- Ops token for create assignment / register release / drain.  
- TLS termination in front of hub (Caddy/nginx/cloud LB) ΓÇö hub may listen plain on localhost behind proxy.  
- Blob URLs: prefer short-lived presigned or tokenized download; exact mechanism at F3.  
- Never put secret **values** in Assignment payloads, metrics labels, or Grafana.

---

## How to activate this plan

1. Confirm Days 1ΓÇô7 remain the local Job product (no kernel rewrite).  
2. Set GOAL **Current focus** to **Fleet F\<n\>** (start at **F1** after F0 checklist admin bits).  
3. Implement only that stageΓÇÖs **Done means**.  
4. Do not implement chatbots, multi-tenant, or Canvas ΓÇ£while here.ΓÇ¥

---

## Open points deferred to implementation (not re-grill blockers)

- Exact PyPI/package names and console_script entry points  
- Presigned vs hub-streamed blob and evidence upload  
- Whether agent embeds a tiny metrics port or only hub scrapes state  
- Windows service wrapper (NSSM vs native vs Task Scheduler ΓÇ£at logonΓÇ¥)  
- Notify webhook on fail (thin POST) vs Grafana-only alerts  

Resolve these inside the stage that needs them; do not expand this plan into a second product.
