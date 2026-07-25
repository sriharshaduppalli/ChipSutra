# What Git can (and cannot) install for you

ChipSutra repos **automate everything that runs after** platform tools exist. We **cannot** commit Docker Desktop or Ollama binaries into Git (size, license, OS-specific builds).

## Automated from the repo

| Script | Repo | Does |
|--------|------|------|
| `scripts/setup-windows.ps1` | ChipSutra | Offers `winget` install for **Docker Desktop**, runs `bootstrap`, optional `docker compose up` |
| `scripts/setup.sh` | ChipSutra | Checks Docker, bootstrap, optional compose (Linux/macOS) |
| `scripts/bootstrap.ps1` / `.sh` | ChipSutra | Creates `backend/.env` |
| `models/chipsutra-vlsi/` + compose | ChipSutra | Builds **ChipSutra-VLSI** inside Docker (no separate LLM repo clone) |
| `scripts/setup-windows.ps1` | ChipSutra-VLSI-LLM | Offers `winget` install for **Ollama**, builds model tags |
| `scripts/create-all.ps1` | ChipSutra-VLSI-LLM | `ollama pull` + `ollama create` |

## One command (Windows, after clone)

```powershell
cd ChipSutra
.\scripts\setup-windows.ps1 -InstallDependencies
```

If Docker was just installed, **restart Windows or log out/in**, open Docker Desktop, then:

```powershell
.\scripts\setup-windows.ps1 -Start
```

## One command (LLM only, no ChipSutra app)

```powershell
cd ChipSutra-VLSI-LLM
.\scripts\setup-windows.ps1 -InstallDependencies -Tag 3b
```

## Still manual once

- Approve **UAC** / **winget** prompts (Docker ~500MB+, Ollama ~100MB+ installer).
- **Docker Desktop** must be **running** (whale icon) before compose.
- **~6 GB RAM** for default `chipsutra-vlsi:3b`.
