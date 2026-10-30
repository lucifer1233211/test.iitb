$ErrorActionPreference = "Continue"
$root = $PSScriptRoot

Write-Host "Stopping IITB Integrated Security System..." -ForegroundColor Yellow
Write-Host ""

# --- Stop application processes on known ports ---
$services = @(
    @{ Name = "Campus backend";  Port = 8000 },
    @{ Name = "Campus frontend"; Port = 5000 },
    @{ Name = "CORTEX";          Port = 3000 },
    @{ Name = "GCS backend";     Port = 5002 },
    @{ Name = "Drone backend";   Port = 8001 },
    @{ Name = "GCS dashboard";   Port = 8765 }
)

foreach ($svc in $services) {
    $conns = Get-NetTCPConnection -LocalPort $svc.Port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        foreach ($conn in $conns) {
            $procId = $conn.OwningProcess
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "Stopping $($svc.Name) (PID $procId on port $($svc.Port))..."
                # Kill the process tree so child processes are also terminated
                taskkill /PID $procId /T /F 2>&1 | Out-Null
            }
        }
        Write-Host "  $($svc.Name) stopped." -ForegroundColor Green
    } else {
        Write-Host "  $($svc.Name) was not running." -ForegroundColor DarkGray
    }
}

Write-Host ""

# --- Stop PostgreSQL Docker container ---
Write-Host "Stopping PostgreSQL Docker container..."
Push-Location $root
try {
    docker compose down 2>&1 | ForEach-Object {
        if ($_ -notmatch "level=warning.*obsolete") { Write-Host "  $_" }
    }
    Write-Host "  PostgreSQL container stopped." -ForegroundColor Green
} catch {
    Write-Host "  Docker compose down failed: $_" -ForegroundColor Red
} finally {
    Pop-Location
}

Write-Host ""

# --- Close specific terminal windows and browser tabs tracked during startup ---
$terminalsPidFile = Join-Path $root ".terminals.pid"
$browsersPidFile = Join-Path $root ".browsers.pid"

if (Test-Path $terminalsPidFile) {
    Write-Host "Closing service terminal windows..."
    Get-Content $terminalsPidFile | ForEach-Object {
        $tid = $_.Trim()
        if ($tid -match '^\d+$') {
            taskkill /PID $tid /T /F 2>&1 | Out-Null
        }
    }
    Remove-Item $terminalsPidFile -ErrorAction SilentlyContinue
    Write-Host "  Terminals closed." -ForegroundColor Green
}



Write-Host ""
Write-Host "All services stopped." -ForegroundColor Green
