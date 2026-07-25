# ChipSutra on Windows WITHOUT Docker (Docker Hub blocked / EOF pulls).
# Uses: native Ollama + ChipSutra-VLSI model + MongoDB Atlas + local Python/React.
param(
    [switch]$InstallOllama,
    [switch]$BuildModel,
    [switch]$InstallPythonDeps
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Test-Cmd($n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }

& (Join-Path $Root 'scripts\bootstrap.ps1') -Quiet

Write-Host ''
Write-Host '=== ChipSutra native Windows setup (no Docker) ==='
Write-Host ''

if ($InstallOllama -or -not (Test-Cmd ollama)) {
    if (-not (Test-Cmd ollama)) {
        if (Test-Cmd winget) {
            Write-Host 'Installing Ollama via winget...'
            winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
            Write-Host 'Open a NEW PowerShell window after install, then re-run with -BuildModel -InstallPythonDeps'
            exit 0
        }
        Write-Host 'Install Ollama from https://ollama.com/download then re-run.'
        exit 1
    }
}

if ($BuildModel -or $InstallOllama) {
    $mf = Join-Path $Root 'models\chipsutra-vlsi\Modelfile.3b'
    if (-not (Test-Path $mf)) { Write-Error "Missing $mf" }
    Write-Host 'Pulling base model qwen2.5-coder:3b (Ollama CDN, not Docker Hub)...'
    ollama pull qwen2.5-coder:3b
    Write-Host 'Creating chipsutra-vlsi:3b ...'
    ollama create chipsutra-vlsi:3b -f $mf
    Write-Host 'Model ready.'
}

$envFile = Join-Path $Root 'backend\.env'
$envText = Get-Content $envFile -Raw
if ($envText -match 'MONGO_URL="mongodb://localhost' -or $envText -match "MONGO_URL=mongodb://localhost") {
    Write-Host ''
    Write-Host 'IMPORTANT: Set MongoDB Atlas in backend\.env'
    Write-Host '  MONGO_URL="mongodb+srv://USER:PASS@cluster....mongodb.net/chipsutra_db?retryWrites=true&w=majority"'
    Write-Host '  Free cluster: https://www.mongodb.com/cloud/atlas/register'
    Write-Host ''
}

if (-not ($envText -match 'OLLAMA_URL')) {
    Add-Content $envFile "`nOLLAMA_URL=http://127.0.0.1:11434`nOLLAMA_MODEL=chipsutra-vlsi:3b"
} else {
    Write-Host 'Ensure backend\.env has:'
    Write-Host '  OLLAMA_URL=http://127.0.0.1:11434'
    Write-Host '  OLLAMA_MODEL=chipsutra-vlsi:3b'
}

if ($InstallPythonDeps) {
    Write-Host 'Installing Python dependencies...'
    python -m pip install -r (Join-Path $Root 'backend\requirements-oss.txt')
}

Write-Host ''
Write-Host '=== Start ChipSutra (two terminals) ==='
Write-Host 'Terminal 1 - backend:'
Write-Host "  cd $Root\backend"
Write-Host '  python -m uvicorn server:app --host 0.0.0.0 --port 8001'
Write-Host ''
Write-Host 'Terminal 2 - frontend:'
Write-Host "  cd $Root\frontend"
Write-Host '  yarn install'
Write-Host '  yarn start'
Write-Host ''
Write-Host 'Open http://localhost:3000  (API health: http://localhost:8001/api/health)'
Write-Host 'Note: Verilator sim in Docker needs Linux; AI Generate works natively on Windows.'
