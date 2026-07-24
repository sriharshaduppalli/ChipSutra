# ChipSutra — AI-Powered VLSI Design Verification

[![Made in India](https://img.shields.io/badge/Made%20in-India-orange)](https://github.com/sriharshaduppalli/ChipSutra)
[![Verilator](https://img.shields.io/badge/Verilator-5.x-green)](https://www.veripool.org/verilator/)
[![Claude](https://img.shields.io/badge/LLM-Claude%20Sonnet%204.5-purple)](https://www.anthropic.com)

An open-source EDA copilot that automates the full verification lifecycle — testbenches, assertions, coverage closure, waveforms and formal — powered by Claude Sonnet 4.5 and GPT-5.2.

**Two ways to run:**
- **Hosted** — try it live at https://chipsutra-verify.emergent.host (no install)
- **Self-host** — clone, set 2 env vars, run. See [SELF_HOST.md](./SELF_HOST.md).

## What ships

- **10 AI modules**: UVM Testbench, SVA Assertions, Checkers, Covergroups, Spec↔RTL (bi-dir), Testplan, Coverage-Hole Tests, Debug Analysis, Formal Hints
- **Real Verilator integration**: `--lint-only` and full `compile + run + VCD capture` streamed via SSE
- **Real SymbiYosys formal**: Yosys + Z3 SMT (needs Yosys ≥ 0.35 for full proofs; graceful hint otherwise)
- **In-browser VCD viewer** — WaveDrom-style timing diagrams
- **Coverage parser** — heatmap + ranked holes + closure test generation
- **Workspaces/Orgs** — owner/admin/member roles, activity log, seat limits
- **Team collab** — invite by email, editor/viewer, threaded comments on every generation
- **In-app notifications** — bell icon, unread badge, polling
- **UCIe/BoW/Chiplet template gallery** — pre-baked verification patterns
- **GitHub Actions integration** — downloadable workflow + webhook stub
- **Auth** — JWT email/password + optional Google OAuth (standard or Emergent-managed)

## Stack

| Layer | Tech |
|---|---|
| Frontend | React 19, Tailwind, Shadcn UI, Monaco, Framer Motion, Sonner |
| Backend | FastAPI, MongoDB (motor), Pydantic v2 |
| LLMs | Anthropic Claude Sonnet 4.5 + OpenAI GPT-5.2 (via official SDKs or Emergent) |
| Sim | Verilator 5 (subprocess, SSE-streamed logs) |
| Formal | SymbiYosys + Yosys + Z3 (subprocess) |
| Storage | Local disk (default) or Emergent Object Storage |
| Auth | JWT + optional Google OAuth 2.0 |

## Quick start (self-host)

```bash
git clone https://github.com/sriharshaduppalli/ChipSutra.git
cd ChipSutra

# --- backend ---
cd backend
cp .env.example .env
# EDIT .env: set MONGO_URL, JWT_SECRET, ADMIN_PASSWORD, ANTHROPIC_API_KEY
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001

# --- frontend (new terminal) ---
cd frontend
cp .env.example .env
# EDIT .env: set REACT_APP_BACKEND_URL=http://localhost:8001
yarn install && yarn start
```

Open http://localhost:3000 — sign up with any email and start verifying.

Full self-host guide (system deps, Docker, Google OAuth, formal toolchain): **[SELF_HOST.md](./SELF_HOST.md)**.

## Architecture

```
       ┌─────────────────────┐
       │   React Frontend    │
       │  Monaco · WaveDrom  │
       └──────────┬──────────┘
                  │  /api/*
       ┌──────────▼──────────┐        ┌──────────────────┐
       │   FastAPI Backend   │──────► │  Anthropic /     │
       │  SSE · JWT · Bcrypt │        │  OpenAI SDKs     │
       └──┬───────┬───────┬──┘        └──────────────────┘
          │       │       │
          │       │       ├──► Verilator (subprocess, --cc --build --trace)
          │       │       ├──► SymbiYosys + Yosys + Z3 (subprocess)
          │       │       └──► Local disk OR Emergent Object Storage
          │       │
          │       └──► MongoDB (users, projects, gens, workspaces, notifs)
          │
          └──► Optional: Google OAuth 2.0
```

## API surface (partial)

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/{register,login}` · `GET /api/auth/me` | Email/password auth |
| `POST /api/auth/google/session` · `GET /api/auth/google/{url,callback}` | Google OAuth (Emergent OR standalone) |
| `POST /api/projects` + `/files` + `/collaborators` + `/comments` | Project workspace |
| `POST /api/generate/stream` (SSE) | Streaming LLM generation |
| `POST /api/simulate/stream` (SSE) | Verilator lint OR compile+run+VCD |
| `POST /api/formal/stream` (SSE) | SymbiYosys formal proofs |
| `POST /api/coverage/parse` · `POST /api/waveform/parse` | Coverage + VCD parsers |
| `GET /api/templates` | UCIe / BoW / Chiplet templates |
| `GET /api/workspaces` + `/members` + `/activity` | Team workspaces |
| `GET /api/notifications` | In-app notifications |
| `GET /api/ci/github-workflow` · `POST /api/ci/webhook` | GitHub Actions |
| `GET /api/health` | Provider status & tool detection |

## Screenshots

_(Coming soon — landing, dashboard, waveform viewer, simulate modal, workspaces)_

## Roadmap

- [ ] Redis-backed rate limiting (multi-pod safe)
- [ ] Full CI webhook AI review worker (PR diff → auto-review + comment back)
- [ ] Yosys ≥ 0.35 Docker image for full formal proofs
- [ ] Workspace-level project auto-sharing
- [ ] Regression dashboard (pass/fail sparklines per project)
- [ ] CXL / HBM / D2D template gallery
- [ ] Router split for `server.py` (~1600 → per-domain modules)

## License

See [LICENSE](./LICENSE).

## Contact

- Website: https://chipsutra-verify.emergent.host
- Issues: https://github.com/sriharshaduppalli/ChipSutra/issues
- Email: verification@chipsutra.ai

Made with ❤️ in India — for verification engineers, by verification engineers.
