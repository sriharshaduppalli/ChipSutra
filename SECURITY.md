# Security

## Supported versions

Security fixes are applied on the **`main`** branch. Deploy production from tagged releases when possible.

## Reporting a vulnerability

Please **do not** open public GitHub issues for exploitable security bugs.

Email **verification@chipsutra.ai** with:

- Description and impact
- Steps to reproduce
- Affected component (backend, frontend, Docker image, etc.)

We aim to acknowledge within **5 business days**.

## Production hardening (operators)

- Use **`backend/.env.production.example`** — strong `JWT_SECRET`, Atlas credentials, tight `CORS_ORIGINS`
- Terminate TLS at Caddy/nginx (`docker-compose.prod.yml`)
- Set **`FREE_DAILY_QUOTA`** on public multi-tenant hosts
- Never commit `backend/.env`, RTL uploads, or customer data
- Rotate **`ADMIN_PASSWORD`** after bootstrap

See [deploy/README.md](./deploy/README.md) and [docs/CHIPSUTRA_ORG_LAUNCH.md](./docs/CHIPSUTRA_ORG_LAUNCH.md).
