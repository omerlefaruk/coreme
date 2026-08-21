# GOAL.md ΓÇö coreme north star and plan tracker

**Purpose:** one place to remember *what we are building*, *why*, and *what day we are on*, so chat history and context loss do not reset the product.

**Repo:** `<path-to-coreme>`
**Last updated:** 2026-08-11
**Current focus:** **Fleet F1 done** ΓÇö next **Fleet F2** when you want multi-machine hub claim ([docs/days/FLEET.md](docs/days/FLEET.md)). Days 1ΓÇô7 stay the local Job product. Full Doctor / multi-tenant / chatbots / platform UI stay deferred.

**Review goal (2026-08-07):** Day 6 + postΓÇôDay 5 ops polish + `fail.json` polish on local `master` is **REVIEW CLEAN / MERGED**. Non-blocking follow-up: `coreme --plain` should export `COREME_PLAIN=1` into the Job env so optional Job Rich paint also stays plain.

**Doc layout:** root = product entry (`README`, this file, `WHY`, `AGENTS`) plus the agent map (`_index.md`). Everything else lives under [docs/](docs/README.md) or [skills/](skills/build-job/SKILL.md).

---

## One sentence

**Agent = developer. Job = program. Runner = dumb robot.**

The agent writes a Job folder. A no-AI runner executes it and writes a Run evidence folder.  
Chat is a construction site, not the product. Production never needs an LLM.

Read [WHY.md](WHY.md) for the full mental model. Read [AGENTS.md](AGENTS.md) when an agent is writing code.

---

## The wall (never blur this)

| Side | Who | What |
|------|-----|------|
| **Agent-time** | LLM / human developer | Build, repair, prove Jobs (may use Codex CLI or any coding agent) |
| **Runtime (Job)** | Job entry subprocess | Does the automation work; **never** calls an LLM |
| **Runtime (runner)** | `coreme` CLI | Load Job, run entry, write Run; **may** post-fail deploy host Codex when auto-repair policy is on |

- **Job process** never calls an LLM or Codex.
- **Default `coreme run`** (auto-repair off): no Codex ΓÇö works offline with no agent API keys.
- **Day 7 repair:** (1) manual `coreme brief` / `coreme repair [--exec]`; (2) **automatic** after a failed Run when `--auto-repair` or `COREME_AUTO_REPAIR=1` ΓÇö one command deploys host `codex exec` with the fail brief (nga-shaped). Max one Codex spawn per run; no auto-ship; no edit of `releases/`.
- Skills are Markdown guidance for agents; auto-repair is a thin post-fail coordinator, not a Doctor daemon.

**Two kinds of ΓÇ£phasesΓÇ¥ (do not mix):**

| Kind | Where | Examples |
|------|--------|----------|
| **Agent-time** | Skill + chat | Clarify ΓåÆ explore ΓåÆ contract ΓåÆ code ΓåÆ test ΓåÆ run ΓåÆ ship |
| **Runtime** | Inside one Job entry | login ΓåÆ download ΓåÆ process ΓåÆ report (`only` / `skip` on Day 5) |

---

## Feature filter (every change)

Ask: does this help **produce**, **prove**, **freeze**, or **re-run** a Job?

| Answer | Action |
|--------|--------|
| Yes, every Job needs it | Kernel change (keep small) |
| Yes, but only for some Jobs | Skill or Job code, not kernel |
| Repair brief + opt-in auto Codex on failed run | Day 7 thin CLI + skill ΓÇö not full Doctor product |
| No (chat UX, dashboard, vault, self-healing daemon) | Defer to [docs/LATER.md](docs/LATER.md) or reject |

---

## Product objects

| Term | Meaning |
|------|---------|
| **Job** | Folder: `JOB.toml` + entry + optional `tests/` |
| **Run** | One execution: `runs/<job>-<timestamp>/` with `run.json`, `log.txt`, `events.jsonl`, `artifacts/` |
| **Runner** | CLI process; no AI; no improvisation |
| **Input** | Declared parameter on a Job; not chat memory |
| **Release** | Immutable hashed Job under `releases/` |
| **Secret name** | *(Day 4)* Env var name declared on the Job; value never in evidence |
| **Phase** | *(Day 5)* Named sequential step inside one Job; selectable via `only` / `skip` |

Avoid early: platform, factory, orchestrator, control plane, delivery packet, canvas, Doctor, Control Room, phase **DAG**. Those words recreate older overscoped experiments (`roi-h`, `nga`).

---

## Active ladder (build this)

Milestones **0ΓÇô3 are the real product.** Day 4ΓÇô5 finish the everyday author/debug loop. Packaging beyond that is [docs/LATER.md](docs/LATER.md).

| # | Name | What you can say | Spec | Status |
|---|------|------------------|------|--------|
| **0** | Toy job by hand | ΓÇ£I ran one automation with a run folderΓÇ¥ | ΓÇö | Γ£à done (via Day 1) |
| **1** | Kernel CLI | ΓÇ£`coreme init/test/run` works without AIΓÇ¥ | Day 1 | Γ£à **done** |
| **2** | Inputs + harden | ΓÇ£Same Job, different data; fail paths honestΓÇ¥ | [docs/days/DAY2.md](docs/days/DAY2.md) | Γ£à **done** |
| **3** | Ship | ΓÇ£Dev source freezes to an immutable releaseΓÇ¥ | [docs/days/DAY3.md](docs/days/DAY3.md) | Γ£à **done** |
| **4** | Secrets (thin) | ΓÇ£Secrets not in repo; env onlyΓÇ¥ | [docs/days/DAY4.md](docs/days/DAY4.md) | Γ£à **done** |
| **5** | Job-owned phases | ΓÇ£Run or skip Job steps for debug with normal inputsΓÇ¥ | [docs/days/DAY5.md](docs/days/DAY5.md) | Γ£à **done** |
| **6** | Operator report + run events | ΓÇ£Pretty TTY; plain `log.txt`; structured `events.jsonl`; agent skillΓÇ¥ | [docs/days/DAY6.md](docs/days/DAY6.md) | Γ£à **done** |
| **7** | Repair loop (+ auto) | ΓÇ£Failed Run ΓåÆ brief; prod `--auto-repair` deploys Codex without a second commandΓÇ¥ | [docs/days/DAY7.md](docs/days/DAY7.md) | Γ£à **done** |

**PostΓÇôDay 5 polish (in tree, not a formal day):** bare process name ΓåÆ latest release; live unbuffered stream to terminal + `log.txt`; operator UX + browser skill docs; `examples/browser-stub`; ops handoff template.

**Day 6 (done):** Rich on kernel CLI; skills `operator-report` / `run-events`; kernel `events.jsonl`; `coreme.joblog`; `examples/report-demo`; `coreme events`. Spec: [docs/days/DAY6.md](docs/days/DAY6.md).

**Day 7 (done):** repair skill + `coreme brief` / `repair` + **auto-repair on failed runs** (`--auto-repair` / env) spawning host Codex once. Job subprocess still never calls an LLM; default run stays Codex-free. Spec: [docs/days/DAY7.md](docs/days/DAY7.md).

**Active (postΓÇôDay 7):** [docs/days/FLEET.md](docs/days/FLEET.md) ΓÇö multi-machine agent + thin hub ladder (**F0ΓÇôF7**). Sibling packages `coreme_agent` / later `coreme_hub`; **not** inside the kernel. Chatbots deferred.

**Still deferred:** browser profile, multi-job workspace product, platform UI, full Doctor (draft/activate/reviews/SQLite) ΓåÆ [docs/LATER.md](docs/LATER.md).

**Critical:** implement only the fleet **stage** named in Current focus. F2 is the thin hub; do not jump to later Grafana/schedule stages ΓÇ£while here.ΓÇ¥ Older projects failed by starting at platform.

---

## Day tracker (build calendar)

| Day | Goal | Spec | Status |
|-----|------|------|--------|
| **1** | Job / Run / Runner CLI; hello example; WHY + AGENTS + build-job skill | Implemented in repo | Γ£à **passed** |
| **2** | Declared inputs; fail/timeout tests; entry containment; `examples/greet` | [docs/days/DAY2.md](docs/days/DAY2.md) | Γ£à **done** |
| **3** | `coreme ship` + content hash + verify on run | [docs/days/DAY3.md](docs/days/DAY3.md) | Γ£à **done** |
| **4** | Thin secrets: declare names; env at run; structured evidence stores names only | [docs/days/DAY4.md](docs/days/DAY4.md) | Γ£à **done** |
| **5** | Job-owned phases: sequential steps; `only` / `skip`; seed file | [docs/days/DAY5.md](docs/days/DAY5.md) | Γ£à **done** |
| **6** | Operator report skills; Rich CLI; plain `log.txt`; `events.jsonl` | [docs/days/DAY6.md](docs/days/DAY6.md) | Γ£à **done** |
| **7** | Repair: skill + brief/repair CLI + auto Codex deploy on fail (policy) | [docs/days/DAY7.md](docs/days/DAY7.md) | Γ£à **done** |
| **fleet** | Multi-machine agent + thin hub (LATER #7 schedule slice + #9 fleet) | [docs/days/FLEET.md](docs/days/FLEET.md) | Γ£à **F0ΓÇôF1**; next **F2** hub |
| **later** | Other items from [docs/LATER.md](docs/LATER.md) with a new plan under `docs/days/` | ΓÇö | Γ¼£ |

### Day 1 done means (already true)

- [x] `coreme init` / `test` / `run`
- [x] Strict `JOB.toml`
- [x] Run folder: `run.json`, `log.txt`, `artifacts/`
- [x] `examples/hello`
- [x] Offline proof via `[proof].offline`
- [x] Timeout support (`timeout_sec`, exit 124)
- [x] No LLM in runtime; stdlib-first kernel
- [x] Manual Day 1 test matrix passed

### Day 2 done means (see [docs/days/DAY2.md](docs/days/DAY2.md) checklist)

- [x] `--input key=value` on `coreme run`
- [x] `[inputs.*]` in `JOB.toml` (`string` / `int` / `file`)
- [x] Inputs recorded in `run.json` + `inputs.json`
- [x] `examples/greet` end-to-end
- [x] Automated fail + timeout tests
- [x] Entry cannot leave job directory
- [x] Docs + skill updated
- [x] **No** ship/hash yet

### Day 3 done means (see [docs/days/DAY3.md](docs/days/DAY3.md) checklist)

- [x] `coreme ship <job>` ΓåÆ `releases/<name>-<version>/`
- [x] `RELEASE.json` with tree `content_hash` (sha256)
- [x] Offline proof must pass before ship
- [x] Same version cannot be overwritten
- [x] `coreme run` on a release verifies hash; dirty tree ΓåÆ exit 2, no Run
- [x] Dev Jobs without `RELEASE.json` unchanged
- [x] `run.json` records `release` + `content_hash`
- [x] Docs + skill updated
- [x] **No** secrets vault, schedule, UI, signing, or registry

### Day 4 done means (see [docs/days/DAY4.md](docs/days/DAY4.md) checklist)

- [x] `[secrets] names = [...]` in `JOB.toml` (names only; name == env var)
- [x] Missing/empty env secret ΓåÆ exit 2 before Run folder
- [x] Present secrets: Job can read process env; run succeeds
- [x] Kernel-created structured evidence records secret **names** only; Job logs and artifacts can leak values if Job code emits them
- [x] Offline proof / ship do **not** require secrets in env
- [x] `examples/secret-echo` end-to-end
- [x] Docs + skill updated
- [x] **No** vault, Credential Manager, keyring, Coreme secret-store file, `.env` loader, CLI secret flag/helper, encryption at rest, schedule, UI, signing, or registry
- [x] Host-setup polish ΓÇö superseded by secrets ceremony in skill + [skills/build-job/OPS-TEMPLATE.md](skills/build-job/OPS-TEMPLATE.md)

### Day 5 done means (see [docs/days/DAY5.md](docs/days/DAY5.md) checklist)

- [x] No kernel changes; no `[phases]`, `COREME_PHASES`, or `run.json.phases`
- [x] Job helper selects fixed-order phases from normal `only` / `skip` inputs
- [x] Invalid selection or missing selected-consumer seed fails with Run evidence
- [x] Day 4 checks all Job-level required inputs and declared secret names before Run
- [x] `examples/phased-demo` + offline proof + full / only / skip / seed runs + ship
- [x] **No** phase DAG, parallel engine, resume protocol, schedule, vault, UI, or platform

### After Day 7

**Fleet** is active via [docs/days/FLEET.md](docs/days/FLEET.md): F1 local agent is done; F2 hub is next. Prefer that ladder over inventing Doctor/platform. Other LATER rows still need their own day plan.

PostΓÇôDay 5 polish remains in tree: process-name resolve, live stream, operator UX / browser skill, `browser-stub`.

### Day 6 done means (see [docs/days/DAY6.md](docs/days/DAY6.md) checklist)

- [x] Skills: `operator-report.md` + `run-events.md`; pointers in SKILL / AGENTS / OPS-TEMPLATE
- [x] Kernel depends on `rich>=13`; pretty CLI footer/header; `COREME_PLAIN` / `--plain`
- [x] Every new Run has plain `log.txt` + `events.jsonl` (`run.start` / `run.end` minimum)
- [x] Secret values never in kernel events; Jobs not required to depend on Rich
- [x] `examples/report-demo` emits step events; offline proof green; `coreme.joblog`
- [x] README / Run layout docs updated; AGENT_DRILL checks events; `coreme events` read path
- [x] **No** Loguru/OTel stack, Textual TUI, SQLite event store, fleet, Doctor, vault, UI

### Day 7 done means (see [docs/days/DAY7.md](docs/days/DAY7.md) checklist)

- [x] Skill `skills/build-job/repair.md` + pointers from SKILL / OPS / run-events
- [x] `coreme brief <run_path>` assembles evidence-backed markdown (fail.json + log tail + events + run.json)
- [x] `coreme repair <run_path>` prints brief + next steps; `repair --exec` spawns host Codex
- [x] **`coreme run --auto-repair`** (or `COREME_AUTO_REPAIR=1`): on failed Run, deploys Codex **without a second command**; writes `repair.json`
- [x] Default `coreme run` (auto-repair off) never spawns Codex; suite needs no real Codex (fake PATH ok)
- [x] Job process never LLM; no auto-ship; no edit of `releases/`; Job failure exit not masked as success
- [x] **No** Doctor daemon, heal-until-green, SDK embed, secret values in briefs

---

## Explicit non-goals (until GOAL says otherwise)

Do **not** build these into the kernel early:

- Secrets vault / Credential Manager / keyring / Coreme secret-store file / `.env` loader / encryption at rest ΓÇö **beyond Day 4 thin names** (see [docs/days/DAY4.md](docs/days/DAY4.md))
- Code signing / GPG / full release registry product (fleet uses hub catalog + hash verify per [FLEET.md](docs/days/FLEET.md) ΓÇö not in kernel)
- Dev vs prod channels as a product surface
- Browser/Playwright **inside the kernel** (Jobs may add deps; see skill ΓÇö not LATER ΓÇ£browser profileΓÇ¥ unless a day plan says so)
- Control Room / web UI / dashboard (Grafana is OSS compose, not coreme UI)
- Kernel SQLite event store / ActiveGraph (agent local queue SQLite is fleet package only)
- Agent operation catalog / JSON-RPC
- Phase **DAG** / parallel scheduler (Day 5 = sequential `only`/`skip` only; fleet fan-out = many Assignments)
- Doctor daemon / folder watcher / heal-until-green / auto-ship (Day 7 auto-repair is **one** post-fail Codex spawn under explicit policy only)
- Background **chatbots** / chat workers (explicit FLEET non-goal)
- Installer, updater, multi-project data home
- Porting code from `roi-h` or `nga` or Qubitory (steal **ideas**, not code)
- Everything else in [docs/LATER.md](docs/LATER.md) until a day plan pulls it in

---

## Quality constraints

| Rule | Limit |
|------|--------|
| Dependencies | Stdlib first; **Rich** is the only runtime dep (Day 6 TTY paint). No Loguru/OTel; no Codex package |
| Understandability | Entire `src/coreme/` readable in one sitting |
| Runtime | Default run: no agent API keys. Auto-repair/prod: host Codex must be installed and signed in |

The milestone LOC snapshots are retired: they described historical implementation checkpoints and no longer define a useful current budget. Keep the kernel small by applying the feature filter and package Fleet components as siblings rather than growing `src/coreme/`.

If the kernel is growing and you are not shipping Jobs, you are re-adding platform.

---

## Definition of ΓÇ£reproducible automationΓÇ¥

A Job (and later a Release) is the product when:

1. Offline tests pass without the agent present.
2. A live run produces success evidence in a Run folder.
3. Someone tomorrow can `coreme run` without the chat transcript.
4. Declared inputs ΓÇö not hidden agent memory ΓÇö parameterize the run.
5. Bit-identity of code (Day 3 hash); secret **names** not values in evidence (Day 4).
6. Multi-step Jobs can be debugged phase-by-phase without a second product (Day 5).
7. Ops can re-run by process name against the latest release from the workspace root (postΓÇôDay 5 polish).

**Not required at first:** containers, signed packages, multi-OS matrix.

---

## How agents should work (procedure)

```text
1. Read GOAL.md (this file) ΓÇö know the focus and non-goals
2. Read WHY.md + AGENTS.md
3. If GOAL names an active day plan, read docs/days/DAYn.md
4. Prefer skills (skills/build-job/) over new kernel features
5. Product of work = Job folder + green test + Run evidence (+ OPS.md when ops will re-run)
6. Stop when the checklist is done; update this fileΓÇÖs status boxes
7. Do not implement docs/LATER.md items without a new docs/days/ plan
```

Human UX:

> Open agent ΓåÆ ΓÇ£Build an automation that ΓÇªΓÇ¥  
> Agent clarifies, explores, writes Job, tests, runs, hands you the Job path and Run path.

That loop is **skills + CLI**, not a second orchestrator product. See [skills/build-job/SKILL.md](skills/build-job/SKILL.md).

---

## Related docs

| File | Role |
|------|------|
| [WHY.md](WHY.md) | Mental model and non-goals narrative |
| [AGENTS.md](AGENTS.md) | Hard rules for coding agents |
| [README.md](README.md) | Install and commands |
| [docs/README.md](docs/README.md) | Doc map (what lives under `docs/`) |
| [docs/days/DAY2.md](docs/days/DAY2.md) | Day 2 archive checklist |
| [docs/days/DAY3.md](docs/days/DAY3.md) | Day 3 plan (ship / hash) ΓÇö sealed |
| [docs/days/DAY4.md](docs/days/DAY4.md) | Day 4 plan (thin secrets) ΓÇö sealed |
| [docs/days/DAY5.md](docs/days/DAY5.md) | Day 5 plan (Job-owned phases) ΓÇö sealed |
| [docs/days/DAY7.md](docs/days/DAY7.md) | Day 7 plan (agent-time repair / Codex) ΓÇö **done** |
| [docs/days/FLEET.md](docs/days/FLEET.md) | Fleet ladder F0ΓÇôF7 (agent + hub; **F1 done, F2 next**) |
| [docs/LATER.md](docs/LATER.md) | Deferred milestones; #7/#9 slices tracked in FLEET |
| [skills/build-job/repair.md](skills/build-job/repair.md) | Agent-time repair process (Day 7) |
| [docs/LESSONS-phases.md](docs/LESSONS-phases.md) | What to steal/drop from roi-h and nga |
| [docs/AGENT_DRILL.md](docs/AGENT_DRILL.md) | Cold-agent stress test for the Job loop |
| [skills/build-job/SKILL.md](skills/build-job/SKILL.md) | How to create a Job |
| [skills/build-job/clarify.md](skills/build-job/clarify.md) | Batch grill when contract unknowns block coding |
| [skills/build-job/phases.md](skills/build-job/phases.md) | Multistep Job pattern |
| [skills/build-job/operator-report.md](skills/build-job/operator-report.md) | Operator report / UX (steps, ├ûZET, idle) |
| [skills/build-job/browser.md](skills/build-job/browser.md) | Browser Jobs (deps in Job, not kernel) |
| [skills/build-job/OPS-TEMPLATE.md](skills/build-job/OPS-TEMPLATE.md) | Ops handoff template |

---

## Status log

| Date | Note |
|------|------|
| 2026-08-07 | Day 1 passed (manual + automated). GOAL.md + DAY2.md written. Current focus: Day 2 inputs + hardening. |
| 2026-08-07 | Day 2 passed: declared inputs, file evidence, greet example, and hardening tests. Day 3 needs a plan before code. |
| 2026-08-07 | Day 3 plan written: ship, tree hash, verify on run. Implementation next; no secrets yet. |
| 2026-08-07 | Day 3 done: `coreme ship`, RELEASE.json content hash, verify-on-run, refuse dirty release. LOC ~813 code-ish baseline. No secrets. |
| 2026-08-07 | Product rebalance (no kernel day): `examples/wordcount` file-input Job, cold-agent scorecard, build-job skill gaps. Day 4 not started. |
| 2026-08-07 | Quality pass: `paths`/`proof`/`util` split (no shipΓåörunner cycle; proof timeout; JobPathError); `tests/helpers.py`; docs note product-vs-tests. Still no Day 4. |
| 2026-08-07 | Day 4 plan written: env-only names; kernel-created structured evidence stores names only. Job logs and artifacts remain Job-controlled and are not redacted. Implementation not started. |
| 2026-08-07 | Day 4 plan refined: runtime = process env; an agent needs explicit user authority to save a value; session is default for one run and User scope is only for explicit persistence. Credential Manager and keyring are out of scope. |
| 2026-08-07 | Plan reset: old milestones 5ΓÇô10 moved to docs/LATER.md. Day 4 secrets treated as done in tree. Active calendar = Day 5 Job-owned phases (`only`/`skip`, seed file). build-job skill gains clarify/explore + runtime phase pattern. Day 5 not implemented. |
| 2026-08-07 | Compared roi-h (runtime DAG/ActiveGraph) and nga (delivery phases). Lessons in docs/LESSONS-phases.md. Day 5 refined: artifacts-as-wire, seed for mid-chain debug, no needs/parallel. build-job rewritten (writing-for-agents): process + disclosed phases.md. |
| 2026-08-07 | Day 5 plan corrected: phases are a Job-owned pattern. Normal inputs select fixed-order Job functions; Day 4 kernel checks stay unchanged. |
| 2026-08-07 | Day 5 done: `examples/phased-demo` with Job-owned `only`/`skip`/seed; no kernel changes. Offline proof, e2e (full/only/skip/fail/ship), docs + skill updated. |
| 2026-08-07 | PostΓÇôDay 5 ops polish: bare-name ΓåÆ latest release (`resolve.py`); live unbuffered stream; operator-ux / browser / OPS-TEMPLATE skills; `examples/browser-stub`. Kernel LOC ~1063. Day 4 host-setup checkbox closed (superseded by skill ceremony). |
| 2026-08-07 | Docs cleanup: sealed day plans + AGENT_DRILL under `docs/`; root keeps README / GOAL / WHY / AGENTS only. Map: [docs/README.md](docs/README.md). |
| 2026-08-07 | Skill-only: batch grill in build-job clarify ([skills/build-job/clarify.md](skills/build-job/clarify.md)) ΓÇö unknowns + recommended defaults + assumptions; no kernel, no decisions tree (nga idea, not delivery OS). |
| 2026-08-07 | PostΓÇôDay 6 polish: kernel `fail.json` on failed Runs (kind/message/step brief + `coreme events` FAIL header + plain footer `fail_path`); operator-facing **contract spine** (grill ΓåÆ contract ΓåÆ steps ΓåÆ ├ûZET) in build-job skill. Not full repair loop / Doctor. Days 1ΓÇô6 remain done; focus still ship real Jobs or one LATER item. |
| 2026-08-07 | **Day 7 plan written** (not implemented yet): repair skill + brief/repair CLI + **automatic Codex deploy** on failed runs when `--auto-repair` / `COREME_AUTO_REPAIR` (nga-shaped one-command recovery, thin). Job never LLM; no auto-ship. Spec: [docs/days/DAY7.md](docs/days/DAY7.md). |
| 2026-08-07 | **Day 7 done:** `brief.py` / `repair.py`; `coreme brief` / `repair [--exec]`; `run --auto-repair` / `--no-auto-repair` / `COREME_AUTO_REPAIR`; `repair.json` + skill; fake-Codex tests. No Doctor / auto-ship / release edits. |
| 2026-08-07 | **Repair polish:** crash-signature brief; default Codex sandbox `danger-full-access`; quiet `codex.log` tee; richer prompt + fail.png attach; auto offline prove; env knobs (`COREME_CODEX_*`, `COREME_REPAIR_PROVE` / `RERUN`); optional quiet Codex profile sample; rpa-challenge emits `step.fail`. |
| 2026-08-08 | **Operator fail UX:** `say_fail` / `short_error`; kernel live-echo colors (step cyan, FAIL red) with plain `log.txt`; fail footer shows failed step + reason + `fail.png`; rpa-challenge exits clean without Playwright traceback wall. |
| 2026-08-08 | **PostΓÇôDay 7 helpers (not a formal day):** (A) `coreme seed-from-fail` stages Run artifacts + prints/execs seeded re-run; (B) Job-local `JOB.md` + template + init stub; (G) Windows `make-shortcut.ps1` + OPS section. No resume protocol / Control Room / scheduler product. |
| 2026-08-08 | **Fleet F0 activated + F1 done:** plan [docs/days/FLEET.md](docs/days/FLEET.md); LATER #7/#9 tracked there. Sibling package `coreme_agent`: local SQLite queue, `coreme-agent enqueue/once/drain/list/show`, shells `coreme run --plain`, Attempt outcomes, `tests/test_agent_queue.py`. No hub HTTP, no kernel fleet code, no chatbots. Next stage **F2**. |
| *(add rows when a day closes or scope changes)* | |

---

## How to update this file

When a day finishes:

1. Check off the dayΓÇÖs boxes above.
2. Set **Current focus** at the top to the next day (or ΓÇ£done; ship Jobs / LATERΓÇ¥).
3. Add a **Status log** row.
4. Write `docs/days/DAYn.md` for the next day *before* implementing it (plan first).

When tempted by a new feature:

1. Run the feature filter.
2. Place it on the **active** ladder, in [docs/LATER.md](docs/LATER.md), or reject it.
3. If it is not the current day, do not silently expand the active day plan.
