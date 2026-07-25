# Docker image pull failed (EOF / timeout)

Errors like:

```text
failed to copy: httpReadSeeker: failed open: ... production.cloudfront.docker.com ... EOF
```

mean the download from **Docker Hub’s CDN** was interrupted (network, firewall, VPN, ISP, or rate limit). ChipSutra’s compose files are fine; fix connectivity or use a workaround below.

## Try first (PowerShell)

```powershell
cd ChipSutra
docker compose pull
docker compose up --build
```

Repeat 2–3 times. Between attempts:

```powershell
wsl --shutdown
```

Restart **Docker Desktop**, then pull again.

## Docker Desktop network tweaks

**Settings → Docker Engine** — add or merge (keep existing JSON valid):

```json
{
  "dns": ["8.8.8.8", "1.1.1.1"],
  "max-concurrent-downloads": 2
}
```

Apply and restart Docker.

Also try:

- **VPN off** (or different server / mobile hotspot)
- Sign in to Docker Hub in Docker Desktop
- **~10 GB** free disk space
- Temporarily pause antivirus HTTPS scanning

## Skip `mongo:6` if only Mongo fails

Use **MongoDB Atlas** (free tier) so you do not pull the Mongo image:

1. [Create Atlas cluster](https://www.mongodb.com/cloud/atlas/register) (M0 free).
2. User + password, network access `0.0.0.0/0` (dev only).
3. Copy `mongodb+srv://...` into `backend/.env` as `MONGO_URL`.
4. Run:

```powershell
docker compose -f docker-compose.atlas.yml up --build
```

You still need **`ollama/ollama:latest`** from Docker Hub. If that also EOFs, use **native Ollama** (below).

## Pull images one at a time

```powershell
docker pull mongo:6
docker pull ollama/ollama:latest
docker compose up --build
```

## If Docker Hub never works on your network

Run **without Docker images** for LLM/DB:

1. **Ollama (Windows app):** `winget install Ollama.Ollama` or [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) `.\setup.ps1 -InstallDependencies -Tag 3b`
2. **MongoDB Atlas** — `MONGO_URL` in `backend/.env`
3. **Backend:** `pip install -r backend/requirements-oss.txt`, `uvicorn server:app --port 8001` from `backend/`
4. **Frontend:** `cd frontend`, `yarn install`, `yarn start`

Set in `backend/.env`:

```env
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=chipsutra-vlsi:3b
```

See [SELF_HOST.md](../SELF_HOST.md).

## After images are local

```powershell
docker compose up --build
```

Ollama inside compose still downloads **qwen2.5-coder:3b** (~2 GB) from Ollama’s CDN (separate from Docker Hub).

## Verify

```powershell
docker images
docker compose config --quiet
```
