@echo off
rem Windows: double-click this file to start the accountability agent.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3 is required but was not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
  pause
  exit /b 1
)

if not exist .venv (
  echo First run: setting things up ^(this takes a minute^)...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

python main.py web
pause
