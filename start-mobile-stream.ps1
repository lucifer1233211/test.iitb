# =============================================================
# IITB Security System - Mobile Phone Stream Quick-Start
# Works from ANYWHERE -- even different WiFi or mobile data.
# =============================================================

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   IITB Security System -- Mobile Stream (Any Network)     " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Start MediaMTX relay ─────────────────────────────────────────────
Write-Host "[1/5] Starting MediaMTX relay..." -ForegroundColor Yellow
Set-Location -Path $ScriptDir
# Run docker compose with Continue so stderr status messages don't cause a fatal error
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
docker compose up mediamtx -d 2>&1 | ForEach-Object { $_ } | Out-Null
$ErrorActionPreference = $prev
Start-Sleep -Seconds 2
$mediamtxRunning = docker ps --filter "name=mediamtx" --filter "status=running" -q
if ($mediamtxRunning) {
    Write-Host "  OK: MediaMTX is running" -ForegroundColor Green
} else {
    Write-Host "  ERROR: MediaMTX failed to start. Is Docker Desktop running?" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# ── Step 2: Find/Download cloudflared ────────────────────────────────────────
Write-Host "[2/5] Setting up Cloudflare Tunnel (makes backend public)..." -ForegroundColor Yellow

$cloudflaredExe = $null

# Check if cloudflared is in PATH
try {
    $null = Get-Command cloudflared -ErrorAction Stop
    $cloudflaredExe = "cloudflared"
    Write-Host "  OK: Found cloudflared in PATH" -ForegroundColor Green
} catch {
    # Not in PATH -- check project directory
    $localExe = Join-Path $ScriptDir "cloudflared.exe"
    if (Test-Path $localExe) {
        $cloudflaredExe = $localExe
        Write-Host "  OK: Found cloudflared.exe in project folder" -ForegroundColor Green
    } else {
        # Download it from GitHub releases
        Write-Host "  cloudflared not found -- downloading (one-time, ~30 MB)..." -ForegroundColor Yellow
        $downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
        try {
            $ProgressPreference = "SilentlyContinue"
            Invoke-WebRequest -Uri $downloadUrl -OutFile $localExe -UseBasicParsing
            $cloudflaredExe = $localExe
            Write-Host "  OK: Downloaded cloudflared.exe to project folder" -ForegroundColor Green
        } catch {
            Write-Host "  ERROR: Could not download cloudflared: $_" -ForegroundColor Red
            Write-Host "  Download manually from: https://github.com/cloudflare/cloudflared/releases" -ForegroundColor DarkGray
            Write-Host "  Place cloudflared.exe in: $ScriptDir" -ForegroundColor DarkGray
            Read-Host "Press Enter to exit"
            exit 1
        }
    }
}
Write-Host ""

# ── Step 3: Start Cloudflare Tunnel and capture public URL ───────────────────
Write-Host "[3/5] Starting Cloudflare Tunnel (please wait up to 30s)..." -ForegroundColor Yellow

$tunnelLogFile = Join-Path $env:TEMP "iitb_tunnel.log"
if (Test-Path $tunnelLogFile) { Remove-Item $tunnelLogFile -Force }

# Launch cloudflared in background, writing output to a temp log file
$cfArgs = "tunnel", "--url", "http://localhost:8000", "--no-autoupdate"
$cfProcess = Start-Process -FilePath $cloudflaredExe `
    -ArgumentList $cfArgs `
    -RedirectStandardError $tunnelLogFile `
    -WindowStyle Hidden `
    -PassThru

# Wait for the trycloudflare.com URL to appear (up to 45 seconds)
$publicUrl = $null
$deadline = [DateTime]::UtcNow.AddSeconds(45)
while ([DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 800
    if (Test-Path $tunnelLogFile) {
        $logContent = Get-Content $tunnelLogFile -Raw -ErrorAction SilentlyContinue
        if ($logContent -match "https://[a-z0-9\-]+\.trycloudflare\.com") {
            $publicUrl = $Matches[0]
            break
        }
    }
}

if (-not $publicUrl) {
    Write-Host "  WARNING: Could not detect public Cloudflare URL in 45s." -ForegroundColor Red
    Write-Host "  Falling back to local IP mode (same-WiFi only)." -ForegroundColor Yellow

    # Kill the cloudflared process since it didn't produce a URL
    try { Stop-Process -Id $cfProcess.Id -Force -ErrorAction SilentlyContinue } catch {}

    $backendBaseUrl = $null
} else {
    Write-Host "  OK: Public URL: $publicUrl" -ForegroundColor Green
    $backendBaseUrl = $publicUrl
    # Save the cloudflared PID so stop-all.ps1 can kill it
    $cfProcess.Id | Out-File -FilePath (Join-Path $ScriptDir ".cloudflared.pid") -Encoding ascii
}
Write-Host ""

# ── Step 4: Auto-detect local IP (fallback if no tunnel) ─────────────────────
if (-not $backendBaseUrl) {
    Write-Host "[4/5] Detecting local IP (same-WiFi only mode)..." -ForegroundColor Yellow
    $localIp = (Get-NetIPAddress -AddressFamily IPv4 |
           Where-Object {
               $_.InterfaceAlias -notmatch "Loopback|vEthernet|Bluetooth|WSL" -and
               $_.IPAddress -notlike "169.*" -and
               $_.IPAddress -notlike "127.*"
           } |
           Select-Object -First 1).IPAddress

    if ($localIp) {
        $backendBaseUrl = "http://${localIp}:8000"
        Write-Host "  OK: Using $backendBaseUrl" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: Could not detect IP. Enter it manually." -ForegroundColor Red
        $manualIp = Read-Host "  Your laptop IP"
        $backendBaseUrl = "http://${manualIp}:8000"
    }
} else {
    Write-Host "[4/5] Skipped (using Cloudflare public URL)" -ForegroundColor DarkGray
}
Write-Host ""

# ── Step 5: Log in and get token ─────────────────────────────────────────────
Write-Host "[5/5] Logging in to get an auth token..." -ForegroundColor Yellow

$email = Read-Host "  Email    (Enter = admin@security.iitb.ac.in)"
if ([string]::IsNullOrWhiteSpace($email)) { $email = "admin@security.iitb.ac.in" }

$passwordSecure = Read-Host "  Password (Enter = admin123)" -AsSecureString
$plainPassword  = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                      [Runtime.InteropServices.Marshal]::SecureStringToBSTR($passwordSecure))
if ([string]::IsNullOrWhiteSpace($plainPassword)) { $plainPassword = "admin123" }

try {
    $body     = "{`"email`":`"$email`",`"password`":`"$plainPassword`"}"
    $response = Invoke-RestMethod -Method POST `
                    -Uri "http://localhost:8000/api/v1/auth/login" `
                    -ContentType "application/json" `
                    -Body $body
    $token = $response.access_token
    Write-Host "  OK: Token obtained (valid 60 min)" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Login failed: $_" -ForegroundColor Red
    Write-Host "  Make sure the backend is running: .\start-all.ps1" -ForegroundColor DarkGray
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# ── Build the phone URL ───────────────────────────────────────────────────────
$streamId = Read-Host "Stream name for this phone (Enter = phone_guard1)"
if ([string]::IsNullOrWhiteSpace($streamId)) { $streamId = "phone_guard1" }

$phoneUrl = "${backendBaseUrl}/api/v1/mobile/stream/page?stream_id=${streamId}&token=${token}&backend_url=${backendBaseUrl}"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  PHONE URL READY                                           " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host $phoneUrl -ForegroundColor White
Write-Host ""

$phoneUrl | Set-Clipboard
Write-Host "  URL copied to clipboard!" -ForegroundColor Green
Write-Host ""

if ($backendBaseUrl -like "https://*.trycloudflare.com*") {
    Write-Host "  Works from ANY network (different WiFi, mobile data, etc.)" -ForegroundColor Green
    Write-Host "  Cloudflare Tunnel is running in background." -ForegroundColor DarkGray
    Write-Host "  Note: Tunnel URL changes each time you run this script." -ForegroundColor DarkGray
    Write-Host "  Run .\stop-mobile-stream.ps1 to stop the tunnel when done." -ForegroundColor DarkGray
} else {
    Write-Host "  NOTE: Works on same WiFi only. For any network, ensure" -ForegroundColor Yellow
    Write-Host "  cloudflared is available and backend is running first." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  1. Send URL to guard via WhatsApp/SMS/QR code" -ForegroundColor DarkGray
Write-Host "  2. They open it in Chrome or Safari" -ForegroundColor DarkGray
Write-Host "  3. Tap 'Start Streaming' -- feed appears in dashboard" -ForegroundColor DarkGray
Write-Host "------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

Read-Host "Press Enter to exit"
