# =============================================================
# IITB Security System - Stop Mobile Stream Tunnel
# Stops the Cloudflare Tunnel started by start-mobile-stream.ps1
# =============================================================

$ScriptDir = $PSScriptRoot

Write-Host ""
Write-Host "Stopping Cloudflare Tunnel..." -ForegroundColor Yellow

$pidFile = Join-Path $ScriptDir ".cloudflared.pid"
if (Test-Path $pidFile) {
    $pid = (Get-Content $pidFile -Raw).Trim()
    if ($pid -match '^\d+$') {
        try {
            Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue
            Write-Host "  OK: Tunnel stopped (PID $pid)" -ForegroundColor Green
        } catch {
            Write-Host "  Already stopped or not found." -ForegroundColor DarkGray
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
} else {
    # Try to kill all cloudflared processes
    $procs = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force
        Write-Host "  OK: Stopped $($procs.Count) cloudflared process(es)" -ForegroundColor Green
    } else {
        Write-Host "  No Cloudflare Tunnel was running." -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
