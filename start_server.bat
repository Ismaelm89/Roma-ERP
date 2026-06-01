@echo off
REM Double-click to start Roma ERP server in the background.
REM The server keeps running even after this window closes.
REM To stop: double-click stop_server.bat (or kill the python process in Task Manager).

cd /d "%~dp0"
".venv\Scripts\python.exe" start_detached.py
echo.
echo ============================================================
echo   Server started in background.
echo   Open in browser:  http://127.0.0.1:8001/
echo   Login:            admin / roma2026
echo.
echo   To stop the server, double-click stop_server.bat
echo ============================================================
echo.
timeout /t 8 >nul
