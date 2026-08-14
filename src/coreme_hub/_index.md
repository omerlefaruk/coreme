# coreme_hub

Thin fleet hub (F3): claim loop, hashed release catalog, fail evidence.

**Status:** F3. No schedule or Grafana.

## Interface

- CLI `coreme-hub`: `migrate`, `serve`, `register`, `enqueue`, `list`, `show`
- HTTP `/v1/machines/*`, `/v1/assignments/*`, `/v1/releases/*` — [FLEET.md](../../docs/days/FLEET.md)

## File map

| File | Role |
|------|------|
| `db.py` | DSN, schema, migrate |
| `blobs.py` | Blob/evidence paths and storage |
| `store.py` | Claim / catalog / evidence |
| `http.py` | stdlib HTTP + bearer tokens |
| `cli.py` | Ops console |

## Next

[docs/days/FLEET.md](../../docs/days/FLEET.md) F3 done-means. Do not start F4 here.
