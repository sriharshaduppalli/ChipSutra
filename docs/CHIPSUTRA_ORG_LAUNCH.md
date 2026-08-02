# Launch checklist — chipsutra.org (official portal)

Use this when moving from **personal dev** (native Windows, mock sim, local ports) to a **public, multi-tenant** deployment at **https://chipsutra.org** (and API on a stable host).

**Audience:** operators / founders — not end users. End users only need the website URL and an account.

---

## 1. Define what “official” means

| User-facing promise | Production requirement |
|---------------------|----------------------|
| Sign up / log in | MongoDB + `JWT_SECRET` + TLS |
| Upload RTL, projects, history | Durable DB + file storage (`STORAGE_MODE`) |
| **Generate** (UVM, SVA, …) | LLM with capacity for concurrent users |
| **Simulate** (Lint / VCD) | Backend image with **Verilator** (Linux/Docker) |
| Waveform viewer | VCD storage same as uploads |
| Optional Google login | OAuth client + redirect URIs |
| No “localhost” in UI | Frontend built with public API URL |

**Not the same as self-host on a laptop:** visitors never run Ollama, Atlas, or Docker locally.

Reference: [SUPPORTED_FEATURES.md](./SUPPORTED_FEATURES.md) — set expectations (engineer-in-the-loop, UVM vs Verilator limits).

---

## 2. Recommended architecture

```text
                    ┌─────────────────────────────────────┐
  User browser ───► │  https://chipsutra.org            │
                    │  (CDN or nginx — static React)     │
                    └──────────────┬──────────────────────┘
                                   │ API calls
                    ┌──────────────▼──────────────────────┐
                    │  https://api.chipsutra.org          │
                    │  (FastAPI + Verilator + Yosys)      │
                    └──────────────┬──────────────────────┘
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
   MongoDB Atlas              Ollama (GPU VM)         Object storage
   (M0+ prod cluster)         or cloud LLM keys       (local vol / S3 later)
```

**Minimum viable (single VM, 8–16 GB RAM, Linux):**

- `docker compose -f docker-compose.atlas.yml up -d` **or** Compose with managed Mongo
- Caddy/Nginx on the host for TLS → `chipsutra.org` + `api.chipsutra.org`
- Ollama on same VM or separate GPU box (`OLLAMA_URL` internal)

**Do not** point chipsutra.org at a developer’s `localhost:3000`.

---

## 3. Domain & DNS

| Host | Purpose | Record |
|------|---------|--------|
| `chipsutra.org` | SPA (frontend) | `A` / `AAAA` → load balancer or VM |
| `www.chipsutra.org` | Redirect to apex | `CNAME` → `chipsutra.org` or same A |
| `api.chipsutra.org` | Backend API | `A` / `AAAA` or `CNAME` to API ingress |

**Steps:**

1. Register / renew **chipsutra.org** at your registrar.
2. Create DNS records at registrar or Cloudflare.
3. Issue TLS certificates (Let’s Encrypt via Caddy, cert-manager, or Cloudflare SSL).
4. Force **HTTPS** redirect on both hosts.

---

## 4. Pre-launch engineering checklist

### 4.1 Repository & images

- [ ] Deploy from a **tagged release** on `main` (not an uncommitted dev tree).
- [ ] Run community validation: `./scripts/validate-community.sh` (Linux CI or WSL).
- [ ] Build and push images to a registry (roadmap: GHCR) — until then, build on the server:
  ```bash
  docker compose -f docker-compose.atlas.yml build
  ```
- [ ] Document the deployed git SHA on an internal `/about` or health metadata field.

### 4.2 Backend (`backend/.env` — production)

Copy from `.env.example` and set **production-only** values:

| Variable | Production guidance |
|----------|---------------------|
| `MONGO_URL` | **Atlas** `mongodb+srv://...` (not `localhost`). Dedicated DB user, least privilege. IP allowlist: server egress IPs or VPC peering — avoid `0.0.0.0/0` in prod if you can pin IPs. |
| `DB_NAME` | e.g. `chipsutra_prod` |
| `JWT_SECRET` | 64 hex chars, unique, stored in secrets manager |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Strong password; rotate after first login |
| `CORS_ORIGINS` | `https://chipsutra.org,https://www.chipsutra.org` (not `*` on public internet) |
| `FRONTEND_URL` | `https://chipsutra.org` |
| `OLLAMA_URL` | Internal URL, e.g. `http://ollama:11434` or GPU host |
| `OLLAMA_MODEL` | `chipsutra-vlsi:3b` (pull/create on server) |
| `FREE_DAILY_QUOTA` | Set &gt; 0 for abuse control on public portal (e.g. `50`) |
| `REQUIRE_EMAIL_VERIFICATION` | `true` when you have SMTP; else rate-limit heavily |
| `STORAGE_MODE` | `local` + persistent volume, or extend to S3-compatible later |
| `TELEMETRY_ENABLED` | Optional; set `TELEMETRY_ENDPOINT` if you run your own collector |

**Optional cloud LLM (overflow / quality tier):**

- `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` — UI shows providers when configured.

**Google OAuth (optional):**

- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI=https://api.chipsutra.org/api/auth/google/callback`

See [SELF_HOST.md](../SELF_HOST.md) § Google Sign-in.

### 4.3 Frontend build

Build-time variable (baked into JS):

```bash
docker build -f frontend/Dockerfile \
  --build-arg REACT_APP_BACKEND_URL=https://api.chipsutra.org \
  -t chipsutra-frontend:prod ./frontend
```

Or in Compose override:

```yaml
frontend:
  build:
    args:
      REACT_APP_BACKEND_URL: https://api.chipsutra.org
```

- [ ] Confirm browser network tab calls **`https://api.chipsutra.org/api/...`**, not `localhost:8001`.

### 4.4 LLM capacity (public traffic)

- [ ] **Ollama:** size VM RAM for model (3b ≈ 4–6 GB working set; 7b more). Limit concurrent generations (queue or `FREE_DAILY_QUOTA`).
- [ ] Warm model after deploy: one test generation or `ollama run chipsutra-vlsi:3b`.
- [ ] Fallback: cloud keys if Ollama saturated (cost + privacy policy update).

### 4.5 Simulation (Verilator)

- [ ] Backend must run **Linux container** or VM with Verilator ([backend/Dockerfile](../backend/Dockerfile)).
- [ ] Health check public: `GET https://api.chipsutra.org/api/health` → `"verilator": true`.
- [ ] Document in FAQ: full **UVM** may not sim in Verilator; lint/block TB is the sweet spot.

---

## 5. Deploy procedure (single VM example)

**Prerequisites:** Ubuntu 22.04+, Docker Engine + Compose v2, DNS pointing to VM, Atlas cluster ready.

1. **Clone on server**
   ```bash
   git clone https://github.com/sriharshaduppalli/ChipSutra.git
   cd ChipSutra
   git checkout <release-tag>
   ```

2. **Secrets**
   ```bash
   cp backend/.env.example backend/.env
   # edit backend/.env (Atlas, JWT, CORS, FRONTEND_URL, quotas)
   ```

3. **Atlas** — follow [MONGODB_ATLAS_SETUP.md](./MONGODB_ATLAS_SETUP.md); use **production** cluster tier when you outgrow M0.

4. **Start stack** (Atlas, no local Mongo pull):

   ```bash
   cp backend/.env.production.example backend/.env   # edit on server
   cp deploy/env.prod.example deploy/.env.prod
   docker compose -f docker-compose.prod.yml --env-file deploy/.env.prod up -d --build
   ```

   See **[deploy/README.md](../deploy/README.md)** and **[docs/PRODUCTION.md](./PRODUCTION.md)**.

5. **Reverse proxy (Caddy example sketch)**
   - `chipsutra.org` → `localhost:3000` (frontend container)
   - `api.chipsutra.org` → `localhost:8001` (backend)
   - Automatic HTTPS

6. **Smoke test** (see §7).

**Windows operators:** use a **Linux VM** for production; do not host the public API on native Windows (no Verilator). Dev hybrid: [VERILATOR_WINDOWS.md](./VERILATOR_WINDOWS.md).

---

## 6. Security & compliance (before marketing “official”)

- [ ] TLS everywhere; HSTS optional.
- [ ] Rotate all secrets from dev (JWT, admin, Atlas user, API keys).
- [ ] **Privacy policy** — what you store (RTL, logs, email), retention, India/global users.
- [ ] **Terms of use** — AI output not sign-off; user owns RTL; acceptable use.
- [ ] **MIT attribution** — keep “Powered by ChipSutra” per [LICENSE](../LICENSE) unless Enterprise.
- [ ] Backups: Atlas continuous backup / snapshots; volume backup for `storage/`.
- [ ] Rate limits: `FREE_DAILY_QUOTA`, reverse-proxy rate limit, max upload size.
- [ ] Disable default admin password from `.env.example` in production.
- [ ] No customer RTL or `.env` in git.

---

## 7. Go-live smoke tests

Run from any machine (replace URLs):

```bash
curl -s https://api.chipsutra.org/api/health | jq .
# Expect: status healthy, verilator true, ollama ready, llm_providers

# Register + login in browser at https://chipsutra.org
# Create project → upload small counter.sv → Generate (testbench)
# Simulate → Lint on selected RTL → engine verilator, not mock
```

**Checklist:**

- [ ] Sign up / login / logout
- [ ] Upload `.v`/`.sv`, preview, delete
- [ ] Generate streams complete; no CORS errors
- [ ] Simulate lint on sample RTL
- [ ] Share link / workspace (if enabled)
- [ ] Mobile layout sanity check
- [ ] Error page if API down (user-visible message)

---

## 8. Cutover from demo host

If today users hit **https://chipsutra-verify.emergent.host**:

That Emergent demo is an **older build** that still surfaces Claude/GPT via `EMERGENT_LLM_KEY`. It does **not** run ChipSutra-VLSI (Ollama) unless you redeploy with Ollama + latest ChipSutra.

**To show ChipSutra-VLSI on the public site:**

1. Redeploy latest `main` (frontend defaults to ChipSutra-VLSI; Claude/GPT only if `SHOW_CLOUD_MODELS=true`).
2. Run **Ollama + `chipsutra-vlsi:3b`** on that host (`OLLAMA_URL`, `OLLAMA_MODEL=chipsutra-vlsi:3b`).
3. Leave `SHOW_CLOUD_MODELS` unset/false so users do not see Claude/GPT.
4. Prefer cutting over to **chipsutra.org** (or your cloud) with the full compose stack — see above.

Until redeploy, tell users: local/self-host for ChipSutra-VLSI; Emergent demo may still show legacy cloud models.

1. Deploy production stack (above) on chipsutra.org.
2. **Migrate MongoDB** (export/import or Atlas cluster clone) if you need existing users/projects.
3. Update marketing links in [README.md](../README.md), site, and docs to **https://chipsutra.org**.
4. Lower TTL on DNS; switch `A`/`CNAME` records.
5. Keep old host redirecting 301 → chipsutra.org for 30–90 days.
6. Announce maintenance window if DB migration causes downtime.

---

## 9. Operations after launch

| Task | Frequency |
|------|-----------|
| Monitor `/api/health`, disk, RAM, Ollama | Continuous |
| Atlas alerts (connections, disk) | Atlas dashboard |
| Dependency / CVE updates (`requirements-oss.txt`, base images) | Monthly |
| Ollama model updates ([ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM)) | As released |
| Review abuse (quota hits, large uploads) | Weekly |
| GitHub Issues for community bugs | Ongoing |

**Support channel:** link **GitHub Issues** or `verification@chipsutra.ai` on the portal footer.

---

## 10. User-facing “official” messaging (copy-ready)

**What to say on chipsutra.org:**

- ChipSutra is an **AI verification copilot** for Verilog/SystemVerilog — testbenches, SVA, coverage plans, debug hints.
- **Community portal:** free tier with daily limits (if you set quotas); data processed on your infrastructure.
- **Not a replacement** for sign-off simulation or commercial EDA — engineer review required.
- **Self-host:** link to GitHub + [OPEN_SOURCE.md](./OPEN_SOURCE.md).

**What not to promise until Enterprise:**

- Questa/VCS/Xcelium integration, SSO/SAML, formal sign-off, SLA.

---

## 11. Quick owner timeline (suggested)

| Phase | Duration | Outcome |
|-------|----------|---------|
| **A. Staging** | 1–2 weeks | `staging.chipsutra.org` + Atlas staging DB; full smoke tests |
| **B. Hardening** | 1 week | TLS, CORS, quotas, legal pages, backups |
| **C. Production deploy** | 1–2 days | chipsutra.org live, health green |
| **D. Soft launch** | 1 week | Invite-only or waitlist; fix load issues |
| **E. Public launch** | — | Blog/docs, GitHub README updated, monitor |

---

## Related docs

- [OPEN_SOURCE.md](./OPEN_SOURCE.md) — Community checklist
- [MONGODB_ATLAS_SETUP.md](./MONGODB_ATLAS_SETUP.md) — Database
- [SELF_HOST.md](../SELF_HOST.md) — Provider matrix, OAuth
- [VERILATOR_WINDOWS.md](./VERILATOR_WINDOWS.md) — **Dev only** (not public portal)
- [DOCKER_PULL_TROUBLESHOOTING.md](./DOCKER_PULL_TROUBLESHOOTING.md) — Image pulls
- [ROADMAP.md](../ROADMAP.md) — GHCR images, enterprise

When staging is ready, add **`docs/CHIPSUTRA_ORG_LAUNCH.md`** to your internal runbook and tick sections 4–7 before announcing **official** access on chipsutra.org.
