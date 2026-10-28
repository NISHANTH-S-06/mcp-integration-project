@echo off
echo ============================================
echo   MCP Data Assistant - Starting MCP Server
echo ============================================

cd /d "%~dp0"

echo [*] Starting MCP Streamable HTTP server on http://127.0.0.1:8020/mcp
echo [*] Press Ctrl+C to stop.
echo.

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m app.mcp_server
) else (
    python -m app.mcp_server
)

pause
