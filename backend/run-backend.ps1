# Start ChipSutra API with Python 3.12 venv (avoids Windows Python 3.14 + Atlas TLS issues).
$ErrorActionPreference = "Stop"
$Backend = $PSScriptRoot
$Py = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "Creating .venv with Python 3.12..."
    py -3.12 -m venv (Join-Path $Backend ".venv")
    & $Py -m pip install -r (Join-Path $Backend "requirements-oss.txt")
}

Write-Host "Using:" (& $Py --version)
# Prefer 7B ChipSutra-VLSI for TB quality (falls back to 3b via router if missing).
if (-not $env:OLLAMA_URL) { $env:OLLAMA_URL = "http://127.0.0.1:11434" }
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "chipsutra-vlsi:7b" }
if (-not $env:CHIPSUTRA_PREFER_7B) { $env:CHIPSUTRA_PREFER_7B = "true" }
if (-not $env:CHIPSUTRA_VERIFY_TB) { $env:CHIPSUTRA_VERIFY_TB = "auto" }
# WSL Verilator shim (backend\tools\verilator.bat) → enables the auto compile gate.
$Tools = Join-Path $Backend "tools"
if ((Test-Path $Tools) -and ($env:PATH -notlike "*$Tools*")) { $env:PATH = "$Tools;$env:PATH" }
Set-Location $Backend
& $Py -m uvicorn server:app --host 0.0.0.0 --port 8001 @args
