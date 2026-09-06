# ChipSutra local Windows tester: start / stop / status / desktop app.
# Usage (repo root or this folder):
#   .\scripts\chipsutra-local.ps1 -App
#   .\scripts\chipsutra-local.ps1 -Start
#   .\scripts\chipsutra-local.ps1 -Stop
#   .\scripts\chipsutra-local.ps1 -Status
#   .\scripts\chipsutra-local.ps1 -Shortcut
param(
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$App,
    [switch]$Shortcut,
    [int]$HealthRetries = 45
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"
$Pyw = Join-Path $Backend ".venv\Scripts\pythonw.exe"
$RunBackend = Join-Path $Backend "run-backend.ps1"
$FrontendEnv = Join-Path $Frontend ".env"
$FrontendEnvExample = Join-Path $Frontend ".env.example"

function Test-Url([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500)
    } catch { return $false }
}

function Get-ListenPids([int]$Port) {
    $ids = @()
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($c in $conns) {
            if ($c.OwningProcess -and $c.OwningProcess -ne 0) { $ids += [int]$c.OwningProcess }
        }
    } catch {}
    return $ids | Select-Object -Unique
}

function Stop-Port([int]$Port) {
    foreach ($procId in (Get-ListenPids $Port)) {
        try { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue } catch {}
    }
}

function Ensure-FrontendEnv {
    if (-not (Test-Path $FrontendEnv)) {
        if (Test-Path $FrontendEnvExample) {
            Copy-Item $FrontendEnvExample $FrontendEnv
        } else {
            Set-Content -Path $FrontendEnv -Value "REACT_APP_BACKEND_URL=http://localhost:8001`n" -Encoding ascii
        }
    }
}

function Get-NpmCmd {
    $cmd = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
    if (Test-Path $cmd) { return $cmd }
    $found = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $found = Get-Command npm -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    return $null
}

function Start-BackendProc {
    if (Test-Url "http://127.0.0.1:8001/api/health") {
        Write-Host "[chipsutra] backend already up"
        return
    }
    if (-not (Test-Path $Py)) {
        throw "Missing backend\.venv. Create it with: py -3.12 -m venv backend\.venv then pip install -r backend\requirements-oss.txt"
    }
    if (-not $env:OLLAMA_URL) { $env:OLLAMA_URL = "http://127.0.0.1:11434" }
    if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "chipsutra-vlsi:7b" }
    if (-not $env:CHIPSUTRA_PREFER_7B) { $env:CHIPSUTRA_PREFER_7B = "true" }
    if (-not $env:CHIPSUTRA_VERIFY_TB) { $env:CHIPSUTRA_VERIFY_TB = "auto" }
    $tools = Join-Path $Backend "tools"
    if ((Test-Path $tools) -and ($env:PATH -notlike "*$tools*")) { $env:PATH = "$tools;$env:PATH" }
    Write-Host "[chipsutra] starting backend :8001"
    if (Test-Path $RunBackend) {
        Start-Process -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $RunBackend
        ) -WorkingDirectory $Backend -WindowStyle Minimized | Out-Null
    } else {
        Start-Process -FilePath $Py -ArgumentList @(
            "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"
        ) -WorkingDirectory $Backend -WindowStyle Minimized | Out-Null
    }
}

function Start-FrontendProc {
    if (Test-Url "http://127.0.0.1:3000") {
        Write-Host "[chipsutra] frontend already up"
        return
    }
    Ensure-FrontendEnv
    $npm = Get-NpmCmd
    if (-not $npm) { throw "npm not found. Install Node.js 20+ from https://nodejs.org" }
    if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
        Write-Host "[chipsutra] installing frontend packages (first run)..."
        & $npm "install" --prefix $Frontend
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    }
    $env:BROWSER = "none"
    $env:PORT = "3000"
    Write-Host "[chipsutra] starting frontend :3000"
    Start-Process -FilePath $npm -ArgumentList @("start") -WorkingDirectory $Frontend -WindowStyle Minimized | Out-Null
}

function Wait-Healthy {
    $be = $false
    $fe = $false
    for ($i = 1; $i -le $HealthRetries; $i++) {
        $be = Test-Url "http://127.0.0.1:8001/api/health"
        $fe = Test-Url "http://127.0.0.1:3000"
        if ($be -and $fe) {
            Write-Host "[chipsutra] ready - http://localhost:3000   API http://localhost:8001/api/health"
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Warning "[chipsutra] timed out (backend=$be frontend=$fe). Check minimized console windows."
    return $false
}

function Get-AdminHint {
    $envPath = Join-Path $Backend ".env"
    $email = "admin@chipsutra.local"
    if (Test-Path $envPath) {
        foreach ($line in Get-Content $envPath) {
            if ($line -like "ADMIN_EMAIL=*") {
                $raw = $line.Split("=", 2)[1].Trim()
                $email = $raw.Trim([char]34).Trim([char]39)
            }
        }
    }
    return $email
}

function Write-Status {
    $ollama = Test-Url "http://127.0.0.1:11434/api/tags"
    $be = Test-Url "http://127.0.0.1:8001/api/health"
    $fe = Test-Url "http://127.0.0.1:3000"
    $obj = [ordered]@{
        backend  = $be
        frontend = $fe
        ollama   = $ollama
        portal   = "http://localhost:3000"
        api      = "http://localhost:8001/api/health"
        admin    = Get-AdminHint
        venv     = (Test-Path $Py)
    }
    $obj | ConvertTo-Json -Compress
}

function New-DesktopShortcut {
    $bat = Join-Path $Root "ChipSutra-Local.bat"
    $lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "ChipSutra Local.lnk"
    $w = New-Object -ComObject WScript.Shell
    $s = $w.CreateShortcut($lnk)
    $s.TargetPath = $bat
    $s.WorkingDirectory = $Root
    $s.WindowStyle = 7
    $s.Description = "ChipSutra local tester"
    $s.Save()
    Write-Host "[chipsutra] desktop shortcut: $lnk"
}

function Start-App {
    $exe = if (Test-Path $Pyw) { $Pyw } elseif (Test-Path $Py) { $Py } else { $null }
    if (-not $exe) { throw "Missing backend\.venv - cannot open the local app." }
    $gui = Join-Path $PSScriptRoot "chipsutra_local_app.py"
    Start-Process -FilePath $exe -ArgumentList @($gui) -WorkingDirectory $Root | Out-Null
}

if ($App) { Start-App; return }
if ($Shortcut) { New-DesktopShortcut; return }
if ($Status) { Write-Status; return }
if ($Stop) {
    Write-Host "[chipsutra] stopping listeners on :8001 and :3000 (Ollama stays up)"
    Stop-Port 8001
    Stop-Port 3000
    Start-Sleep -Seconds 1
    Write-Status
    return
}
if ($Start -or (-not ($Start -or $Stop -or $Status -or $App -or $Shortcut))) {
    Start-BackendProc
    Start-FrontendProc
    $ok = Wait-Healthy
    if ($ok) { Start-Process "http://localhost:3000" | Out-Null }
    if ($ok) { exit 0 } else { exit 1 }
}
