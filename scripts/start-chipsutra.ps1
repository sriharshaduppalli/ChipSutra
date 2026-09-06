# Start ChipSutra frontend + backend with basic supervision (restart on crash).
# Usage (from repo root):
#   .\scripts\start-chipsutra.ps1
#   .\scripts\start-chipsutra.ps1 -Once   # no restart loop
param(
    [switch]$Once,
    [int]$HealthRetries = 30
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }

function Test-Url($Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -ge 200 -and $r.StatusCode -lt 500
    } catch { return $false }
}

function Start-Backend {
    Write-Host "[chipsutra] starting backend :8001"
    $env:OLLAMA_URL = if ($env:OLLAMA_URL) { $env:OLLAMA_URL } else { "http://127.0.0.1:11434" }
    $env:OLLAMA_MODEL = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "chipsutra-vlsi:7b" }
    $env:CHIPSUTRA_PREFER_7B = if ($env:CHIPSUTRA_PREFER_7B) { $env:CHIPSUTRA_PREFER_7B } else { "true" }
    $env:CHIPSUTRA_VERIFY_TB = if ($env:CHIPSUTRA_VERIFY_TB) { $env:CHIPSUTRA_VERIFY_TB } else { "auto" }
    $Tools = Join-Path $Backend "tools"
    if ((Test-Path $Tools) -and ($env:PATH -notlike "*$Tools*")) { $env:PATH = "$Tools;$env:PATH" }
    return Start-Process -FilePath $Py -ArgumentList @("-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001") `
        -WorkingDirectory $Backend -PassThru -WindowStyle Minimized
}

function Start-Frontend {
    Write-Host "[chipsutra] starting frontend :3000"
    $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source
    if (-not $npm) { throw "npm not found on PATH" }
    return Start-Process -FilePath $npm -ArgumentList @("start") `
        -WorkingDirectory $Frontend -PassThru -WindowStyle Minimized
}

function Wait-Healthy {
    for ($i = 1; $i -le $HealthRetries; $i++) {
        $be = Test-Url "http://127.0.0.1:8001/api/health"
        $fe = Test-Url "http://127.0.0.1:3000"
        if ($be -and $fe) {
            Write-Host "[chipsutra] healthy — http://localhost:3000  (API http://localhost:8001/api/health)"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Warning "[chipsutra] health check timed out (backend=$be frontend=$fe) — check windows"
    return $false
}

$beProc = $null
$feProc = $null
try {
    if (-not (Test-Url "http://127.0.0.1:8001/api/health")) {
        $beProc = Start-Backend
    } else {
        Write-Host "[chipsutra] backend already up"
    }
    if (-not (Test-Url "http://127.0.0.1:3000")) {
        $feProc = Start-Frontend
    } else {
        Write-Host "[chipsutra] frontend already up"
    }
    Wait-Healthy | Out-Null

    if ($Once) {
        Write-Host "[chipsutra] -Once: leaving processes running; exiting supervisor"
        return
    }

    Write-Host "[chipsutra] supervisor running — Ctrl+C to stop watching (child processes keep running unless you close them)"
    while ($true) {
        Start-Sleep -Seconds 5
        if (-not (Test-Url "http://127.0.0.1:8001/api/health")) {
            Write-Warning "[chipsutra] backend down — restarting"
            if ($beProc -and -not $beProc.HasExited) { try { Stop-Process -Id $beProc.Id -Force } catch {} }
            $beProc = Start-Backend
        }
        if (-not (Test-Url "http://127.0.0.1:3000")) {
            Write-Warning "[chipsutra] frontend down — restarting"
            if ($feProc -and -not $feProc.HasExited) { try { Stop-Process -Id $feProc.Id -Force } catch {} }
            $feProc = Start-Frontend
        }
    }
} finally {
    # Leave children running so a closed supervisor does not kill the portal mid-use.
}
