# Community Edition validation (Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "[1/4] docker compose syntax..."
docker compose config --quiet

Write-Host "[2/4] pip install OSS requirements..."
python -m pip install -q -r backend/requirements-oss.txt

Write-Host "[3/4] pytest offline..."
Set-Location backend
python -m pytest tests/test_iteration_5.py -n 0 `
  -k "docker_compose or env_example or requirements or readme or available_providers or stream_chat"

Set-Location $Root
Write-Host "[4/4] modelfiles..."
if (-not (Test-Path "models/chipsutra-vlsi/Modelfile.3b")) { throw "missing Modelfile.3b" }

Write-Host "OK - community validation passed."
