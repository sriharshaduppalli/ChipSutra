# Paste your MongoDB Atlas connection string (Connect -> Drivers in Atlas).
# Example shape: mongodb+srv://user:pass@cluster0.xxx.mongodb.net/chipsutra_db?retryWrites=true&w=majority
param(
    [Parameter(Mandatory = $true)]
    [string]$MongoUrl
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvPath = Join-Path $Root 'backend\.env'

if (-not (Test-Path $EnvPath)) {
    Copy-Item (Join-Path $Root 'backend\.env.example') $EnvPath
}

$content = Get-Content $EnvPath -Raw
if ($content -match '(?m)^MONGO_URL=.*$') {
    $content = $content -replace '(?m)^MONGO_URL=.*$', "MONGO_URL=`"$MongoUrl`""
} else {
    $content += "`nMONGO_URL=`"$MongoUrl`"`n"
}

Set-Content -Path $EnvPath -Value $content -NoNewline -Encoding utf8
Write-Host 'Updated backend\.env MONGO_URL.'
Write-Host 'Start backend: cd backend; python -m uvicorn server:app --host 0.0.0.0 --port 8001'
