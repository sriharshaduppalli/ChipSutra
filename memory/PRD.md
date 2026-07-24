# ChipSutra — Product Requirements (Living Doc)

## Problem Statement (verbatim)
ChipSutra is a Made-in-India AI-powered VLSI Design Verification Platform that automates
the entire design verification lifecycle — from spec to testbench to coverage closure — for
verification engineers, semiconductor companies and research labs.

## Architecture
- Frontend: React 19 + Tailwind + Shadcn + Framer Motion + Monaco + Sonner
- Backend: FastAPI + MongoDB (motor) + emergentintegrations
- Auth: JWT (Bearer) + Emergent Google OAuth (rate-limited)
- Storage: Emergent-managed object storage (inline fallback)
- LLMs: Claude Sonnet 4.5 + GPT-5.2 switchable via EMERGENT_LLM_KEY
- Simulator: real Verilator (`--lint-only` and `--cc --exe --build --trace --timing` compile+run+VCD capture) with mock fallback
- Formal: real SymbiYosys + Yosys + Z3 SMT (best-effort — Debian Yosys 0.23 is version-mismatched with latest SBY; friendly diagnostic surfaced in log stream)

## Implemented

### v0.1 — MVP (2026-02)
- Landing site, JWT auth, projects CRUD, file upload, 9 AI modules with SSE, coverage parser, VCD viewer, reports

### v0.2 — Collab + Verilator (lint) + Templates (2026-02)
- Team collab (invite by email, editor/viewer)
- Generation comments
- Verilator `--lint-only` streaming
- Chiplet templates gallery (UCIe/BoW/Chiplet/IP)
- Emergent Google Sign-in
- Docs page

### v0.3 — Compile+Run + Workspaces + Notifications + Formal + CI (2026-02)
- **Verilator compile+run+VCD capture** (mode='run', sim_time_ns configurable, VCD auto-saved to project files)
- **Workspaces/Orgs** (owner/admin/member roles, activity log, seat limit=5, delete endpoint)
- **In-app notifications** (bell icon, unread badge, mark-single/all-read, 30s poll)
- **Rate-limited Google session** endpoint (20/5min per IP with X-Forwarded-For)
- **GitHub Actions integration**: downloadable `chipsutra.yml` workflow + `/api/ci/webhook` stub + events list page
- **Formal verification** via SymbiYosys + Z3 (real toolchain; friendly hint when Yosys 0.23 version-mismatch)
- **New AI module `formal_hints`** — LLM drafts SVA properties for formal proofs
- Pydantic Literal validation for workspace roles (422 on invalid)
- Sonner toasts moved to bottom-right (no button overlap)

## Tested
- v0.1: 16/16 ✅ · v0.2: 22/22 ✅ · v0.3: 24/25 backend + 100% frontend ✅
- 1 flaky test (Google rate-limit on multi-pod K8s) — product feature works via sequential curl

## Backlog / Next Priorities

### P0 (next)
- Redis-backed rate limiter (share buckets across pods)
- Cascade `simulate/formal` DB doc cleanup on process kill
- Full AI review worker on `/api/ci/webhook` (parse PR diffs → run generation → post GitHub comment)

### P1
- Rebuild Yosys ≥ 0.35 from source for full SBY proofs
- Split `server.py` (~1600 lines) into routers (auth, projects, collab, files, generate, simulate, formal, workspaces, notifications, ci)
- Fine-tuned domain LLM for RTL/UVM
- Full-text search across artifacts
- Workspace-level project sharing (auto-share on create)

### P2
- SAML/OIDC beyond Google
- On-prem deployment package
- Blog + SEO polish
- Template gallery expansion (CXL, HBM, D2D)
- Redis + Celery worker queue for background sims

## Deployment
- Verilator 5.006, Yosys 0.23, SymbiYosys, Z3 4.8.12 all installed at container startup.
- Emergent Object Storage initialised via `EMERGENT_LLM_KEY`.
- GitHub target: https://github.com/sriharshaduppalli/ChipSutra (push via Emergent "Save to GitHub" or PAT).
