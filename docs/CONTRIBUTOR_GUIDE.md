# Contributor guide — ChipSutra (India & global DV community)

Thank you for helping build open verification tooling from India for the world.

## Who should contribute?

- Verification engineers (UVM, SVA, coverage closure)
- RTL designers moving into DV automation
- Students and faculty at VLSI programs (IITs, NITs, IIITs, private colleges)
- DevOps folks improving Docker, CI, and self-host docs

## Before you code

1. Read [SUPPORTED_FEATURES.md](./SUPPORTED_FEATURES.md) and [ROADMAP.md](../ROADMAP.md)
2. For LLM behavior changes, edit **[ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM)**, bump `VERSION`, then run **`./scripts/sync-vlsi-llm.sh`** (see [docs/LLM_SYNC.md](./LLM_SYNC.md))
3. For large features, open an issue first

## Development setup

### Option A — Docker (recommended)

```bash
git clone https://github.com/sriharshaduppalli/ChipSutra.git
cd ChipSutra
cp backend/.env.example backend/.env
docker compose up --build
# http://localhost:3000
```

First boot pulls Qwen base weights and builds `chipsutra-vlsi:3b` locally (no API keys).

### Option B — Native

See [SELF_HOST.md](../SELF_HOST.md). Install Verilator, MongoDB, Ollama, then backend + frontend.

### Custom local LLM (no credits)

```powershell
git clone https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM.git
cd ChipSutra-VLSI-LLM
.\scripts\create-all.ps1   # or ./scripts/create-all.sh
```

Set in `backend/.env`: `OLLAMA_MODEL=chipsutra-vlsi:3b`

## Running tests

Backend tests assume a **running API** and `REACT_APP_BACKEND_URL`:

```bash
# Terminal 1
cd backend && uvicorn server:app --port 8001

# Terminal 2
cd backend
export REACT_APP_BACKEND_URL=http://localhost:8001   # Git Bash / Linux
# $env:REACT_APP_BACKEND_URL="http://localhost:8001"  # PowerShell
pytest -n 0
```

For file-only checks (no server):

```bash
REPO_ROOT=$(pwd)/.. pytest tests/test_iteration_5.py -n 0 -k "docker_compose or env_example or requirements"
```

(`REPO_ROOT` defaults to repo root detected from test file path when `/app` is absent.)

## Code conventions

- **Backend:** FastAPI in `server.py` (routers split welcome in PRs)
- **Frontend:** React + shadcn; match existing monospace / emerald theme
- **Prompts:** Prefer ChipSutra-VLSI system prompt over one-off prompt hacks
- **Scope:** Smallest correct diff; no drive-by refactors

## Good first issues

- Coverage parser: more simulator report formats (Xcelium, VCS, Questa)
- Docs: Hindi/Telugu quick-start (optional)
- Templates: CXL, HBM, AMBA ACE5
- Tests: make iteration tests offline-friendly

## Attribution & license

- Software: [MIT](../LICENSE) with “Powered by ChipSutra” on derivative UIs
- Do not commit secrets (`.env`, API keys, customer RTL)

## Contact

- Issues: https://github.com/sriharshaduppalli/ChipSutra/issues
- Email: verification@chipsutra.ai
