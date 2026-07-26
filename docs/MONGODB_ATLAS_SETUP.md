# Step 1 — MongoDB Atlas (free database for ChipSutra)

Use this when you **do not run Mongo in Docker** (native Windows setup or `docker-compose.atlas.yml`).

ChipSutra stores users, projects, and generations in MongoDB. Atlas free tier (M0) is enough for development.

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

## 3. Network access (allow your PC)

1. Left menu → **Network Access** → **Add IP Address**.  
2. For local dev: **Allow access from anywhere** → `0.0.0.0/0`  
   (Tighten this in production.)  
3. **Confirm**.

---

## 4. Get the connection string

1. Left menu → **Database** → **Connect** on your cluster.  
2. **Drivers** → driver **Python**, version **3.12 or later**.  
3. Copy the connection string. It looks like:

```text
mongodb+srv://myuser:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

4. Replace `<password>` with your real password.  
5. Add a database name before `?` or in the path, e.g. `chipsutra_db`:

```text
mongodb+srv://myuser:MyEncodedPass@cluster0.xxxxx.mongodb.net/chipsutra_db?retryWrites=true&w=majority
```

**Special characters in password:** URL-encode them (`@` → `%40`, `#` → `%23`, etc.).  
https://www.mongodb.com/docs/atlas/troubleshoot-connection/

---

## 5. Put it in ChipSutra (Windows — edit file, not PowerShell)

PowerShell does **not** use `MONGO_URL=...` on the command line. Edit the file:

```powershell
cd C:\Users\sriha\Desktop\chipsutra_clone_test\ChipSutra
notepad backend\.env
```

Set (with your real string):

```env
MONGO_URL="mongodb+srv://myuser:YOUR_ENCODED_PASSWORD@cluster0.xxxxx.mongodb.net/chipsutra_db?retryWrites=true&w=majority"
DB_NAME="chipsutra_db"
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=chipsutra-vlsi:3b
```

Save and close.

---

## 6. Verify (after backend is running)

```powershell
cd backend
python -m uvicorn server:app --host 0.0.0.0 --port 8001
```

If MongoDB is wrong, startup will log a connection error. Fix `MONGO_URL` and try again.

Browser: http://localhost:8001/api/health — should return `"status": "healthy"`.

---

## SSL handshake errors (`TLSV1_ALERT_INTERNAL_ERROR`)

If startup fails with **SSL handshake failed** to `*.mongodb.net`:

### 1. Atlas Network Access (most common)

Atlas often returns **`TLSV1_ALERT_INTERNAL_ERROR`** when your **IP is not allowed** — not because Python or certificates are wrong.

1. Open [MongoDB Atlas](https://cloud.mongodb.com/) → your project → **Network Access**.
2. **Add IP Address** → **Add Current IP Address**, or for local dev only: **Allow Access from Anywhere** (`0.0.0.0/0`).
3. Wait **1–2 minutes**, then retry.

Check your public IPv4 (Atlas whitelist is usually IPv4):

```powershell
curl -4 https://ifconfig.me/ip
```

Add that address as `/32` in Network Access if you do not use `0.0.0.0/0`.

Diagnostic (does not print your password):

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python scripts/test_mongo_connect.py
```

If **raw TLS** to the shard host fails with the same alert, whitelist/VPN is the fix — not certifi.

### 2. Connection string

Use the Atlas **Drivers** string and include the database name:

```env
MONGO_URL="mongodb+srv://USER:PASS@cluster....mongodb.net/chipsutra_db?retryWrites=true&w=majority"
DB_NAME=chipsutra_db
```

URL-encode special characters in the password.

### 3. Python version (Windows)

Use **Python 3.11 or 3.12** for the backend. **Python 3.14** can also fail TLS with Atlas on Windows.

```powershell
cd ChipSutra\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-oss.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8001
```

### 4. VPN / antivirus

Disable VPN or “HTTPS scanning” temporarily and retry.

### 5. Dev fallback — local MongoDB in Docker

If Atlas is blocked on your network, run Mongo locally and point the backend at it:

```powershell
cd ChipSutra
docker compose up mongo -d
```

In `backend/.env`:

```env
MONGO_URL=mongodb://127.0.0.1:27017
DB_NAME=chipsutra_db
```

Then start uvicorn again. (Data is separate from Atlas.)

### 6. Docker backend + Atlas

Run the API in Linux container: `docker compose -f docker-compose.atlas.yml up --build` with Atlas `MONGO_URL` in `backend/.env`.

ChipSutra sets `tlsCAFile` via **certifi** for `mongodb+srv://` URLs automatically.

---

## Next steps

- **Native Windows (no Docker):** [docs/OPEN_SOURCE.md](./OPEN_SOURCE.md) + `.\setup-native.ps1`  
- **Docker without mongo image:** `docker compose -f docker-compose.atlas.yml up --build`  
- **Full native run:** backend `uvicorn` + frontend `yarn start` — see [OPEN_SOURCE.md](./OPEN_SOURCE.md)
