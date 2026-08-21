# Skill: job-owned phases

Multi-step Jobs use fixed-order phase functions inside one entry — not a
DAG, not kernel features.

## Pattern

```python
PHASES = ["login", "download", "process", "report"]

def main() -> None:
    only = os.environ.get("COREME_INPUT_ONLY", "")
    skip = os.environ.get("COREME_INPUT_SKIP", "")
    selected = select_phases(PHASES, only=only, skip=skip)
    for phase in selected:
        say_step(phase)
        globals()[phase]()
```

- Normal inputs (`only`, `skip`) select phases; invalid selections fail
  with Run evidence.
- Each phase logs via `say_step` so `events.jsonl` shows `step.ok/fail`.
- Debug mid-chain: run with `--input only download,process` plus a seed
  input pointing at prior artifacts; or `coreme seed-from-fail`.

## Non-goals

No parallel engine, no cross-phase resume protocol, no needs-graph.
Fan-out across machines is many Assignments of the same release (fleet),
not phases.
