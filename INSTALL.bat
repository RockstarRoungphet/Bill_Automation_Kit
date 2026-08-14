@echo off
setlocal
cd /d "%~dp0"
title Bill Automation Kit - One-Click Install
color 0B

echo.
echo  ============================================================
echo   Bill Automation Kit - One-Click Install
echo  ============================================================
echo.
echo   This will:
echo     - Install Python (if missing) via winget
echo     - Create virtual environments + install packages
echo     - Install Playwright Chromium
echo     - Create Desktop icons (Send Bill / Capture Bill)
echo.
echo   After this finishes, double-click "Send Bill Launcher"
echo   on the Desktop and fill Settings yourself.
echo.
echo  ============================================================
echo.

REM Prefer PowerShell 5.1 (Windows built-in)
where powershell >nul 2>&1
if errorlevel 1 (
    echo ERROR: PowerShell not found.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1" -InstallPrerequisites -CreateDesktopShortcuts
set ERR=%ERRORLEVEL%

echo.
if %ERR% NEQ 0 (
    echo  ============================================================
    echo   INSTALL FAILED  (exit code %ERR%)
    echo   Read the messages above, fix, then run INSTALL.bat again.
    echo  ============================================================
    pause
    exit /b %ERR%
)

echo  ============================================================
echo   INSTALL OK
echo.
echo   Next: open Desktop icon  "Send Bill Launcher"
echo   Then fill Settings (Sheet / Facebook / Webhook).
echo  ============================================================
echo.
pause
exit /b 0
