@echo off
echo ============================================
echo   MCP Data Assistant - Starting Backend
echo ============================================

cd /d "%~dp0"

echo [*] Starting FastAPI backend on http://127.0.0.1:8200
echo [*] Start run_mcp_server.bat first for real MCP transport.
echo [*] Press Ctrl+C to stop.
echo.

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8200 --reload
) else (
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8200 --reload
)

pause
