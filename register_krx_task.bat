@echo off
REM =====================================================================
REM  Register KRX morning task -> run_morning.ps1 (in this folder)
REM  Mon-Fri 08:05. Output JSON lands in this folder's parent directory.
REM  Usage: right-click > "Run as administrator" (or double-click)
REM =====================================================================

set "PS1=%~dp0run_morning.ps1"

schtasks /create ^
 /tn "KRX_Morning_Data" ^
 /tr "powershell -ExecutionPolicy Bypass -NoProfile -File \"%PS1%\"" ^
 /sc weekly ^
 /d MON,TUE,WED,THU,FRI ^
 /st 08:05 ^
 /f

if %errorlevel%==0 (
  echo.
  echo [OK] Task "KRX_Morning_Data" registered - Mon-Fri 08:05
) else (
  echo.
  echo [FAIL] Run as administrator and retry.
)
echo.
pause
