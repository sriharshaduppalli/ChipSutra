# Deploy ChipSutra-VLSI to public portals

Goal: users on **https://chipsutra.org** (and optionally Emergent) see **ChipSutra-VLSI**, not Claude/GPT.

## Prerequisites

- Latest `main` pushed (this repo + synced `models/chipsutra-vlsi` from ChipSutra-VLSI-LLM)
- MongoDB Atlas with Network Access allowing the **server egress** IP (or `0.0.0.0/0`)
- Linux VM (8–16 GB RAM recommended) with Docker Compose v2
- DNS: `chipsutra.org`, `www`, `api.chipsutra.org` → that VM

## chipsutra.org (recommended)

```bash
# On the server
sudo mkdir -p /opt/chipsutra && cd /opt/chipsutra
git clone https://github.com/sriharshaduppalli/ChipSutra.git .
# or: git pull origin main

cp backend/.env.production.example backend/.env
# Edit backend/.env:
#   MONGO_URL=mongodb+srv://...
#   DB_NAME=chipsutra_db
#   JWT_SECRET=<64 hex>
#   CORS_ORIGINS=https://chipsutra.org,https://www.chipsutra.org
#   OLLAMA_URL=http://ollama:11434
#   OLLAMA_MODEL=chipsutra-vlsi:3b
#   SHOW_CLOUD_MODELS=false
#   # Do NOT set EMERGENT_LLM_KEY for the default path

cp deploy/env.prod.example deploy/.env.prod
cp deploy/Caddyfile.example deploy/Caddyfile
# Edit hosts / ACME email in Caddyfile and .env.prod

docker compose -f docker-compose.prod.yml --env-file deploy/.env.prod up -d --build

# Wait for ollama-bootstrap, then:
curl -s https://api.chipsutra.org/api/health | jq '.ollama,.llm_providers'
# Expect: ollama.ready=true, product_model ChipSutra-VLSI, show_cloud_models=false

./scripts/prod-smoke.sh "https://api.chipsutra.org" "https://chipsutra.org"
```

Open https://chipsutra.org → project → Generate: model switcher should list **ChipSutra-VLSI** only.

CI auto-deploy (optional): configure `DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY` per [docs/AUTOMATION.md](./AUTOMATION.md).

## chipsutra-verify.emergent.host

1. In Emergent, redeploy from GitHub `main` (not an old snapshot).
2. If the platform can run Ollama: set the same `OLLAMA_*` + `SHOW_CLOUD_MODELS=false`.
3. If Emergent **cannot** host Ollama: keep it as a legacy demo, or disable cloud models and rely on Fast-random TB only; point product users to **chipsutra.org**.

## Acceptance

| Check | Pass |
|-------|------|
| `GET /api/health` → `llm_providers.ollama` true | ✓ |
| `ollama.ready` true | ✓ |
| `show_cloud_models` false | ✓ |
| UI model list = ChipSutra-VLSI only | ✓ |
| Generate testbench (skeleton or LLM) works | ✓ |

## Related

- [CHIPSUTRA_ORG_LAUNCH.md](./CHIPSUTRA_ORG_LAUNCH.md)
- [deploy/README.md](../deploy/README.md)
- [MONGODB_ATLAS_SETUP.md](./MONGODB_ATLAS_SETUP.md)
- [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM)
