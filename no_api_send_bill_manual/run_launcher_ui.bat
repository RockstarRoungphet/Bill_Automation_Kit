@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" launcher_ui.py
) else (
    pythonw launcher_ui.py
)
if errorlevel 1 if not exist ".venv\Scripts\pythonw.exe" (
    python launcher_ui.py
)
