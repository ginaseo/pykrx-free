@echo off
REM =====================================================================
REM  Register KRX morning task (Mon-Fri 08:05 -> run_morning.ps1).
REM  Thin launcher: self-elevates to admin, then runs register_krx_task.ps1
REM  which bakes in battery/wake/catch-up settings (schtasks defaults skip
REM  on battery and never wake the PC).
REM  Usage: double-click (UAC prompt) or right-click > Run as administrator.
REM =====================================================================

set "PS1=%~dp0register_krx_task.ps1"

REM --- elevate if not already admin ---
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Requesting administrator privileges...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)

powershell -ExecutionPolicy Bypass -NoProfile -File "%PS1%"

echo.
pause
