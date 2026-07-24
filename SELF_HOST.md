# ChipSutra Self-Hosting Guide

You can run ChipSutra on your own laptop, VM or Kubernetes cluster — no Emergent account required. The backend auto-detects which providers are available and gracefully falls back to local disk / OSS SDKs.

---

## 1. System requirements

- **Python 3.11+**
- **Node.js 20+** and **Yarn**
- **MongoDB 6+** (local, Atlas, or any managed provider)
- **Verilator 5.x** (for simulation)
- **Yosys ≥ 0.35** + **SymbiYosys** + **Z3** (for formal — optional; Debian 12's yosys 0.23 is too old for full proofs, but the endpoint still works with a graceful hint)

Install on Debian/Ubuntu:
```bash
sudo apt-get update
sudo apt-get install -y verilator yosys z3 python3-click build-essential git
# SymbiYosys
git clone --depth 1 https://github.com/YosysHQ/sby.git /tmp/sby
cd /tmp/sby && sudo make install
```

On macOS (Homebrew):
```bash
brew install verilator yosys z3
pip install --user click
git clone https://github.com/YosysHQ/sby.git && cd sby && sudo make install
```

## 2. Get an LLM provider

Pick one:

### Option A — Anthropic Claude only (recommended)
Get a key at https://console.anthropic.com → set `ANTHROPIC_API_KEY` in `.env`. Claude Sonnet 4.5 covers every default AI module.

### Option B — Anthropic + OpenAI (dual)
Get both keys and set `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`. Users can then switch between Claude Sonnet 4.5 and GPT-5.2 in the UI.

### Option C — Emergent Universal Key (single key for all providers)
Sign up at https://app.emergent.sh and paste your key as `EMERGENT_LLM_KEY`. The `emergentintegrations` PyPI package is only available inside Emergent-hosted pods, so this option is really for Emergent users.

## 3. Google Sign-in (optional)

Leave blank to hide the "Continue with Google" button. To enable:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create an **OAuth 2.0 Client ID** (Web application)
3. Authorized redirect URI: `https://<your-backend>/api/auth/google/callback`
4. Copy client id + secret into `.env`:
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://<your-backend>/api/auth/google/callback
FRONTEND_URL=https://<your-frontend>
```

## 4. Backend

```bash
cd backend
cp .env.example .env
# EDIT .env — set MONGO_URL, JWT_SECRET, ADMIN_PASSWORD, ANTHROPIC_API_KEY (or EMERGENT_LLM_KEY)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

Verify:
```bash
curl http://localhost:8001/api/health
# Should print: llm_providers, storage, google_auth, verilator/yosys/sby flags
```

## 5. Frontend

```bash
cd frontend
cp .env.example .env
# EDIT .env — set REACT_APP_BACKEND_URL=http://localhost:8001
yarn install
yarn start
```

Open http://localhost:3000. Sign up with any email, or use the admin credentials you set in `.env`.

## 6. Docker (optional)

A minimal `docker-compose.yml` for local dev (bring your own `.env`):

```yaml
version: "3.9"
services:
  mongo:
    image: mongo:6
    ports: ["27017:27017"]
    volumes: [mongo_data:/data/db]
  backend:
    build: ./backend
    depends_on: [mongo]
    ports: ["8001:8001"]
    env_file: ./backend/.env
    environment:
      MONGO_URL: mongodb://mongo:27017
  frontend:
    build: ./frontend
    depends_on: [backend]
    ports: ["3000:3000"]
    environment:
      REACT_APP_BACKEND_URL: http://localhost:8001
volumes:
  mongo_data:
```

## 7. Provider matrix

| Feature | Emergent mode | Standalone mode |
|---|---|---|
| Claude Sonnet 4.5 | `EMERGENT_LLM_KEY` | `ANTHROPIC_API_KEY` |
| GPT-5.2 | `EMERGENT_LLM_KEY` | `OPENAI_API_KEY` |
| Object storage | Emergent bucket | Local disk (`./storage`) |
| Google sign-in | Emergent hosted | Google Cloud OAuth client |
| Verilator / Yosys / SBY | System install | System install |

## 8. Production deployment tips

- Set `CORS_ORIGINS` to your exact frontend origin (not `*`).
- Put a reverse proxy (Nginx/Caddy) in front and terminate TLS there.
- Use MongoDB with authentication + backups.
- Rotate `JWT_SECRET` and `ADMIN_PASSWORD` on first run.
- Behind a proxy, X-Forwarded-For is auto-honored for rate limits.
- For real formal proofs, build Yosys ≥ 0.35 from source (Debian 12's 0.23 is version-mismatched with latest SBY).

## 9. Troubleshooting

- **`llm_providers.anthropic` is `false`**: `ANTHROPIC_API_KEY` not set or SDK failed to init — check backend logs.
- **`storage` reports `local` but you wanted Emergent**: `EMERGENT_LLM_KEY` isn't set or the emergent endpoint is unreachable.
- **Verilator "unexpected `@`" errors**: the module has SVA — Verilator ignores those in `--lint-only`. Use `--assert` or switch to SBY.
- **SBY `formalff` error**: your Yosys is too old. Upgrade to ≥ 0.35 or use the AI "Formal Hints" module for LLM-drafted properties.

## 10. Community

- Issues / feature requests: https://github.com/sriharshaduppalli/ChipSutra/issues
- Contact: verification@chipsutra.ai
