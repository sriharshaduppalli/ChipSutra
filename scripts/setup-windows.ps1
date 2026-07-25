# ChipSutra Windows setup — env, Docker (winget), optional compose start
param(
    [switch]$InstallDependencies,
    [switch]$Start,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Refresh-SessionPath {
    $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Test-Cmd($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# True only if docker CLI exists AND the daemon responds (not winget's last exit code).
function Test-DockerEngine {
    Refresh-SessionPath
    if (-not (Test-Cmd docker)) { return $false }
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Ensure-Winget {
    if (Test-Cmd winget) { return $true }
    Write-Host 'winget not found. Install App Installer from Microsoft Store, or install Docker manually:'
    Write-Host '  https://docs.docker.com/desktop/setup/install/windows-install/'
    return $false
}

function Ensure-Docker {
    if (Test-DockerEngine) { return $true }

    if (Test-Cmd docker) {
        Write-Host 'Docker is installed but the engine is not running.'
        Write-Host '1. Open Docker Desktop from the Start menu'
        Write-Host '2. Wait until it says Engine running'
        Write-Host '3. Run: .\setup.ps1 -Start'
        return $false
    }

    if (-not $InstallDependencies) {
        Write-Host 'Docker is not on PATH in this PowerShell session.'
        Write-Host 'If you just installed it: RESTART Windows or open a NEW terminal, start Docker Desktop, then:'
        Write-Host '  .\setup.ps1 -Start'
        Write-Host 'If not installed yet:'
        Write-Host '  .\setup.ps1 -InstallDependencies'
        Write-Host 'Manual: https://docs.docker.com/desktop/setup/install/windows-install/'
        return $false
    }

    if (-not (Ensure-Winget)) { return $false }
    Write-Host 'Installing Docker Desktop via winget (approve UAC if prompted)...'
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    Refresh-SessionPath
    if (Test-DockerEngine) {
        Write-Host 'Docker engine is already running.'
        return $true
    }
    Write-Host ''
    Write-Host 'Docker Desktop installed. Required before -Start:'
    Write-Host '  1. RESTART Windows (or log out/in) — recommended'
    Write-Host '  2. Start Docker Desktop → wait for Engine running'
    Write-Host '  3. New PowerShell window, then:'
    Write-Host "     cd $Root"
    Write-Host '     .\setup.ps1 -Start'
    return $false
}

if (-not $SkipBootstrap) {
    & (Join-Path $Root 'scripts\bootstrap.ps1') -Quiet
}

if (-not (Ensure-Docker)) {
    exit 0
}

Write-Host 'Docker engine OK.'

if ($Start) {
    Write-Host 'Starting ChipSutra (first run downloads images + VLSI model; may take 15+ minutes)...'
    docker compose up --build
} else {
    Write-Host 'Next: .\setup.ps1 -Start'
}
