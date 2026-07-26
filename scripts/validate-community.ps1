# Community Edition validation (Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "[1/5] docker compose syntax..."
docker compose config --quiet
docker compose -f docker-compose.atlas.yml config --quiet
docker compose -f docker-compose.backend-verilator.yml config --quiet
docker compose -f docker-compose.prod.yml --env-file deploy/env.prod.example config --quiet

Write-Host "[2/5] pip install OSS requirements..."
python -m pip install -q -r backend/requirements-oss.txt

Write-Host "[3/5] pytest offline..."
Set-Location backend
python -m pytest tests/test_iteration_5.py tests/test_rag_and_golden.py tests/test_rtl_ports_and_feedback.py tests/test_eda_industry.py -n 0 `
  -k "docker_compose or env_example or requirements or readme or available_providers or stream_chat or rag or golden"

Set-Location $Root
Write-Host "[4/5] modelfiles..."
if (-not (Test-Path "models/chipsutra-vlsi/Modelfile.3b")) { throw "missing Modelfile.3b" }

Write-Host "[5/5] production templates..."
@(
  "docker-compose.prod.yml",
  "backend/.env.production.example",
  "deploy/Caddyfile",
  "models/chipsutra-vlsi/ollama-bootstrap.sh",
  "models/chipsutra-vlsi/VERSION"
) | ForEach-Object { if (-not (Test-Path $_)) { throw "missing $_" } }

Write-Host "OK - community validation passed."
