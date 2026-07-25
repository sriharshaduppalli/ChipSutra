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

## Next steps

- **Native Windows (no Docker):** [docs/OPEN_SOURCE.md](./OPEN_SOURCE.md) + `.\setup-native.ps1`  
- **Docker without mongo image:** `docker compose -f docker-compose.atlas.yml up --build`  
- **Full native run:** backend `uvicorn` + frontend `yarn start` — see [OPEN_SOURCE.md](./OPEN_SOURCE.md)
