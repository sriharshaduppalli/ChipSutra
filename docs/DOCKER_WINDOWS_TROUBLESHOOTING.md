# Docker Desktop on Windows — "unable to start"

If `docker version` shows **Client** but **Server: ERROR** / *Docker Desktop is unable to start*, ChipSutra cannot run until the engine starts. Fix Docker first (below), then `.\setup.ps1 -Start`.

## 1. Enable required Windows features (Admin PowerShell)

```powershell
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
```

Restart Windows.

## 2. Install / update WSL2

```powershell
wsl --install
wsl --set-default-version 2
wsl --update
```

Restart again if prompted. Open **Ubuntu** (or any WSL distro) once from Start menu so it finishes setup.

## 3. Docker Desktop settings

1. Open **Docker Desktop** (Start menu).
2. **Settings → General** → enable **Use the WSL 2 based engine**.
3. **Settings → Resources → WSL Integration** → enable your distro.
4. **Apply & Restart**.

## 4. BIOS

Enable **Intel VT-x** / **AMD-V** (virtualization). Without it, the engine will not start.

## 5. Reset or reinstall Docker

- Docker Desktop → **Troubleshoot** (bug icon) → **Reset to factory defaults** (last resort).
- Or: uninstall Docker Desktop, restart, `winget install -e --id Docker.DockerDesktop`, restart, start Docker Desktop.

## 6. Verify

```powershell
docker info
```

Must succeed (no daemon error). Then:

```powershell
cd ChipSutra
.\setup.ps1 -Start
```

## No Docker? (advanced fallback)

Run MongoDB + Ollama natively and start backend/frontend manually — see [SELF_HOST.md](../SELF_HOST.md). ChipSutra-VLSI: [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) `.\setup.ps1 -InstallDependencies -Tag 3b`.
