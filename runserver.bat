@echo off
REM Convenience launcher for Roma-ERP dev server.
REM Double-click this file to start the server.  Open the URL below in your browser.

cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   Roma ERP - starting Django dev server
echo   Open this URL in your browser:
echo       http://127.0.0.1:8001/
echo   Login: admin / roma2026
echo.
echo   NOTE: Roma uses port 8001 so it does not conflict with
echo         Comfit ERP (which runs on port 8000).
echo.
echo   To stop the server, press Ctrl+C in this window or close it.
echo ============================================================
echo.

".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8001

echo.
echo ============================================================
echo   Server stopped or failed to start.  See message above.
echo ============================================================
pause
