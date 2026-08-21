# Rules for coding agents (coreme)

## Traps

- Job code never calls an LLM.
- Default `coreme run` does not spawn Codex.
- Source-first: `coreme run ./<job>`. Bare name is ops after ship.
- Feature filter: implement only what [GOAL.md](GOAL.md) names. Leave [docs/LATER.md](docs/LATER.md) and un-named Fleet stages.
- Never edit `releases/`.
- Secrets: names in the Job; values in process env; never in structured evidence.
- Fail: read `fail.json`, then `log.txt` / `events.jsonl`. Do not invent root cause.
- One live surface: Job stdout only. Do not also Rich-paint to `CONOUT$`.
- Verify: [scripts/verify.ps1](scripts/verify.ps1).
- Same-change maps: add, rename, or move a public module, CLI command, or product concept → update [_index.md](_index.md) in the same change.

## Discovery

1. [GOAL.md](GOAL.md) — current focus and non-goals.
2. Named day plan under [docs/days/](docs/days/) if GOAL names one.
3. [WHY.md](WHY.md) — product model.
4. This file.
5. [_index.md](_index.md) — path / concept / task maps.
6. Owning module from the map.
7. The matching skill below.

## Pointers

- **Job** author / change / prove / ship → [skills/build-job/SKILL.md](skills/build-job/SKILL.md)
- **Fleet** register / enroll / enqueue / schedules / evidence → [skills/fleet/SKILL.md](skills/fleet/SKILL.md)
- **Kernel implement** CLI / runner / ship / resolve / events / repair coordinator / `coreme_agent` → [skills/devex/implement-kernel.md](skills/devex/implement-kernel.md)
- **Repair** failed Run / brief / auto-repair → [skills/build-job/repair.md](skills/build-job/repair.md)
- **Phases** / seed-from-fail → [skills/build-job/phases.md](skills/build-job/phases.md)
- **Debug** kernel / test red → [skills/devex/debug-kernel.md](skills/devex/debug-kernel.md)
- **Maps** → [_index.md](_index.md)

## Style

Python 3.11, stdlib first, Windows paths. `ruff` + `mypy` are the style guide via [scripts/verify.ps1](scripts/verify.ps1).
