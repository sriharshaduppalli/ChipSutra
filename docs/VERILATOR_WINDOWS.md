# Real Verilator on Windows (hybrid setup)

You can keep **what already works natively** (Ollama, MongoDB Atlas, React on port 3000) and only move the **API** to an environment that has **Verilator**.

| Component | Where | Why |
|-----------|--------|-----|
| Frontend | Windows `yarn start` / `npm start` | Already working |
| Ollama + `chipsutra-vlsi:3b` | Windows app | Avoids Docker Hub `ollama` image |
| MongoDB | Atlas (`MONGO_URL` in `backend/.env`) | Avoids `mongo:6` pull |
| **Backend API** | **Docker or WSL2** | Verilator + Yosys live here |

After switching the backend, open **http://localhost:8001/api/health** and confirm `"verilator": true`. In the sim dialog the engine badge should say **`verilator`**, not **`mock`**.

---

## Option A — Backend-only Docker (recommended on Windows)

**Requires:** Docker Desktop running and able to **build** the backend image (Debian packages from the internet; no full `docker compose up` stack).

1. **Stop** the native backend (the PowerShell window running `uvicorn` on **8001**).

2. Ensure **Ollama** is running on Windows and the model exists:
   ```powershell
   ollama list
   ```
   You should see `chipsutra-vlsi:3b`.

3. Ensure `backend\.env` has your **Atlas** `MONGO_URL`, `JWT_SECRET`, etc. (same as native).

4. From the repo root:
   ```powershell
   cd C:\path\to\ChipSutra
   docker compose -f docker-compose.backend-verilator.yml up --build
   ```
   First build can take several minutes (Verilator, Yosys, Python deps).

5. Verify:
   ```powershell
   curl http://localhost:8001/api/health
   ```
   Expect `"verilator": true` and `"ollama"` / model info OK.

6. Keep **frontend** as today (`frontend\.env` → `REACT_APP_BACKEND_URL=http://localhost:8001`). Run **Simulate → Lint → Run**.

**Storage note:** The container mounts `backend/storage`. Projects you created with native backend used the same folder if you ran from this clone; if data looks empty, you are still on the same Atlas DB — only **uploaded file blobs** might differ between paths. Re-upload RTL if needed.

**If Ollama from inside the container fails:** Docker Desktop → Settings → ensure **host.docker.internal** works (default on recent Docker Desktop). `backend/.env` must not override `OLLAMA_URL` to `127.0.0.1` when using this compose file (compose sets host gateway URL).

---

## Option B — Full stack in Docker

When Docker Hub pulls work:

```powershell
docker compose -f docker-compose.atlas.yml up --build
```

Uses container Ollama + your Atlas `MONGO_URL` from `.env`. Frontend is on **http://localhost:3000** (nginx in Docker). You can stop the native frontend to avoid port 3000 conflicts.

Pull issues: [DOCKER_PULL_TROUBLESHOOTING.md](./DOCKER_PULL_TROUBLESHOOTING.md).

---

## Option C — WSL2 Ubuntu (no Docker for backend)

Run the Python backend **inside Linux** with apt Verilator; keep Ollama on Windows.

1. Open Ubuntu from the Start menu (WSL2).

2. Install tools:
   ```bash
   sudo apt update
   sudo apt install -y verilator yosys z3 build-essential python3 python3-pip python3-venv git
   ```

3. Clone or use the Windows copy:
   ```bash
   cd /mnt/c/Users/YOURUSER/Desktop/chipsutra_clone_test/ChipSutra
   ```
   (Or clone fresh under `~/ChipSutra` in WSL.)

4. Copy/env: use the same `backend/.env` (Atlas `MONGO_URL` works from WSL).

5. Point Ollama at the **Windows host** (Ollama app on Windows):
   ```bash
   export OLLAMA_URL=http://$(grep nameserver /etc/resolv.conf | awk '{print $2}'):11434
   export OLLAMA_MODEL=chipsutra-vlsi:3b
   curl -s "$OLLAMA_URL/api/tags" | head
   ```

6. Python deps + run API:
   ```bash
   cd backend
   pip3 install -r requirements-oss.txt
   python3 -m uvicorn server:app --host 0.0.0.0 --port 8001
   ```

7. On Windows, stop native `uvicorn` if it was on 8001. Health check from PowerShell:
   ```powershell
   curl http://localhost:8001/api/health
   ```
   WSL2 usually exposes the port to Windows as `localhost:8001`.

8. Frontend stays on Windows → `REACT_APP_BACKEND_URL=http://localhost:8001`.

---

## Simulation expectations (CAN / UVM)

- **Lint** on RTL `.v`/`.sv` is the best first test with Verilator.
- **Compile + Run** needs a **simple SV testbench**; full **UVM** often will not build in Verilator.
- Generated UVM from the LLM is for editing and vendor sims; download, simplify, or lint RTL only for Verilator.

---

## Quick troubleshooting

| Symptom | Fix |
|---------|-----|
| Still `mock` / `verilator: false` | API not running in Docker/WSL; native Windows uvicorn still active |
| Backend crash on startup (Mongo) | Use **Atlas** `mongodb+srv://...` in `backend/.env` (not `localhost` in Docker). Remove stray quotes or rebuild after server env fix. Run `docker compose ... run --rm backend python3 -c "import os; print(os.environ.get('MONGO_URL','')[:40])"` — should start with `mongodb+srv` |
| Port 8001 in use | Stop other backend; one listener only |
| Ollama errors from Docker backend | Use `docker-compose.backend-verilator.yml`; check `host.docker.internal` |
| Lint errors on CAN RTL | Normal — read Verilator log lines; fix RTL or set **top module** |
