# ChipSutra™ — AI-Powered VLSI Design Verification

> © 2026 **Sri Harsha Duppalli** · [ChipSutra.ai](https://chipsutra-verify.emergent.host) · Open source under MIT (with attribution)

[![License: MIT](https://img.shields.io/badge/License-MIT%20+%20attribution-emerald)](./LICENSE)
[![Made in India](https://img.shields.io/badge/Made%20in-India-orange)](https://github.com/sriharshaduppalli/ChipSutra)
[![Verilator](https://img.shields.io/badge/Verilator-5.x-green)](https://www.veripool.org/verilator/)
[![Claude](https://img.shields.io/badge/LLM-Claude%20Sonnet%204.5-purple)](https://www.anthropic.com)

An open-source EDA copilot for the semiconductor industry — testbenches, assertions, coverage closure, waveforms, and formal verification, powered by Claude Sonnet 4.5 and GPT-5.2. **Free for community use. No quotas. No email walls.**

**Two ways to run:**
- **Hosted** — try it live at https://chipsutra-verify.emergent.host (no install)
- **Self-host** — clone, set 2 env vars, run. See [SELF_HOST.md](./SELF_HOST.md).

## What ships (v0.6 · fully open)

- **10 AI modules**: UVM Testbench, SVA Assertions, Checkers, Covergroups, Spec↔RTL, Testplan, Coverage-Hole Tests, Debug Analysis, Formal Hints
- **Real Verilator**: `--lint-only` and full `compile + run + VCD capture`
- **Real SymbiYosys** formal (Yosys + Z3 SMT)
- **In-browser VCD viewer** — WaveDrom-style timing diagrams
- **Coverage parser** — heatmap + ranked holes + auto-close tests
- **Workspaces/orgs** — owner/admin/member, activity log, seat limits
- **In-app notifications** — bell icon, unread badge
- **Team collab** — invite by email, threaded comments
- **UCIe/BoW/Chiplet templates**
- **GitHub Actions integration** — workflow template + webhook stub
- **Auth**: JWT email/password + optional Google OAuth (standalone or Emergent-managed)
- **No default quotas** — `FREE_DAILY_QUOTA=0` means unlimited out of the box

## Stack

| Layer | Tech |
|---|---|
| Frontend | React 19, Tailwind, Shadcn UI, Monaco, Framer Motion, Sonner |
| Backend | FastAPI, MongoDB (motor), Pydantic v2 |
| LLMs | Anthropic Claude Sonnet 4.5 + OpenAI GPT-5.2 (auto-routed) |
| Sim | Verilator 5 (subprocess, SSE-streamed) |
| Formal | SymbiYosys + Yosys + Z3 |
| Storage | Local disk (default) or Emergent Object Storage |
| Auth | JWT + optional Google OAuth 2.0 |

## Quick start (**zero API keys required**)

```bash
git clone https://github.com/sriharshaduppalli/ChipSutra.git
cd ChipSutra
cp backend/.env.example backend/.env
# Optional: edit backend/.env to change JWT_SECRET / ADMIN_PASSWORD
docker compose up --build
```

That's it. Docker Compose spins up:
- **MongoDB** — data store
- **Ollama** — local LLM server (auto-pulls `qwen2.5-coder:1.5b`, ~1 GB, on first run)
- **ChipSutra backend** — FastAPI + Verilator + Yosys + SymbiYosys pre-installed
- **ChipSutra frontend** — React SPA served via nginx

Open **http://localhost:3000** → sign up → upload RTL → click **Generate**. **No API key. No token cost. Testbench generated locally.**

### Want better quality?
Set one of these in `backend/.env` (all optional):
- `ANTHROPIC_API_KEY=sk-ant-...` → uses Claude Sonnet 4.5 (best code quality)
- `OPENAI_API_KEY=sk-...` → uses GPT-5.2
- Change `OLLAMA_MODEL=qwen2.5-coder:7b` (~4.5 GB) for better local quality
- `EMERGENT_LLM_KEY=sk-emergent-...` → Emergent Universal Key (Emergent-hosted only)

The backend auto-detects which providers are configured and routes accordingly.

## Tracking your community 📈

GitHub gives you built-in analytics — no code needed:

1. Go to **https://github.com/sriharshaduppalli/ChipSutra/graphs/traffic**
2. See:
   - **Clones** per day (last 14 days) — who's downloading your code
   - **Visitors** (unique IPs) — landing page views
   - **Referring sites** — where your traffic is coming from
   - **Popular content** — most-viewed files/paths
3. **Stars** and **Forks** are also public counters at the top of the repo.

For deeper analytics (post-clone activation, retention, geography), consider:
- **Plausible / Umami** — privacy-friendly web analytics on your hosted deployment
- **PostHog** — product analytics for the SaaS side
- **Repo insights via API**: `curl https://api.github.com/repos/sriharshaduppalli/ChipSutra/traffic/clones -H "Authorization: token <PAT>"` (needs push access on the repo)

## Licensing & Attribution

- **License**: MIT with attribution clause — see [LICENSE](./LICENSE)
- **Trademark**: "ChipSutra™" is a trademark of Sri Harsha Duppalli. Redistributions must keep the "Powered by ChipSutra" attribution + link.
- **Commercial re-branding** requires a separate commercial license — reach out at verification@chipsutra.ai.

## Ownership

This project — the code, the ChipSutra brand, the domain, and the hosted deployment — is owned by **Sri Harsha Duppalli** (GitHub: [@sriharshaduppalli](https://github.com/sriharshaduppalli)). Anyone can clone, run, and contribute; commercial forks need a chat first.

## Roadmap

- [ ] Redis-backed rate limiting (multi-pod safe)
- [ ] Full CI webhook AI review worker
- [ ] Yosys ≥ 0.35 Docker image
- [ ] Regression dashboard (pass/fail sparklines)
- [ ] CXL / HBM / D2D template gallery
- [ ] SMTP integration for verify emails (Resend/SendGrid drop-in)

## Contact

- Website: https://chipsutra-verify.emergent.host
- Issues: https://github.com/sriharshaduppalli/ChipSutra/issues
- Email: verification@chipsutra.ai

Made with ❤️ in India — for verification engineers, by verification engineers.
