@echo off
cd /d "%~dp0"

REM Prefer local venv, then repo-root venv, then system Python
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" launcher_ui.py
    goto :eof
)
if exist "..\.venv\Scripts\pythonw.exe" (
    "..\.venv\Scripts\pythonw.exe" launcher_ui.py
    goto :eof
)
where pythonw >nul 2>&1
if %ERRORLEVEL%==0 (
    pythonw launcher_ui.py
    goto :eof
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python launcher_ui.py
    goto :eof
)

echo ERROR: Python / venv not found. Double-click INSTALL.bat at the repo root first.
pause
