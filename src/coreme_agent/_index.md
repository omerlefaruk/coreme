# coreme_agent

Fleet agent: local SQLite queue (F1) or hub claim + hash pull (F3 `--hub`).

**Status:** F3. Hub HTTP lives in `coreme_hub`.

## Interface

- CLI `coreme-agent`: `enqueue`, `once`, `drain`, `list`, `show`
- Hub run: `hub_worker.process_one(client, tags=...) -> RunOutcome | None`
- Local run: `worker.process_one(queue) -> RunOutcome | None`
- Executor: `execute_assignment(RunRequest) -> ExecResult`

## File map

| File | Role |
|------|------|
| `run.py` | `RunRequest` / `RunOutcome` |
| `store.py` | Local SQLite queue; `Assignment` stays here |
| `executor.py` | Contained coreme process |
| `hub.py` | `HubClient` adapter + `CompletePayload` |
| `hub_worker.py` | Hub Assignment run |
| `cache.py` | Hashed release cache policy |
| `outbox.py` | Complete + evidence outbox |
| `worker.py` | Local queue drain |
| `cli.py` | Ops console |

## Next

[docs/days/FLEET.md](../../docs/days/FLEET.md) F3 done-means. Do not start F4 here.
