# Machine-readable surfaces

Stable output contracts for coding agents. Additive changes only; bump
schema versions on breaking changes.

## Run result frame (`coreme run --plain`)

Emitted by the kernel to `COREME_RESULT_CHANNEL` (length-prefixed JSON,
64 KiB cap). Schema: `coreme.run-result`, version 1.

```json
{
  "schema": "coreme.run-result",
  "version": 1,
  "status": "succeeded",
  "exit_code": 0,
  "run_path": "runs/report-20260821-101300",
  "run_id": "report-20260821-101300",
  "message": null
}
```

`status` ∈ `succeeded | failed | timeout | error`. Agents must treat
unknown statuses as failures and unknown keys as ignorable.

## Doctor (`coreme doctor --json`)

```json
{
  "checks": [
    {"name": "python", "status": "pass", "detail": "3.11.9"},
    {"name": "hub", "status": "fail", "detail": "...unreachable"}
  ],
  "ok": false
}
```

`status` ∈ `pass | warn | fail`; `ok` is false when any check failed.
Exit code: 0 when ok, 1 otherwise.

## Hub assignment (`assignment_public`)

Keys: `id`, `batch_id`, `status`, `release` (`name`, `version`,
`content_hash`, `blob_url`, `size_bytes`), `inputs`, `secret_names`
(names only, never values), `required_tags`, `lease_seconds`,
`claimed_by`, `attempt_id`, `summary`, `fail`, `log_tail`, `evidence`
(`size_bytes`, `sha256`) when present.

## Machine (`machine_public`)

Keys: `id`, `tags`, `status`, `agent_version`, `last_heartbeat`,
`running_assignment_id`, `drained`.

## Metrics (`GET /metrics`, Prometheus text)

```
coreme_machines_total N
coreme_machines_online N
coreme_machines_drained N
coreme_assignments{status="pending"} N
coreme_attempts_failed_total N
coreme_attempts_succeeded_total N
```
