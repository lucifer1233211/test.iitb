$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$cortexDirectory = Join-Path $root "T1T2IIT(Bom) copy"
$droneBackendDirectory = Join-Path $cortexDirectory "drone_backend"
$gcsBackendDirectory = Join-Path $root "GCS_folder\backend"
$frontendDirectory = Join-Path $root "frontend"
$logsDirectory = Join-Path $root "logs"
$gcsPort = 8765

New-Item -ItemType Directory -Force -Path $logsDirectory | Out-Null

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

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python was not found; it is required." }

if (-not (Test-ListeningPort 3000)) {
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw "npm.cmd was not found. Install Node.js before starting CORTEX."
    }
    if (-not (Test-Path (Join-Path $cortexDirectory "node_modules"))) {
        Write-Host "Installing CORTEX dependencies (first run only)..."
        Push-Location $cortexDirectory
        try {
            & npm.cmd install
            if ($LASTEXITCODE -ne 0) { throw "CORTEX dependency installation failed." }
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "Starting CORTEX on http://localhost:3000 ..."
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList @("run", "dev") `
        -WorkingDirectory $cortexDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logsDirectory "cortex_stdout.log") `
        -RedirectStandardError (Join-Path $logsDirectory "cortex_stderr.log")
}
else {
    Write-Host "CORTEX is already running on port 3000."
}

if (-not (Test-ListeningPort 8001)) {
    Write-Host "Starting Drone Backend on http://localhost:8001 ..."
    $dronePython = Join-Path $droneBackendDirectory ".venv\Scripts\python.exe"
    if (-not (Test-Path $dronePython)) { $dronePython = $python.Source }
    Start-Process -FilePath $dronePython `
        -ArgumentList @("main.py") `
        -WorkingDirectory $droneBackendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logsDirectory "drone_backend_stdout.log") `
        -RedirectStandardError (Join-Path $logsDirectory "drone_backend_stderr.log")
}
else {
    Write-Host "Drone Backend is already running on port 8001."
}

if (-not (Test-ListeningPort 5002)) {
    Write-Host "Starting GCS Backend on http://localhost:5002 ..."
    $campusPython = Join-Path $root "..\campus-security-system-complete\backend_server\venv\Scripts\python.exe"
    if (-not (Test-Path $campusPython)) { $campusPython = $python.Source }
    
    # We must set the environment variable for the port. We can do this in PowerShell via a small wrapper or passing arguments if app.py accepts it. Since it reads GCS_BACKEND_PORT:
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-WindowStyle", "Hidden", "-Command", "`$env:GCS_BACKEND_PORT='5002'; & `'$campusPython`' app.py") `
        -WorkingDirectory $gcsBackendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logsDirectory "gcs_backend_stdout.log") `
        -RedirectStandardError (Join-Path $logsDirectory "gcs_backend_stderr.log")
}
else {
    Write-Host "GCS Backend is already running on port 5002."
}


if (-not (Test-ListeningPort $gcsPort)) {
    Write-Host "Starting GCS frontend on http://localhost:$gcsPort ..."
    Start-Process -FilePath $python.Source `
        -ArgumentList @("-m", "http.server", "$gcsPort", "--directory", "`"$frontendDirectory`"") `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logsDirectory "frontend_stdout.log") `
        -RedirectStandardError (Join-Path $logsDirectory "frontend_stderr.log")
}
else {
    Write-Host "GCS frontend is already running on port $gcsPort."
}

$deadline = [DateTime]::UtcNow.AddSeconds(20)
while ([DateTime]::UtcNow -lt $deadline) {
    if ((Test-ListeningPort 3000) -and (Test-ListeningPort $gcsPort) -and (Test-ListeningPort 5002) -and (Test-ListeningPort 8001)) {
        Write-Host "GCS services (CORTEX, Drone Backend, GCS Backend, GCS Frontend) are ready."
        Start-Process "http://localhost:$gcsPort"
        exit 0
    }
    Start-Sleep -Milliseconds 300
}

throw "Startup timed out. Check logs directory for errors."
