# Later milestones (deferred)

**Status:** Not on the active build calendar except where GOAL pulls one item. Days 1ΓÇô7 are **done** (repair loop = Day 7). Do not implement remaining rows without a new day plan under [days/](days/) and a GOAL focus update.

These were the old ladder steps **5ΓÇô10**. They package the same product loop (Job ΓåÆ prove ΓåÆ parameterize ΓåÆ freeze ΓåÆ re-run).

Active plan: [GOAL.md](../GOAL.md) ┬╖ sealed Day 7: [days/DAY7.md](days/DAY7.md) ┬╖ sealed Day 6: [days/DAY6.md](days/DAY6.md).

**Pulled (2026-08-08):** old **#7** (schedule slice) and **#9** (fleet) are tracked in **[days/FLEET.md](days/FLEET.md)** (ladder F0ΓÇôF7). Implement only the stage GOAL names. Chatbots / platform UI / multi-tenant remain out.

**Not this file:** Job-local browser deps, operator UX wording, and `examples/browser-stub` are **skill/example** guidance ([skills/build-job/browser.md](../skills/build-job/browser.md)). They do **not** implement old ladder **6** (declared browser profile path / kernel session manager).

---

## Why this file exists

Older projects failed by starting at fleet/platform/self-healing. coreme freezes those ideas here so they do not creep into day plans or the kernel.

**Rule:** reopen an item only by writing `docs/days/DAYn.md` and updating GOAL. Do not invent schedule, UI, signing, or registry ΓÇ£while here.ΓÇ¥

---

## Deferred ladder

| Old # | Name | You can say | Kernel / product adds | Not this |
|-------|------|-------------|------------------------|----------|
| **5** | Repair loop (**ΓåÆ Day 7 Γ£à**) | ΓÇ£Prod failed; Codex deploys; agent patches sourceΓÇ¥ | Delivered: skill + `brief`/`repair` + **auto-repair** ([days/DAY7.md](days/DAY7.md)) | Full Doctor (draft/activate/reviews/SQLite), Control Room, Job-process LLM, auto-ship |
| **6** | Browser profile | ΓÇ£Login once; jobs reuse profileΓÇ¥ | Declared profile **path** on the Job; Job owns browser deps | Playwright/browser engine inside the kernel |
| **7** | Schedule + notify | ΓÇ£OS scheduler + webhook on failΓÇ¥ | **ΓåÆ [FLEET.md](days/FLEET.md) F5** (hub cron ΓåÆ Assignments) + thin OS wrappers | In-kernel cron, multi-job orchestrator |
| **8** | Multi-job workspace | ΓÇ£Several Jobs share runner + skillsΓÇ¥ | Workspace root conventions | Microservices, control plane |
| **9** | Fleet | ΓÇ£Machines pull releasesΓÇ¥ | **ΓåÆ [FLEET.md](days/FLEET.md) F1ΓÇôF6** (agent + hub + hash pull + evidence) | Full registry product, K8s-style plane, chatbots |
| **10** | Platform | Studio-like UX | UI over the same Job / Release / Run folders | Starting here; replacing the CLI product |

---

## Notes per item (when reopened)

### Repair loop (old 5) ΓÇö delivered in Day 7

- Failed Run is the brief: `fail.json` + `log.txt` + `events.jsonl`, exit code, artifacts, inputs (and secret **names** only).
- Agent patches Job **source** ΓåÆ offline proof ΓåÆ source re-run ΓåÆ bump `version` ΓåÆ `ship` only with user authority ΓåÆ re-run release.
- Kernel writes a small structured fail summary (`fail.json` on every failed Run folder). The **Job process** never calls an LLM.
- **Already delivered (Day 6 + polish):** `events.jsonl` + operator-report skill + `coreme events`; kernel `fail.json`; contract spine in build-job skill.
- **Day 7 delivers:** skill [`repair.md`](../skills/build-job/repair.md); `coreme brief` / `coreme repair [--exec]`; **automatic** post-fail Codex when `coreme run --auto-repair` or `COREME_AUTO_REPAIR=1` (nga-shaped one command; max one spawn; `repair.json` audit; no auto-ship; no release tree edits). Host Codex CLI only ΓÇö no LLM SDK in kernel.
- **Still deferred after Day 7:** full Doctor (isolated draft, multi-review, activate/restore), heal-until-green loops, SQLite incident store, Control Room, notifications product.

### Browser profile (old 6)

- Profile path is data (input or fixed path), not a kernel session manager.
- Login once is host/agent setup; Jobs reuse the path.
- Skill guidance for Job-owned browser deps already exists; this ladder step is still the **declared profile path** product surface.

### Schedule + notify (old 7) ΓÇö tracked in FLEET F5

- Active design: [days/FLEET.md](days/FLEET.md) stage **F5** (hub schedule creates Assignments).
- OS still owns the clock for thin wrappers; unit of work remains `coreme run` on an agent.
- Notify = thin post on fail or Grafana alerts ΓÇö not an event bus product.

### Multi-job workspace (old 8)

- Many Job folders, one repo, shared skills and runs/releases layout.
- Still one entry process per run; no phase DAG across Jobs in the kernel.

### Fleet (old 9) ΓÇö tracked in FLEET F1ΓÇôF6

- Active design: [days/FLEET.md](days/FLEET.md). Bit-identity (Day 3 hash) remains trust root.
- Sibling packages (`coreme_agent`, later `coreme_hub`); kernel stays produce/prove/freeze/re-run only.
- No Canvas, multi-tenant, chatbots, or Control Room in that plan.

### Platform (old 10)

- Only when 1ΓÇô4 (and Day 5 phases, repair, etc.) feel boring.
- UI lists Jobs/Runs and triggers the same CLI contracts.

---

## Explicitly still out until a day plan says otherwise

- Secrets vault / Credential Manager / keyring as product (beyond Day 4 env names)
- Phase **DAG** / parallel step engine / resume protocol in the kernel
  (Day 5 is sequential phases in **one** entry with `only` / `skip` and artifact seeding ΓÇö see [days/DAY5.md](days/DAY5.md); lessons: [LESSONS-phases.md](LESSONS-phases.md))
- Full Doctor daemon / folder watcher / heal-until-green / auto-ship (Day 7 auto-repair is policy-gated, one Codex spawn)
- Agent RPC, SQLite event store, Control Room
- Code signing, installer, multi-project data home
- Porting code from `roi-h` or `nga` (ideas only)
- Embedding OpenAI/Anthropic SDKs in coreme (Day 7 only shells host `codex`)

---

## How to pull one item back in

1. Confirm Days 1ΓÇô5 and any postΓÇôDay 5 polish already in GOAL are boring.
2. Write `docs/days/DAYn.md` with a tight checklist and non-goals.
3. Point GOAL **Current focus** at that day.
4. Leave the other rows in this file.
