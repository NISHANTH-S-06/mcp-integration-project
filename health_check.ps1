# health_check.ps1 - Health Verification for MCP PROJECT

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

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
Write-Host "  MCP PROJECT - Health Diagnostic Check" -ForegroundColor Cyan
Write-Host "  Backend Port:  $BackendPort" -ForegroundColor Cyan
Write-Host "  Frontend Port: $FrontendPort" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Test Backend Endpoint /api/health
$HealthUrl = "http://127.0.0.1:$BackendPort/api/health"
Write-Host "[*] Testing Backend API ($HealthUrl)..." -NoNewline
try {
    $backendRes = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 5 -ErrorAction Stop
    if ($backendRes -and $backendRes.status -eq "ok") {
        Write-Host " [ OK - HTTP 200 ]" -ForegroundColor Green
        Write-Host "    Service:    $($backendRes.service)" -ForegroundColor Gray
        Write-Host "    Version:    $($backendRes.version)" -ForegroundColor Gray
        Write-Host "    Read-Only:  $($backendRes.read_only)" -ForegroundColor Gray
        Write-Host "    Uptime:     $($backendRes.uptime_human)" -ForegroundColor Gray
    } else {
        Write-Host " [ WARN - Unexpected Payload ]" -ForegroundColor Yellow
    }
} catch {
    Write-Host " [ FAILED ]" -ForegroundColor Red
    Write-Host "    Error: $_" -ForegroundColor Red
}

# 2. Test Frontend Endpoint /
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
Write-Host "[*] Testing Frontend UI ($FrontendUrl)..." -NoNewline
try {
    $frontendRes = Invoke-WebRequest -Uri $FrontendUrl -Method Get -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    if ($frontendRes.StatusCode -eq 200) {
        Write-Host " [ OK - HTTP 200 ]" -ForegroundColor Green
    } else {
        Write-Host " [ WARN - HTTP $($frontendRes.StatusCode) ]" -ForegroundColor Yellow
    }
} catch {
    Write-Host " [ FAILED ]" -ForegroundColor Red
    Write-Host "    Error: $_" -ForegroundColor Red
}

Write-Host "==========================================" -ForegroundColor Cyan
