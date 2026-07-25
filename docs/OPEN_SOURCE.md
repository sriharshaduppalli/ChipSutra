# Open source — Community Edition

ChipSutra Community Edition is **MIT licensed** (with UI attribution). Anyone can clone, self-host, and contribute without API credits.

## What you get

| Item | Location |
|------|----------|
| Application source | This repo |
| Local LLM (no tokens) | [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) + `models/chipsutra-vlsi/` |
| Feature maturity | [docs/SUPPORTED_FEATURES.md](./docs/SUPPORTED_FEATURES.md) |
| Roadmap | [ROADMAP.md](./ROADMAP.md) |
| Self-host guide | [SELF_HOST.md](./SELF_HOST.md) |
| Contributing | [docs/CONTRIBUTOR_GUIDE.md](./docs/CONTRIBUTOR_GUIDE.md) |

## Production self-host checklist

1. **Clone** and `cp backend/.env.example backend/.env`
2. Set **`JWT_SECRET`** to 64 hex chars (`python -c "import secrets; print(secrets.token_hex(32))"`)
3. Change **`ADMIN_PASSWORD`** from the example
4. **RAM**: 6 GB+ recommended (Ollama `chipsutra-vlsi:3b` + MongoDB)
5. Run **`docker compose up --build`** (uses `requirements-oss.txt` — no Emergent account)
6. Open **http://localhost:3000**, register, upload RTL, Generate
7. Optional cloud LLM: set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `backend/.env`

## Validate before deploy

```bash
./scripts/validate-community.sh
```

See also **[docs/AUTOMATED_SETUP.md](./docs/AUTOMATED_SETUP.md)** (what Git installs vs one-time OS tools).

## Editions

- **Community (OSS)**: This repository — Verilator, Ollama, MIT license.
- **Enterprise (future)**: Commercial sim integrations, SSO, support — contact `verification@chipsutra.ai`.

## Security

- Never commit `backend/.env` or customer RTL.
- Keep `REQUIRE_EMAIL_VERIFICATION=false` for frictionless OSS demos; enable for public multi-tenant hosts.
- Put TLS (Nginx/Caddy) in front for internet-facing deploys — see [SELF_HOST.md](./SELF_HOST.md).
