@echo off
echo ============================================
echo   MCP Data Assistant - Starting Frontend
echo ============================================

cd /d "%~dp0"

echo [*] Starting frontend server on http://127.0.0.1:3200
echo [*] Open your browser at: http://127.0.0.1:3200
echo [*] Press Ctrl+C to stop.
echo.

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m http.server 3200 --directory frontend
) else (
    python -m http.server 3200 --directory frontend
)

pause
