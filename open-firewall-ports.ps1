# =============================================================
# IITB Security System - Open Firewall Ports
# RIGHT-CLICK this file -> "Run as Administrator"
# =============================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  IITB Security System -- Opening Firewall Ports           " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")
if (-not $isAdmin) {
    Write-Host "  ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "  Right-click the file and choose 'Run as Administrator'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "  Running as Administrator -- OK" -ForegroundColor Green
Write-Host ""

$rules = @(
    @{ Name="IITB Backend API";       Port=8000; Proto="TCP"; Desc="FastAPI backend (phone page + detection API)" },
    @{ Name="IITB MediaMTX RTSP";     Port=8554; Proto="TCP"; Desc="RTSP relay (video stream)" },
    @{ Name="IITB MediaMTX RTSP UDP"; Port=8554; Proto="UDP"; Desc="RTSP relay UDP" },
    @{ Name="IITB MediaMTX WHIP TCP"; Port=8889; Proto="TCP"; Desc="WebRTC/WHIP ingest (phone camera push)" },
    @{ Name="IITB MediaMTX WHIP UDP"; Port=8889; Proto="UDP"; Desc="WebRTC/WHIP ingest UDP" },
    @{ Name="IITB MediaMTX ICE UDP";  Port=8189; Proto="UDP"; Desc="WebRTC ICE media packets UDP" }
)

foreach ($rule in $rules) {
    Write-Host "  Opening port $($rule.Port)/$($rule.Proto) -- $($rule.Desc)" -ForegroundColor Yellow
    # Remove old rule if exists (ignore errors)
    netsh advfirewall firewall delete rule name="$($rule.Name)" | Out-Null 2>&1
    # Add fresh rule
    $result = netsh advfirewall firewall add rule `
        name="$($rule.Name)" `
        protocol=$($rule.Proto) `
        dir=in `
        localport=$($rule.Port) `
        action=allow 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "    OK" -ForegroundColor Green
    } else {
        Write-Host "    WARNING: $result" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  All ports opened!                                         " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    1. Run .\start-all.ps1  (start the full system)" -ForegroundColor DarkGray
Write-Host "    2. Run .\start-mobile-stream.ps1  (get phone URL)" -ForegroundColor DarkGray
Write-Host "    3. Before opening URL on phone, verify backend is" -ForegroundColor DarkGray
Write-Host "       reachable: open http://YOUR_IP:8000/health" -ForegroundColor DarkGray
Write-Host "       in the phone browser -- should show: ok" -ForegroundColor DarkGray
Write-Host ""

Read-Host "Press Enter to exit"
