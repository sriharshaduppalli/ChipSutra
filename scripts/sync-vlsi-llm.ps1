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
$know = Join-Path $Root 'backend\knowledge'
New-Item -ItemType Directory -Force -Path $know | Out-Null
$prompts = Join-Path $SourceRepo 'prompts'
$ragFiles = @(
  'vlsi_protocols_compact.txt',
  'vlsi_soc_dft_power.txt',
  'vlsi_verification_glossary.txt',
  'covergroup_patterns.txt'
)
foreach ($name in $ragFiles) {
  $src = Join-Path $prompts $name
  if (Test-Path $src) {
    Copy-Item -Force $src (Join-Path $know $name)
    Write-Host "[sync] updated backend/knowledge/$name"
  }
}

Write-Host "[sync] updated $Dest"
Write-Host "[sync] VERSION=$((Get-Content (Join-Path $Dest 'VERSION') -ErrorAction SilentlyContinue))"
