@echo off
REM Double-click to stop the Roma ERP server.

cd /d "%~dp0"
".venv\Scripts\python.exe" stop_server.py
echo.
timeout /t 5 >nul
