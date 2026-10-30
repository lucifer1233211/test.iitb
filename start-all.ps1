param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$campusRoot = Join-Path $root "campus-security-system-complete"
$campusBackend = Join-Path $campusRoot "backend_server"
$campusFrontend = Join-Path $campusRoot "frontend"
$gcsRoot = Join-Path $root "send_gcs"
$cortexRoot = Join-Path $gcsRoot "T1T2IIT(Bom) copy"
$droneRoot = Join-Path $cortexRoot "drone_backend"
$gcsBackend = Join-Path $gcsRoot "GCS_folder\backend"
$campusPython = Join-Path $campusBackend "venv\Scripts\python.exe"
$campusUvicorn = Join-Path $campusBackend "venv\Scripts\uvicorn.exe"
$dronePython = Join-Path $droneRoot ".venv\Scripts\python.exe"

# Clean up old tracking files
$terminalsPidFile = Join-Path $root ".terminals.pid"
$browsersPidFile = Join-Path $root ".browsers.pid"
if (Test-Path $terminalsPidFile) { Remove-Item $terminalsPidFile -ErrorAction SilentlyContinue }
if (Test-Path $browsersPidFile) { Remove-Item $browsersPidFile -ErrorAction SilentlyContinue }

function Test-ListeningPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        return $result.AsyncWaitHandle.WaitOne(250) -and $client.Connected
    }
    finally {
        $client.Dispose()
    }
}

function ConvertTo-QuotedString([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Start-ServiceTerminal([string]$Name, [string]$WorkingDirectory, [string]$Command) {
    Write-Host "Starting $Name ..."
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
    $proc = Start-Process -FilePath "powershell.exe" -WorkingDirectory $WorkingDirectory -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", $encoded
    ) -PassThru
    $proc.Id | Out-File -FilePath (Join-Path $root ".terminals.pid") -Append -Encoding ascii
}

foreach ($requiredPath in @($campusUvicorn, $campusPython, $dronePython)) {
    if (-not (Test-Path $requiredPath)) {
        throw "Required runtime was not found: $requiredPath. Complete the setup steps in STARTUP_GUIDE.md first."
    }
}

$rootPS = ConvertTo-QuotedString $root
$campusBackendPS = ConvertTo-QuotedString $campusBackend
$campusFrontendPS = ConvertTo-QuotedString $campusFrontend
$gcsRootPS = ConvertTo-QuotedString $gcsRoot
$cortexRootPS = ConvertTo-QuotedString $cortexRoot
$gcsBackendPS = ConvertTo-QuotedString $gcsBackend
$droneRootPS = ConvertTo-QuotedString $droneRoot
$gcsFrontendPS = ConvertTo-QuotedString (Join-Path $gcsRoot "frontend")
$campusPythonPS = ConvertTo-QuotedString $campusPython
$campusUvicornPS = ConvertTo-QuotedString $campusUvicorn
$dronePythonPS = ConvertTo-QuotedString $dronePython

if (-not (Test-ListeningPort 5432)) {
    Start-ServiceTerminal "PostgreSQL" $root "Set-Location -LiteralPath $rootPS; docker compose up db"
} else { Write-Host "PostgreSQL is already running on port 5432." }

if (-not (Test-ListeningPort 8000)) {
    $command = "Set-Location -LiteralPath $campusBackendPS; `$env:DATABASE_URL='postgresql://campus_security:campus_security@localhost:5432/campus_security'; & $campusUvicornPS main:app --host 0.0.0.0 --port 8000"
    Start-ServiceTerminal "Campus backend" $campusBackend $command
} else { Write-Host "Campus backend is already running on port 8000." }

if (-not (Test-ListeningPort 5000)) {
    Start-ServiceTerminal "Campus frontend" $campusFrontend "Set-Location -LiteralPath $campusFrontendPS; npm.cmd run dev"
} else { Write-Host "Campus frontend is already running on port 5000." }

if (-not (Test-ListeningPort 3000)) {
    Start-ServiceTerminal "CORTEX" $cortexRoot "Set-Location -LiteralPath $cortexRootPS; npm.cmd run dev"
} else { Write-Host "CORTEX is already running on port 3000." }

if (-not (Test-ListeningPort 5002)) {
    $command = "Set-Location -LiteralPath $gcsBackendPS; `$env:GCS_BACKEND_PORT='5002'; & $campusPythonPS app.py"
    Start-ServiceTerminal "GCS backend" $gcsBackend $command
} else { Write-Host "GCS backend is already running on port 5002." }

if (-not (Test-ListeningPort 8001)) {
    Start-ServiceTerminal "Drone backend" $droneRoot "Set-Location -LiteralPath $droneRootPS; & $dronePythonPS main.py"
} else { Write-Host "Drone backend is already running on port 8001." }

if (-not (Test-ListeningPort 8765)) {
    $command = "Set-Location -LiteralPath $gcsRootPS; & $campusPythonPS -m http.server 8765 --directory $gcsFrontendPS"
    Start-ServiceTerminal "GCS dashboard" $gcsRoot $command
} else { Write-Host "GCS dashboard is already running on port 8765." }

Write-Host "Waiting for services to become reachable..."
$ports = 5432, 8000, 5000, 3000, 5002, 8001, 8765
$deadline = [DateTime]::UtcNow.AddSeconds(30)
do {
    $ready = @($ports | Where-Object { Test-ListeningPort $_ }).Count
    Write-Host "Ready: $ready/$($ports.Count) ports"
    if ($ready -eq $ports.Count) { break }
    Start-Sleep -Milliseconds 500
} while ([DateTime]::UtcNow -lt $deadline)

if ($ready -ne $ports.Count) {
    $missing = $ports | Where-Object { -not (Test-ListeningPort $_) }
    throw "Startup timed out. Missing ports: $($missing -join ', '). Check the service terminal output."
}

Write-Host "All seven services are ready." -ForegroundColor Green
if (-not $NoBrowser) {
    $urls = @(
        "http://localhost:5000",          # Campus Security UI
        "http://localhost:3000",          # CORTEX
        "http://localhost:8765",          # GCS dashboard
        "http://127.0.0.1:8000/health",  # Campus backend health
        "http://localhost:5002/health",   # GCS backend health
        "http://127.0.0.1:8001/docs"     # Drone API docs
    )
    foreach ($url in $urls) {
        Start-Process $url
        Start-Sleep -Milliseconds 500
    }
    Write-Host "Opened all service URLs in browser." -ForegroundColor Cyan
}
