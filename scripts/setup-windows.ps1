# ChipSutra Windows setup — env, Docker (winget), optional compose start
param(
    [switch]$InstallDependencies,
    [switch]$Start,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Test-Cmd($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Ensure-Winget {
    if (Test-Cmd winget) { return $true }
    Write-Host 'winget not found. Install App Installer from Microsoft Store, or install Docker manually:'
    Write-Host '  https://docs.docker.com/desktop/setup/install/windows-install/'
    return $false
}

function Ensure-Docker {
    if (Test-Cmd docker) {
        try {
            docker info 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $true }
        } catch {}
        Write-Host 'Docker CLI exists but the engine is not running. Start Docker Desktop, wait for Engine running, then re-run with -Start.'
        return $false
    }
    if (-not $InstallDependencies) {
        Write-Host 'Docker is not installed. Re-run with -InstallDependencies to install via winget:'
        Write-Host '  .\scripts\setup-windows.ps1 -InstallDependencies'
        Write-Host 'Or: https://docs.docker.com/desktop/setup/install/windows-install/'
        return $false
    }
    if (-not (Ensure-Winget)) { return $false }
    Write-Host 'Installing Docker Desktop via winget (approve UAC if prompted)...'
    winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    Write-Host ''
    Write-Host 'Docker Desktop installed. RESTART Windows or log out/in, start Docker Desktop, then run:'
    Write-Host "  cd $Root"
    Write-Host '  .\scripts\setup-windows.ps1 -Start'
    return $false
}

if (-not $SkipBootstrap) {
    & (Join-Path $Root 'scripts\bootstrap.ps1')
}

if (-not (Ensure-Docker)) {
    exit 0
}

Write-Host 'Docker OK.'

if ($Start) {
    Write-Host 'Starting ChipSutra (first run downloads images + VLSI model; may take 15+ minutes)...'
    docker compose up --build
} else {
    Write-Host 'Next: .\scripts\setup-windows.ps1 -Start'
    Write-Host '  or: docker compose up --build'
}
