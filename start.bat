@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install the Python environment first. See docu\guide\cli_usage.md
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m xmbwavestudio %*
if errorlevel 1 pause
