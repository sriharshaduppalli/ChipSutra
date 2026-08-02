# Step 1 — MongoDB Atlas (online database for ChipSutra)

ChipSutra is designed for **online MongoDB Atlas**, not local Mongo, so every user can share the same backend.

**Important:** End users never talk to MongoDB. Only the ChipSutra API does.  
So Atlas Network Access must allow the **machine (or cloud host) running the API** — not each browser user’s IP.

---

## Why the API “keeps crashing”

Startup **requires** a successful Atlas `ping`. If Atlas refuses the connection, uvicorn exits and Docker restart-loops.

The usual error is:

```text
SSL: TLSV1_ALERT_INTERNAL_ERROR
```

On Atlas this almost always means **your public IPv4 is not in Network Access** (not a bad password, and not “broken SSL certs”).  
Home/ISP IPs change often → yesterday’s `/32` entry stops working → API dies again until you re-whitelist.

**Permanent fix for product / all users / dynamic IP:** allow **`0.0.0.0/0`** (Access from Anywhere).

---

## 1. Create an Atlas account and cluster

1. Open https://www.mongodb.com/cloud/atlas/register  
2. Sign up and create an organization/project if prompted.  
3. **Build a database** → choose **M0 FREE** → pick a cloud region close to you → **Create**.

Wait until the cluster status is **Available** (a few minutes).

---

## 2. Database user (username + password)

1. Left menu → **Database Access** → **Add New Database User**.  
2. Authentication: **Password**.  
3. Choose a **username** and **strong password** (save them).  
4. Role: **Atlas admin** or **Read and write to any database** (dev).  
5. **Add User**.

---

## 3. Network access (required for online multi-user)

1. Open https://cloud.mongodb.com/ → your project → **Network Access**.  
2. **Add IP Address**.  
3. Choose **Allow Access from Anywhere** → CIDR **`0.0.0.0/0`** → Confirm.  
4. Wait until the entry shows **Active** (often 1–2 minutes).

| Goal | Network Access |
|------|----------------|
| Product / many users / home ISP changes | **`0.0.0.0/0`** |
| Fixed cloud VM only | That host’s egress IPv4 `/32` |
| Single laptop, IP never changes | Current IP `/32` (fragile) |

Check the IPv4 Atlas sees from your API host:

```powershell
curl https://api.ipify.org
```

---

## 4. Get the connection string

1. Left menu → **Database** → **Connect** on your cluster.  
2. **Drivers** → driver **Python**, version **3.12 or later**.  
3. Copy the connection string. It looks like:

```text
mongodb+srv://myuser:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

4. Replace `<password>` with your real password.  
5. Prefer a database name in the path:

```text
mongodb+srv://myuser:MyEncodedPass@cluster0.xxxxx.mongodb.net/chipsutra_db?retryWrites=true&w=majority
```

**Special characters in password:** URL-encode them (`@` → `%40`, `#` → `%23`, etc.).  
https://www.mongodb.com/docs/atlas/troubleshoot-connection/

---

## 5. Put it in ChipSutra

Edit `backend/.env` (not PowerShell `$env:` for long-term config):

```env
MONGO_URL="mongodb+srv://myuser:YOUR_ENCODED_PASSWORD@cluster0.xxxxx.mongodb.net/chipsutra_db?retryWrites=true&w=majority"
DB_NAME="chipsutra_db"
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=chipsutra-vlsi:3b
```

Optional startup resilience (default: 8 tries × 5s) while Atlas whitelist propagates:

```env
MONGO_STARTUP_RETRIES=8
MONGO_STARTUP_RETRY_SEC=5
```

---

## 6. Verify

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\test_mongo_connect.py
```

Expect `raw TLS OK` and `pymongo [certifi]: OK`.

Then start the API:

```powershell
.\run-backend.ps1
```

Browser: http://localhost:8001/api/health — `"mongo":{"ok":true}` and `"status":"healthy"`.

Frontend: `REACT_APP_BACKEND_URL=http://localhost:8001`.

---

## SSL handshake errors (`TLSV1_ALERT_INTERNAL_ERROR`)

### 1. Network Access (most common) — do this first

1. Atlas → **Network Access** → ensure an **Active** `0.0.0.0/0` entry (or your current IPv4 `/32`).  
2. Wait 1–2 minutes.  
3. Re-run `python scripts/test_mongo_connect.py`.

If **raw TLS** to `*.mongodb.net:27017` fails with the same alert, whitelist/VPN is the cause — not Python certifi.

### 2. Connection string

Use the Atlas **Drivers** string; URL-encode the password; set `DB_NAME` to match.

### 3. Python version (Windows native)

Use **Python 3.11 or 3.12** (`.\run-backend.ps1`). Avoid **3.14** for Atlas on Windows.

### 4. VPN / antivirus

Disable VPN or HTTPS scanning temporarily and retry.

### 5. Docker backend + Atlas

```powershell
docker compose -f docker-compose.atlas.yml up --build
```

with Atlas `MONGO_URL` in `backend/.env`. Same Network Access rule applies to the **Docker host egress IP** (still use `0.0.0.0/0` if unsure).

ChipSutra sets `tlsCAFile` via **certifi** for `mongodb+srv://` automatically and retries Mongo on startup.

---

## Architecture reminder

```text
[Users anywhere] → ChipSutra API (:8001) → MongoDB Atlas
```

Allowing `0.0.0.0/0` on Atlas does **not** expose your database to browsers; it only lets the API’s outbound connection succeed from any egress IP. Protect data with a strong DB user password and (in production) tighten to your cloud provider’s known egress ranges when those are stable.

---

## Next steps

- **Native Windows:** [docs/OPEN_SOURCE.md](./OPEN_SOURCE.md) + `.\run-backend.ps1`  
- **Docker without local mongo image:** `docker compose -f docker-compose.atlas.yml up --build`  
- After Network Access shows Active: `python scripts/test_mongo_connect.py` then start the API
