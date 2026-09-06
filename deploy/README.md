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

| Host | Must point at |
|------|----------------|
| `chipsutra.org` / `www` | Frontend (this Caddy, or GitHub Pages / Cloudflare Pages) |
| `api.chipsutra.org` | **This Caddy/API host only** — never the Pages IPs |

**Do not** give `api` the same A/AAAA records as the marketing site. Pages (and Cloudflare custom-hostname SSL) only issue certs for hostnames you add there. If `api` hits those IPs anyway, Chrome shows **`ERR_SSL_VERSION_OR_CIPHER_MISMATCH`** / “unsupported protocol” — the TCP port is open, but there is no TLS cert for `api.chipsutra.org`.

If Cloudflare proxies `api` (orange cloud): SSL/TLS mode **Full (strict)**, and wait until **SSL/TLS → Edge Certificates** lists `api.chipsutra.org`. Grey-cloud `api` to the origin if you want Caddy to terminate Let’s Encrypt instead.

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

Merging to `main` deploys automatically once the deploy secrets are configured —
see [docs/AUTOMATION.md](../docs/AUTOMATION.md).

Manual fallback (same script CI runs):

```bash
cd /opt/chipsutra && ./scripts/deploy-prod.sh main
```

## Caddy notes

- First request may take a minute while ACME certificates issue.
- For staging, use real subdomains (e.g. `staging.chipsutra.org`) with the same pattern.

## Related

- [docs/CHIPSUTRA_ORG_LAUNCH.md](../docs/CHIPSUTRA_ORG_LAUNCH.md) — full launch checklist
- [docs/MONGODB_ATLAS_SETUP.md](../docs/MONGODB_ATLAS_SETUP.md) — database
- [docker-compose.backend-verilator.yml](../docker-compose.backend-verilator.yml) — dev hybrid (Windows)
