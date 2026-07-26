# Print the IPv4 to whitelist in MongoDB Atlas (Network Access).
$ErrorActionPreference = "Stop"
try {
    $ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing -TimeoutSec 10).Content.Trim()
} catch {
    Write-Host "Could not fetch public IP. Open https://api.ipify.org in a browser."
    exit 1
}
Write-Host ""
Write-Host "MongoDB Atlas -> Network Access -> Add IP Address"
Write-Host "  $ip/32"
Write-Host ""
Write-Host "Dev shortcut (less secure): Allow Access from Anywhere -> 0.0.0.0/0"
Write-Host "Wait 1-2 minutes after saving, then restart the backend."
Write-Host ""
Write-Host "Your Wi-Fi IP may change (mobile hotspot). Re-run this script when Atlas fails again."
