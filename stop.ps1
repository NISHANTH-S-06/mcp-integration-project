# stop.ps1 - Stop MCP PROJECT Backend & Frontend Services

$ErrorActionPreference = "SilentlyContinue"
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
Write-Host "  MCP PROJECT - Stopping Services" -ForegroundColor Cyan
Write-Host "  Target Ports: $BackendPort (Backend), $FrontendPort (Frontend)" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

function Stop-ProcessOnPort ($port, $serviceName) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 0 }
    if ($connections) {
        $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pidToKill in $pids) {
            if ($pidToKill -gt 0) {
                $proc = Get-Process -Id $pidToKill -ErrorAction SilentlyContinue
                $procName = if ($proc) { $proc.ProcessName } else { "PID $pidToKill" }
                Write-Host "[*] Stopping $serviceName (Process: $procName, PID: $pidToKill) on port $port..." -ForegroundColor Yellow
                Stop-Process -Id $pidToKill -Force -ErrorAction SilentlyContinue
                Write-Host "[+] Stopped process $pidToKill." -ForegroundColor Green
            }
        }
    } else {
        Write-Host "[*] No process running on port $port ($serviceName)." -ForegroundColor Gray
    }
}

Stop-ProcessOnPort -port $BackendPort -serviceName "Backend"
Stop-ProcessOnPort -port $FrontendPort -serviceName "Frontend"

Write-Host "==========================================" -ForegroundColor Green
Write-Host "  MCP PROJECT Services Stopped Successfully." -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
