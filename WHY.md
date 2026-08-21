# Why coreme

## One sentence

**Agent = developer. Job = program. Runner = dumb robot.**

The agent writes a Job folder. A no-AI runner executes it and writes a Run evidence folder. Chat is a construction site, not the product.

## The wall

| Side | Who | Work |
|------|-----|------|
| **Agent-time** | LLM or human developer | Build, repair, and prove Jobs (may use Codex CLI or any coding agent) |
| **Runtime** | `coreme` runner | Load `JOB.toml`, run the entry, and write evidence |

The **Job process** never calls an LLM. Default `coreme run` does not need the chat transcript or agent API keys. **Repair** uses the failed Run as the brief and patches **source** only. Day 7 adds manual repair CLI and **optional automatic** host Codex deploy after a failed Run (`--auto-repair` / env) — one command for ops, like a thin nga recovery path, not a Doctor daemon or auto-ship.

**Agent-time steps** (clarify → prove → ship) live in the skill and chat — not a delivery-plan product.
**Runtime phases** (login → download → report) live inside one Job as sequential steps wired by **artifacts**; Day 5 formalizes Job-owned `only` / `skip` for debug (see `examples/phased-demo`).
Neither is roi-h’s phase graph nor nga’s delivery OS. See [docs/LESSONS-phases.md](docs/LESSONS-phases.md).

## Terms

| Term | Meaning |
|------|---------|
| **Job** | Folder with `JOB.toml`, an entry script, and optional offline tests |
| **Input** | A declared `string`, `int`, or `file` parameter; not chat memory |
| **Run** | One execution with `run.json`, `inputs.json`, plain `log.txt`, structured `events.jsonl`, and artifacts |
| **Runner** | Local CLI process that executes Jobs without AI |
| **Release** | Immutable hashed snapshot under `releases/<name>-<version>/` with `RELEASE.json` |
| **Secret name** | *(Day 4)* Process env name declared on the Job; value never in structured evidence |
| **Phase** | *(Day 5)* Named sequential step inside one Job; selectable for debug |

Inputs make one Job useful with different data. Ship freezes proven code; run refuses a dirty release before start.

## Guardrail

Add a kernel feature only when it helps every Job produce, prove, freeze, or re-run. Keep Job-specific behavior in the Job or its skill.

Vaults, browser engines, dashboards, SQLite, schedulers, agent RPC, full Doctor (draft/activate/reviews), heal-until-green daemons, fleet, and platform UX are deferred — see [docs/LATER.md](docs/LATER.md). Day 7 is thin repair: brief + optional auto Codex on fail under policy.

## North star

Grow one proven layer at a time: **Job → prove → parameterize → freeze → re-run** (then secrets, phases, operator report + run events, then agent-time repair).
