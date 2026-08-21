# Deploy the hub to a VPS (docker-compose)

One command brings up Postgres, the hub, and Caddy (automatic TLS).

## Prerequisites

- A VPS with Docker + the compose plugin (any $5 box handles small fleets).
- A DNS A record pointing your domain at the VPS IP.

## Steps

```bash
ssh root@your-vps
git clone <your-fork-url> coreme && cd coreme
cp deploy/.env.example deploy/.env
nano deploy/.env        # set HUB_DOMAIN, POSTGRES_PASSWORD, COREME_HUB_OPS_TOKEN
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

Caddy obtains and renews a Let's Encrypt certificate automatically. The hub
listens on plain HTTP inside the compose network only.

Verify:

```bash
curl https://$HUB_DOMAIN/healthz     # {"status": "ok"}
curl https://$HUB_DOMAIN/version
```

## Onboard a worker PC

```bash
# on the VPS: mint a one-time enroll token (printed once)
docker compose -f deploy/docker-compose.yml exec hub \
  coreme-hub enroll-token create --tags site=lab

# on the worker PC
pipx install coreme
coreme-agent enroll --hub https://$HUB_DOMAIN --token <token> --tags site=lab
coreme-agent run
```

## Schedules

```bash
docker compose -f deploy/docker-compose.yml exec hub coreme-hub schedule create \
  --name nightly-report --release report --version 0.1.0 \
  --interval-sec 86400 --tag site=lab
```

The hub ticker (every `COREME_HUB_TICK_SECONDS`, default 30) creates due
Assignments; agents still only pull and run.

## Backups

```bash
# database
docker compose -f deploy/docker-compose.yml exec postgres \
  pg_dump -U postgres postgres > backup-$(date +%F).sql

# blobs + evidence (release zips, fail trees)
tar czf hubdata-$(date +%F).tgz $(docker volume inspect --format '{{.Mountpoint}}' coreme_hubdata)
```

## Upgrades

```bash
git pull
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

`coreme-hub migrate` runs on container start; schema changes are additive.

## Running on a Windows dev machine (WSL2 Docker)

Without Docker Desktop: install the engine inside WSL
(`wsl -u root -- apt install docker.io docker-compose-v2`), start it with
systemd or `service docker start`, and run the same compose file from
`/mnt/c/...`. Two caveats:

- **Idle shutdown**: WSL terminates when nothing keeps it alive, stopping
  the stack. Keep a process open (`wsl -- sleep infinity`) or raise
  `vmIdleTimeout` in `.wslconfig`. Real VPS deployments are unaffected.
- **TLS trust**: Caddy's local CA is not in the Windows trust store.
  Export `/data/caddy/pki/authorities/local/root.crt` from the caddy
  container and point `SSL_CERT_FILE` at it for agent commands.

## Environment reference

| Variable | Default | Meaning |
|---|---|---|
| `COREME_HUB_DSN` | — | Postgres DSN (required) |
| `COREME_HUB_OPS_TOKEN` | — | Ops bearer token (required) |
| `COREME_HUB_DATA` | `coreme-hub-data` | Blob + evidence directory |
| `COREME_HUB_BIND` | `127.0.0.1:8787` | Listen address |
| `COREME_HUB_TICK_SECONDS` | `30` | Schedule ticker interval (0 disables) |
| `COREME_HUB_WEBHOOK_URL` | — | POSTed JSON when an Assignment fails |
| `COREME_HUB_MAX_BODY_MB` | `200` | Request body cap |
