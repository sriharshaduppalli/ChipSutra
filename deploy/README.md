# Production deploy (chipsutra.org)

Run from the **repository root** on a Linux server with Docker Compose v2.

## 1. Files to create (never commit secrets)

```bash
cp backend/.env.production.example backend/.env    # edit MONGO_URL, JWT, admin, CORS
cp deploy/env.prod.example deploy/.env.prod
cp deploy/Caddyfile.example deploy/Caddyfile       # edit hosts + ACME email
```

Add `deploy/.env.prod` and `deploy/Caddyfile` to your secrets backup; they are gitignored if named `.env.prod`.

## 2. DNS

Point **A/AAAA** records for `chipsutra.org`, `www.chipsutra.org`, and `api.chipsutra.org` to this machine (or load balancer in front of it).

## 3. Start

```bash
docker compose -f docker-compose.prod.yml --env-file deploy/.env.prod up -d --build
```

Only **Caddy** publishes ports **80/443**. Backend and frontend are internal.

## 4. Verify

```bash
./scripts/prod-smoke.sh "https://api.chipsutra.org"
```

Open `https://chipsutra.org` — register, upload RTL, Generate, Simulate (engine **verilator**).

## 5. Updates

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file deploy/.env.prod up -d --build
```

## Caddy notes

- First request may take a minute while ACME certificates issue.
- For staging, use real subdomains (e.g. `staging.chipsutra.org`) with the same pattern.

## Related

- [docs/CHIPSUTRA_ORG_LAUNCH.md](../docs/CHIPSUTRA_ORG_LAUNCH.md) — full launch checklist
- [docs/MONGODB_ATLAS_SETUP.md](../docs/MONGODB_ATLAS_SETUP.md) — database
- [docker-compose.backend-verilator.yml](../docker-compose.backend-verilator.yml) — dev hybrid (Windows)
