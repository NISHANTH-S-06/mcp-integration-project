# start.ps1 - Start MCP PROJECT Backend & Frontend Services

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# Load .env variables if present
$BackendPort = "8200"
$FrontendPort = "3200"

if (Test-Path "$ScriptDir\.env") {
    Get-Content "$ScriptDir\.env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $key = $parts[0].Trim()
            $value = $parts[1].Trim()
            if ($key -eq "BACKEND_PORT") { $BackendPort = $value }
            if ($key -eq "FRONTEND_PORT") { $FrontendPort = $value }
        }
    }
}

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MCP PROJECT - Starting Services" -ForegroundColor Cyan
Write-Host "  Backend Port:  $BackendPort" -ForegroundColor Cyan
Write-Host "  Frontend Port: $FrontendPort" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Function to check port availability
function Test-PortInUse ($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return ($null -ne $conns)
}

if (Test-PortInUse $BackendPort) {
    Write-Host "[!] Port $BackendPort is already in use! Run .\stop.ps1 first." -ForegroundColor Red
    exit 1
}

if (Test-PortInUse $FrontendPort) {
    Write-Host "[!] Port $FrontendPort is already in use! Run .\stop.ps1 first." -ForegroundColor Red
    exit 1
}

# Ensure logs directory exists
New-Item -ItemType Directory -Force -Path "$ScriptDir\logs" | Out-Null

# Determine Python Executable
$PythonExe = "python"
if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    $PythonExe = (Resolve-Path "$ScriptDir\.venv\Scripts\python.exe").Path
}

# 1. Start Backend Process
Write-Host "[*] Starting FastAPI Backend on http://127.0.0.1:$BackendPort ..." -ForegroundColor Yellow
$bCmd = "`"$PythonExe`" -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort"
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $bCmd
    CurrentDirectory = $ScriptDir
} | Out-Null

# 2. Start Frontend Process
Write-Host "[*] Starting Frontend Web Server on http://127.0.0.1:$FrontendPort ..." -ForegroundColor Yellow
$fCmd = "`"$PythonExe`" -m http.server $FrontendPort --directory frontend"
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $fCmd
    CurrentDirectory = $ScriptDir
} | Out-Null

Write-Host "[*] Services launched via persistent background process." -ForegroundColor Green
Write-Host "[*] Waiting for Health Check..." -ForegroundColor Yellow

$HealthUrl = "http://127.0.0.1:$BackendPort/api/health"
$Success = $false
for ($i = 1; $i -le 15; $i++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response -and $response.status -eq "ok") {
            $Success = $true
            break
        }
    } catch {
        # Retry
    }
}

if ($Success) {
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host "  MCP PROJECT IS RUNNING SUCCESSFULLY!" -ForegroundColor Green
    Write-Host "  Backend API:  http://127.0.0.1:$BackendPort" -ForegroundColor Green
    Write-Host "  Health API:   http://127.0.0.1:$BackendPort/api/health" -ForegroundColor Green
    Write-Host "  Frontend Dashboard: http://127.0.0.1:$FrontendPort" -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
} else {
    Write-Host "[!] Warning: Health check did not respond within 15 seconds." -ForegroundColor Red
    Write-Host "[!] Check log files or process status." -ForegroundColor Yellow
}
