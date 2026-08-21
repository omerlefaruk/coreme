# Skill: repair a failed Run

Agent-time repair. The runtime stays LLM-free.

## Reading order (never skip)

1. `<run>/fail.json` — kind, message, failed step.
2. `<run>/log.txt` tail and `<run>/events.jsonl` (`step.fail` first).
3. `<run>/run.json` — inputs used, release hash if shipped.

Do not invent root cause; quote evidence.

## Commands

```bash
coreme brief <run_path>             # evidence-backed markdown brief
coreme repair <run_path>            # brief + next steps (no execution)
coreme repair <run_path> --exec     # deploys host Codex once with the brief
coreme run ./job --auto-repair      # automatic post-fail Codex deploy
```

- Max one Codex spawn per run; requires host `codex` installed and signed
  in. Default `coreme run` never spawns Codex.
- Repair edits **source**, then `coreme test` → `coreme ship` again.
  Never patch `releases/`; ship a new version instead.
- Mid-chain debug: `coreme seed-from-fail <run_path>` stages artifacts as
  seed inputs for a partial re-run.

## Fleet note

On worker PCs the source may not exist. Pull fail evidence from the hub
(`coreme-hub show <id>`, evidence zip), repair on a machine that has the
source, ship, re-register, re-enqueue. See [../fleet/SKILL.md](../fleet/SKILL.md).
