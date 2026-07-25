# Docker image pull failed (EOF / timeout)

Errors like:

```text
failed to copy: httpReadSeeker: failed open: ... production.cloudfront.docker.com ... EOF
```

mean the download from **Docker Hub’s CDN** was interrupted (network, firewall, VPN, or rate limit). ChipSutra’s `docker-compose.yml` is fine; retry or fix connectivity.

## Try first (PowerShell)

```powershell
cd ChipSutra
docker compose pull
docker compose up --build
```

Repeat `docker compose pull` 2–3 times on flaky Wi‑Fi.

## Checklist

1. **Stable internet** — try another network or mobile hotspot.
2. **VPN off** (or try a different region) — VPNs often break CloudFront pulls.
3. **Antivirus / firewall** — allow Docker Desktop; pause HTTPS scanning briefly to test.
4. **Docker signed in** — Docker Desktop → Sign in (helps with Hub rate limits).
5. **Disk space** — need ~10 GB free for images + Ollama model.

## Pull images one at a time

```powershell
docker pull mongo:6
docker pull ollama/ollama:latest
docker compose up --build
```

## After images are local

```powershell
docker compose up --build
```

Ollama will still download **qwen2.5-coder:3b** inside the `ollama-pull` step (~2 GB) — that uses Ollama’s servers, not Docker Hub. If that step fails, run again; pulls are resumable.

## Corporate / restricted networks

You may need a registry mirror or IT allowlist for:

- `production.cloudfront.docker.com`
- `registry-1.docker.io`

## Verify

```powershell
docker images
docker compose config --quiet
```

Then open **http://localhost:3000** after `up` completes.
