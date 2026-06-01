@echo off
REM فتح Windows Firewall على بورت 8001 عشان أي جهاز في نفس شبكة الـ WiFi
REM يقدر يفتح Roma ERP من المتصفح
REM
REM مهم: اعمل right-click على الملف ده واختار "Run as administrator"
REM (مرة واحدة بس، مش محتاج تعمل ده كل مرة)

cd /d "%~dp0"

REM طلب صلاحيات admin لو مفيش
NET SESSION >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ============================================================
    echo   لازم تشغل الملف ده بصلاحيات Administrator
    echo   اعمل right-click على open_firewall.bat
    echo   واختار "Run as administrator"
    echo ============================================================
    echo.
    pause
    exit /b 1
)

echo.
echo اضافة قاعدة firewall لـ TCP port 8001 (Roma ERP)...
echo.

netsh advfirewall firewall delete rule name="Roma ERP 8001" >nul 2>&1
netsh advfirewall firewall add rule name="Roma ERP 8001" dir=in action=allow protocol=TCP localport=8001 profile=private,domain

echo.
echo ============================================================
echo   تم. الآن أي جهاز على نفس شبكة الـ WiFi يقدر يفتح:
echo.
ipconfig | findstr /C:"IPv4"
echo.
echo   اضف ":8001" في الآخر في المتصفح على الموبايل.
echo   مثال: http://192.168.1.10:8001/
echo ============================================================
echo.
pause
