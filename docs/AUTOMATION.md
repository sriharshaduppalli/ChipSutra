# Automation — what runs without you

Everything below is driven from the repo. The only manual step left for a normal
change is *merging to `main`*.

## Pipelines

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `community-ci.yml` | push / PR on `main` | compose syntax, `compileall`, source-sanity guard, full offline pytest suite, CI-strict frontend build, Verilator lint of golden DUTs |
| `docker-publish.yml` | push on `main`, tag `v*` | GHCR images: `edge` + `sha-<short>` on main, `latest` + semver on tags |
| `deploy-prod.yml` | after CI succeeds on `main`, or manual | SSH to the server, runs `scripts/deploy-prod.sh`, then post-deploy smoke test |
| `uptime.yml` | every 30 min | probes `api.chipsutra.org` + `chipsutra.org`; opens/updates an `incident` issue on failure |
| `release.yml` | tag `v*` | GitHub Release with generated changelog and image coordinates |
| `sync-vlsi-modelfiles.yml` | manual | PRs modelfile/RAG updates from ChipSutra-VLSI-LLM |
| `dependabot.yml` | weekly / monthly | grouped dependency PRs (pip, npm, actions, docker) |

## One-time setup for auto-deploy

Add these under **Settings → Secrets and variables → Actions**, environment `production`:

| Secret | Example | Notes |
|--------|---------|-------|
| `DEPLOY_HOST` | `203.0.113.10` | server running the prod stack |
| `DEPLOY_USER` | `deploy` | must be in the `docker` group |
| `DEPLOY_SSH_KEY` | *private key* | passwordless key; public half in the server's `authorized_keys` |
| `DEPLOY_PORT` | `22` | optional |
| `DEPLOY_PATH` | `/opt/chipsutra` | repo checkout on the server |
| `PUBLIC_API_URL` | `https://api.chipsutra.org` | optional, used by the smoke test |
| `PUBLIC_APP_URL` | `https://chipsutra.org` | optional |

**Until `DEPLOY_HOST` exists the deploy job skips cleanly instead of failing**, so CI
stays green on forks and before the server is wired up.

On the server, once:

```bash
sudo mkdir -p /opt/chipsutra && sudo chown "$USER" /opt/chipsutra
git clone https://github.com/sriharshaduppalli/ChipSutra.git /opt/chipsutra
cd /opt/chipsutra
cp backend/.env.production.example backend/.env    # edit secrets
cp deploy/env.prod.example deploy/.env.prod
cp deploy/Caddyfile.example deploy/Caddyfile       # edit domains + ACME email
```

`scripts/deploy-prod.sh` refuses to run if any of those three files is missing.

## Deploying by hand (fallback)

```bash
cd /opt/chipsutra && ./scripts/deploy-prod.sh main
```

Same script CI uses: fast-forward pull, rebuild, wait for backend health, prune
dangling images, smoke test. It exits non-zero (with backend logs) if health never
comes up, so a bad deploy is loud rather than silent.

## Guard rails

- `scripts/check_source_sanity.py` fails CI if editor line-number prefixes
  (`    10|import x`) ever get written into a source file — this actually happened and
  silently broke imports.
- The frontend build runs with `CI=true`, so React hook/lint warnings fail the build
  instead of accumulating.
- Golden DUTs are Verilator-linted on every push, so the reference designs can't rot.
- `deploy-prod.yml` only runs on a **successful** CI run of `main`.

## Still manual by choice

- Cutting a version tag (`git tag v1.3.0 && git push --tags`) — releases should be deliberate.
- Merging Dependabot PRs.
- DNS, TLS email, and server provisioning (one-time, in `deploy/README.md`).
