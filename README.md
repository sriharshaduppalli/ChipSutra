# ChipSutra — AI-Powered VLSI Design Verification

Made-in-India EDA platform that automates the full verification lifecycle — testbenches, assertions, coverage closure, waveforms — powered by Claude Sonnet 4.5 + GPT-5.2.

## Stack
- **Frontend**: React 19 + Tailwind + Shadcn UI + Monaco editor + Framer Motion
- **Backend**: FastAPI (Python) + MongoDB
- **AI**: Emergent Universal LLM key (Claude Sonnet 4.5 default, GPT-5.2 switchable)
- **Sim**: Verilator (real compile + run + VCD capture)
- **Formal**: SymbiYosys + Yosys + Z3 SMT
- **Auth**: JWT + Emergent Google OAuth
- **Storage**: Emergent Object Storage

## Features
- 10 AI generation modules: UVM Testbench, SVA Assertions, Checkers, Covergroups, Spec↔RTL, Testplan, Coverage-Hole Tests, Debug Analysis, Formal Hints
- Full workspaces/orgs with roles (owner/admin/member), activity log, seat limits
- In-app notifications (bell icon + unread count)
- Team collaboration (invite by email, editor/viewer)
- Threaded comments on every generation
- Coverage report parser + heatmap + holes dashboard
- In-browser VCD viewer (WaveDrom-style)
- Verilator lint + compile+run+VCD capture
- SymbiYosys formal verification (best-effort — Yosys ≥ 0.35 needed for full proofs)
- UCIe / BoW / Chiplet template gallery
- GitHub Actions workflow template + webhook stub

## Quickstart

### 1. Backend
```bash
cd backend
cp .env.example .env  # then edit .env with your keys
pip install -r requirements.txt
# System deps: verilator, yosys, z3, sby
apt-get install -y verilator yosys z3 python3-click
git clone --depth 1 https://github.com/YosysHQ/sby.git /tmp/sby && (cd /tmp/sby && make install)
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### 2. Frontend
```bash
cd frontend
cp .env.example .env  # then set REACT_APP_BACKEND_URL
yarn install
yarn start
```

### 3. Log in
- Admin (seeded on first start): `admin@chipsutra.ai` / value of `ADMIN_PASSWORD` from your `.env`
- Or sign up via email or Google

## Architecture

```
frontend (React)  ──►  /api/*  ──►  FastAPI  ──►  MongoDB
                                       │
                                       ├──►  Emergent LLM (Claude / GPT)
                                       ├──►  Emergent Object Storage
                                       ├──►  Verilator (subprocess)
                                       └──►  SymbiYosys + Yosys + Z3 (subprocess)
```

## API Surface (partial)
| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register`, `/login`, `/google/session` | Auth |
| `POST /api/projects` + files/collaborators/comments | Project workspace |
| `POST /api/generate/stream` (SSE) | AI generation |
| `POST /api/simulate/stream` (SSE) | Verilator lint / compile+run+VCD |
| `POST /api/formal/stream` (SSE) | SymbiYosys formal |
| `GET  /api/templates` | UCIe / BoW / Chiplet templates |
| `GET  /api/notifications`, `/workspaces`, `/ci/*` | Team + CI |

## License
See LICENSE file.

---
Built by ChipSutra Engineering · verification@chipsutra.ai
