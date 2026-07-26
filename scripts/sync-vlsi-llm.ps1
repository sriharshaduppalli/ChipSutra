# Sync vendored Modelfiles from ChipSutra-VLSI-LLM
param(
    [string]$SourceRepo = $env:CHIPSUTRA_VLSI_LLM_REPO
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dest = Join-Path $Root 'models\chipsutra-vlsi'

if (-not $SourceRepo) {
    $Tmp = Join-Path $env:TEMP ("chipsutra-vlsi-sync-" + [guid]::NewGuid().ToString())
    git clone --depth 1 https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM.git $Tmp
    $SourceRepo = $Tmp
    Write-Host "[sync] cloned upstream to temp"
}

$SrcModelfiles = Join-Path $SourceRepo 'modelfiles'
if (-not (Test-Path $SrcModelfiles)) { throw "Missing $SrcModelfiles" }

Copy-Item -Force (Join-Path $SrcModelfiles 'Modelfile.*') $Dest
$ver = Join-Path $SourceRepo 'VERSION'
if (Test-Path $ver) { Copy-Item -Force $ver (Join-Path $Dest 'VERSION') }

Write-Host "[sync] updated $Dest"
Write-Host "[sync] VERSION=$((Get-Content (Join-Path $Dest 'VERSION') -ErrorAction SilentlyContinue))"
