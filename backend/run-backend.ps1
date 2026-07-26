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
Set-Location $Backend
& $Py -m uvicorn server:app --host 0.0.0.0 --port 8001 @args
