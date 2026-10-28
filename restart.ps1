# restart.ps1 - Restart MCP PROJECT Backend & Frontend Services

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  MCP PROJECT - Restarting Services" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Execute Stop
& "$ScriptDir\stop.ps1"

Start-Sleep -Seconds 2

# 2. Execute Start
& "$ScriptDir\start.ps1"
