# Production deployment

Operators hosting **chipsutra.org** or a private instance should use:

| Asset | Purpose |
|-------|---------|
| [deploy/README.md](./deploy/README.md) | Step-by-step Docker + Caddy deploy |
| [docker-compose.prod.yml](./docker-compose.prod.yml) | Atlas + Ollama + Verilator + TLS |
| [backend/.env.production.example](./backend/.env.production.example) | API secrets template |
| [deploy/env.prod.example](./deploy/env.prod.example) | Public URLs for frontend build |
| [docs/CHIPSUTRA_ORG_LAUNCH.md](./docs/CHIPSUTRA_ORG_LAUNCH.md) | Launch checklist (legal, DNS, ops) |
| [scripts/prod-smoke.sh](./scripts/prod-smoke.sh) | Post-deploy health checks |

**Developers** self-hosting locally: [docs/OPEN_SOURCE.md](./docs/OPEN_SOURCE.md) and [SELF_HOST.md](./SELF_HOST.md).

**Validate** before release:

```bash
./scripts/validate-community.sh
docker compose -f docker-compose.prod.yml config --quiet
```
