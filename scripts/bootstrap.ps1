$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $Root "backend\.env"
$Example = Join-Path $Root "backend\.env.example"

if (-not (Test-Path $Example)) {
  Write-Error "Missing $Example - are you in the ChipSutra repo root?"
}

if (-not (Test-Path $EnvPath)) {
  Copy-Item $Example $EnvPath
  Write-Host "[chipsutra] Created backend\.env - set JWT_SECRET and ADMIN_PASSWORD before a public deploy."
} else {
  Write-Host "[chipsutra] backend\.env already exists."
}

Write-Host "Next: docker compose up --build"
