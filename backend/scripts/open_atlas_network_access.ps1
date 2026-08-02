# Print current public IPv4 and open Atlas Network Access in the browser.
# Fix for TLSV1_ALERT_INTERNAL_ERROR / API crash-loops: allow 0.0.0.0/0 (or this IP/32).
$ErrorActionPreference = "Continue"
try {
    $ip = Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 10
    Write-Host "Public IPv4: $ip"
    Write-Host "Add in Atlas Network Access either:"
    Write-Host "  - Allow Access from Anywhere: 0.0.0.0/0   (recommended for multi-user / changing ISP)"
    Write-Host "  - or: $ip/32"
} catch {
    Write-Host "Could not detect public IP: $($_.Exception.Message)"
}
Start-Process "https://cloud.mongodb.com/v2#/security/network/accessList"
Write-Host "After the entry is Active (1-2 min), run:"
Write-Host "  cd backend; .\.venv\Scripts\python.exe scripts\test_mongo_connect.py"
Write-Host "Then: .\run-backend.ps1"
